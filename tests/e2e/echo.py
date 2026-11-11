"""Speakers without headphones: the bot's voice leaks back into the mic at half volume, with no
echo cancellation at all. Run with an isolated state dir and port:

  CLAUDE_VOICE_STATE=/tmp/cv-state-echo CLAUDE_VOICE_DAEMON_PORT=7864 uv run python -I tests/e2e/echo.py
"""

import asyncio
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rig import transcribe, ROOT, Browser, fresh_state, log_lines, stop_daemon  # noqa: E402
from scenarios import check, reply_after, results  # noqa: E402

ECHO_GAIN = float(os.environ.get("ECHO_GAIN", "0.5"))
STORY = "Tell me a story about a lighthouse keeper, about eight sentences long."


def user_lines() -> list[str]:
    return log_lines(r"user said: ")


async def main():
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    fresh_state()
    subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], env=dict(os.environ), check=True)
    browser = Browser(echo_gain=ECHO_GAIN)
    try:
        t0 = time.time()
        await browser.connect()
        await reply_after(browser, t0, timeout=20)

        # 1. A long answer is not cut off by its own echo, and the echo is never taken as the user.
        n_user, n_barge = len(user_lines()), len(log_lines("barge-in"))
        _, end = await browser.say(STORY)
        await asyncio.sleep(max(0, end - time.time()))
        first, said = await reply_after(browser, end, timeout=60, quiet=4)
        spans = browser.speaker.speech_spans(since=end)
        talked = spans[-1][1] - spans[0][0] if spans else 0
        heard = user_lines()[n_user:]
        barged = log_lines("barge-in")[n_barge:]
        check("the story plays to the end over its own echo", talked > 15 and not barged,
              seconds=round(talked, 1), barge_ins=barged[:2], said=said[-160:])
        check("the bot's echo never reaches the model as the user", len(heard) == 1,
              heard=[h.split("user said: ")[1] for h in heard], dropped=len(log_lines("echo dropped")))

        # 2. The user can still cut in, by voice, over the echo.
        _, end = await browser.say("Tell me another long story, about a sailor, ten sentences.")
        await asyncio.sleep(max(0, end - time.time()))
        deadline = time.time() + 20  # cut in once the bot has been talking for 4 s
        while time.time() < deadline:
            spans = browser.speaker.speech_spans(since=end)
            if spans and spans[-1][1] - spans[0][0] > 4 and time.time() - spans[-1][1] < 0.3:
                break
            await asyncio.sleep(0.2)
        n_barge = len(log_lines("barge-in"))
        start, _ = await browser.say("Stop. What is two plus two?")
        await asyncio.sleep(3)
        cut = log_lines("barge-in")[n_barge:]
        stopped = [b for a, b in browser.speaker.speech_spans(since=start - 2) if b > start]
        check("the user's own words still interrupt the bot", bool(cut), barge_in=cut[:1])
        await asyncio.sleep(4)  # the reply can already be over: judge everything said since the question ended
        spans = browser.speaker.speech_spans(since=start)
        said = await transcribe(browser.speaker.audio(spans[0][0], spans[-1][1])) if spans else ""
        check("and the bot answers the new question", re.search(r"\bfour\b|\b4\b", said, re.I) is not None,
              said=said[:200], stop_spans=[round(b - start, 1) for b in stopped[:2]])
    finally:
        await browser.close()
        stop_daemon()
        passed = sum(r["ok"] for r in results)
        print(f"\n{passed}/{len(results)} passed (echo, gain {ECHO_GAIN})")


asyncio.run(main())
