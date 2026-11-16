"""Every feature on every harness, in one call: Claude Code, OpenCode and Codex sessions joined to one isolated daemon.

Each session works in its own scratch repo that holds one fact only it knows, so routing and reports can be checked.

Run (spends a few model turns on each agent; Codex needs its daemon, OpenCode its service):
  CLAUDE_VOICE_STATE=/tmp/cv-state-matrix CLAUDE_VOICE_DAEMON_PORT=7903 CLAUDE_VOICE_TLS_PORT=7503 \
      uv run python -u -I tests/e2e/harness_matrix.py [cc,oc,cx]
Cleanup of what it creates (OpenCode session, Codex thread, the Codex daemon it started) runs at the end.
"""

import asyncio
import fcntl
import json
import os
import pty
import re
import select
import struct
import subprocess
import sys
import termios
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rig import ROOT, STATE, Browser, fresh_state, log_lines, stop_daemon  # noqa: E402
from hook_session import JoinedSession  # noqa: E402
from scenarios import TEST_MODEL, _daemon, check, daemon_status, log_time, results  # noqa: E402

# Every blocking step (a Claude Code start, `pointe join`, a Codex daemon start) runs in a thread: a test loop blocked for
# half a minute stops answering the call's WebSocket pings, and the daemon drops the call mid-run.

BASE = Path("/tmp/mx")
WANT = (sys.argv[1] if len(sys.argv) > 1 else "cc,oc,cx").split(",")
ONLY = os.environ.get("MATRIX_ONLY", "")  # "approvals": rows 1, 5-8 and 15 only (a cheaper rerun)
REPO = {"cc": BASE / "lighthouse", "oc": BASE / "orchard", "cx": BASE / "harbor"}
NAME = {"cc": "lighthouse", "oc": "orchard", "cx": "harbor"}
HARNESS = {"cc": "claude-code", "oc": "opencode", "cx": "codex"}
FACT = {"cc": ("The release codename is Juniper.", "juniper", "the release codename"),
        "oc": ("The database port is 6543.", "6543", "the database port"),
        "cx": ("The on-call engineer is Marisol.", "marisol", "the on-call engineer")}
WRONG = {"cc": "lightning", "oc": "orchid", "cx": "harvard"}  # what speech-to-text "misheard"
ENV = dict(os.environ)
created: dict = {"oc_session": None, "cx_threads": [], "cx_daemon": False}
matrix: dict[tuple[str, str], str] = {}


def mark(row: str, h: str, ok: bool | None, evidence: str = "") -> None:
    matrix[(row, h)] = ("PASS" if ok else "FAIL" if ok is False else "N/A") + (f": {evidence[:90]}" if evidence else "")
    if ok is not None:
        check(f"{row} [{h}]", ok, evidence=evidence[:300])


def status() -> dict:
    return daemon_status()


def session(h: str) -> dict | None:
    return next((s for s in status().get("sessions", []) if s["name"].split("/")[0] == NAME[h]), None)


def said_since(t: float) -> list[str]:
    return [line.split("speak: ", 1)[1] for line in log_lines(r"speak: ") if log_time(line) >= t]


async def until(test, timeout: float, step: float = 1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        got = test()
        if got:
            return got
        await asyncio.sleep(step)
    return test()


async def spoken_with(t: float, needle: str, timeout: float = 150) -> str:
    """The first thing the bot said after t that contains needle (case-insensitive), from the daemon's own log."""
    got = await until(lambda: next((s for s in said_since(t) if needle.lower() in s.lower()), None), timeout, 2)
    return got or ""


async def quiet(b: Browser, settle: float = 2.0, timeout: float = 40) -> None:
    """Wait until the bot has stopped talking for a moment: talking over it cuts it off (known limit)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        spans = b.speaker.speech_spans(since=time.time() - 30)
        if not spans or time.time() - spans[-1][1] > settle:
            return
        await asyncio.sleep(0.5)


async def say(b: Browser, text: str) -> float:
    await quiet(b)
    _, end = await b.say(text)
    await asyncio.sleep(max(0, end - time.time()))
    return end


def typed(text: str) -> float:
    t = time.time()
    _daemon("/voice/say", {"text": text})
    return t


async def pending(h: str, timeout: float = 150) -> dict | None:
    return await until(lambda: (lambda s: s if s and s.get("request_id") else None)(session(h)), timeout, 1)


def finished(h: str) -> int:
    return len(log_lines(rf"{NAME[h]}[^\]]*finished its turn"))


async def finish_turn(h: str, n: int, timeout: float = 180) -> bool:
    """Wait for the session's turn to end, tapping through approvals that are not what the check is about."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if finished(h) > n:
            return True
        s = session(h)
        if s and s.get("request_id"):
            _daemon("/voice/approve", {"session": s["name"], "request_id": s["request_id"], "decision": "allow"})
        await asyncio.sleep(2)
    return finished(h) > n


TAPPER = {"on": True}  # off while a row tests approvals itself


async def tapper() -> None:
    """A person tapping Approve on prompts that are not what the current row is about (a model may pick a command too
    complex to read out just to find a file)."""
    while True:
        await asyncio.sleep(2)
        if not TAPPER["on"]:
            continue
        for s in status().get("sessions", []):
            if s.get("request_id"):
                _daemon("/voice/approve", {"session": s["name"], "request_id": s["request_id"], "decision": "allow"})


async def clear(h: str, timeout: float = 120) -> None:
    """No prompt left open and no turn still running from an earlier row: a check about approvals starts clean."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = session(h)
        if not s:
            return
        if s.get("request_id"):
            _daemon("/voice/approve", {"session": s["name"], "request_id": s["request_id"], "decision": "deny"})
        elif not s.get("working"):
            await asyncio.sleep(3)
            if not (session(h) or {}).get("working"):
                return
        await asyncio.sleep(2)


# ---------- the three agents ----------

def make_repo(h: str) -> None:
    repo = REPO[h]
    subprocess.run(["rm", "-rf", str(repo)], check=True)
    repo.mkdir(parents=True)
    (repo / "FACT.md").write_text(f"# Facts\n{FACT[h][0]}\n")
    (repo / "README.md").write_text(f"# {NAME[h]}\nA scratch project for a voice test.\n")
    subprocess.run("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm init",
                   shell=True, cwd=repo, check=True)


async def opencode_session() -> str:
    from harnesses.opencode import Service

    service = Service()
    try:
        made = await service.call("POST", "/api/session", {
            "title": "pointe matrix", "location": {"directory": str(REPO["oc"])},
            "permissions": [{"action": "shell", "resource": "*", "effect": "ask"},  # v2's shell tool is "shell"
                            {"action": "bash", "resource": "*", "effect": "ask"},
                            {"action": "edit", "resource": "*", "effect": "ask"}]})
        return (made.get("data") or made)["id"]
    finally:
        await service.close()


async def opencode_delete(session_id: str) -> None:
    from harnesses.opencode import Service

    service = Service()
    try:
        await service.call("DELETE", f"/api/session/{session_id}")
    finally:
        await service.close()


async def opencode_messages(session_id: str) -> int:
    from harnesses.opencode import Service

    service = Service()
    try:
        got = await service.call("GET", f"/api/session/{session_id}/message?limit=200")
        items = got.get("data") if isinstance(got, dict) else got
        return len([m for m in (items or []) if (m.get("info") or m).get("role", m.get("type")) in ("user", "prompt")])
    finally:
        await service.close()


class CodexTui:
    """`codex --remote unix://` in a pty, answering the terminal's own queries so it does not hang."""

    ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[()][A-Z0-9]")

    def __init__(self, cwd: Path):
        self.cwd, self.screen, self._stop = cwd, "", False

    def start(self) -> None:
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(self.cwd)
            os.execvp("codex", ["codex", "--remote", "unix://", "-C", str(self.cwd), "-a", "on-request", "-s", "read-only"])
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 160, 0, 0))
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        while not self._stop:
            r, _, _ = select.select([self.fd], [], [], 0.3)
            if not r:
                continue
            try:
                data = os.read(self.fd, 65536)
            except OSError:
                return
            if b"\x1b[6n" in data:
                os.write(self.fd, b"\x1b[1;1R")
            if b"\x1b[c" in data or b"\x1b[0c" in data:
                os.write(self.fd, b"\x1b[?62;c")
            self.screen = (self.screen + self.ANSI.sub("", data.decode("utf-8", "replace")))[-60_000:]

    def flat(self) -> str:
        return re.sub(r"\s+", "", self.screen).lower()

    def type(self, text: str) -> None:
        os.write(self.fd, text.encode())
        time.sleep(0.4)
        os.write(self.fd, b"\r")

    def stop(self) -> None:
        self._stop = True
        for sig in (2, 2, 9):
            try:
                os.kill(self.pid, sig)
            except ProcessLookupError:
                break
            time.sleep(0.5)
        try:
            os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            pass


async def codex_ready(tui: CodexTui, timeout: float = 90) -> None:
    """Through Codex's start-up questions, to its input box. A new folder asks to be trusted (Codex saves that); new or
    changed hooks ask for review: "continue without trusting" skips them for this test session and saves nothing."""
    deadline = time.time() + timeout
    answered: set[str] = set()
    while time.time() < deadline:
        tail = tui.flat()[-3000:]
        if "trustthisfolder" in tail and "trust" not in answered:
            os.write(tui.fd, b"1"), await asyncio.sleep(0.5), os.write(tui.fd, b"\r")
            answered.add("trust")
            await asyncio.sleep(4)
            continue
        if "hooksneedreview" in tail.replace(" ", "") or "reviewhooks" in tail and "hooks" not in answered:
            if "hooks" not in answered:
                os.write(tui.fd, b"3"), await asyncio.sleep(0.5), os.write(tui.fd, b"\r")
                answered.add("hooks")
                await asyncio.sleep(4)
                continue
        last = max(tail.rfind("trustthisfolder"), tail.rfind("reviewhooks"))
        if "askcodex" in tail[last:] and time.time() > deadline - timeout + 12:  # the questions come in over a few seconds
            await asyncio.sleep(2)
            return
        await asyncio.sleep(1)


async def codex_turns(thread_id: str) -> int:
    from harnesses.codex import Connection

    link = Connection()
    try:
        await link.ensure()
        got = await link.request("thread/turns/list", {"threadId": thread_id, "limit": 100})
        return len(got.get("data") or got.get("turns") or [])
    finally:
        await link.close()


def join(h: str, *extra: str) -> dict:
    run = subprocess.run([str(ROOT / "bin" / "pointe"), "join", HARNESS[h], "--name", NAME[h], *extra], cwd=REPO[h],
                         env=ENV, capture_output=True, text=True, timeout=60)
    return {"code": run.returncode, "out": (run.stdout + run.stderr)[-300:]}


def leave(h: str, *extra: str) -> dict:
    run = subprocess.run([str(ROOT / "bin" / "pointe"), "leave", HARNESS[h], *extra], cwd=REPO[h],
                         env=ENV, capture_output=True, text=True, timeout=60)
    return {"code": run.returncode, "out": (run.stdout + run.stderr)[-300:]}


# ---------- the checks ----------

async def per_harness(b: Browser, h: str, ids: dict) -> None:
    name, (fact, key, what) = NAME[h], FACT[h]
    s = session(h)
    caps = (s or {}).get("capabilities") or {}
    mark("1 join", h, bool(s) and s.get("harness") == HARNESS[h] and caps.get("approvals") is not None,
         f"{(s or {}).get('name')} {(s or {}).get('harness')} {caps}")

    if ONLY == "approvals":
        await approvals(b, h, caps)
        return

    # 3: a spoken request, by name, and its report
    t = await say(b, f"Ask {name} what {what} is in its FACT file.")
    got = await spoken_with(t, key)
    mark("3 named request + report", h, bool(got), got)

    # 4: typed (by harness label for OpenCode and Codex: row 14), then a corrected misheard turn
    label = {"cc": "lighthouse", "oc": "the opencode one", "cx": "the codex one"}[h]
    n = finished(h)
    t = typed(f"Tell {label} to list the files in its folder and say how many there are.")
    sent = await until(lambda: [line for line in log_lines(rf" - -> {name}") if log_time(line) >= t], 30)
    done = await finish_turn(h, n)
    mark("4a typed request", h, bool(sent) and bool(done), (sent or [""])[-1][-120:])
    if h != "cc":
        mark("14 'the <harness> one'", h, bool(sent), (sent or [""])[-1][-120:])
    t = await say(b, f"Ask {WRONG[h]} what {what} is.")
    await asyncio.sleep(6)
    turn = next((x for x in reversed(_daemon("/voice/status").get("talk", [])) if x["who"] == "user"), None)
    t2 = time.time()
    if turn:
        _daemon("/voice/correct", {"id": turn["id"], "text": f"Ask {name} what {what} is."})
    got = await spoken_with(t - 1, key)  # it may already have read the misheard name right, before the correction came
    mark("4b corrected turn acted on", h, bool(turn) and bool(got), f"heard {turn and turn['text']!r} -> {got[:80]}")

    await approvals(b, h, caps)

    # 9: by the way, and the real session gets no new turn
    await by_the_way_and_switch(b, h, ids)


async def approvals(b: Browser, h: str, caps: dict) -> None:
    name = NAME[h]
    if not caps.get("approvals"):
        for row in ("5 voice approve", "6 voice deny", "7 tap approve (unreadable)", "8 'wait' keeps it open"):
            mark(row, h, None, "harness declares no approvals")
    else:
        # 5 + 7 + 8: one turn, a readable command then one that cannot be read out. Its approvals are read out only while
        # it is the active session (another session's are announced), so switch to it first, as a person would.
        TAPPER["on"] = False
        await clear(h)
        _daemon("/voice/switch", {"name": session(h)["name"]})
        await asyncio.sleep(3)
        n = finished(h)
        # The second must stay past a read-out whatever the transcriber and the model make of it: "echo $PWD" came
        # through as "echo pwd", the model ran "pwd > where.txt", and that is read out (two_machines.py asks the same).
        t = await say(b, f"Ask {name} to run exactly two shell commands, one at a time: first touch created.txt, then "
                         f"uname dash a, redirected into where.txt.")
        first = await pending(h)
        read = await spoken_with(t, "should it", 60) if first else ""
        if first and first.get("voice_can_approve"):
            await say(b, "Wait, what is that?")
            await asyncio.sleep(8)
            still = session(h)
            mark("8 'wait' keeps it open", h, bool(read) and bool(still) and still.get("request_id") == first["request_id"],
                 f"read-out {read[:60]!r}")
            for _ in range(3):  # after a question, the voice reads the command out again; a yes counts right after that
                await say(b, "Yes.")
                if await until(lambda: (REPO[h] / "created.txt").exists(), 25):
                    break
        else:
            mark("8 'wait' keeps it open", h, False, f"first request not readable: {first}")
        mark("5 voice approve", h, (REPO[h] / "created.txt").exists(), "created.txt exists")
        second = await until(lambda: (lambda s: s if s and s.get("request_id") and not s.get("voice_can_approve") else None)(session(h)), 90, 1)
        if second:
            _daemon("/voice/approve", {"session": second["name"], "request_id": second["request_id"], "decision": "allow"})
        ok = await until(lambda: (REPO[h] / "where.txt").exists(), 60)
        mark("7 tap approve (unreadable)", h, bool(second) and bool(ok), (second or {}).get("request", "")[:80] if second else "no unreadable request came")
        await until(lambda: finished(h) > n, 120, 2)

        # 6: deny, after the approvals: a denial can make an agent stop asking (Claude Code then asks in conversation)
        await clear(h)
        _daemon("/voice/switch", {"name": session(h)["name"]})
        await asyncio.sleep(3)
        n = finished(h)
        t = await say(b, f"Ask {name} to run touch denied.txt")
        asked = await pending(h)
        if asked:
            await spoken_with(t, "should it", 60)
            await say(b, "No.")
        await until(lambda: finished(h) > n, 120, 2)
        mark("6 voice deny", h, bool(asked) and not (REPO[h] / "denied.txt").exists(), f"asked={bool(asked)}")
        TAPPER["on"] = True



async def by_the_way_and_switch(b: Browser, h: str, ids: dict) -> None:
    name, (_fact, key, what) = NAME[h], FACT[h]
    before = await count_turns(h, ids)
    t = await say(b, f"By the way, what did {name} say {what} is?")
    got = await spoken_with(t, key, 90)
    await asyncio.sleep(5)
    after = await count_turns(h, ids)
    mark("9 by the way, session untouched", h, bool(got) and before == after, f"turns {before}->{after}; {got[:60]}")

    # 10: switch, focus, back
    await say(b, f"Switch to {name}.")
    switched = await until(lambda: (status().get("active") or "").startswith(name), 20)
    _daemon("/voice/mode", {"mode": "session"})
    focused = status().get("mode") == "session" and (status().get("active") or "").startswith(name)
    _daemon("/voice/mode", {"mode": "orchestrator"})
    mark("10 switch, focus, back", h, bool(switched) and focused and status().get("mode") == "orchestrator",
         f"active={status().get('active')}")


def registered(h: str) -> dict:
    """The daemon's own record of a session (status leaves out ids and paths)."""
    saved = json.loads((STATE / "sessions.json").read_text()).get("sessions") or []
    saved = saved if isinstance(saved, list) else list(saved.values())
    return next((x for x in saved if str(x.get("name", "")).split("/")[0] == NAME[h]), {})


async def count_turns(h: str, ids: dict) -> int:
    if h == "oc":
        return await opencode_messages(ids["oc"])
    if h == "cx":
        return await codex_turns(ids["cx"])
    entry = registered(h)
    transcript = Path(entry["transcript"]) if entry.get("transcript") else None
    if not transcript or not transcript.exists():
        return -1
    return sum(1 for line in transcript.read_text().splitlines()
               if '"type":"user"' in line.replace(" ", "") and '"tool_use_id"' not in line)


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    fresh_state()
    for h in WANT:
        make_repo(h)
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=ENV).returncode == 0
    ids, cc, tui = {}, None, None
    browser = Browser()
    try:
        await browser.connect()
        tapping = asyncio.create_task(tapper())
        await asyncio.sleep(6)
        if "cc" in WANT:
            cc = JoinedSession(REPO["cc"], "--model", TEST_MODEL, "--permission-mode", "default", front="brain")
            await asyncio.to_thread(cc.start)
        if "oc" in WANT:
            ids["oc"] = created["oc_session"] = await opencode_session()
            print("opencode join", await asyncio.to_thread(join, "oc", "--session", ids["oc"]), flush=True)
        if "cx" in WANT:
            await asyncio.to_thread(subprocess.run, ["codex", "app-server", "daemon", "start"], capture_output=True, timeout=60)
            created["cx_daemon"] = True
            tui = CodexTui(REPO["cx"])
            tui.start()
            await codex_ready(tui)
            tui.type("Reply with the single word ok.")
            await until(lambda: "ok" in tui.screen.split("Reply with the single word ok.")[-1].lower(), 90, 2)
            await asyncio.sleep(5)
            joined = await asyncio.to_thread(join, "cx")
            print("codex join", joined, flush=True)
            entry = registered("cx")
            if entry:
                ids["cx"] = entry["id"]
                created["cx_threads"].append(entry["id"])
        await asyncio.sleep(5)

        # 2: one status question covers every session
        t = await say(browser, "What's going on with all my sessions?") if not ONLY else time.time()
        await asyncio.sleep(14)
        heard = " ".join(said_since(t)).lower()
        for h in WANT if not ONLY else ():
            mark("2 status covers all", h, NAME[h] in heard, heard[:120])

        for h in WANT:
            await per_harness(browser, h, ids)

        # 13: an unnamed request about one repo's fact goes to that repo's session
        if "cc" in WANT and not ONLY:
            t = time.time()
            await say(browser, "Ask Claude Code to check the release codename in the FACT file again.")
            sent = await until(lambda: [line for line in log_lines(r" - -> ") if log_time(line) >= t], 30)
            mark("13 unnamed request routed", "cc", bool(sent) and "lighthouse" in sent[-1], (sent or [""])[-1][-120:])

        # 11: brain dump (harness-independent: once). "Done" structures the thoughts for review; nothing is sent, the bot
        # says only that it is ready (docs/design/brain-dump.md). "Discard" clears it so later cases start clean.
        if not ONLY:
            t = await say(browser, "Brain dump.")
            for thought in ("The orchard migration should go first,", "because the database port moved,",
                            "and the harbor on-call needs to know before Friday."):
                await say(browser, thought)
                await asyncio.sleep(5)
            silent = not said_since(t + 1) and (status().get("brain_dump") or {}).get("state") == "dumping"
            t2 = await say(browser, "Okay, done.")
            review = await until(lambda: (status().get("brain_dump") or {}).get("state") == "review", 45)
            answer = await spoken_with(t2, "", 30)
            prompt = ((status().get("brain_dump") or {}).get("prompt") or {}).get("text", "").lower()
            sent = [line for line in log_lines(r" - -> ") if log_time(line) >= t]
            ok = silent and bool(review) and bool(answer) and not sent and \
                any(w in prompt for w in ("port", "migration", "friday", "on-call", "orchard"))
            for h in WANT:
                mark("11 brain dump (once, all harnesses)", h, ok, (answer or prompt)[:120])
            await say(browser, "Discard.")
            await until(lambda: status().get("brain_dump") is None, 15)

        # 15: two pending approvals from two harnesses: a stray yes answers only the focused one
        other = "cx" if "cx" in WANT else "oc" if "oc" in WANT else None
        if "cc" in WANT and other:
            TAPPER["on"] = False
            await clear("cc"), await clear(other)
            await say(browser, "Switch to lighthouse.")
            await asyncio.sleep(4)
            typed(f"Tell lighthouse to run touch both-a.txt, and tell {NAME[other]} to run touch both-b.txt.")
            a, c = await pending("cc", 150), await pending(other, 150)
            await asyncio.sleep(10)
            await say(browser, "Yes.")
            await until(lambda: (REPO["cc"] / "both-a.txt").exists(), 60)
            only_focused = (REPO["cc"] / "both-a.txt").exists() and not (REPO[other] / "both-b.txt").exists()
            await say(browser, f"Switch to {NAME[other]}.")
            await asyncio.sleep(10)
            await say(browser, "Yes.")
            done = await until(lambda: (REPO[other] / "both-b.txt").exists(), 90)
            mark("15 two approvals, one stray yes", "cc", bool(a) and bool(c) and only_focused,
                 f"cc pending={bool(a)} {other} pending={bool(c)}")
            mark("15 two approvals, one stray yes", other, bool(c) and bool(done), "answered after switching")
            TAPPER["on"] = True

        # 12: leave, and reaping for one
        for h in WANT:
            if h == "cc" and cc:
                await asyncio.to_thread(cc.stop)
                gone = await until(lambda: session("cc") is None, 40)
                mark("12 leave / reaped", h, bool(gone), "Claude Code killed: reaped")
            elif h in ("oc", "cx"):
                extra = ("--session", ids["oc"]) if h == "oc" else (("--thread", ids["cx"]) if ids.get("cx") else ())
                out = await asyncio.to_thread(leave, h, *extra)
                gone = await until(lambda: session(h) is None, 20)
                mark("12 leave / reaped", h, bool(gone), str(out)[:120])
    finally:
        await browser.close()
        if cc:
            cc.stop()
        if tui:
            tui.stop()
        stop_daemon()
        if created["oc_session"]:  # what this run made, and nothing else
            try:
                await opencode_delete(created["oc_session"])
            except Exception as e:
                print("opencode cleanup:", type(e).__name__)
        for thread_id in created["cx_threads"]:
            subprocess.run(["codex", "delete", "--force", thread_id], capture_output=True, timeout=60)
        print("\nMATRIX")
        rows = sorted({r for r, _ in matrix}, key=lambda r: (int(re.match(r"\d+", r).group()), r))
        for row in rows:
            print(f"{row:42} " + " | ".join(f"{h}: {matrix.get((row, h), '-')}" for h in WANT))
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (harness matrix)")
        print("CREATED", json.dumps(created))


if __name__ == "__main__":  # two_machines.py borrows its Codex and OpenCode helpers
    asyncio.run(main())
