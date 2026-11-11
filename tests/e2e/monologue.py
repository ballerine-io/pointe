"""Thinking out loud on a real call: the bot stays silent through long pauses, then answers with everything in mind.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-mono CLAUDE_VOICE_DAEMON_PORT=7871 uv run python -u -I tests/e2e/monologue.py
"""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rig import ROOT, Browser, fresh_state, log_lines, stop_daemon, transcribe  # noqa: E402
from scenarios import check, results  # noqa: E402

THOUGHTS = [
    "So the checkout flow keeps timing out for some customers.",
    "I think it might be the retry loop around the payment provider,",
    "because it retries five times with no backoff.",
    "Also we never cache the tax rates, so every checkout calls the tax service twice.",
]


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    fresh_state()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    browser = Browser()
    try:
        await browser.connect()
        await asyncio.sleep(8)  # the greeting
        start = time.time()
        await browser.say("Just listen.")
        await asyncio.sleep(4)
        for thought in THOUGHTS:
            _, end = await browser.say(thought)
            await asyncio.sleep(end - time.time() + 6)  # a long thinking pause after each
        spoke = [line for line in log_lines(r"speak: ") if line[:23] >= time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start))]
        check("the bot stays silent through long pauses while the user thinks out loud",
              bool(log_lines("monologue started")) and not spoke, spoke=[s[-80:] for s in spoke])
        asked = time.time()
        await browser.say("Okay, what do you think?")
        await asyncio.sleep(18)
        spans = browser.speaker.speech_spans(since=asked)
        said = await transcribe(browser.speaker.audio(spans[0][0], spans[-1][1])) if spans else ""
        lowered = said.lower()
        check("the hand-off gets one answer that uses the whole monologue",
              any(w in lowered for w in ("retry", "backoff", "back off")) and any(w in lowered for w in ("tax", "cache")),
              said=said)
    finally:
        await browser.close()
        stop_daemon()
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (monologue)")


asyncio.run(main())
