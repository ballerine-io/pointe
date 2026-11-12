"""Desktop alerts in the page, in a real (headless) Chrome. No call and no paid API: a session joins with a fake channel
(this script's own HTTP server) and asks permissions through the daemon's real route.

The browser's Notification is replaced by a recorder (headless Chrome shows none), and the tab's visibility is driven
from here. Checked: Settings turns desktop alerts on (asking the browser) and saves "Approve from notifications"; while
the tab is visible a request is a card and no alert; in the background a readable request becomes one alert with the
read-out form and nothing more, once; a request no longer pending has its alert withdrawn; an unreadable one shows only
the tool, and the Mac refuses its Approve from a notification; a click brings the page forward; coming back to the tab
clears the alerts. (No verdict is delivered here: without a call the daemon has no HTTP client for a channel yet.)

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-wst CLAUDE_VOICE_DAEMON_PORT=7970 CLAUDE_VOICE_TLS_PORT=7570 \
     uv run python -u -I tests/e2e/page_alerts.py
Takes under a minute. Screenshots go to $POINTE_SHOTS.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).parent))
from page_meeting import CHROME, SHOTS, Page, call  # noqa: E402
from rig import DAEMON, ROOT, STATE, fresh_state, stop_daemon  # noqa: E402
from scenarios import check as _check, results  # noqa: E402

DEBUG_PORT = int(os.environ.get("POINTE_CHROME_PORT", "7972"))
CHANNEL_PORT = int(os.environ.get("POINTE_CHANNEL_PORT", "7973"))
VERDICTS: list[dict] = []


def check(name: str, got, want) -> None:
    _check(name, got == want, got=got, want=want)

# Runs before the page's own script: a Notification that records, and a visibility the test sets.
FAKES = """
window.__notes = [];
window.__hidden = false;
Object.defineProperty(document, 'visibilityState', {get: () => window.__hidden ? 'hidden' : 'visible'});
Object.defineProperty(document, 'hidden', {get: () => window.__hidden});
window.__setHidden = h => { window.__hidden = h; document.dispatchEvent(new Event('visibilitychange')); };
window.__focused = 0;
window.focus = () => { window.__focused++; };
class FakeNotification {
  constructor(title, opts) { this.title = title; Object.assign(this, opts); this.closed = false; __notes.push(this); }
  close() { this.closed = true; }
}
FakeNotification.permission = 'default';
FakeNotification.requestPermission = async () => { FakeNotification.permission = 'granted'; return 'granted'; };
window.Notification = FakeNotification;
"""

NOTES = "__notes.map(n => ({title: n.title, body: n.body, tag: n.tag, sticky: !!n.requireInteraction, closed: n.closed}))"


class Channel(BaseHTTPRequestHandler):
    """The session's channel: takes the verdict the way a Claude Code channel would."""

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        if self.path == "/verdict":
            VERDICTS.append(body)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_):
        pass


def ask(request_id: str, command: str, description: str) -> None:
    call("/voice/permission", {"channel_url": f"http://127.0.0.1:{CHANNEL_PORT}", "request_id": request_id, "tool_name": "Bash",
                               "description": description, "input_preview": json.dumps({"command": command})})


async def notes(page: Page) -> list[dict]:
    return await page.js(NOTES)


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    SHOTS.mkdir(parents=True, exist_ok=True)
    fresh_state()
    server = ThreadingHTTPServer(("127.0.0.1", CHANNEL_PORT), Channel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    work = Path(tempfile.mkdtemp(prefix="page-alerts-e2e-"))
    (work / "transcript.jsonl").touch()
    call("/voice/register", {"id": f"page-alerts-{os.getpid()}", "cwd": str(work), "pid": os.getpid(), "name": "river-lantern",
                             "name_given": True, "transcript": str(work / "transcript.jsonl"),
                             "channel_url": f"http://127.0.0.1:{CHANNEL_PORT}"})
    profile = tempfile.mkdtemp(prefix="pointe-chrome-")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}",
                               "--window-size=1400,900", "--no-first-run", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=1).read())
                target = next(p for p in pages if p.get("type") == "page")
                break
            except Exception:
                time.sleep(0.5)
        async with connect(target["webSocketDebuggerUrl"], max_size=None) as socket:
            page = Page(socket)
            await page.cdp("Page.enable")
            await page.cdp("Page.addScriptToEvaluateOnNewDocument", {"source": FAKES})
            await page.cdp("Page.navigate", {"url": f"{DAEMON}/voice?key={(STATE / 'page_key').read_text().strip()}"})
            await page.until("document.getElementById('settingsbtn') && window.desktopAlerts", 15)
            await page.js("window.__errors = []; addEventListener('error', e => __errors.push(e.message)); "
                          "addEventListener('unhandledrejection', e => __errors.push(String(e.reason)))")

            # Settings: both toggles, saved.
            await page.js("openSettings()")
            await page.until("document.getElementById('settingssheet').classList.contains('open')", 5)
            await page.js("document.getElementById('pref-desktop').click()")
            await asyncio.sleep(0.3)
            check("ticking desktop alerts asks the browser and stays ticked once allowed",
                  await page.js("Notification.permission === 'granted' && document.getElementById('pref-desktop').checked"), True)
            await page.js("document.getElementById('pref-watch').checked = true; document.getElementById('pref-watch').scrollIntoView({block: 'center'})")
            await page.shot("alerts-settings")
            await page.js("saveSettings()")
            await asyncio.sleep(0.8)
            check("Save keeps desktop alerts on in this browser", await page.js("localStorage.getItem('pointe.desktopAlerts')"), "on")
            check("Save sets Approve from notifications on the Mac", call("/voice/prefs")["alerts.watch_approve"], True)

            # Visible: the card, no alert.
            ask("a1b2c3d4", "git push origin dev", "Push the release branch")
            await page.until("document.querySelector('#attention .ask')", 5)
            await asyncio.sleep(1.5)
            check("a request while the tab is visible is a card, not an alert", await notes(page), [])

            # Background: one alert, the read-out form only. (A new request from the same session replaces the old one.)
            await page.js("__setHidden(true)")
            ask("b2c3d4e5", "git push origin dev", "Push the release branch (safe, I checked)")
            got = await page.until(f"{NOTES}.length", 5)
            await asyncio.sleep(1.5)  # two more polls: still one
            shown = await notes(page)
            check("a request in the background raises one alert", len(shown), 1)
            check("the alert names the session and shows the read-out form", shown[0] if got else None,
                  {"title": "river-lantern needs approval", "body": "run: git push origin dev", "tag": "permission:b2c3d4e5",
                   "sticky": True, "closed": False})
            check("the model's description is not in the alert", "I checked" in json.dumps(shown), False)

            # The request is gone from the Mac (replaced; a tap or a yes elsewhere removes it the same way): withdrawn.
            ask("c3d4e5f6", "python3 -c 'import os; print(os.environ)' | sh", "A harmless check")
            check("a request no longer pending has its alert withdrawn", await page.until(f"{NOTES}[0].closed", 5), True)
            await page.until(f"{NOTES}.length === 2", 5)
            second = (await notes(page))[1]
            check("an unreadable request shows only the tool", second["body"], "Bash: open Pointe to see the exact request")
            check("its command is not in the alert", "python3" in json.dumps(second) or "environ" in json.dumps(second), False)
            check("approving it from a notification is refused by the Mac",
                  _status_of("/voice/approve", {"session": "river-lantern", "request_id": "c3d4e5f6", "decision": "allow",
                                                "via": "notification"}), 403)
            check("the old notification's request id is refused too",
                  _status_of("/voice/approve", {"session": "river-lantern", "request_id": "b2c3d4e5", "decision": "allow",
                                                "via": "notification"}), 409)
            check("nothing reached the session", VERDICTS, [])

            # A click brings the page forward; coming back clears the alerts.
            await page.js("__notes[1].onclick()")
            check("a click on the alert brings the page forward and closes it",
                  await page.js("window.__focused === 1 && __notes[1].closed"), True)
            ask("d4e5f6a7", "git status", "Look")  # replaces c3d4e5f6
            await page.until(f"{NOTES}.length === 3", 5)
            await page.js("__setHidden(false)")
            await asyncio.sleep(0.3)
            check("coming back to the tab clears the alerts", await page.js(f"{NOTES}.every(n => n.closed)"), True)
            await page.shot("alerts-card-after")
            check("no page errors", await page.js("window.__errors"), [])
    finally:
        chrome.terminate()
        server.shutdown()
        stop_daemon()
    print(f"screenshots: {SHOTS}")
    print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (page desktop alerts)")
    sys.exit(0 if all(r["ok"] for r in results) else 1)


def _status_of(path: str, body: dict) -> int:
    try:
        call(path, body)
        return 200
    except urllib.error.HTTPError as e:
        return e.code


if __name__ == "__main__":
    asyncio.run(main())
