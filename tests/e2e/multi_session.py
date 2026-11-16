"""Two live Claude Code sessions on one shared voice. Run with an isolated state dir and port:

  CLAUDE_VOICE_STATE=/tmp/cv-state CLAUDE_VOICE_DAEMON_PORT=7861 uv run python -I tests/e2e/multi_session.py
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rig import DAEMON, STATE, Browser, ClaudeSession, fresh_state, log_lines, stop_daemon  # noqa: E402
from hook_session import JoinedSession  # noqa: E402
from scenarios import TEST_MODEL, ask, check, daemon_status, reply_after, reset_repo, results, tap, wait_log  # noqa: E402

REPO_A = Path("/tmp/cv-repo-multi")
REPO_B = Path("/tmp/cv-notes")


def status() -> dict:
    token = (STATE / "token").read_text().strip()
    with urllib.request.urlopen(urllib.request.Request(f"{DAEMON}/voice/status", headers={"Authorization": f"Bearer {token}"}), timeout=3) as r:
        return json.load(r)


def make_repo_b() -> None:
    if subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=REPO_B if REPO_B.exists() else "/",
                      capture_output=True).returncode != 0 or not (REPO_B / ".git").exists():
        subprocess.run(["rm", "-rf", str(REPO_B)], check=True)  # macOS clears /tmp files left for days, not folders: a .git with no HEAD
        REPO_B.mkdir(parents=True, exist_ok=True)
        (REPO_B / "notes.md").write_text("# Notes\nThe launch date is March 3rd.\n")
        subprocess.run("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm init",
                       shell=True, cwd=REPO_B, check=True)
    subprocess.run("git reset -q --hard && git clean -qfd", shell=True, cwd=REPO_B, check=True)


async def quiet_moment(browser, need: float = 2.0, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        spans = browser.speaker.speech_spans(since=time.time() - 10)
        if not spans or time.time() - spans[-1][1] > need:
            return
        await asyncio.sleep(0.3)


def delegations() -> list[str]:
    return log_lines(r" - -> ")



TAPPING = {"on": True}  # off while a check is about what a spoken word alone does


async def tap_what_voice_cannot_approve() -> None:
    """A person on the page: a request too complex to read out is approved with a tap, as the bot asks."""
    while True:
        await asyncio.sleep(2)
        if not TAPPING["on"]:
            continue
        status = daemon_status()
        for session in status.get("sessions", []):  # the page offers a tap for the active session's request only
            if session["name"] == status.get("active") and session.get("request_id") and not session.get("voice_can_approve"):
                tap(session, "allow")

async def main():
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    reset_repo(REPO_A)
    make_repo_b()
    fresh_state()
    a = JoinedSession(REPO_A, "--model", TEST_MODEL, "--permission-mode", "default")
    b_session = JoinedSession(REPO_B, "--model", TEST_MODEL, "--permission-mode", "default")
    a.start()
    b_session.start()
    deadline = time.time() + 30
    while time.time() < deadline and len(status()["sessions"]) < 2:
        await asyncio.sleep(1)
    names = [s["name"] for s in status()["sessions"]]
    check("both sessions register with one daemon", len(names) == 2, names=names, active=status()["active"])
    name_a = next(n for n in names if n.startswith("cv-repo-multi"))
    name_b = next(n for n in names if n.startswith("cv-notes"))

    browser = Browser()
    try:
        t0 = time.time()
        await browser.connect()
        tapper = asyncio.create_task(tap_what_voice_cannot_approve())
        await reply_after(browser, t0, timeout=20)

        first, end, said = await ask(browser, "Which sessions are running?")
        check("lists both sessions", re.search(r"repo", said, re.I) and re.search(r"notes", said, re.I), said=said)

        n = len(delegations())
        n_perm = len(log_lines(r"permission request\]"))
        await ask(browser, "Ask Claude Code to tell me what files are in this repo.")
        n_done = len(log_lines("finished its turn"))
        if await wait_log(r"permission request\]", n_perm, timeout=20):  # the model may list files with Bash
            await asyncio.sleep(5)
            if any(s.get("request_id") and s.get("voice_can_approve") for s in daemon_status().get("sessions", [])):
                await browser.say("Yes.")  # only a request still open and read out; a stray yes accepts the session's offers
        sent = await wait_log(r" - -> ", n, timeout=10)
        check("a request goes to the active session", sent is not None and f"-> {name_a}:" in sent,
              sent=sent and sent[-140:])
        await wait_log("finished its turn", n_done, timeout=90)
        await reply_after(browser, time.time(), timeout=15)

        first, end, said = await ask(browser, "Switch to cv notes.")
        check("switching by name changes the active session", status()["active"] == name_b,
              active=status()["active"], said=said)

        n, n_perm, n_heard = len(delegations()), len(log_lines(r"permission request\]")), len(log_lines("mirror heard: "))
        await ask(browser, "Ask Claude Code what the launch date in the notes is.")
        sent = await wait_log(r" - -> ", n, timeout=10)
        if await wait_log(r"permission request\]", n_perm, timeout=15):  # it may search with a tool
            await asyncio.sleep(5)
            await browser.say("Yes.")
        check("after switching, requests go to the new session", sent is not None and f"-> {name_b}:" in sent,
              sent=sent and sent[-140:])
        report, t = "", time.time()  # another session's announcement may come first
        for _ in range(3):
            first, said = await reply_after(browser, t, timeout=60)
            report += " " + said
            if first is None or re.search(r"march|3", said, re.I):
                break
            t = time.time()
        spoken = " ".join(l.split("mirror heard: ", 1)[1] for l in log_lines("mirror heard: ")[n_heard:])
        check("the new session's answer is reported",  # the bot's own words, as its mirror ears heard them
              re.search(r"march|\b3\b", report + " " + spoken, re.I) is not None, said=report.strip(), spoken=spoken[-200:])

        n = len(delegations())
        await ask(browser, "Ask Claude Code to show me the apply discount function in pricing.py.")
        sent = await wait_log(r" - -> ", n, timeout=15)
        check("an unnamed request is routed to the session it is about",
              sent is not None and f"-> {name_a}:" in sent and re.search(r"routing: (auto|brain)", sent) and status()["active"] == name_b,
              sent=sent and sent[-160:])
        await asyncio.sleep(15)

        n = len(delegations())
        await ask(browser, "Tell the cv repo multi session to print the README file.")
        n_done = len(log_lines("finished its turn"))
        sent = await wait_log(r" - -> ", n, timeout=10)
        check("a named one-off request reaches the other session without switching",
              sent is not None and f"-> {name_a}:" in sent and status()["active"] == name_b,
              sent=sent and sent[-140:], active=status()["active"])
        await wait_log("finished its turn", n_done, timeout=90)
        await reply_after(browser, time.time(), timeout=15)

        first, end, said = await ask(browser, "By the way, what files did the cv repo multi session say it has?")
        check("a by-the-way question is answered from history",
              bool(log_lines("ask_about_session")) or re.search(r"pricing|readme|test", said, re.I) is not None,
              said=said)

        # Permission from the session that is not active: announced, not answerable until switched to.
        n_perm = len(log_lines(r"permission from .* not active"))
        await quiet_moment(browser)  # talking over the bot saying the same name strips it as echo (known limit)
        TAPPING["on"] = False  # a tap here would answer what the stray yes must not
        await ask(browser, "Tell the cv repo multi session to create an empty file called voice-check.txt.")
        perm = await wait_log(r"permission from .* not active", n_perm, timeout=60)
        await asyncio.sleep(6)
        await browser.say("Yes.")
        await asyncio.sleep(6)
        check("a background session's permission is not answered by a stray yes",
              perm is not None and not (REPO_A / "voice-check.txt").exists(), perm=perm and perm[-120:])
        TAPPING["on"] = True
        await quiet_moment(browser)  # the bot may be inviting these same words; over it, they are dropped as echo (known limit)
        await ask(browser, "Switch to cv repo multi.")
        await asyncio.sleep(8)  # the request has to be read out first
        deadline = time.time() + 60
        while time.time() < deadline and not (REPO_A / "voice-check.txt").exists():  # once more if it was read out again
            await quiet_moment(browser)
            await browser.say("Yes, go ahead.")
            await asyncio.sleep(10)
        check("after switching, a spoken yes approves it", (REPO_A / "voice-check.txt").exists(),
              active=status()["active"])

        b_session.stop()
        deadline = time.time() + 20
        while time.time() < deadline and len(status()["sessions"]) > 1:
            await asyncio.sleep(1)
        check("a closed session drops off", [s["name"] for s in status()["sessions"]] == [name_a],
              sessions=status()["sessions"])
    finally:
        await browser.close()
        a.stop()
        b_session.stop()
        stop_daemon()
        passed = sum(r["ok"] for r in results)
        print(f"\n{passed}/{len(results)} passed (multi-session)")


asyncio.run(main())
