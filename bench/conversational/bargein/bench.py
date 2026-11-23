"""bargein: Barge-in and Time to a Correct Answer (design revision 2, section 5.5).

Part A: the agent runs long_job.sh; when step_03.txt exists the scripted user stops it, stops and undoes it, redirects
it, or says a backchannel that must not stop it. Scored from the file system.
Part B: the agent has read a status file; the user asks one question; scored on the arm's recorded answer through the
one pinned Whisper: time to first audio, and time to the end of the first utterance that states the fact (TTCA).

One worker only (asserted): local Whisper, Kokoro and parallel runs on one machine corrupt latency.
"""

import json
import random
import shutil
import subprocess
import time
import tomllib
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np

from core import agent as agent_mod
from core import audio, corpus, ledger, runner
from core.adapter import RunEnv, now
from bargein import check

HERE = Path(__file__).resolve().parent
ITEMS = tomllib.loads((HERE / "items.toml").read_text())
CANARY = (HERE.parent / "CANARY").read_text().strip()
BENCH = "bargein"
CAP_USD = 14.0
SEED = 20261123
WINDOW_B = 45.0  # seconds after the question; an answer later than this is censored
SETTLE_B, QUIET_B = 8.0, 6.0  # before the question: seconds after the setup turn ended, and of the arm's silence
MODE = "acceptEdits"
MAX_RUN_USD = 0.5  # the most one run can cost, for the ledger gate (a Pointe run is estimated at $0.11)
ARMS_A = ["pointe", "llm-router", "naive", "keyboard", "null"]
ARMS_B = ["pointe", "llm-router", "naive", "keyboard"]
EST = {("a", "pointe"): 0.11, ("a", "llm-router"): 0.07, ("a", "naive"): 0.065, ("a", "keyboard"): 0.06,
       ("a", "null"): 0.06, ("b", "pointe"): 0.035, ("b", "llm-router"): 0.035, ("b", "naive"): 0.035,
       ("b", "keyboard"): 0.035}
EST_REPEAT = {"a": 1.1 / 12, "b": 0.6 / 16}
NULL_A, REPEAT_A, REPEAT_B = 8, 6, 8
LOAD_WAIT = {"a": 45.0, "b": 120.0}  # seconds to wait for the load to fall: Part B's times are the latency result
# The agent's settings file, the same in every arm: the job's commands and the file moves a stop, undo or redirect
# needs, so no permission prompt stands between the user and the outcome. Reads of this suite are denied.
ALLOW = ["Bash(./long_job.sh:*)", "Bash(./long_job.sh)", "Bash(bash long_job.sh:*)", "Bash(bash ./long_job.sh:*)",
         "Bash(sh long_job.sh:*)", "Bash(sh ./long_job.sh:*)", "Bash(ls:*)", "Bash(ls)", "Bash(cat:*)", "Bash(mkdir:*)",
         "Bash(mv:*)", "Bash(cp:*)", "Bash(rm step_:*)", "Bash(rm -f step_:*)", "Bash(rm ./step_:*)",
         "Bash(rm -f ./step_:*)", "Bash(rm -v step_:*)", "Bash(rm out/step_:*)", "Bash(rm -f out/step_:*)",
         "Bash(pkill -f long_job:*)", "Bash(kill:*)", "Bash(find . -name:*)", "Bash(head:*)", "Bash(wc:*)", "Read", "Glob",
         "Grep"]


def deny() -> list[str]:
    suite = str(HERE.parent)
    return [f"Read({suite}/**)", f"Bash(cat {suite}:*)", "Bash(rm -rf /:*)", "Bash(rm -rf ~:*)"]


def items(part: str) -> list[dict]:
    return ITEMS[f"part_{part}"]["items"]


def voice_for(item_id: str) -> str:
    return random.Random(f"{SEED}:{item_id}").choice(corpus.voices())


def clips() -> dict[str, tuple[str, str]]:
    from core import user

    out = {i["id"]: (i["text"], voice_for(i["id"])) for part in ("a", "b") for i in items(part)}
    for v in corpus.voices():
        for slot, line in user.LINES.items():
            out[f"answer:{slot}:{v}"] = (line, v)
    return out


class Replies:
    """The scripted user's ears and its side of a clarification: each finished output span is recognized once (the
    same Whisper that scores it); a question gets its slot's line in the item's voice, at most twice per item.
    Clarifications are counted, never penalized."""

    def __init__(self, adapter, pcm: dict, voice: str, wants_action: bool, fact: str | None = None, asr=None):
        self.adapter, self.pcm, self.voice, self.wants, self.fact = adapter, pcm, voice, wants_action, fact
        self.asr = asr or audio.transcribe
        self.heard: dict[float, tuple[float, float, str]] = {}
        self.made: list[dict] = []

    def poll(self, since: float, zero: float) -> None:
        from core import user
        from bargein import facts

        if not hasattr(self.adapter, "frames"):
            return
        for a, b in audio.spans(self.adapter.frames(), since=since):
            if a in self.heard or now() - b < 1.2:
                continue
            text = self.asr(audio.cut(self.adapter.frames(), a, b))
            self.heard[a] = (a, b, text)
            if len(self.made) >= 2 or not user.is_question(text) or (self.fact and facts.states(self.fact, text)):
                continue
            slot, line = user.answer(text, self.wants)
            key = "yes" if line == user.LINES["yes"] else "no" if line == user.LINES["no"] else "generic"
            s, e = self.adapter.say(self.pcm[f"answer:{key}:{self.voice}"], audio.RATE)
            self.made.append({"question": text, "slot": slot, "line": line, "t": round(s - zero, 3)})
            return

    def stated_at(self) -> float | None:
        from bargein import facts

        ends = [b for a, b, text in self.heard.values() if self.fact and facts.states(self.fact, text)]
        return min(ends) if ends else None


# ---------- the plan ----------

def plan(adapters: list[str], smoke: bool, only: str | None = None) -> list[dict]:
    rng = random.Random(SEED)
    runs = []
    for part, arms in (("a", ARMS_A), ("b", ARMS_B)):
        pool = items(part)
        if smoke:
            pool = [pool[0]] if part == "a" else [pool[0]]
        order = pool[:]
        rng.shuffle(order)
        nulls = {i["id"] for i in rng.sample(pool, min(NULL_A, len(pool)))} if part == "a" else set()
        for item in order:
            arm_order = [a for a in arms if a in adapters and (a != "null" or item["id"] in nulls or smoke)]
            rng.shuffle(arm_order)
            for arm in arm_order:
                runs.append({"part": part, "item": item["id"], "arm": arm, "k": 0})
    if not smoke:
        for part, n in (("a", REPEAT_A), ("b", REPEAT_B)):
            for item in random.Random(f"{SEED}:repeat:{part}").sample(items(part), n):
                for arm in ("pointe", "llm-router"):
                    if arm in adapters:
                        runs.append({"part": part, "item": item["id"], "arm": arm, "k": 1})
    if only:
        import fnmatch

        runs = [r for r in runs if fnmatch.fnmatch(r["item"], only)]
    return runs


def estimate(run: dict) -> float:
    return EST_REPEAT[run["part"]] if run["k"] else EST[(run["part"], run["arm"])]


def measured() -> dict[str, float]:
    """Twice the mean computed cost of an arm's runs so far in the ledger (smoke and debug included), per arm."""
    by: dict[str, list[float]] = {}
    for r in ledger.rows():
        if r.get("benchmark") == BENCH and r.get("item") != "preflight":
            by.setdefault(r["arm"], []).append(r["usd"])
    return {arm: 2 * sum(v) / len(v) for arm, v in by.items() if v}


def trim(runs: list[dict], left: float, cost=None) -> tuple[list[dict], list[str]]:
    """The written trim order when the cap is short: repeats first, then Part B naive. `cost` prices one run (the
    design's estimates by default; the runner passes twice the measured mean where the ledger has one)."""
    cost = cost or estimate
    trimmed = []
    for label, drop in (("repeats", lambda r: r["k"] > 0), ("part B naive", lambda r: r["part"] == "b" and r["arm"] == "naive")):
        if sum(cost(r) for r in runs) <= left:
            break
        runs = [r for r in runs if not drop(r)]
        trimmed.append(label)
    return runs, trimmed


# ---------- one run ----------

def make_adapter(arm: str):
    if arm == "keyboard":
        from adapters.keyboard import Keyboard
        return Keyboard()
    if arm == "null":
        from adapters.null import Null
        return Null()
    if arm == "naive":
        from adapters.naive import Naive
        return Naive()
    if arm == "llm-router":
        from adapters.llm_router import LlmRouter
        return LlmRouter()
    if arm == "pointe":
        from adapters.pointe import Pointe
        return Pointe()
    if arm == "echo":
        from adapters.echo import Echo
        return Echo()
    raise SystemExit(f"unknown adapter {arm}")


def job_alive(root: Path) -> bool:
    out = subprocess.run(["pgrep", "-f", "long_job"], capture_output=True, text=True).stdout.split()
    for pid in out:
        cwd = subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True, text=True).stdout
        if any(line[1:].startswith((str(root), "/private" + str(root))) for line in cwd.splitlines() if line.startswith("n")):
            return True
    return False


def _flat(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def pty_time(agent: agent_mod.AgentPty, since: float, text: str, fact: str) -> tuple[float | None, str]:
    """When the sentence that states the fact first showed on the terminal, from the pty's own byte times."""
    from bargein import facts

    sentence = next((s for s in __import__("re").split(r"(?<=[.!?\n])\s+", text) if facts.states(fact, s)), text)
    probe = _flat(sentence)[:24]
    if not probe:
        return None, ""
    acc = ""
    for t, chunk in list(agent.chunks):
        if t < since:
            continue
        acc += _flat(chunk)
        if probe in acc:
            return t, sentence
    return None, sentence


def wait_for_load(limit: float = 120.0) -> float:
    """Waits (up to `limit` s) for the 1-minute load average to fall under the flag line; returns the seconds waited.
    Other work on the machine is not ours to stop: a row that still starts above the line is flagged."""
    began = time.time()
    while runner.load() > runner.LOAD_FLAG and time.time() - began < limit:
        time.sleep(10)
    return round(time.time() - began, 1)


def run_one(run: dict, clips_pcm: dict, args, results: runner.Results, run_id: str, kind: str,
            audio_ok: bool, asr=None, waited: float = 0.0) -> dict:
    asr = asr or audio.transcribe
    part, arm = run["part"], run["arm"]
    item = next(i for i in items(part) if i["id"] == run["item"])
    meta = ITEMS[f"part_{part}"]
    root = Path("/tmp/pccb") / run_id / f"{item['id']}-{arm}-{run['k']}"
    runner.check_state_dir(root)
    shutil.rmtree(root, ignore_errors=True)
    repo = root / meta["session"]
    shutil.copytree(HERE / meta["fixture"], repo)
    subprocess.run(["git", "init", "-q"], cwd=repo)
    subprocess.run(["git", "-c", "user.name=bench", "-c", "user.email=bench@example.invalid", "add", "-A"], cwd=repo)
    subprocess.run(["git", "-c", "user.name=bench", "-c", "user.email=bench@example.invalid", "commit", "-qm", "fixture"],
                   cwd=repo)
    env = RunEnv(root=root, port_base=args.port_base, setup=args.pointe_setup, mode=MODE, allow=ALLOW, deny=deny(),
                 voice=voice_for(item["id"]))
    pcm = clips_pcm[item["id"]]
    row = {"run_id": run_id, "time": datetime.now().astimezone().isoformat(timespec="seconds"),
           "repo_commit": runner.head_commit(), "pointe_commit": runner.product_commit(), "benchmark": BENCH,
           "item_version": ITEMS["version"], "part": part, "item": item["id"],
           "kind": item.get("kind") or item.get("fact"), "adapter": arm, "voice": env.voice if arm != "keyboard" else None,
           "noise": "none", "seed": SEED, "run_index": run["k"], "kind_of_run": kind, "load_start": runner.load(), "load_wait_s": waited,
           "audio_matches_lock": audio_ok, "status": "ok"}
    log: list[dict] = []
    adapter = make_adapter(arm)
    t0 = now()
    try:
        adapter.start({meta["session"]: repo}, env)
        if part == "a":
            row.update(_part_a(adapter, item, meta, repo, root, pcm, log, clips_pcm, env.voice))
        else:
            row.update(_part_b(adapter, item, meta, pcm, log, asr, clips_pcm, env.voice))
    except Exception as e:
        row["status"], row["error"] = "error", f"{type(e).__name__}: {str(e)[:300]}"
        log.append({"error": traceback.format_exc()[-2000:]})
    finally:
        if getattr(adapter, "agent", None):
            row["permission_mode"] = adapter.agent.permission_mode_seen()
            if row["permission_mode"] not in (None, MODE) and row["status"] == "ok":
                row["status"], row["error"] = "error", f"permission mode {row['permission_mode']}"
        try:
            row["versions"] = adapter.versions()
        except Exception as e:
            row["versions"] = {"error": str(e)[:100]}
        spend = []
        try:
            spend = [s.__dict__ for s in adapter.spend()]
        except Exception as e:
            log.append({"spend_error": str(e)[:200]})
        if getattr(adapter, "agent", None):
            log.append({"pty_tail": "".join(c for t, c in adapter.agent.chunks if t >= t0)[-6000:]})
            log.append({"agent_text": [(round(t - t0, 3), x[:400]) for t, x in adapter.agent.assistant_texts()],
                        "tool_uses": [{"t": round(u["t"] - t0, 3), "name": u["name"],
                                       "input": json.dumps(u["input"])[:300]} for u in adapter.agent.tool_uses()]})
        if arm == "pointe" and hasattr(adapter, "log"):
            log.append({"daemon_log_tail": "\n".join(line for line in adapter.log().splitlines()
                                                      if " Linking " not in line)[-60000:]})
        log.append({"events": [{"t": round(e.t - t0, 3), "kind": e.kind, "text": e.text[:300], "data": e.data}
                               for e in adapter.events()]})
        adapter.stop()
        killed = agent_mod.sweep(root)
        row["leftover_processes_killed"] = len(killed)
        row["spend"] = spend
        row["spend_usd"] = round(sum(s["usd"] for s in spend), 6)
        row["load_end"] = runner.load()
        row["load_flag"] = max(row["load_start"], row["load_end"]) > runner.LOAD_FLAG
        row["wall_s"] = round(now() - t0, 1)
        ledger.record(BENCH, run_id, item["id"], arm, kind, spend)
        results.append("rows.jsonl", row)
        results.append("events.jsonl", {"run_id": run_id, "item": item["id"], "adapter": arm, "k": run["k"], "log": log})
        results.append("spend.jsonl", {"item": item["id"], "adapter": arm, "k": run["k"], "kind": kind, "spend": spend})
        shutil.rmtree(root, ignore_errors=True)  # the config folder holds the session's cached key approval
    return row


def _part_a(adapter, item, meta, repo, root, pcm, log, clips_pcm, voice) -> dict:
    watch = runner.FileWatcher(repo)
    try:
        t_job = adapter.setup_type(meta["job"])
        trigger = None
        while now() - t_job < 120:
            if meta["trigger_file"] in watch.seen:
                trigger = watch.seen[meta["trigger_file"]]
                break
            time.sleep(0.02)
        ok, why = check.setup_ok([u for u in adapter.agent.tool_uses() if u["t"] >= t_job], trigger)
        if not ok:
            return {"status": "setup_failed", "setup_failed": why}
        t_act = now()
        if adapter.name == "keyboard":
            first = None
            for k in item["keyboard"]["keys"]:
                at = adapter.key(k)
                first = first or at
                time.sleep(0.6)
            if item["keyboard"]["text"]:
                at = adapter.type(item["keyboard"]["text"])
                first = first or at
            speech_start = speech_end = first
        else:
            speech_start, speech_end = adapter.say(pcm, audio.RATE)
            speech_end -= 0.0
        replies = Replies(adapter, clips_pcm, voice, item["kind"] != "backchannel")
        while now() - speech_end < 150:
            time.sleep(0.25)
            if adapter.name not in ("keyboard", "null"):
                replies.poll(speech_end - 0.5, speech_end)
            idle = adapter.idle_since(t_job) is not None
            quiet = not (hasattr(adapter, "speaking") and adapter.speaking())
            settled = now() - watch.last_change >= 6
            if now() - speech_end >= 8 and idle and quiet and settled and not job_alive(root):
                break
        capped = now() - speech_end >= 150
        final = watch.present()
        spoken = []
        if hasattr(adapter, "frames"):
            for a, b in audio.spans(adapter.frames(), since=t_job):
                spoken.append({"t": round(a - speech_end, 3), "end": round(b - speech_end, 3),
                               "text": audio.transcribe(audio.cut(adapter.frames(), a, b))})
        log.append({"files": {p: round(t - speech_end, 3) for p, t in sorted(watch.seen.items())},
                    "final": sorted(final), "spoken": spoken, "replies": replies.made})
        scored = check.part_a(item["kind"], dict(watch.seen), final, speech_end)
        return {**scored, "clarifications": len(replies.made), "status": "capped" if capped else "ok", "trigger_to_speech_start": round(speech_start - trigger, 3),
                "speech_s": round(speech_end - speech_start, 3), "trigger_at_s": round(trigger - t_job, 3)}
    finally:
        watch.stop()


def _part_b(adapter, item, meta, pcm, log, asr, clips_pcm, voice) -> dict:
    t_setup = adapter.setup_type(meta["setup"])
    while now() - t_setup < 120 and adapter.idle_since(t_setup) is None:
        time.sleep(0.2)
    if adapter.idle_since(t_setup) is None:
        return {"status": "setup_failed", "setup_failed": "the agent did not finish reading the status file"}
    # The question waits until the arm has said what it says about the setup turn: at least 8 s after the turn ended
    # and 6 s of silence (Pointe reports a finished turn a few seconds after it ends). The same rule in every arm.
    done = adapter.idle_since(t_setup)
    while now() - done < 40 and (now() - done < SETTLE_B or (hasattr(adapter, "frames") and (
            adapter.speaking() or audio.spans(adapter.frames(), since=now() - QUIET_B)))):
        time.sleep(0.2)
    if adapter.name == "keyboard":
        speech_end = adapter.type(item["text"])
    else:
        _, speech_end = adapter.say(pcm, audio.RATE)
    replies = Replies(adapter, clips_pcm, voice, True, item["fact"], asr)
    while now() - speech_end < WINDOW_B:
        time.sleep(0.2)
        if adapter.name != "keyboard":
            replies.poll(speech_end - 0.5, speech_end)
        if adapter.name == "keyboard":
            done = adapter.idle_since(speech_end)
            if done is not None and now() - done > 1.0:
                break
            continue
        stated = replies.stated_at()  # an answer that is never right runs to the end of the window: it may come late
        if stated is not None and now() - stated >= 1.0:
            break
    utterances = []
    if adapter.name == "keyboard":
        for t_seen, text in adapter.agent.assistant_texts(speech_end):
            t_pty, sentence = pty_time(adapter.agent, speech_end, text, item["fact"])
            utterances.append((t_pty or t_seen, t_pty or t_seen, text))
            log.append({"keyboard_text": text[:400], "pty_match": t_pty is not None,
                        "t_seen": round(t_seen - speech_end, 3), "t_pty": round(t_pty - speech_end, 3) if t_pty else None})
    else:
        for a, b in audio.spans(adapter.frames(), since=speech_end - 0.5):
            known = replies.heard.get(a)
            text = known[2] if known and abs(known[1] - b) < 0.05 else asr(audio.cut(adapter.frames(), a, b))
            utterances.append((a, b, text))
        log.append({"spoken": [{"t": round(a - speech_end, 3), "end": round(b - speech_end, 3), "text": x}
                               for a, b, x in utterances]})
    log.append({"replies": replies.made})
    scored = check.part_b(item["fact"], speech_end, utterances, WINDOW_B)
    scored["clarifications"] = len(replies.made)
    if adapter.name == "keyboard":
        scored["first_output"] = None  # a different quantity: the keyboard arm is time to correct text
    return {**scored, "measure": "text" if adapter.name == "keyboard" else "audio"}


def cleanup(run_id: str, port_base: int) -> dict:
    """Every agent, daemon and child this run started is gone: a sweep of the run folder, then anything still
    listening on the run's ports that is Pointe's daemon from /tmp. Returns what it had to kill."""
    swept = agent_mod.sweep(Path("/tmp/pccb") / run_id)
    killed = []
    for port in range(port_base, port_base + 2):
        pids = subprocess.run(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout.split()
        for pid in pids:
            cmd = subprocess.run(["ps", "-o", "command=", "-p", pid], capture_output=True, text=True).stdout
            if "/tmp/pccb/" in cmd or "daemon.py" in cmd:
                subprocess.run(["kill", "-9", pid])
                killed.append(int(pid))
    listening = subprocess.run(["lsof", "-t", f"-iTCP:{port_base}-{port_base + 99}", "-sTCP:LISTEN"],
                               capture_output=True, text=True).stdout.split()
    return {"swept": len(swept), "daemons_killed": len(killed), "still_listening_in_range": len(listening)}


# ---------- the command ----------

def main(args) -> int:
    if args.workers != 1:
        raise SystemExit("bargein runs with --workers 1: local Whisper, Kokoro and parallel workers corrupt latency")
    runner.check_ports(args.port_base)
    assert all(i.get("id") for p in ("a", "b") for i in items(p)) and ITEMS["canary"] == CANARY, "items or canary"
    adapters = args.adapter.split(",") if args.adapter else ARMS_A
    runs = plan(adapters, args.smoke, args.items)
    kind = "smoke" if args.smoke else ("debug" if args.debug else "paid")
    left = CAP_USD - ledger.spent(BENCH)
    seen = measured()
    priced = lambda r: seen.get(r["arm"], estimate(r))  # noqa: E731
    runs, trimmed = trim(runs, left, priced) if kind == "paid" else (runs, [])
    est = sum(priced(r) for r in runs)
    print(f"bargein: {len(runs)} runs, estimated ${est:.2f}; ${left:.2f} left of ${CAP_USD:.2f}"
          + (f"; trimmed: {', '.join(trimmed)}" if trimmed else ""))
    if args.dry_run:
        for r in runs:
            print(f"  part {r['part']} {r['item']} {r['arm']:<10} run {r['k']}  ~${estimate(r):.3f}")
        return 0
    freeze = runner.frozen()
    if kind == "paid":
        if not freeze:
            raise SystemExit("commit FROZEN.json before the first paid row (run.py freeze, then git commit)")
        if freeze["pointe_commit"] != runner.product_commit():
            raise SystemExit("Pointe changed since FROZEN.json: a new freeze, labelled 'after changes'")
    run_id = args.resume or f"bargein-{datetime.now().strftime('%Y%m%d-%H%M%S')}{'-smoke' if args.smoke else ''}"
    probe = agent_mod.preflight(Path("/tmp/pccb") / f"preflight-{run_id}", MODE)
    ledger.record(BENCH, run_id, "preflight", "probe", kind, [{"vendor": "anthropic:agent", "usd": probe["usd"],
                                                               "how": "metered", "detail": "claude -p probe"}])
    results = runner.Results(run_id)
    done = set()
    if args.resume and (results.dir / "rows.jsonl").exists():
        done = {(r["part"], r["item"], r["adapter"], r["run_index"])
                for r in map(json.loads, (results.dir / "rows.jsonl").read_text().splitlines())}
    pcm, audio_ok = corpus.render(clips(), HERE / "audio.lock")
    audio.transcribe(pcm[items("b")[0]["id"]])  # load the recognizer before the first timed run
    meta = {"run_id": run_id, "benchmark": BENCH, "cap_usd": CAP_USD, "seed": SEED, "kind": kind, "workers": 1,
            "trimmed": trimmed, "planned": len(runs), "estimated_usd": round(est, 3),
            "design_estimate_usd": round(sum(estimate(r) for r in runs), 3), "measured_cost_per_run_x2": seen, "load_flag": runner.LOAD_FLAG,
            "window_b_s": WINDOW_B, "claude_code": agent_mod.claude_version(), "agent_model": agent_mod.MODEL,
            "permission_mode": MODE, "frozen": freeze, "started": datetime.now().astimezone().isoformat(timespec="seconds"),
            "audio_matches_lock": audio_ok, "preflight": probe}
    results.write("run.json", meta)
    for n, r in enumerate(runs):
        if (r["part"], r["item"], r["arm"], r["k"]) in done:
            continue
        try:
            ledger.gate(BENCH, CAP_USD, 1, MAX_RUN_USD)
        except ledger.BudgetExceeded as e:
            print(f"stopped at the cap: {e}")
            meta["stopped_at_cap"] = n
            break
        waited = wait_for_load(LOAD_WAIT[r["part"]])
        row = run_one(r, pcm, args, results, run_id, kind, audio_ok, waited=waited)
        brief = {k: row.get(k) for k in ("status", "halted", "overshoot", "time_to_halt", "redirected", "false_stop",
                                          "correct", "first_output", "ttca", "spend_usd", "load_start", "error")
                 if row.get(k) is not None}
        print(f"[{n + 1}/{len(runs)}] {r['part']} {r['item']} {r['arm']} k={r['k']}: {json.dumps(brief)}", flush=True)
    meta["leftover_at_end"] = cleanup(run_id, args.port_base)
    meta["finished"] = datetime.now().astimezone().isoformat(timespec="seconds")
    meta["spent_usd_benchmark_total"] = ledger.spent(BENCH)
    results.write("run.json", meta)
    print(f"bargein: ledger total ${ledger.spent(BENCH):.2f} of ${CAP_USD:.2f}; results in {results.dir.relative_to(HERE.parents[2])}")
    return 0
