"""A brain dump on a real call: the bot stays silent through long pauses, then "done" structures the thoughts for review;
the bot says only that it is ready, and the prompt on screen holds every thought (docs/design/brain-dump.md).

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
from scenarios import check, daemon_status, results  # noqa: E402

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
        await browser.say("Brain dump.")
        await asyncio.sleep(4)
        for thought in THOUGHTS:
            _, end = await browser.say(thought)
            await asyncio.sleep(end - time.time() + 6)  # a long thinking pause after each
        spoke = [line for line in log_lines(r"speak: ") if line[:23] >= time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start))]
        check("the bot stays silent through long pauses while the user dumps their thoughts",
              bool(log_lines("brain dump started")) and not spoke, spoke=[s[-80:] for s in spoke])
        asked = time.time()
        await browser.say("Okay, done.")
        for _ in range(45):
            dump = daemon_status().get("brain_dump") or {}
            if dump.get("state") == "review":
                break
            await asyncio.sleep(1)
        await asyncio.sleep(8)  # the one line it says
        spans = browser.speaker.speech_spans(since=asked)
        said = await transcribe(browser.speaker.audio(spans[0][0], spans[-1][1])) if spans else ""
        prompt = ((dump.get("prompt") or {}).get("text") or "").lower()
        check("\"done\" structures every thought for review and nothing is sent",
              dump.get("state") == "review" and any(w in prompt for w in ("retry", "backoff", "back off"))
              and any(w in prompt for w in ("tax", "cache")) and not log_lines(r" - -> "), prompt=prompt[:300])
        check("the bot says only that it is ready, not the answer",
              bool(said.strip()) and "retry" not in said.lower() and "tax" not in said.lower(), said=said)
    finally:
        await browser.close()
        stop_daemon()
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (monologue)")


asyncio.run(main())
