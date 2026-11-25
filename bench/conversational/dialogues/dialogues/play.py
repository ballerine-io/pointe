"""One dialogue on one arm: the sessions, the typed setup turn (the same in every arm), the call, the scripted user's
turns at their triggers, and everything the scorer needs, recorded with wall-clock times. No model plays the user."""

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
import traceback
from pathlib import Path

import numpy as np

from core import corpus, scrub
from core.adapter import RunEnv, _ts
from core.asr import Whisper
from dialogues.fixtures import FIXTURES, SETUP_LINE

GUARD_BIN = Path("/tmp/pccb-pointe/guard-bin")
CAPS = {"idle": 75, "approval": 50, "readout": 50, "speaking": 30, "working": 40, "quick": 30, "now": 0}
WALL_SECS = 420


def guard_bin() -> Path:
    """Commands the isolated daemon must never run (a terminal window, an app, the other harnesses)."""
    GUARD_BIN.mkdir(parents=True, exist_ok=True)
    for name in ("open", "osascript", "codex", "opencode"):
        p = GUARD_BIN / name
        p.write_text("#!/bin/sh\necho \"pccb guard: $0 refused in the benchmark\" >&2\nexit 1\n")
        p.chmod(0o755)
    return GUARD_BIN


def write_repos(names: list, root: Path) -> dict:
    out = {}
    for name in names:
        repo = root / name
        repo.mkdir(parents=True, exist_ok=True)
        for rel, text in FIXTURES[name].items():
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
            if rel.endswith(".sh"):
                p.chmod(0o755)
        env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, env=env)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
        subprocess.run(["git", "-c", "user.email=bench@example.invalid", "-c", "user.name=bench", "commit", "-qm",
                        "initial"], cwd=repo, check=True, env=env)
        out[name] = repo
    return out


def tree(repos: dict) -> dict:
    import hashlib
    out = {}
    for name, repo in repos.items():
        for p in repo.rglob("*"):
            if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts and "logs" not in p.parts:
                out[f"{name}/{p.relative_to(repo)}"] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def voiced(pcm: np.ndarray, rate: int) -> tuple[float, float]:
    loud = np.flatnonzero(np.abs(pcm.astype(np.int32)) > 500)
    if not len(loud):
        return 0.0, len(pcm) / rate
    return loud[0] / rate, (loud[-1] + 1) / rate


def make_adapter(arm: str, port: int, ctx: dict):
    if arm == "pointe":
        from adapters.pointe import Pointe
        return Pointe(port)
    if arm == "llm-router":
        from adapters.llm_router import LLMRouter
        return LLMRouter(ctx["soniox_model"], ctx["brain"])
    raise ValueError(arm)


def kill_tree(root: Path) -> None:
    got = subprocess.run(["pgrep", "-f", str(root)], capture_output=True, text=True)
    for pid in got.stdout.split():
        try:
            os.kill(int(pid), 9)
        except (ProcessLookupError, PermissionError, ValueError):
            pass


class Watch:
    """What the scripted user can observe: the arm's voice (on or off, since when) and the sessions' state."""

    def __init__(self, adapter):
        self.a = adapter

    def spans(self) -> list:
        return [(s, e) for s, e, *_ in self.a.speech()]

    def speech_end(self) -> float:
        sp = self.spans()
        return sp[-1][1] if sp else 0.0

    def speaking(self) -> bool:
        sp = self.spans()
        now = time.time()
        return bool(sp) and sp[-1][0] <= now and now - sp[-1][1] < 0.35

    def spoke_since(self, t: float) -> bool:
        return any(s >= t for s, _ in self.spans())

    def quiet(self, secs: float) -> bool:
        return time.time() - self.speech_end() >= secs and not self.a.thinking()

    def busy(self) -> bool:
        return any(ag.busy() for ag in self.a.agents.values())

    def pending(self):
        for name, ag in self.a.agents.items():
            ap = ag.pending_approval()
            if ap:
                return name, ap
        return None, None


async def wait_for(turn, w: Watch, last_end: float, last_busy: list) -> str:
    """Waits for the turn's trigger. Returns how it fired: "ok" or "cap"."""
    cap = CAPS[turn.when]
    t0 = time.time()
    held = None
    while True:
        now = time.time()
        if w.busy():
            last_busy[0] = now
        if turn.when == "now":
            await asyncio.sleep(max(0.0, last_end + max(turn.delay, 1.0) - now))
            return "ok"
        if now - t0 > cap:
            return "cap"
        if turn.when == "idle":
            name, ap = w.pending()
            ok = (not w.busy() and ap is None and w.quiet(3.0) and now - last_end >= 4.0 and now - last_busy[0] >= 6.0)
            held = (held or now) if ok else None
            if held and now - held >= 1.0:
                break
        elif turn.when == "quick":
            if w.spoke_since(last_end) and w.quiet(1.5):
                break
        elif turn.when == "speaking":
            if w.spoke_since(last_end) and w.speaking():
                break
        elif turn.when == "working":
            if w.busy() and now - last_end > 1.0:
                break
        elif turn.when == "approval":
            name, ap = w.pending()
            # A person answers the request they heard: the turn waits for its read-out, not for any speech after it
            # ("Sent to atlas." is not the request).
            read = w.a.readout_since(max(ap["_t"] - 1, last_end)) if ap is not None else None
            if read is not None and any(s >= read - 1.5 for s, _ in w.spans()) and w.quiet(1.5):
                break
        elif turn.when == "readout":  # over the read-out itself: a yes said before it ends
            name, ap = w.pending()
            read = w.a.readout_since(max(ap["_t"] - 1, last_end)) if ap is not None else None
            if read is not None and now - read >= 0.8 and w.speaking():
                break
        await asyncio.sleep(0.2)
    if turn.delay:
        await asyncio.sleep(turn.delay)
    if turn.when not in ("speaking", "readout", "now"):  # a person does not start over the voice: at most 8 s more
        t1 = time.time()
        while time.time() - t1 < 8 and not w.quiet(1.0):
            await asyncio.sleep(0.2)
    return "ok"


async def settle(w: Watch, cap: float, quiet: float = 3.0) -> None:
    t0 = time.time()
    last_busy = time.time()
    while time.time() - t0 < cap:
        if w.busy():
            last_busy = time.time()
        name, ap = w.pending()
        if not w.busy() and w.quiet(quiet) and time.time() - last_busy > max(6.0, quiet) and ap is None:
            return
        await asyncio.sleep(0.3)


def session_record(agent) -> dict:
    """Ground truth from the session itself: the user messages it received (transcript), its hook events."""
    prompts = []
    for e in agent.entries():
        if e.get("type") != "user":
            continue
        content = (e.get("message") or {}).get("content")
        if isinstance(content, str) and content.strip():
            prompts.append((_ts(e.get("timestamp")) or 0.0, content))
        elif isinstance(content, list):
            texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            if texts and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                prompts.append((_ts(e.get("timestamp")) or 0.0, "\n".join(texts)))
    hooks = []
    for e in agent.hooks():
        name = e.get("hook_event_name")
        if name in ("UserPromptSubmit", "PermissionRequest", "PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop",
                    "Notification"):
            ti = e.get("tool_input") or {}
            hooks.append({"t": e["_t"], "name": name, "tool": e.get("tool_name"),
                          "command": str(ti.get("command") or ti.get("file_path") or "")[:300],
                          "type": e.get("notification_type")})
    return {"prompts": [(t, scrub.clean(p)[:1500]) for t, p in prompts], "hooks": hooks,
            "interrupted_at": getattr(agent, "interrupted_at", 0.0)}


async def run(d, arm: str, ctx: dict, port: int) -> dict:
    run_id = ctx["run_id"]
    slot = Path(f"/tmp/pccb/{run_id}/{d.id}-{arm}")
    stage = Path(f"/tmp/pccb-keys/{run_id}/{d.id}-{arm}")
    for p in (slot, stage):
        shutil.rmtree(p, ignore_errors=True)
        p.mkdir(parents=True)
    repos = write_repos(d.sessions, slot)
    before = tree(repos)
    env = RunEnv(run_id, slot, stage, ctx["api_key"], port, ctx["pointe"], ctx["keys"], allow=d.allow, net=d.net_opts())
    adapter = make_adapter(arm, port, ctx)
    row = {"run_id": run_id, "dialogue": d.id, "dim": d.dim, "arm": arm, "digest": d.digest(), "voice": d.voice,
           "net": d.net, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "load_avg": round(os.getloadavg()[0], 2),
           "pointe_commit": ctx["pointe_commit"], "pointe_dirty": ctx["pointe_dirty"]}
    turns, error = [], None
    t_start = time.time()
    try:
        await asyncio.to_thread(adapter.start, repos, env)
        for ag in adapter.agents.values():
            ag.type(SETUP_LINE)
        t0 = time.time()
        while time.time() - t0 < 120:
            if all(ag.stops() >= 1 and not ag.busy() for ag in adapter.agents.values()):
                break
            await asyncio.sleep(0.5)
        if hasattr(adapter, "connect"):
            await adapter.connect()
        w = Watch(adapter)
        await settle(w, 40)  # the greeting and any report of the setup turn are over before the first user turn
        row["call_ready"] = time.time()
        last_end, last_busy = time.time(), [0.0]
        multi_lang = any(t.lang != "en" for t in d.turns)
        for i, turn in enumerate(d.turns):
            if time.time() - t_start > WALL_SECS:
                row["capped"] = "wall"
                break
            fired = await wait_for(turn, w, last_end, last_busy)
            path = corpus.render(turn.voice or d.voice, turn.say, turn.noise)
            pcm = corpus.load(path)
            lead, tail = voiced(pcm, corpus.RATE)
            if env.net.get("loss") and arm == "llm-router":  # the same loss on the plain router's input audio
                pcm = impair(pcm, env.net["loss"], seed=i)
            started_at = time.time()
            s, e = await adapter.say(pcm, corpus.RATE)
            voiced_start, voiced_end = s + lead, s + tail
            rec = {"i": i, "say": turn.say, "lang": turn.lang, "when": turn.when, "fired": fired, "expect": turn.expect,
                   "voice": turn.voice or d.voice, "need": turn.need, "start": voiced_start, "end": voiced_end, "said_at": started_at,
                   "speaking_at_start": any(a <= voiced_start <= b + 0.05 for a, b in w.spans())}
            turns.append(rec)
            last_end = voiced_end
            if env.net.get("reconnect") and hasattr(adapter, "reconnect"):
                await asyncio.sleep(1.0)
                rec["reconnect"] = await adapter.reconnect(gap=2.5)
        # The last turn's outcome: a session's answer, or a report, may come well after Pointe's acknowledgement. The
        # user stays on the line until 8 s of quiet with every session idle, as long as 90 s.
        await settle(w, 90, quiet=8.0)
        row["multi_lang"] = multi_lang
    except Exception as e:
        error = scrub.clean(f"{type(e).__name__}: {e}")[:400]
        ctx["errors"].append(scrub.clean(traceback.format_exc())[-2000:])
    finally:
        row["ended"] = time.time()
        spend = spend_rows(adapter)
        spans = list(adapter.speech()) if adapter else []
        sessions = {}
        for name, ag in getattr(adapter, "agents", {}).items():
            try:
                sessions[name] = session_record(ag)
            except Exception:
                sessions[name] = {"prompts": [], "hooks": []}
        log = [scrub.clean(l)[:600] for l in getattr(adapter, "log_lines", []) if " - " in l][-600:]
        interrupts = getattr(getattr(adapter, "call", None), "interrupts", None)
        try:
            row["health"] = adapter.health() if hasattr(adapter, "health") else None
        except Exception as e:
            row["health"] = {"error": type(e).__name__}
        router_ms = [c.get("ms") for c in getattr(adapter, "calls", [])]
        try:
            await asyncio.to_thread(adapter.stop)
        except Exception:
            pass
        kill_tree(slot)
        if arm == "pointe" and getattr(adapter, "state", None):
            kill_tree(adapter.state)
    after = tree(repos)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    said = []
    for item in spans:
        s, e, pcm = item[0], item[1], item[2]
        # The reply's language follows the turn before it: Hebrew after a Hebrew or mixed turn, English otherwise. Left
        # to guess, the recognizer wrote Hebrew speech in Latin letters, and a Hebrew reply was scored as English.
        before = [t for t in turns if t["end"] <= s + 0.2]
        lang = "he" if before and before[-1]["lang"] in ("he", "mix") else "en"
        rate = 48000 if arm == "pointe" else corpus.RATE
        try:
            text = await asyncio.to_thread(Whisper.transcribe, np.asarray(pcm), rate, lang)
        except Exception as e:
            text = f"[transcription failed: {type(e).__name__}]"
        said.append((s, e, scrub.clean(text)))
    row.update(turns=turns, said=said, sessions=sessions, changed=changed, log=log, error=error,
               interrupts=interrupts, router_ms=router_ms, spend=spend, spend_usd=round(sum(r["usd"] for r in spend), 5),
               wall_secs=round(time.time() - t_start, 1), versions=safe_versions(adapter))
    return row


def impair(pcm: np.ndarray, loss: float, seed: int, frame: int = 480) -> np.ndarray:
    """Frame loss on input audio: each 20 ms frame dropped (zeroed) with probability `loss`."""
    rng = np.random.default_rng(seed)
    out = pcm.copy()
    for i in range(0, len(out), frame):
        if rng.random() < loss:
            out[i:i + frame] = 0
    return out


def safe_versions(adapter) -> dict:
    try:
        return adapter.versions()
    except Exception:
        return {}


def spend_rows(adapter) -> list:
    from core import ledger
    rows = []
    for name, agent in getattr(adapter, "agents", {}).items():
        try:
            usd = sum(ledger.token_cost(model, u) for model, u in agent.usage())
        except Exception:
            usd = 0.0
        rows.append({"vendor": "anthropic", "role": "agent", "session": name, "usd": usd, "how": "computed"})
    try:
        for r in adapter.spend():
            rows.append({"vendor": r.vendor, "role": adapter.name, "usd": r.usd, "how": r.how, "what": r.what})
    except Exception:
        pass
    return rows


def dump(row: dict) -> str:
    """The row as one line, every string scrubbed (scrub.clean): a session's own output can carry the owner's name."""
    return scrub.clean(json.dumps(row, default=str, ensure_ascii=False))
