"""Push to talk against a real daemon, Soniox and a brain: the test's own call speaks with and without a press.

Without a press nothing is heard and no microphone audio passes the gate (the byte counter stays 0); with a press the
words are heard; a press while the bot speaks stops it; a release lost with the link closes by itself after 2 s.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-ptt CLAUDE_VOICE_DAEMON_PORT=7920 CLAUDE_VOICE_TLS_PORT=7520 \
     uv run python -u -I tests/e2e/ptt.py
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rig import DAEMON, ROOT, STATE, Browser, fresh_state, log_lines, stop_daemon  # noqa: E402
from scenarios import check, results  # noqa: E402


def call(path: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(f"{DAEMON}{path}", data=json.dumps(body).encode() if body is not None else None,
                                     method="POST" if body is not None else "GET", headers={
                                         "Authorization": f"Bearer {(STATE / 'token').read_text().strip()}",
                                         "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=30).read())


async def until(test, timeout: float, every: float = 0.3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = test()
        if value:
            return value
        await asyncio.sleep(every)
    return test()


def heard(word: str) -> list[str]:
    return [line for line in log_lines(r"user said: ") if word.lower() in line.lower()]


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    fresh_state()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    work = Path(tempfile.mkdtemp(prefix="ptt-e2e-"))
    (work / "transcript.jsonl").touch()
    call("/voice/register", {"id": f"ptt-{os.getpid()}", "cwd": str(work), "pid": os.getpid(), "name": "orchard",
                             "name_given": True, "transcript": str(work / "transcript.jsonl")})
    call("/voice/prefs", {"microphone": "ptt"})
    browser = Browser()
    try:
        await browser.connect()
        await until(lambda: call("/voice/status")["connected"], 10)

        # ---- a press while the bot speaks stops it (the greeting is the bot speaking) ----
        speaking = await until(lambda: call("/voice/status")["speaking"] == "bot", 25, 0.1)
        before = browser.interrupts
        await browser.control({"type": "ptt", "open": True, "at": int(time.time() * 1000)})
        stopped = await until(lambda: browser.interrupts > before, 3, 0.05)
        await browser.control({"type": "ptt", "open": False})
        check("a press while the bot speaks stops it at once", bool(speaking) and bool(stopped),
              speaking=speaking, interrupts=browser.interrupts, log=log_lines(r"ptt: open")[-1:])
        await until(lambda: call("/voice/status")["speaking"] != "bot", 20)
        await asyncio.sleep(2)

        # ---- no press: nothing is heard, and no audio passes the gate ----
        sent0 = call("/voice/status")["ptt"]["sent_bytes"]
        _, end = await browser.say("Tell me what the orchard session is working on")
        await asyncio.sleep(end - time.time() + 6)
        status = call("/voice/status")["ptt"]
        check("without a press nothing is heard and no microphone audio passes the gate",
              not heard("orchard session") and status["sent_bytes"] == sent0 and not status["open"],
              heard=heard("orchard")[-1:], sent_bytes=status["sent_bytes"], before=sent0)

        # ---- a press: the words are heard ----
        await browser.control({"type": "ptt", "open": True, "at": int(time.time() * 1000)})
        opened = await until(lambda: call("/voice/status")["ptt"]["open"], 3, 0.1)
        _, end = await browser.say("What time zone is Lisbon in?")
        await asyncio.sleep(end - time.time() + 0.1)
        await browser.control({"type": "ptt", "open": False, "at": int(time.time() * 1000)})
        got = await until(lambda: heard("Lisbon"), 12)
        status = call("/voice/status")["ptt"]
        check("with a press the words are heard, and the release closes the gate", bool(opened) and bool(got) and not status["open"]
              and status["closed_why"] == "released" and status["sent_bytes"] > sent0,
              heard=got[-1:], ptt=status)
        await until(lambda: call("/voice/status")["speaking"] != "bot", 30)
        await asyncio.sleep(3)

        # ---- a release lost with the link: the gate closes by itself after 2 s without audio ----
        await browser.control({"type": "ptt", "open": True})
        await until(lambda: call("/voice/status")["ptt"]["open"], 3, 0.1)
        browser.muted = True
        closed = await until(lambda: (lambda p: not p["open"] and p["closed_why"])(call("/voice/status")["ptt"]), 5, 0.2)
        browser.muted = False
        check("open with no audio arriving closes by itself in about 2 s", closed == "no audio", closed=closed)

        # ---- a meeting: the room is heard without a press; the conversation still is not ----
        await until(lambda: call("/voice/status")["speaking"] != "bot", 30)
        conversation_before = len(log_lines(r"user said: "))
        sent_before = call("/voice/status")["ptt"]["sent_bytes"]
        call("/voice/meeting", {"action": "start", "mode": "listening", "consent": True})
        room = await until(lambda: call("/voice/status")["ptt"]["room_heard"], 10)
        _, end = await browser.say("The orchard harvest review moves to Friday morning")
        got = await until(lambda: [t for t in call("/voice/meeting/transcript")["turns"] if "friday" in t["text"].lower()],
                          end - time.time() + 20, 1)
        status = call("/voice/status")["ptt"]
        check("in a meeting the room is heard without a press, the status says so, and the conversation hears nothing",
              bool(room) and bool(got) and status["room_bytes"] > 0 and status["sent_bytes"] == sent_before and not status["open"]
              and len(log_lines(r"user said: ")) == conversation_before,
              transcript=[t["text"] for t in got][-1:], ptt=status)
        call("/voice/meeting", {"action": "end"})
        call("/voice/meeting", {"action": "discard"})
        after = await until(lambda: not call("/voice/status")["ptt"]["room_heard"], 10)
        check("after the meeting the room is no longer heard without a press", bool(after))

        # ---- always on: heard without a press, as before ----
        call("/voice/prefs", {"microphone": "always"})
        _, end = await browser.say("What time zone is Oslo in?")
        got = await until(lambda: heard("Oslo"), end - time.time() + 12)
        check("switched back to always on, the words are heard without a press", bool(got), heard=got[-1:])
    finally:
        await browser.close()
        try:
            call("/voice/prefs", {"microphone": "always"})
        except Exception:
            pass
        stop_daemon()
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (push to talk)")


asyncio.run(main())
