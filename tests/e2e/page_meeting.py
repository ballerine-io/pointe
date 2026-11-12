"""Meeting mode from the page, in a real (headless) Chrome: the operator starts a meeting through the start and consent
sheets, three synthesized voices talk in the room (the call is the test's own client), the notes land in the page, the
raised hand shows as a banner the operator lets speak, and the end sheet exports and sends the action items.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-meetweb CLAUDE_VOICE_DAEMON_PORT=7905 CLAUDE_VOICE_TLS_PORT=7505 \
     uv run python -u -I tests/e2e/page_meeting.py
Screenshots of each state go to $POINTE_SHOTS (default: a temporary folder, printed at the end).
"""

import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).parent))
from rig import DAEMON, GUEST_VOICES, ROOT, STATE, Browser, fresh_state, stop_daemon  # noqa: E402
from scenarios import check, results  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEBUG_PORT = int(os.environ.get("POINTE_CHROME_PORT", "9335"))  # parallel runs each need their own
DANA, SAM = GUEST_VOICES
ROOM = [  # (voice, or None for the owner; line): the lines tests/e2e/meeting.py uses, minus its approval checks
    (DANA, "Hi everyone, I'm Dana. The new pricing page goes live on Thursday."),
    (SAM, "Do we know what the conversion rate of the old checkout page was last quarter?"),
    (DANA, "No idea. Nobody here has that number."),
    (None, "Okay, let's move on."),
    (SAM, "Who is writing the release note for the pricing launch?"),
    (DANA, "I'll write the release note by Wednesday."),
    (DANA, "Also, the refunds flow still uses the old prices."),
]
RISKY = [
    (SAM, "To save time we will skip the payment tests and ship Thursday anyway."),
    (DANA, "Right, nobody runs those tests, and refunds were never tested either."),
    (SAM, "And we will turn off the error alerts during the launch so nobody gets paged."),
]
SHOTS = Path(os.environ.get("POINTE_SHOTS") or tempfile.mkdtemp(prefix="pointe-meeting-shots-"))


async def room(browser: Browser, lines, pause: float = 1.0) -> None:
    for voice, line in lines:
        _, end = await (browser.say(line) if voice is None else browser.say(line, voice))
        await asyncio.sleep(end - time.time() + pause)


def call(path: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(f"{DAEMON}{path}", data=json.dumps(body).encode() if body is not None else None,
                                     method="POST" if body is not None else "GET", headers={
                                         "Authorization": f"Bearer {(STATE / 'token').read_text().strip()}",
                                         "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=120).read())


class Page:
    def __init__(self, socket):
        self.socket, self.n = socket, 0

    async def cdp(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        await self.socket.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            reply = json.loads(await self.socket.recv())
            if reply.get("id") == self.n:
                return reply.get("result", {})

    async def js(self, expression: str):
        result = await self.cdp("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True})
        return result.get("result", {}).get("value")

    async def shot(self, name: str) -> Path:
        await asyncio.sleep(0.8)  # the next poll paints
        data = (await self.cdp("Page.captureScreenshot", {"format": "png"}))["data"]
        path = SHOTS / f"{name}.png"
        path.write_bytes(base64.b64decode(data))
        return path

    async def until(self, expression: str, timeout: float, every: float = 0.5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            value = await self.js(expression)
            if value:
                return value
            await asyncio.sleep(every)
        return await self.js(expression)


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    fresh_state()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    work = Path(tempfile.mkdtemp(prefix="page-meeting-e2e-"))
    (work / "transcript.jsonl").touch()
    call("/voice/register", {"id": f"page-meeting-{os.getpid()}", "cwd": str(work), "pid": os.getpid(), "name": "pricing",
                             "name_given": True, "transcript": str(work / "transcript.jsonl")})
    browser = Browser(echo_gain=0.5)
    profile = tempfile.mkdtemp(prefix="pointe-chrome-")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}",
                               "--window-size=1400,900", "--no-first-run",
                               f"{DAEMON}/voice?key={(STATE / 'page_key').read_text().strip()}"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        await browser.connect()  # the room's call: this test's client plays three voices into it
        await asyncio.sleep(8)
        for _ in range(40):
            try:
                pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=1).read())
                target = next(p for p in pages if p.get("type") == "page" and "/voice" in p.get("url", ""))
                break
            except Exception:
                time.sleep(0.5)
        async with connect(target["webSocketDebuggerUrl"], max_size=None) as socket:
            page = Page(socket)
            await page.js("window.__errors = []; addEventListener('error', e => __errors.push(e.message)); "
                          "addEventListener('unhandledrejection', e => __errors.push(String(e.reason)))")
            await page.js("window.__notesUrls = []; const realFetch = window.fetch; window.fetch = (u, o) => { "
                          "if (String(u).startsWith('/voice/notes?')) __notesUrls.push(String(u)); return realFetch(u, o); }")
            await page.until("!document.getElementById('meetbtn').disabled", 15)

            await page.js("openSettings()")
            await page.until("document.getElementById('settingssheet').classList.contains('open')", 5)
            await page.js("document.getElementById('pref-lang').value = 'en'; document.getElementById('pref-mode').value = 'listening'")
            await page.shot("0-settings")
            await page.js("saveSettings()")
            closed = await page.until("!document.getElementById('settingssheet').classList.contains('open')", 5)
            check("Settings saves the meeting defaults", bool(closed) and call("/voice/prefs").get("meeting.notes_language") == "en",
                  prefs=call("/voice/prefs"))

            await page.js("document.getElementById('meetbtn').click()")
            opened = await page.until("document.getElementById('meetsheet').classList.contains('open') && "
                                      "document.querySelectorAll('#meetsessions input').length", 5)
            await page.js("document.getElementById('meetbrief').value = 'Weekly sync on the checkout pricing launch.'")
            await page.shot("1-start")
            check("Meeting opens the start sheet, with the linked sessions to pick", bool(opened), sessions=opened)

            await page.js("meetingConsent()")
            vendors = await page.until("document.getElementById('meetstep2').style.display === 'flex' && "
                                       "document.getElementById('meetvendors').textContent", 10)
            locked = await page.js("document.getElementById('meetstart').disabled")
            await page.shot("2-consent")
            check("the consent step names who gets the room's audio, and Start waits for the checkbox",
                  bool(vendors) and "Room audio" in vendors and "Soniox" in vendors and locked, vendors=vendors, locked=locked)

            await page.js("document.getElementById('meetconsent').click(); document.getElementById('meetstart').click()")
            on = await page.until("document.body.classList.contains('meeting') && document.getElementById('meetwhat').textContent", 10)
            recording = await page.js("document.title + ' | ' + document.getElementById('meetsub').textContent")
            check("Start shows the recording banner and the title says so",
                  on == "Meeting · Listening" and recording.startswith("● Meeting") and "audio to Soniox" in recording,
                  banner=on, sub=recording)

            start = time.time()
            await room(browser, [(None, "Pointe, that's me.")])
            await room(browser, ROOM)
            noted = await page.until("[...document.querySelectorAll('#notelist li:not(.empty)')].map(x => x.className).join(' ')", 60)
            await asyncio.sleep(6)
            await page.shot("3-listening-notes")
            check("notes land in the page while it stays silent", bool(noted) and not browser.speaker.speech_spans(since=start),
                  kinds=noted)
            chips = await page.js("[...document.querySelectorAll('#speakers .chip')].map(x => x.textContent)")
            owner_known = call("/voice/status")["meeting"]["owner_known"]  # “that's me” is recognized most runs, not all
            check("the banner shows the speakers, and You exactly when the daemon knows the owner",
                  bool(chips) and ("You" in chips) == owner_known, chips=chips, owner_known=owner_known)

            suggested = next((n["meta"]["name"] for n in call("/voice/notes?since=0")["notes"] if n["kind"] == "speaker" and n["state"] == "open"), None)
            await page.js("""(() => { const b = [...document.querySelectorAll('#notelist li.speaker button')]
                                  .find(x => x.textContent === 'Use this name'); if (b) b.click(); })()""")
            if suggested:
                named = await page.until(f"[...document.querySelectorAll('#speakers .chip')].some(x => x.textContent === {json.dumps(suggested)})", 6)
                check("“Use this name” names the speaker", bool(named),
                      chips=await page.js("[...document.querySelectorAll('#speakers .chip')].map(x => x.textContent)"))

            await page.js("document.querySelector('#notes .filters button[data-f=transcript]').click()")
            turns = await page.until("document.querySelectorAll('#notelist li.turn').length", 8)
            check("the Transcript filter shows the room's turns", (turns or 0) >= 3, turns=turns)
            await page.js("document.querySelector('#notes .filters button[data-f=all]').click()")

            urls = await page.js("__notesUrls")
            whole = [u for u in urls if "changed_since=" not in u]  # the start loads the list whole, then only changes
            check("the notes poll asks only for what changed since the version it last saw",
                  len(whole) <= 2 and len(urls) > len(whole), whole=whole, urls=urls[-3:], count=len(urls))
            refused = await page.js("meetPost({action: 'discard'}).then(() => 'accepted', e => e.message)")
            check("a 409 reads as a sentence: discard while the meeting is on", refused == "End the meeting first: it is still on.",
                  shown=refused)
            bad = await page.js("meetPost({action: 'owner', turn_id: 'x'}).then(() => 'accepted', e => e.message)")
            check("a 400 reads as a sentence", (bad or "").startswith("Pointe did not accept that: turn_id must be a number."),
                  shown=bad)

            await page.js("document.getElementById('meetredial').click()")
            told = await page.until("document.getElementById('problem').textContent.includes('that’s me')", 10)
            unknown = await page.until("document.getElementById('meetsub').textContent.includes('say “Pointe, that’s me”')", 15)
            await page.shot("3b-reconnected")
            check("Reconnect audio: a new stream, and it asks the owner to say “Pointe, that's me” again",
                  bool(told) and bool(unknown) and call("/voice/status")["meeting"]["owner_known"] is False,
                  problem=await page.js("document.getElementById('problem').textContent"),
                  sub=await page.js("document.getElementById('meetsub').textContent"))
            await room(browser, [(None, "Pointe, that's me.")])

            await page.js("document.getElementById('mm-participating').click()")
            await page.until("document.getElementById('meetwhat').textContent === 'Meeting · Participating'", 6)
            risky_at = time.time()
            await room(browser, RISKY, pause=1.5)
            hand = await page.until("!document.getElementById('hand').hidden && document.getElementById('handline').textContent", 90, 1)
            await page.shot("4-raised-hand")
            check("participating: the raised hand shows as a banner, and the bot stays quiet",
                  bool(hand) and not browser.speaker.speech_spans(since=risky_at), hand=hand)

            let_at = time.time()
            await page.js("document.getElementById('handspeak').click()")
            for _ in range(40):
                if browser.speaker.speech_spans(since=let_at):
                    break
                await asyncio.sleep(0.5)
            check("Let it speak makes it say its point", bool(browser.speaker.speech_spans(since=let_at)))
            await asyncio.sleep(8)

            await page.js("document.querySelector('#meetbar button[onclick=\"endMeeting()\"]').click()")
            ending = await page.until("document.getElementById('meetsub').textContent.includes('Ending: writing the summary') && "
                                      "document.getElementById('meetend').disabled", 10, 0.2)
            again = await page.js("meetPost({action: 'end'}).then(() => 'accepted', e => e.message)")
            check("while it ends, the banner says so, End is off, and a second end reads as a sentence",
                  bool(ending) and again == "The meeting is already ending: the summary is being written.", second=again)
            ended = await page.until("document.getElementById('endsheet').classList.contains('open') && "
                                     "document.getElementById('endbody').textContent", 90, 1)
            await page.shot("5-end")
            check("End shows the summary and the action items", bool(ended) and "Summary" in ended and "Action items" in ended,
                  body=(ended or "")[:240])
            check("after the end the banner is gone and nothing records",
                  not await page.js("document.body.classList.contains('meeting')") and not call("/voice/status")["meeting"].get("on"))

            await page.js("exportMeeting(true)")
            saved = await page.until("document.getElementById('endok').textContent", 10)
            check("Export saves the notes and the transcript", bool(saved) and "Saved to" in saved and
                  Path(saved.removeprefix("Saved to ")).exists(), saved=saved)

            await page.js("document.getElementById('endsend').click()")
            asked = await page.js("document.getElementById('endsend').textContent + ' | ' + document.getElementById('endok').textContent")
            check("the first Send click only asks where it goes", asked.startswith("Send to pricing?") and "Saved to" in asked,
                  shown=asked)
            await page.js("document.getElementById('endsend').click()")
            sending = await page.until("document.getElementById('endok').textContent.startsWith('Sending')", 2, 0.1)
            check("the second click says it is sending at once", bool(sending))
            sent = await page.until("/Asked to send/.test(document.getElementById('endok').textContent + '') || "
                                    "document.getElementById('enderr').textContent", 120, 1)
            check("the second click sends the action items to the session", sent is True,
                  shown=sent, err=await page.js("document.getElementById('enderr').textContent"))

            await page.js("discardMeeting()")
            gone = await page.until("!document.getElementById('endsheet').classList.contains('open') && "
                                    "!document.body.classList.contains('meetend')", 6)
            check("Discard closes the end sheet", bool(gone))
            errors = await page.js("window.__errors || []")
            check("no page errors", not errors, errors=errors)
    finally:
        chrome.terminate()
        await browser.close()
        stop_daemon()
        print(f"\nscreenshots: {SHOTS}")
        print(f"{sum(r['ok'] for r in results)}/{len(results)} passed (page meeting)")


if __name__ == "__main__":
    asyncio.run(main())
