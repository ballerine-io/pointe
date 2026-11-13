"""What the iPhone app did and the page did not, in a real (headless) Chrome against a real daemon. No call, no paid API.

- Ending a meeting and discarding its notes each take two clicks: the first asks, the second does it.
- Settings → Meetings offers "Ask again before the next meeting" once the consent step was accepted, and it resets it.
- Settings shows the local mode line from the daemon's status.
- Right-to-left text (Hebrew, Arabic) reads from the right in the conversation, the caption, cards and lists: a final
  full stop sits at the left end. English is unchanged. Each element takes its direction from its own first strong
  letter (dir="auto"), not the page's.

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


async def settings(page: Page) -> None:
    call("/voice/prefs", {"meeting.consented": True})
    await page.js("openSettings()")
    await page.until("!document.getElementById('pref-consent').hidden", 5)
    check("Settings → Meetings offers to ask again once consent was accepted",
          await page.js("!document.getElementById('pref-consent').hidden"))
    await page.shot("settings-consent")
    await page.js("document.getElementById('pref-consent-again').click()")
    await page.until("document.getElementById('pref-consent').hidden", 5)
    check("Ask again resets the consent step on the Mac", call("/voice/status") is not None
          and json.loads(urllib.request.urlopen(urllib.request.Request(
              f"{DAEMON}/voice/prefs", headers={"Authorization": f"Bearer {(STATE / 'token').read_text().strip()}"})).read())
          .get("meeting.consented") is False)

    line = await page.until("document.getElementById('pref-local').textContent", 5)
    check("Settings shows the local mode line from the daemon", line == call("/voice/status")["local"]["line"], line=line)
    await page.shot("settings-local")
    await page.js("closeSheet('settingssheet')")


# The first and last character of an element's text, on screen: where a sentence starts and where its full stop sits.
EDGES = """(e => {
  const walk = document.createTreeWalker(e, NodeFilter.SHOW_TEXT); let first = null, last = null, n;
  while ((n = walk.nextNode())) if (n.textContent.trim()) { first = first || n; last = n; }
  const box = (node, i) => { const r = document.createRange(); r.setStart(node, i); r.setEnd(node, i + 1); return r.getBoundingClientRect(); };
  const end = last.textContent.replace(/\\s+$/, '').length - 1;
  return {start: box(first, first.textContent.search(/\\S/)).left, stop: box(last, end).left, dir: getComputedStyle(e).direction};
})"""
LINES = {"Hebrew": "שלחתי את התיקון לבדיקה.", "Arabic": "أرسلت الإصلاح للمراجعة.",
         "Hebrew with English inside": "פתחתי PR חדש ל-billing.", "English": "Billing is opening the PR.",
         "English with Hebrew inside": "Send it to the תור team.", "digits first, then Hebrew": "42 בדיקות עברו."}
RTL = {"Hebrew", "Arabic", "Hebrew with English inside", "digits first, then Hebrew"}


async def rtl(page: Page) -> None:
    for name, text in LINES.items():
        places = {
            "your bubble": f"turnItem({{id: -1, who: 'user', text: {json.dumps(text)}}}, false)",
            "the bot's bubble": f"turnItem({{id: -2, who: 'assistant', text: {json.dumps(text)}}}, false)",
            "a recent request": f"el('div', 'said', {json.dumps('“' + text + '”')})",
        }
        for where, make in places.items():
            got = await page.js(f"(() => {{ const e = {make}; e.style.maxWidth = '600px'; $('talk').append(e);"
                                f" const r = {EDGES}(e); e.remove(); return r; }})()")
            ok = got["stop"] < got["start"] if name in RTL else got["stop"] > got["start"]
            check(f"{name} in {where}: the full stop is at the {'left' if name in RTL else 'right'} end", ok, **got)
        got = await page.js(f"(() => {{ $('caption-text').textContent = {json.dumps(text)}; $('caption').hidden = false;"
                            f" const r = {EDGES}($('caption-text')); $('caption').hidden = true; return r; }})()")
        ok = got["stop"] < got["start"] if name in RTL else got["stop"] > got["start"]
        check(f"{name} in the caption: the full stop is at the {'left' if name in RTL else 'right'} end", ok, **got)
    await page.js("$('talk').append(turnItem({id: -3, who: 'user', text: " + json.dumps(LINES["Hebrew"]) + "}, false),"
                  " turnItem({id: -4, who: 'assistant', text: " + json.dumps(LINES["Arabic"]) + "}, false),"
                  " turnItem({id: -5, who: 'user', text: " + json.dumps(LINES["English"]) + "}, false)); true")
    await page.shot("rtl-conversation")
    await page.js("[...$('talk').querySelectorAll('li')].filter(li => +li.dataset.id < 0 || !li.dataset.id).forEach(li => li.remove()); true")


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
            await settings(page)
            await page.js("for (let i = 1; i < 5000; i++) clearInterval(i); true")  # no poll redraws under the measurements
            await rtl(page)
    finally:
        chrome.terminate()
        stop_daemon()
    print(f"screenshots: {SHOTS}")
    failed = [r for r in results if not r["ok"]]
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
