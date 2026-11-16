"""Pauses in the middle of a sentence on a real call: the bot waits for the rest, and still answers quickly at the real end.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-turns CLAUDE_VOICE_DAEMON_PORT=7877 CLAUDE_VOICE_TLS_PORT=7477 \
     uv run python -u -I tests/e2e/turn_taking.py
"""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rig import ROOT, Browser, fresh_state, log_lines, stop_daemon, synth  # noqa: E402
from scenarios import check, results  # noqa: E402

# (first half, pause in seconds, second half, a word the answer needs from the second half)
CASES = [
    ("The thing I keep forgetting to check is the", 1.5, "staging migration for the billing tables.", "billing"),
    ("Before lunch I want to look at", 1.5, "why the nightly export job is slow.", "export"),
    ("Can you remind me what the difference is between", 2.0, "a mutex and a semaphore?", "semaphore"),
]


def spoke_since(start: float) -> list[str]:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start))
    return [line for line in log_lines(r"speak: ") if line[:19] >= stamp]


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    fresh_state()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    browser = Browser()
    latencies = []
    try:
        await browser.connect()
        await asyncio.sleep(8)  # the greeting
        for first, pause, second, needed in CASES:
            await synth(first), await synth(second)  # made before the pause is timed: a synthesis inside it lengthens it
            await asyncio.sleep(1)
            _, first_end = await browser.say(first)
            await asyncio.sleep(max(0.0, first_end + pause - time.time()))
            cut_in = browser.speaker.speech_spans(since=first_end)
            _, end = await browser.say(second)
            await asyncio.sleep(14)
            spans = [s for s in browser.speaker.speech_spans(since=end)]
            answer = " ".join(line.split("speak: ", 1)[1] for line in spoke_since(first_end - 1))
            heard = [line.split("user said: ", 1)[1] for line in log_lines("user said: ") if line[11:19] >=
                     time.strftime("%H:%M:%S", time.localtime(first_end - 4))]
            check(f"a {pause}s pause mid-sentence does not get an answer ({first!r})", not cut_in and len(heard) == 1,
                  cut_in=[round(a - first_end, 1) for a, _ in cut_in], heard=heard)
            check(f"the answer uses the end of the sentence ({needed})", needed in answer.lower(), answer=answer[-160:])
            if spans:
                latencies.append(round(spans[0][0] - end, 2))
            await asyncio.sleep(max(0.0, (spans[-1][1] if spans else time.time()) - time.time() + 2))
        check("the bot still starts answering within 3 s of the real end", bool(latencies) and max(latencies) < 3.0,
              latencies=latencies)
    finally:
        await browser.close()
        stop_daemon()
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (turn taking)")


asyncio.run(main())
