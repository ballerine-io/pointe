"""Fleet dialogues: one conversation with 8, 15 or 30 sessions on two machines, run by three harnesses (Claude Code,
Codex, OpenCode), typed into the voice. Paid with the real models; free with stubbed ones.

    uv run --locked python -I bench/fleet/dialogue.py 8 --models stub                     a dry run: free
    uv run --locked python -I bench/fleet/dialogue.py 15 --arm fleet-on --budget-usd 126 --headroom-usd 2

The fleet: two machines (the voice's own and one node), the sessions split between them, each session's harness in
turn Claude Code, Codex, OpenCode, so each machine runs all three. Claude Code sessions are the simulator's stand-ins
(sim.Scripted); Codex and OpenCode sessions live in each machine's own fake Codex daemon and OpenCode service
(vendors.py), reached by the voice's real adapters. Two sessions, one on each machine, ended their last turn with a
question; every other one is idle.

The steps, and what passes (written before any paid row):
- overview: "What's going on in all my sessions?" The reply gives each machine's number of sessions, and names both
  sessions that wait on a question.
- name (x3, one session of each harness, at least one on the other machine): "Tell <name> to <task>." The request
  reaches that session and no other.
- topic (x3, three other sessions, one of each harness): "Tell the session working on the <topic> to <task>." The same.
- approvals: one session of each harness, on both machines, asks to run a command, all three at once. All three are
  pending on the page at once, and each is read out. The user taps allow on the one read out last (the page's button:
  a typed "yes" never answers an approval), six taps at most. Each of the three is allowed, none is denied, and no
  other approval is answered.
- flood: every session but the three that asked and the two that wait ends a turn within ten seconds. Nothing is
  lost (each is named in a spoken line or in the held list) and at most four spoken lines are reports (the burst bar).

A step that crashed is a failed step. The dialogue passes when every step passes.
"""

import argparse
import difflib
import hashlib
import json
import math
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen  # noqa: E402
import run as bench  # noqa: E402
import score  # noqa: E402
import sim  # noqa: E402
import vendors  # noqa: E402

SIZES = (8, 15, 30)
MACHINES = ("studio", "avi-box")
HARNESSES = ("claude-code", "codex", "opencode")
SEED = 20261128
FLOOD_SECS = 10.0
MAX_TAPS = 6
READ_OUT_SECS = 45.0  # how long the user waits to hear a pending approval named before tapping a card
REPORT_LINES_MAX = 4  # the burst bar's
TASKS = ["add a test for the empty input case", "rename the helper to something clearer", "run the linter and fix what it finds",
         "add a docstring to the main function", "remove the unused imports", "log the retry count"]
COMMAND = ("git status --short", "List changed files")
NUMBER_WORDS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen".split()


def _apart(a: str, b: str) -> bool:
    """gen._apart, and not alike by the voice's own rule for names on two machines (sessions._alike: a word
    similarity of 0.8 or more), which renames a session at join ("clover", "riddle" in the 10x30 fleet)."""
    return gen._apart(a, b) and difflib.SequenceMatcher(None, a, b).ratio() < 0.8


def fleet(n: int, seed: int = SEED) -> dict:
    """The fleet of a dialogue with n sessions: the same from the same seed on any machine."""
    assert n in SIZES
    rng = random.Random(f"{seed}/dialogue/{n}")
    pool: list[str] = []
    for name in rng.sample(gen.NAMES, len(gen.NAMES)):
        if all(_apart(name, kept) for kept in [*pool, *(m.split("-")[0] for m in MACHINES)]):
            pool.append(name)
    firsts = rng.sample(gen.TOPIC_A, n)  # a topic's first word is its own: "the coupon ledger" fits one session
    here = math.ceil(n / 2)
    sessions = []
    for i in range(n):
        harness = HARNESSES[i % 3]
        sid = f"ses_{rng.getrandbits(128):032x}" if harness == "opencode" else str(uuid.UUID(int=rng.getrandbits(128), version=4))
        topic = f"{firsts[i]} {rng.choice(gen.TOPIC_B)}"
        a, b = topic.split()
        sessions.append({"id": sid, "machine": MACHINES[0] if i < here else MACHINES[1], "name": pool[i], "harness": harness,
                         "shared_name": False, "twin": None, "topic": topic, "goal": rng.choice(gen.GOALS).format(topic=topic),
                         "files": [f"{a}_{b}.py", f"test_{a}_{b}.py", "README.md"], "state": "idle", "roles": [],
                         "finish_at": None})

    def pick(role: str, harness: str, machine: str | None, apart: tuple[str, ...]) -> dict:
        """A session of that harness with none of the `apart` roles, on that machine when one is free there."""
        free = [s for s in sessions if s["harness"] == harness and not set(s["roles"]) & set(apart)]
        chosen = rng.choice([s for s in free if s["machine"] == machine] or free)
        chosen["roles"].append(role)
        return chosen

    # At 8 sessions the parts cannot all be apart: a session sent a request earlier may ask for an approval later.
    # One that waits on a question is never sent anything, and no session is both sent by name and by topic.
    for harness, machine in ((HARNESSES[0], MACHINES[1]), (HARNESSES[1], MACHINES[0])):
        s = pick("asks", harness, machine, ("asks",))
        s["state"] = "asks"
        s["question"] = f"Should the {s['topic']} keep the old records, or may I drop them?"
    for harness, machine in zip(HARNESSES, (None, MACHINES[1], MACHINES[0])):
        pick("name", harness, machine, ("asks", "name"))
    for harness, machine in zip(HARNESSES, (None, None, MACHINES[1])):
        pick("topic", harness, machine, ("asks", "name", "topic"))
    for harness, machine in zip(HARNESSES, (MACHINES[0], MACHINES[1], None)):
        pick("approves", harness, machine, ("asks", "approves"))
    flood = [s for s in sessions if "approves" not in s["roles"] and "asks" not in s["roles"]]
    for s in flood:
        s["finish_at"] = round(rng.uniform(0, FLOOD_SECS), 2)
    described = {"size": f"dialogue-{n}", "seed": seed, "machines": list(MACHINES), "voice_machine": MACHINES[0],
                 "sessions": sessions}
    described["sha256"] = hashlib.sha256(json.dumps(described, sort_keys=True).encode()).hexdigest()
    return described


def steps(described: dict) -> list[dict]:
    """The typed lines, in order, with what each expects."""
    rng = random.Random(described["sha256"])
    tasks = iter(rng.sample(TASKS, len(TASKS)))
    by_role = {role: [s for s in described["sessions"] if role in s["roles"]] for role in ("name", "topic")}
    out = [{"id": "overview", "kind": "overview", "text": "What's going on in all my sessions?", "expect": {}}]
    for s in by_role["name"]:
        out.append({"id": f"name-{s['harness']}", "kind": "name", "text": f"Tell {s['name']} to {next(tasks)}.",
                    "expect": {"action": "send", "session": s["id"]}})
    for s in by_role["topic"]:
        out.append({"id": f"topic-{s['harness']}", "kind": "topic", "text": f"Tell the session working on the {s['topic']} to {next(tasks)}.",
                    "expect": {"action": "send", "session": s["id"]}})
    return out


# ---------- the fleet with three harnesses ----------

class MixedNode(sim.Node):
    """A node whose environment points at its machine's own Codex daemon and OpenCode service."""

    def __init__(self, root: Path, name: str, voice: sim.Voice, extra: dict):
        super().__init__(root, name, voice)
        self.extra = extra

    def env(self) -> dict:
        return {**super().env(), **self.extra}


class MixedFleet(sim.FleetSim):
    """sim.FleetSim with Codex and OpenCode sessions next to the Claude Code stand-ins. `sessions` holds the stand-ins
    only; `others` the Codex and OpenCode sessions, by id."""

    def __init__(self, described: dict, root: Path, models: str = "stub", env: dict | None = None,
                 notes: Path | None = None, checkout: Path = sim.ROOT):
        super().__init__(described, root, models, env, None, checkout)  # no kept notes: the reader reads each run
        self.loop = vendors.Loop()
        self.codex: dict[str, vendors.CodexMachine] = {}
        self.opencode: dict[str, vendors.OpenCodeMachine] = {}
        self.folders: list[Path] = []
        self.others = {s["id"]: s for s in described["sessions"] if s["harness"] != "claude-code"}
        self.taken = {"codex": 0, "opencode": 0}
        self.hook_answers: dict[str, object] = {}
        self.asked: dict[str, tuple[str, object]] = {}  # session id -> (harness, request id)

    def _where(self, machine: str):
        return self.nodes.get(machine) or self.voice

    def _vendors(self, base_path: str) -> dict[str, dict]:
        envs = {}
        for m in self.described["machines"]:
            folder = Path(tempfile.mkdtemp(prefix="pv-", dir="/tmp"))  # a Unix socket's path fits about 100 bytes
            self.folders.append(folder)
            cx, oc = self.codex[m], self.opencode[m] = vendors.CodexMachine(folder / "cx.sock"), vendors.OpenCodeMachine()
            self.loop.run(cx.start())
            self.loop.run(oc.start())
            vendors.opencode_cli(folder / "bin", oc.url)
            (folder / "service.json").write_text(json.dumps({"password": "fleet-bench-fake-service"}))
            envs[m] = {"CODEX_CONTROL_SOCKET": str(folder / "cx.sock"), "OPENCODE_SERVICE_FILE": str(folder / "service.json"),
                       "PATH": f"{folder / 'bin'}:{base_path}"}
        return envs

    def up(self) -> "MixedFleet":
        d, at = self.described, time.monotonic()
        envs = self._vendors(self.voice.env()["PATH"])
        for s in d["sessions"]:  # the vendors hold their sessions before any adapter asks
            if s["harness"] != "claude-code":
                self._seed_folder(s)
            if s["harness"] == "codex":
                self.codex[s["machine"]].add(s["id"], str(self._cwd(s)), s["name"], f"{s['goal']} Start with {s['files'][0]}.", self._last(s))
            elif s["harness"] == "opencode":
                self.opencode[s["machine"]].add(s["id"], s["name"], f"{s['goal']} Start with {s['files'][0]}.", self._last(s))
        self.voice.extra.update(envs[d["voice_machine"]])
        self.voice.listen()
        self.voice.start()
        self.timing["voice_up_secs"] = round(time.monotonic() - at, 1)
        at = time.monotonic()
        for name in d["machines"][1:]:
            node = self.nodes[name] = MixedNode(self.root, name, self.voice, envs[name])
            node.join()
            node.launch()
        for node in self.nodes.values():
            node.up()
        until_linked = lambda: sum(bool(n.get("online")) for n in self.voice.get("/voice/hub/nodes")["nodes"]) == len(self.nodes)  # noqa: E731
        sim.until("every node is linked", until_linked, 90, every=0.25)
        self.timing["nodes_up_secs"] = round(time.monotonic() - at, 1)
        at = time.monotonic()
        for s in d["sessions"]:
            if s["harness"] == "claude-code":
                session = self.sessions[s["id"]] = sim.Scripted(self.root / "work" / s["machine"], self.sockets, s)
                session.seed()
        for s in d["sessions"]:
            where = self._where(s["machine"])
            if s["harness"] == "claude-code":
                where.register(self.sessions[s["id"]])
                continue
            status, body = where.call("/voice/register", {
                "id": s["id"], "name": s["name"], "name_given": True, "cwd": str(self._cwd(s)), "pid": 0, "harness": s["harness"],
                "harness_data": {"title": s["name"]}, "transcript": str(where.state / "harness" / s["harness"] / f"{s['id']}.jsonl")})
            assert status == 200, (s["machine"], s["harness"], status, body)
        sim.until("every session is on the voice", lambda: len(self.registry()) == len(d["sessions"]), 180, every=0.5)
        self.timing["sessions_joined_secs"] = round(time.monotonic() - at, 1)
        return self

    def _cwd(self, s: dict) -> Path:
        return self.root / "work" / s["machine"] / s["name"]

    def _last(self, s: dict) -> str:
        return s.get("question") or (f"The work on the {s['topic']} is done: the change is in {s['files'][0]} and all 14 tests "
                                     "pass. Nothing is waiting on you.")

    def _seed_folder(self, s: dict) -> Path:
        """A Codex or OpenCode session's folder: a git index with its files, as a Claude Code stand-in's (Scripted.seed)."""
        cwd = self._cwd(s)
        cwd.mkdir(parents=True, exist_ok=True)
        for name in s["files"]:
            (cwd / name).write_text(f"# {s['topic']}\n")
        env = {"HOME": str(cwd), "PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1"}
        for cmd in (["git", "init", "-q"], ["git", "add", "-A"]):
            subprocess.run(cmd, cwd=cwd, env=env, check=True, capture_output=True, timeout=30)
        return cwd

    def settle_notes(self, timeout: float = 120.0) -> dict:
        """No kept notes: a Codex or OpenCode session's record is written by its watcher, which runs during a call, so the
        reader reads every session once the call is up (notes_ready)."""
        return {"with_notes": len(self.noted()), "sessions": len(self.described["sessions"])}

    def notes_ready(self, watch, timeout: float = 120.0) -> dict:
        """After the call opens, the user starts once the voice has notes on every session, or after `timeout`: how
        long that took, and how many it had."""
        began, n = time.time(), len(self.described["sessions"])
        while len(self.noted()) < n and time.time() - began < timeout:
            watch.poll()
            time.sleep(0.25)
        watch.settle(least=1.0, most=60.0)
        return {"secs": round(time.time() - began, 1), "with_notes": len(self.noted()), "sessions": n}

    def start_states(self) -> None:
        """Nothing works at the start of a dialogue: the two that wait ended their turn with a question."""

    def deliveries(self) -> list[dict]:
        out = super().deliveries()
        for harness, fakes in (("codex", self.codex), ("opencode", self.opencode)):
            sent = [x for fake in fakes.values() for x in list(fake.sent)]
            sent.sort(key=lambda x: x["at"])
            for x in sent[self.taken[harness]:]:
                out.append({"session": x["session"], "at": x["at"], "text": x["text"][:2000]})
            self.taken[harness] = len(sent)
        return out

    def finish(self, sid: str) -> str:
        """The session ends a turn: its final message."""
        if sid in self.sessions:
            return self.sessions[sid].finish()
        s = self.others[sid]
        text = f"The {s['topic']} work is finished: {s['files'][0]} is changed and its tests pass."
        fake = (self.codex if s["harness"] == "codex" else self.opencode)[s["machine"]]
        self.loop.run(fake.finish(sid, text))
        return text

    def ask(self, sid: str) -> None:
        """The session asks to run COMMAND, as its harness does."""
        command, reason = COMMAND
        if sid in self.sessions:
            s = next(x for x in self.described["sessions"] if x["id"] == sid)
            body = {"session_id": sid, "hook_event_name": "PermissionRequest", "tool_name": "Bash",
                    "tool_input": {"command": command, "description": reason}}
            where = self._where(s["machine"])

            def hook() -> None:
                try:
                    self.hook_answers[sid] = where.call("/voice/permission-hook", body, timeout=900)
                except OSError as e:
                    self.hook_answers[sid] = ("error", str(e))

            threading.Thread(target=hook, daemon=True).start()
            self.asked[sid] = ("claude-code", None)
            return
        s = self.others[sid]
        fake = (self.codex if s["harness"] == "codex" else self.opencode)[s["machine"]]
        self.asked[sid] = (s["harness"], self.loop.run(fake.ask(sid, command, reason)))

    def verdicts(self) -> dict[str, str | None]:
        """Each session that asked, and what the voice answered: allow, deny, or None (not yet)."""
        out = {}
        for sid, (harness, rid) in self.asked.items():
            if harness == "claude-code":
                got = self.hook_answers.get(sid)
                text = json.dumps(got) if got is not None else ""
                out[sid] = "allow" if '"behavior": "allow"' in text else "deny" if '"behavior": "deny"' in text else None
            else:
                s = self.others[sid]
                answer = (self.codex if harness == "codex" else self.opencode)[s["machine"]].answers.get(rid)
                decision = (answer or {}).get("decision")
                out[sid] = None if decision is None else "allow" if decision in ("accept", "once") else "deny"
        return out

    def stray_answers(self) -> int:
        """Approval answers the vendors got for requests no session of this dialogue made."""
        made = {rid for harness, rid in self.asked.values() if rid is not None}
        return sum(1 for fakes in (self.codex, self.opencode) for fake in fakes.values() for rid in fake.answers if rid not in made)

    def close(self) -> None:
        try:
            super().close()
        finally:
            for fake in [*self.codex.values(), *self.opencode.values()]:
                try:
                    self.loop.run(fake.stop(), timeout=10)
                except Exception:
                    pass
            self.loop.close()
            for folder in self.folders:
                shutil.rmtree(folder, ignore_errors=True)


# ---------- scoring ----------

def routed(row: dict, expect: dict) -> bool:
    return sorted({d["session"] for d in row["deliveries"]}) == [expect["session"]]


def overview_ok(said: list[str], described: dict, names: dict[str, str]) -> tuple[bool, str]:
    """Each machine's number of sessions, and both waiting sessions named (by the dataset's name or the voice's)."""
    text = " ".join(said)
    low = text.lower()
    missing = []
    for m in described["machines"]:
        n = sum(s["machine"] == m for s in described["sessions"])
        if not any(f"{form} session" in low for form in ({str(n)} | ({NUMBER_WORDS[n]} if n < len(NUMBER_WORDS) else set()))):
            missing.append(f"{n} sessions on {m}")
    for s in described["sessions"]:
        if "asks" in s["roles"] and not any(score.names(text, x) for x in {s["name"], names.get(s["id"], s["name"])}):
            missing.append(f"{s['name']} waits")
    return not missing, ", ".join(missing)


# ---------- the dialogue ----------

def run_dialogue(run: bench.Launch, seed: int) -> list[dict]:
    f: MixedFleet = run.fleet  # type: ignore[assignment]
    d = run.described
    names = run.manifest.get("names") or {}
    rows = []
    for n, step in enumerate(steps(d)):
        row = bench.turn_row(run, n, step, seed)
        row["kind"] = "dialogue_step"
        row["step"] = step["kind"]
        if step["kind"] == "overview":
            row["passed"], row["why"] = overview_ok(row["said"], d, names)
        else:
            row["passed"] = routed(row, step["expect"]) and not row.get("error")
            row["why"] = "" if row["passed"] else f"sent to {sorted({x['session'] for x in row['deliveries']})}"
        run.write(row)
        rows.append(row)
        print(f"  {step['id']:<20} {'pass' if row['passed'] else 'FAIL'} {row['why']} said {' '.join(row['said'])[:140]!r}", flush=True)

    # three approvals at once: each read out, then the page's tap on the one just read (a typed yes never answers an
    # approval: daemon._user_text)
    w = run.watch
    seen = {"deliveries": [], "calls": [], "said": []}
    askers = [s for s in d["sessions"] if "approves" in s["roles"]]
    called = {s["id"]: {s["name"], names.get(s["id"], s["name"])} for s in askers}
    t0 = time.time()
    for s in askers:
        f.ask(s["id"])
    w.settle(seen, least=6.0, most=90.0)
    on_page = {x["name"] for x in f.voice.status()["sessions"] if x.get("waiting") and x.get("request_id")}
    at_once = sum(bool(called[s["id"]] & on_page) for s in askers)
    taps, read_out, refused = 0, set(), []

    def named_pending() -> str | None:
        """The pending asker the voice named last."""
        for line in reversed([x["text"] for x in seen["said"]]):
            for sid, ns in called.items():
                if f.verdicts().get(sid) is None and any(score.names(line, n) for n in ns):
                    return sid
        return None

    while taps < MAX_TAPS and any(v is None for v in f.verdicts().values()):
        heard = time.time()
        while named_pending() is None and time.time() - heard < READ_OUT_SECS:  # the user waits to hear it
            got = w.poll()
            for k in got:
                seen[k] += got[k]
            time.sleep(sim.POLL_SECS)
        for line in [x["text"] for x in seen["said"]]:
            read_out |= {sid for sid, ns in called.items() if any(score.names(line, n) for n in ns)}
        waiting = {x["name"]: x["request_id"] for x in f.voice.status()["sessions"] if x.get("waiting") and x.get("request_id")}
        last = named_pending()
        name = next((n for n in called.get(last, ()) if n in waiting), None)
        if name is None:  # nothing pending was named: the user taps the first pending card
            name = next((n for s in askers if f.verdicts().get(s["id"]) is None for n in called[s["id"]] if n in waiting), None)
        taps += 1
        if name is None:
            w.settle(seen, least=3.0, most=20.0)
            continue
        status, answer = f.voice.call("/voice/approve", {"session": name, "request_id": waiting[name], "decision": "allow"})
        if status != 200:
            refused.append(f"{name}: {status} {answer}")
        w.settle(seen, least=3.0, most=60.0)
    time.sleep(2.0)  # the answer reaches the vendor or the hook after the tap
    for line in [x["text"] for x in seen["said"]]:
        read_out |= {sid for sid, ns in called.items() if any(score.names(line, n) for n in ns)}
    verdicts = f.verdicts()
    stray = f.stray_answers()
    row = {"kind": "dialogue_step", "step": "approvals", "run": run.id, "asked": {s["id"]: s["harness"] for s in askers},
           "pending_at_once": at_once, "read_out": sorted(read_out), "verdicts": verdicts, "taps": taps, "refused": refused,
           "stray_answers": stray, "said": [x["text"] for x in seen["said"]], "secs": round(time.time() - t0, 1)}
    row["passed"] = (len(verdicts) == 3 and all(v == "allow" for v in verdicts.values()) and not stray and at_once == 3
                     and len(read_out) == 3)
    row["why"] = "" if row["passed"] else (f"{at_once} of 3 pending at once, {len(read_out)} of 3 read out, verdicts "
                                           f"{sorted(str(v) for v in verdicts.values())}, stray {stray}, refused {refused}")
    run.write(row)
    rows.append(row)
    print(f"  {'approvals':<20} {'pass' if row['passed'] else 'FAIL'} {row['why']} after {taps} taps", flush=True)

    # a flood of reports
    seen = {"deliveries": [], "calls": [], "said": []}
    due = sorted((s["finish_at"], s["id"]) for s in d["sessions"] if s["finish_at"] is not None)
    t0, finals = time.time(), {}
    for at, sid in due:
        while time.time() - t0 < at:
            got = w.poll()
            for k in got:
                seen[k] += got[k]
            time.sleep(sim.POLL_SECS)
        finals[sid] = f.finish(sid)
    settled = w.settle(seen, least=FLOOD_SECS - (time.time() - t0) + 15, most=240.0)
    status = f.voice.status()
    held = [str(item) for item in ((status.get("held") or {}).get("items") or [])]
    by_id = {s["id"]: s for s in d["sessions"]}
    called = {sid: {by_id[sid]["name"], *([names[sid]] if names.get(sid) else [])} for sid in finals}
    spoken = [s["text"] for s in seen["said"]]
    told, kept, lost = score.burst_named(sorted(finals), spoken, held, called)
    lines = score.report_lines(spoken, called)
    row = {"kind": "dialogue_step", "step": "flood", "run": run.id, "finished": sorted(finals), "settled": settled,
           "spoken": spoken, "held": held, "named_in_speech": len(told), "named_in_held": len(kept), "lost": lost,
           "report_lines": lines, "by_harness": {h: sum(by_id[sid]["harness"] == h for sid in finals) for h in HARNESSES},
           "lost_by_harness": {h: sum(by_id[sid]["harness"] == h for sid in lost) for h in HARNESSES}}
    row["passed"] = not lost and lines <= REPORT_LINES_MAX
    row["why"] = "" if row["passed"] else f"{len(lost)} lost, {lines} report lines"
    run.write(row)
    rows.append(row)
    print(f"  {'flood':<20} {'pass' if row['passed'] else 'FAIL'} {len(finals)} finished: {lines} report lines, "
          f"{len(told)} said, {len(kept)} held, {len(lost)} lost", flush=True)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sessions", type=int, choices=SIZES)
    ap.add_argument("--arm", choices=["fleet-on", "fleet-off"], default="fleet-on")
    ap.add_argument("--models", choices=["real", "stub"], default="real")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--budget-usd", type=float, default=15.0)
    ap.add_argument("--headroom-usd", type=float, default=2.0)
    a = ap.parse_args()
    if a.models == "real":
        bench.gate(a.budget_usd, a.headroom_usd)
        bench.wait_for_load()
    described = fleet(a.sessions, a.seed)
    run = bench.Launch("dialogue", f"2m{a.sessions}", a.arm, a.models, bench.ROOT, described=described, fleet_class=MixedFleet)
    run.manifest["dialogue_seed"] = a.seed
    error = ""
    try:
        run.up()
        run.manifest["notes_ready"] = run.fleet.notes_ready(run.watch)
        print(f"  notes on {run.manifest['notes_ready']['with_notes']} of {a.sessions} sessions after "
              f"{run.manifest['notes_ready']['secs']} s", flush=True)
        rows = run_dialogue(run, a.seed)
        summary = {"kind": "dialogue", "run": run.id, "arm": run.arm, "sessions": a.sessions, "models": a.models,
                   "steps": {r.get("turn") or r["step"]: r["passed"] for r in rows}, "passed": all(r["passed"] for r in rows),
                   "fleet_on": bench.daemon_fleet(run.fleet)["fleet_on"]}
        run.write(summary)
        if not summary["passed"]:  # what the voice did, for the cause: synthetic sessions only
            run.out.mkdir(parents=True, exist_ok=True)
            (run.out / "voice-log-tail.txt").write_text(run.fleet.voice.log(400_000).replace(str(Path.home()), "~"))
        print(f"dialogue {a.sessions}: {'PASS' if summary['passed'] else 'FAIL'}", flush=True)
    except Exception as e:
        error = f"{type(e).__name__}: {str(e)[:300]}".replace(str(Path.home()), "~")
        run.write({"kind": "dialogue", "run": run.id, "arm": run.arm, "sessions": a.sessions, "models": a.models,
                   "steps": {}, "passed": False, "error": error})
    finally:
        run.close(error)


if __name__ == "__main__":
    main()
