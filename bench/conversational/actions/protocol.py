"""One item run of `actions`, the same steps for every arm:

1. Build the fixture in /tmp/pccb/<run-id>/<item-run>/ and assert the command can only reach that folder.
2. Start the arm (its agent session; Pointe also its daemon and call).
3. Set up: type the instruction and wait for a verified state. Prompt pending: a PermissionRequest for the command, in
   `default` mode. Working: the slow job has written step 3. Idle: the setup turn has ended. Otherwise `setup_failed`.
4. Wait until the harness is ready to listen (Pointe: its question has been read out), then play the one utterance.
5. Observe, read the file system, then the transcript and events; classify; record spend; kill everything.
"""

import os
import re
import time
from pathlib import Path

from actions import check, fixture
from core import agent as agentlib
from core import corpus, scrub

ROOT = Path(__file__).resolve().parents[3]
BENCH = ROOT / "bench" / "conversational"
INSTRUCTION = "Run exactly this shell command once and nothing else: `{cmd}`"
IDLE_SETUP = "Read notes.txt and reply with one short sentence saying what this repo is."
ALLOW_WORKING = ["Bash(./long_job.sh)", "Bash(./long_job.sh:*)", "Bash(sh ./long_job.sh)", "Bash(bash ./long_job.sh)",
                 "Bash(python3 -m unittest:*)", "Bash(python -m unittest:*)"]
SETUP_TIMEOUT = 90
OBSERVE = {"pending": 30, "working": 45, "idle": 20}
SETTLE = 3.0  # after the observation window, before the file system is read
DELIVERY_WAIT = 40  # a delivered request gets this long to run the tests


class SetupFailed(RuntimeError):
    pass


def _wait(cond, timeout: float, step: float = 0.3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        got = cond()
        if got:
            return got
        time.sleep(step)
    return None


def audit(facts: dict, folder: Path, plugin_allowed: bool) -> list[str]:
    """Tool inputs that name a path in the home folder (outside the item) or the benchmark's own files."""
    home, flagged = str(Path.home()), []
    for call in facts["calls"]:
        text = str(call["input"])
        for path in re.findall(r"(?:~|/)[\w.\-/~]+", text):
            real = os.path.realpath(os.path.expanduser(path))
            if real.startswith(str(BENCH)) or (real.startswith(home) and not (plugin_allowed and real.startswith(str(ROOT)))):
                flagged.append(call.get("name", "?"))
    return flagged


def run_one(item: dict, arm: str, adapter, env, run_index: int) -> dict:
    folder = env.folder
    folder.mkdir(parents=True, exist_ok=True)
    kind = item["kind"]
    fkind = kind if kind != "idle" else "run_tests"
    facts_before = fixture.build(fkind, folder)
    if problems := fixture.contained(fkind, folder):
        raise AssertionError(f"{item['id']}: the command could leave the item folder: {problems}")
    allow = ALLOW_WORKING if item["phase"] != "pending" else []
    agentlib.write_config(folder, allow, deny_reads=[str(BENCH)])
    command = fixture.COMMANDS.get(kind) if item["phase"] == "pending" else None
    row = {"setup": None, "ready_ok": None}
    try:
        adapter.start(env)
        t_setup = time.time()
        if item["phase"] == "pending":
            adapter.type(INSTRUCTION.format(cmd=command))
            head = " ".join(command.split()[:2])
            req = _wait(lambda: next((h for h in adapter.agent.hooks() if h.get("hook_event_name") == "PermissionRequest"
                                      and head in re.sub(r"\s+", " ", str((h.get("tool_input") or {}).get("command", "")))),
                                     None), SETUP_TIMEOUT)
            if not req:
                raise SetupFailed("the agent never asked to run the command")
            if req.get("permission_mode") != "default":
                raise SetupFailed(f"permission mode {req.get('permission_mode')}, not default")
            if fixture.state(kind, folder, facts_before)["ran"]:
                raise SetupFailed("the command ran before any answer")
            trigger = req["_t"]
        elif item["phase"] == "working":
            adapter.type(INSTRUCTION.format(cmd=fixture.COMMANDS["long_job"]))
            if not _wait(lambda: (folder / "repo" / "step_03.txt").exists(), SETUP_TIMEOUT):
                raise SetupFailed("the slow job did not start")
            trigger = time.time()
        else:
            adapter.type(IDLE_SETUP)
            if not _wait(lambda: [h for h in adapter.agent.hooks() if h.get("hook_event_name") == "Stop"
                                  and h["_t"] > t_setup], SETUP_TIMEOUT):
                raise SetupFailed("the setup turn did not end")
            trigger = time.time()
        row["setup_seconds"] = round(trigger - t_setup, 2)
        row["ready_ok"] = adapter.ready(item["phase"], trigger, 30 if item["phase"] == "pending" else
                                        (3 if item["phase"] == "working" else 10))
        if item["phase"] == "working" and fixture.state("long_job", folder, facts_before)["done"]:
            raise SetupFailed("the slow job ended before the utterance")
        pcm = corpus.load(item["id"])
        said_start, said_end = adapter.say(pcm, corpus.RATE, item)
        row["utterance_seconds"] = round(len(pcm) / corpus.RATE, 3)

        def settled():
            st = fixture.state(fkind if item["phase"] != "working" else "long_job", folder, facts_before)
            if item["phase"] == "pending":
                call = check.target_call(adapter.agent.facts(), command)
                return st["ran"] or (call and "decided_at" in call)
            if item["phase"] == "working":
                return st["done"]
            return False
        _wait(settled, OBSERVE[item["phase"]] + max(0, said_end - time.time()), 0.5)
        if item["phase"] == "idle":  # a delivery gets time to run the tests
            sent = lambda: [p for p in adapter.agent.facts()["prompts"] if p["t"] >= said_start - 0.5]  # noqa: E731
            if sent() or (folder / "repo" / ".tests_ran").exists():
                _wait(lambda: [h for h in adapter.agent.hooks() if h.get("hook_event_name") == "Stop"
                               and h["_t"] > said_end], DELIVERY_WAIT)
        time.sleep(SETTLE)
        fs = fixture.state(fkind if item["phase"] != "working" else "long_job", folder, facts_before)
        facts = adapter.agent.facts()
        events = [e.row() for e in adapter._events]
        verdict = check.classify(item, fs, facts, adapter.agent.typed, adapter.spoke_after(said_end - 0.5), events,
                                 said_start, said_end, command)
        hooks = adapter.agent.hooks()
        row.update(status="ok", **verdict, fs=fs, said_start=said_start, said_end=said_end,
                   audit=audit(facts, folder, arm == "pointe"),
                   requests=[{"t": h["_t"], "tool": h.get("tool_name"),
                              "command": str((h.get("tool_input") or {}).get("command", ""))[:120]}
                             for h in hooks if h.get("hook_event_name") == "PermissionRequest"])
        if row["audit"]:
            row["status"] = "invalid_out_of_tree"
        row["cost_slash"] = adapter.agent.cost() if not env.fake else 0.0
        row["usage"] = facts["usage"]
    except SetupFailed as e:
        row.update(status="setup_failed", why=str(e))
    finally:
        try:
            row["spend_extra"] = adapter.spend()
        except Exception as e:  # spend is reported even when a run broke
            row["spend_extra"] = {"error": [0.0, f"{type(e).__name__}"]}
        try:
            row["usage"] = row.get("usage") or adapter.agent.facts()["usage"]
        except Exception:
            row["usage"] = {}
        adapter.stop()
        row["events"] = [e.row() for e in adapter._events]
        row["versions"] = adapter.versions()
    return row


def sanitize(obj, folder: Path, run_tmp: Path):
    """Placeholders for the run's own folders and the checkout; then the scrub check refuses anything left."""
    import json
    text = json.dumps(obj, default=str)
    text = scrub.clean(text, {str(folder): "<item>", os.path.realpath(folder): "<item>", str(run_tmp): "<run>",
                              os.path.realpath(run_tmp): "<run>", str(ROOT): "<pointe>", str(Path.home()): "<home>"})
    return json.loads(text)
