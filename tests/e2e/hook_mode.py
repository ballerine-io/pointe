"""The plugin as a stranger gets it: a plain session, no channel and no restart, joined by /pointe:voice, with permission
prompts answered by voice through the PermissionRequest hook. Run with an isolated state dir and port:

  CLAUDE_VOICE_STATE=/tmp/cv-state CLAUDE_VOICE_DAEMON_PORT=7865 uv run python -I tests/e2e/hook_mode.py
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
from hook_session import PluginSession  # noqa: E402
from rig import DAEMON, STATE, Browser, fresh_state, log_lines, stop_daemon  # noqa: E402
from scenarios import TEST_MODEL, ask, check, log_time, reset_repo, results  # noqa: E402

REPO = Path("/tmp/cv-repo-hook")


def status() -> dict:
    token = (STATE / "token").read_text().strip()
    with urllib.request.urlopen(urllib.request.Request(f"{DAEMON}/voice/status", headers={"Authorization": f"Bearer {token}"}), timeout=5) as r:
        return json.load(r)


async def until(condition, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.5)
    return False


ASKED = r"speak:.*(?:Should it\?|[Ss]ay it again)"


async def answer_until(browser, words: str, done, since: float, timeout: float = 90) -> int:
    """As a person would: answer each time the bot asks (since the request), once it has finished asking. Returns how
    many answers it took. Not before the read-out (no answer counts there), and not over it: the log line comes before
    the audio, so the bot is heard out first."""
    deadline, heard, answers = time.time() + timeout, 0, 0
    while time.time() < deadline and not done():
        asked = [line for line in log_lines(ASKED) if log_time(line) >= since]
        if len(asked) > heard:
            heard = len(asked)
            await asyncio.sleep(1.5)  # its audio starts
            while browser.speaker.speech_spans(since=time.time() - 2):
                await asyncio.sleep(0.3)
            await browser.say(words)
            answers += 1
            await asyncio.sleep(5)
        await asyncio.sleep(0.5)
    return answers


async def main():
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    reset_repo(REPO)
    fresh_state()
    session = PluginSession(REPO, "--model", TEST_MODEL, "--permission-mode", "default")
    session.start()
    session.type("/pointe:voice --name hooked")
    try:
        joined = await until(lambda: (STATE / "token").exists() and _registered(), 45)
        Path("/tmp/hook-screen.txt").write_text(session.screen)
        check("/pointe:voice joins a plain session", joined)
        if not joined:
            return
        browser = Browser()
        await browser.connect()
        await asyncio.sleep(8)

        t = time.time()
        await ask(browser, "Ask Claude Code to create an empty file called voice-hook.txt.")
        answers = await answer_until(browser, "Yes.", (REPO / "voice-hook.txt").exists, t)
        check("a spoken yes approves it, with no channel", (REPO / "voice-hook.txt").exists(), answers=answers,
              permissions=[l[-90:] for l in log_lines(r"permission .* -> ")][-2:])
        await asyncio.sleep(25)

        await until(lambda: not browser.speaker.speech_spans(since=time.time() - 3), 30)  # not over the bot: its words get stripped as echo
        await ask(browser, "Ask Claude Code to create an empty file called after-hangup.txt.")
        await until(lambda: bool(log_lines(r"feed.*permission request.*after-hangup")), 60)
        await asyncio.sleep(1)
        # Claude Code draws its dialog while the hook is held, so a hang-up adds nothing to the screen: only answering it shows it still works.
        flat = lambda text: re.sub(r"\s+", "", text).lower()
        dialog_up = flat(session.screen).rfind("doyouwant") > flat(session.screen).rfind("after-hangup")
        token = (STATE / "token").read_text().strip()
        urllib.request.urlopen(urllib.request.Request(f"{DAEMON}/voice/hung-up", method="POST", headers={"Authorization": f"Bearer {token}"}), timeout=5)
        handed = await until(lambda: bool(log_lines("handed back")), 15)
        await asyncio.sleep(2)
        ran_before_answer = (REPO / "after-hangup.txt").exists()
        session.type("")
        ran = await until(lambda: (REPO / "after-hangup.txt").exists(), 45)
        check("hanging up hands the prompt to the terminal, and answering it there runs the command",
              dialog_up and handed and not ran_before_answer and ran,
              dialog_up=dialog_up, handed_back=handed, ran_before_answer=ran_before_answer, ran=ran)
        await asyncio.sleep(15)

        t = time.time()
        await ask(browser, "Ask Claude Code to create an empty file called denied.txt.")
        answers = await answer_until(browser, "No.", lambda: bool(log_lines(r"permission .* -> deny")), t)
        await asyncio.sleep(10)
        check("a spoken no denies it", bool(log_lines(r"permission .* -> deny")) and not (REPO / "denied.txt").exists(), answers=answers)
        await asyncio.sleep(15)

        await asyncio.wait_for(browser.close(), 15)  # a dropped network must not hide the result
    finally:
        Path("/tmp/hook-screen.txt").write_text(session.screen)
        session.stop()
        stop_daemon()
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (hook mode)")


def _registered() -> bool:
    try:
        return any(s["name"] == "hooked" for s in status()["sessions"])
    except OSError:
        return False


import faulthandler  # noqa: E402

faulthandler.dump_traceback_later(1100, exit=True)  # a hang shows its stack instead of a bare timeout
asyncio.run(main())
sys.stdout.flush()
os._exit(0 if results and all(r["ok"] for r in results) else 1)  # leftover call threads must not hold the exit
