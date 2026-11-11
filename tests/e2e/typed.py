"""Typing and fixing on a real call: a typed question gets a spoken answer, and a corrected transcript is what the voice
acts on.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-typed CLAUDE_VOICE_DAEMON_PORT=7889 CLAUDE_VOICE_TLS_PORT=7489 \
     uv run python -u -I tests/e2e/typed.py
"""

import asyncio
import json
import os
import subprocess
import sys
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
    return json.loads(urllib.request.urlopen(request, timeout=20).read())


async def spoken_after(start: float, pattern: str, timeout: float = 30) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        said = [line for line in log_lines(r"speak: ") if line[11:19] >= time.strftime("%H:%M:%S", time.localtime(start))]
        if any(pattern.lower() in line.lower() for line in said):
            return said[-1]
        await asyncio.sleep(1)
    return ""


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    fresh_state()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    browser = Browser()
    try:
        await browser.connect()
        await asyncio.sleep(8)  # the greeting
        start = time.time()
        call("/voice/say", {"text": "What is the capital of Portugal? One word."})
        said = await spoken_after(start, "lisbon")
        talk = call("/voice/status")["talk"]
        check("a typed question gets a spoken answer", bool(said), said=said[-80:])
        check("the typed turn shows as typed", any(t["who"] == "user" and t["typed"] for t in talk), talk=talk[-2:])

        await asyncio.sleep(3)
        start = time.time()
        await browser.say("What is the capital of Spain? One word.")
        await asyncio.sleep(10)
        turn = next(t for t in reversed(call("/voice/status")["talk"]) if t["who"] == "user")
        call("/voice/correct", {"id": turn["id"], "text": "What is the capital of Italy? One word."})
        said = await spoken_after(time.time() - 1, "rome")
        talk = call("/voice/status")["talk"]
        check("a corrected turn is answered as corrected", bool(said), said=said[-80:])
        check("the corrected turn shows the fixed words, marked edited",
              any(t["id"] == turn["id"] and "Italy" in t["text"] and t["corrected"] for t in talk))

        call("/voice/polish", {"on": True})
        await asyncio.sleep(4)
        await browser.say("Um so, like, what's the, uh, capital of France, I mean, just the city name.")
        await asyncio.sleep(12)
        turn = next(t for t in reversed(call("/voice/status")["talk"]) if t["who"] == "user")
        check("clean-up mode shows a tidy version of what was said", "understood" in turn and "um" not in turn["understood"].lower(),
              raw=turn["text"], understood=turn.get("understood"))
    finally:
        await browser.close()
        stop_daemon()
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (typed and corrected)")


asyncio.run(main())
