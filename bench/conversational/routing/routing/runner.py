"""Runs Session Routing conversations through an arm and scores every turn from the file system."""

import asyncio
import json
import os
import random
import re
import time
from pathlib import Path

from ..core import corpus, user
from . import check
from .fixture import make

HERE = Path(__file__).resolve().parent
LOCK = HERE / "audio.lock"
GENERIC = "Please go on with what I asked."
PERMISSION = re.compile(r"\b(allow|approve|permission|wants to run|wants to edit|go ahead with)\b", re.I)
YES = "Yes, go ahead."


def clips(ds: dict) -> dict[str, dict]:
    out = {}
    for conv in ds["conversation"]:
        v = conv["voice"]
        out[f"{conv['id']}.yes"] = {"text": YES, "voice": v}
        out[f"{conv['id']}.generic"] = {"text": GENERIC, "voice": v}
        for i, t in enumerate(conv["turn"], 1):
            line = check.answer_line(t)
            out[f"{conv['id']}.t{i}.say"] = {"text": t["say"], "voice": v, "speed": t.get("speed", 1.0)}
            out[f"{conv['id']}.t{i}.answer"] = {"text": line, "voice": v}
            out[f"{conv['id']}.t{i}.correct"] = {"text": "No, " + line[0].lower() + line[1:], "voice": v}
    return out


def keyboard_turns(ds: dict, seed: int, n: int = 20) -> set[tuple[str, int]]:
    """A seeded sample of the clear (non-ambiguous) turns, typed into the named session by the keyboard arm."""
    clear = [(c["id"], i) for c in ds["conversation"] for i, t in enumerate(c["turn"], 1) if t["type"] != "ambiguous"]
    return set(random.Random(seed).sample(clear, n))


def reply_clip(conv_id: str, i: int, kind: str) -> str:
    return {"answer": f"{conv_id}.t{i}.answer", "correct": f"{conv_id}.t{i}.correct", "yes": f"{conv_id}.yes",
            "generic": f"{conv_id}.generic"}[kind]


async def run_turn(arm, conv: dict, i: int, turn: dict, audio: dict, repos: dict, names: list[str]) -> tuple[dict, list]:
    word, want = turn["word"], check.intended(turn)
    log: list[dict] = []
    base = arm.stop_counts()
    t0 = time.time()
    if arm.kind == "audio":
        cid = f"{conv['id']}.t{i}.say"
        s, e = await arm.utter(cid, corpus.load(audio[cid]))
        log.append({"kind": "user_said", "clip": cid, "t": s, "end": e, "text": turn["say"]})
    elif arm.kind == "typed":
        text = check.typed_line(turn)
        await arm.typed(text, sorted(want, key=turn["target"].index))
        log.append({"kind": "user_typed", "t": t0, "text": text})
    spoke_end = time.time()
    sent: dict[str, float] = {}   # sessions the arm reported sending to, and when
    files: dict[str, float] = {}  # repos where the word appeared, and when it was first seen
    asked_t = None
    followups: list[dict] = []

    declined: set[str] = set()  # sessions whose permission dialog was declined: they may end without a Stop hook

    def finished(names) -> bool:
        """Every session that got something has ended an agent turn since this turn began (its Stop hook)."""
        counts = arm.stop_counts()
        return all(counts.get(n, 1) > base.get(n, 0) for n in set(names) - declined) if counts else True

    deadline = time.time() + arm.wait_after_say
    hard = t0 + 300
    while time.time() < min(deadline, hard):
        evs = arm.events()
        log += evs
        for ev in evs:
            if ev["kind"] == "delivered" and ev.get("session") in repos:
                sent.setdefault(ev["session"], ev["t"])
            if ev["kind"] == "prompt_declined":
                declined.add(ev["session"])
        for name in check.present(repos, word):
            files.setdefault(name, time.time())
        await arm.tick()
        questions = [ev for ev in evs if ev["kind"] == "asked"]
        if questions and not sent and not files:
            asked_t = asked_t or questions[0]["t"]
        # Before anything is delivered every question is answered; after, only on a two-session turn delivered in part
        # ("tariff web has it; can you say the depot part again?"). A permission read-out is never answered here.
        partial = turn["type"] == "two" and not (set(sent) | set(files)) >= want
        if questions and ((not sent and not files) or partial) and not PERMISSION.search(questions[-1]["text"]):
            if len(followups) < 2:
                kind = user.reply(questions[-1]["text"], want, names)
                clip = reply_clip(conv["id"], i, kind)
                s, e = await arm.utter(clip, corpus.load(audio[clip]))
                followups.append({"question": questions[-1]["text"], "reply": kind, "clip": clip})
                log.append({"kind": "user_said", "clip": clip, "t": s, "end": e, "reply_to": questions[-1]["text"]})
                deadline = time.time() + arm.wait_after_say
        active = set(sent) or set(files)  # wait on the sessions that were sent something, not on a repo it strayed into
        if active:
            deadline = max(deadline, min(hard, min({**sent, **files}.values()) + 120))
            if finished(active) and await arm.idle():
                if set(files) >= want or time.time() - min({**sent, **files}.values()) > 25:
                    break
        await asyncio.sleep(0.5)
    active = set(sent) or set(files)
    settle_until = time.time() + 120
    while time.time() < settle_until and not (finished(active) and await arm.idle()):
        await arm.tick()
        for ev in arm.events():
            log.append(ev)
            if ev["kind"] == "prompt_declined":
                declined.add(ev["session"])
        await asyncio.sleep(1)
    log += arm.events()
    final = check.present(repos, word)
    for name in final:
        files.setdefault(name, time.time())
    first_delivery = min((ev["t"] for ev in log if ev["kind"] == "delivered"), default=None)
    first_file = min((files[n] for n in final), default=None)
    delivery_t = min(x for x in (first_delivery, first_file) if x is not None) if (first_delivery or first_file) else None
    sent_to = {ev["session"] for ev in log if ev["kind"] == "delivered" and ev.get("session") in repos}
    score = check.score_turn(turn, final, delivery_t, asked_t, sent_to)
    clarifications = sum(f["reply"] in ("answer", "yes", "correct") for f in followups)
    row = {"turn": i, "type": turn["type"], "word": turn["word"], "targets": turn["target"], **score,
           "asked": asked_t is not None, "followups": followups, "clarifications": clarifications,
           "generic_replies": sum(f["reply"] == "generic" for f in followups),
           "delivery_s": round(delivery_t - spoke_end, 2) if delivery_t else None,
           "turn_s": round(time.time() - t0, 1), "t_start": t0, "t_end": time.time()}
    return row, log


def check_processes(arm, repos: dict) -> dict:
    procs = arm.processes()
    if not procs:
        return {"ok": True, "n": 0}
    cwds = {p["cwd"] for p in procs}
    ok = (len(procs) == 4 and len({p["pid"] for p in procs}) == 4 and all(p["alive"] for p in procs)
          and len(cwds) == 4 and all(p["cwd"] == p["repo"] for p in procs)
          and all(str(c).startswith(("/tmp/", "/private/tmp/")) for c in cwds))
    return {"ok": ok, "n": len(procs), "modes": sorted({p["mode"] for p in procs}),
            "cwds_under_tmp": all(str(c).startswith(("/tmp/", "/private/tmp/")) for c in cwds)}


async def run_conversation(arm, conv: dict, ds: dict, audio: dict, root: Path, only: set[int] | None = None,
                           max_turns: int | None = None) -> dict:
    """One conversation, all its turns, on fresh repos and fresh sessions. Returns rows, events and spend."""
    repos = make.make(root)
    names = list(ds["sessions"])
    rows, events, error = [], [], None
    procs = {}
    try:
        await arm.start(conv["id"], repos)
        procs = check_processes(arm, repos)
        events.append({"kind": "processes", **procs})
        if not procs["ok"]:
            raise RuntimeError(f"process check failed: {procs}")
        for i, turn in enumerate(conv["turn"], 1):
            if (only is not None and i not in only) or (max_turns and i > max_turns):
                continue
            row, log = await run_turn(arm, conv, i, turn, audio, repos, names)
            rows.append(row)
            events.append({"turn": i, "events": log})
    except Exception as e:  # recorded, never hidden: the conversation's remaining turns are missing, not failed
        error = f"{type(e).__name__}: {str(e)[:400]}"
    finally:
        spend = arm.spend() if hasattr(arm, "sessions") or arm.name == "echo" else []
        audit = arm.audit() if hasattr(arm, "sessions") else []
        versions = arm.versions()
        await arm.stop()
    for row in rows:  # the audit, attributed to the turn whose window holds the tool call
        hits = [a for a in audit if a.get("t") and row["t_start"] <= a["t"] <= row["t_end"] + 5]
        row["out_of_tree"] = len(hits)
        row["cross_repo_reads"] = sum(bool(a.get("cross_repo")) for a in hits)
        row["invalid_out_of_tree"] = any(a["scoring"] for a in hits)
    return {"rows": rows, "events": events, "spend": spend, "audit": audit, "versions": versions, "error": error,
            "processes": procs}
