"""What the iPhone app did and the page did not, in a real (headless) Chrome against a real daemon. No call, no paid API.

- Ending a meeting and discarding its notes each take two clicks: the first asks, the second does it.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-par CLAUDE_VOICE_DAEMON_PORT=7960 CLAUDE_VOICE_TLS_PORT=7560 POINTE_CHROME_PORT=7963 \
     uv run python -u -I tests/e2e/page_parity.py
Screenshots go to $POINTE_SHOTS.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from websockets.asyncio.client import connect

os.environ.setdefault("POINTE_SHOTS", tempfile.mkdtemp(prefix="pointe-parity-shots-"))  # before page_meeting reads it
sys.path.insert(0, str(Path(__file__).parent))
from page_meeting import CHROME, Page, call  # noqa: E402
from rig import DAEMON, ROOT, STATE, fresh_state, stop_daemon  # noqa: E402
from scenarios import check, results  # noqa: E402

DEBUG_PORT = int(os.environ.get("POINTE_CHROME_PORT", "7963"))
SHOTS = Path(os.environ["POINTE_SHOTS"])


async def two_clicks(page: Page) -> None:
    await page.js("window.__posted = []; meetPost = async body => { window.__posted.push(body.action); return {}; };"
                  "showEnd = () => {}; closeEnd = () => {}; true")
    await page.js("endMeeting()")
    asked = await page.js("document.getElementById('meetend').textContent")
    check("the first click on End meeting asks, and ends nothing", await page.js("window.__posted.length") == 0
          and asked == "End the meeting?", label=asked)
    await page.js("endMeeting()")
    check("the second click ends the meeting", await page.js("window.__posted") == ["end"])
    await asyncio.sleep(4.5)
    await page.js("window.__posted = []; endMeeting()")
    check("a click after the question lapsed asks again", await page.js("window.__posted.length") == 0)

    await page.js("window.__posted = []; discardMeeting()")
    asked = await page.js("document.getElementById('enddiscard').textContent")
    check("the first click on Discard asks, and keeps the notes", await page.js("window.__posted.length") == 0
          and asked == "Discard the notes?", label=asked)
    await page.js("discardMeeting()")
    check("the second click discards", await page.js("window.__posted") == ["discard"])


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    fresh_state()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    profile = tempfile.mkdtemp(prefix="pointe-chrome-")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}",
                               "--window-size=1440,900", "--no-first-run",
                               f"{DAEMON}/voice?key={(STATE / 'page_key').read_text().strip()}"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json").read())
                target = next(t for t in tabs if t.get("type") == "page")
                break
            except Exception:
                await asyncio.sleep(0.5)
        async with connect(target["webSocketDebuggerUrl"], max_size=50_000_000) as socket:
            page = Page(socket)
            await page.cdp("Runtime.enable")
            await page.until("typeof meetPost === 'function' && !!status && !!status.sessions", 20)
            await two_clicks(page)
    finally:
        chrome.terminate()
        stop_daemon()
    print(f"screenshots: {SHOTS}")
    failed = [r for r in results if not r["ok"]]
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
