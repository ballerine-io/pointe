"""Meeting mode in the page, the edges: every control on the hand banner, lookups only on click, "That was me", renaming
from a chip, typed questions in both modes, mode switches, a dropped and restored call, a second tab, Escape and
keyboard-only use, screen-reader names, a narrow screen, hundreds of notes, Hebrew, no Soniox key, ending while a hand
is up, and a daemon restart mid-meeting. Three synthesized voices talk in the room through the test's own call.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-meetweb CLAUDE_VOICE_DAEMON_PORT=7905 CLAUDE_VOICE_TLS_PORT=7505 \
     uv run python -u -I tests/e2e/page_meeting_qa.py
Takes about fifteen minutes: one raised hand per two minutes is the daemon's rule. Screenshots go to $POINTE_SHOTS.
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

from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).parent))
from page_meeting import CHROME, Page, call, room  # noqa: E402
from rig import DAEMON, GUEST_VOICES, ROOT, STATE, Browser, fresh_state, stop_daemon  # noqa: E402
from scenarios import check, results  # noqa: E402

DEBUG_PORT = int(os.environ.get("POINTE_CHROME_PORT", "9336"))  # parallel runs each need their own
SHOTS = Path(os.environ.get("POINTE_SHOTS") or tempfile.mkdtemp(prefix="pointe-meeting-qa-"))
DANA, SAM = GUEST_VOICES
ROOM = [
    (DANA, "Hi everyone, I'm Dana. The new pricing page goes live on Thursday."),
    (SAM, "What was the conversion rate of the old checkout page last quarter? The pricing session measured it."),
    (DANA, "I don't remember the number. It should be in the pricing work."),
    (None, "Okay, let's move on."),
    (DANA, "I'll write the release note by Wednesday."),
]
RISKY = [
    (SAM, "To save time we will skip the payment tests and ship Thursday anyway."),
    (DANA, "And we will turn off the error alerts during the launch so nobody gets paged."),
]
RISKY2 = [
    (SAM, "Let's give every support agent admin access to the production database so they can fix orders directly."),
    (DANA, "Sure, and we can post the database password in the general channel so everyone has it."),
]
RISKY4 = [
    (SAM, "For the campaign we will email the full list of customer credit card numbers to the marketing agency today."),
    (DANA, "Fine, send them the card numbers in a spreadsheet, unencrypted."),
]
RISKY3 = [
    (SAM, "Tonight we delete the old customers table without a backup, it takes too much space."),
    (DANA, "Right, no backup, just drop it before the launch."),
]
KEYS = {"Tab": 9, "Enter": 13, "Escape": 27, "g": 71}


async def key(page: Page, name: str, shift: bool = False) -> None:
    code = {"g": "KeyG"}.get(name, name)
    params = {"key": name, "code": code, "windowsVirtualKeyCode": KEYS[name], "modifiers": 8 if shift else 0}
    if name in ("Enter", "g"):
        params["text"] = "\r" if name == "Enter" else "g"
    await page.cdp("Input.dispatchKeyEvent", {"type": "keyDown", **params})
    await page.cdp("Input.dispatchKeyEvent", {"type": "keyUp", **{k: v for k, v in params.items() if k != "text"}})
    await asyncio.sleep(0.15)


async def focused(page: Page) -> str:
    return await page.js("(() => { const a = document.activeElement; return a ? (a.id || a.textContent.trim().slice(0, 30) || a.tagName) : ''; })()")


async def in_sheet(page: Page, sheet: str) -> bool:
    return await page.js(f"document.getElementById('{sheet}').contains(document.activeElement)")


def seed_session(work: Path, session_id: str) -> None:
    """A linked session whose record holds the number the room asks for, so a lookup has something to find."""
    lines = [
        {"type": "user", "message": {"role": "user", "content": "Measure the conversion rate of the old checkout page for last quarter."},
         "timestamp": "2026-11-10T09:00:00Z"},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text":
         "Done. The old checkout page converted at 3.2 percent last quarter (12,480 orders from 390,000 sessions)."}]},
         "timestamp": "2026-11-10T09:05:00Z"},
    ]
    (work / "transcript.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    (STATE / "briefs").mkdir(parents=True, exist_ok=True)
    (STATE / "briefs" / f"{session_id}.json").write_text(json.dumps({"brief": {
        "goal": "Pricing launch analysis.", "state": "Measured the old checkout page's conversion rate for last quarter.",
        "decided": "The old checkout converted at 3.2 percent last quarter."}, "size": (work / "transcript.jsonl").stat().st_size}))


async def wait_hand(page: Page, timeout: float) -> str | None:
    return await page.until("!document.getElementById('hand').hidden && document.getElementById('handline').textContent", timeout, 1)


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    SHOTS.mkdir(parents=True, exist_ok=True)
    fresh_state()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    work = Path(tempfile.mkdtemp(prefix="page-meeting-qa-"))
    session_id = f"page-meeting-qa-{os.getpid()}"
    seed_session(work, session_id)
    call("/voice/register", {"id": session_id, "cwd": str(work), "pid": os.getpid(), "name": "pricing", "name_given": True,
                             "transcript": str(work / "transcript.jsonl")})
    browser = Browser(echo_gain=0.5)
    profile = tempfile.mkdtemp(prefix="pointe-chrome-")
    url = f"{DAEMON}/voice?key={(STATE / 'page_key').read_text().strip()}"
    chrome = subprocess.Popen([CHROME, "--headless=new", "--use-mock-keychain", "--password-store=basic", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}",
                               "--window-size=1400,900", "--no-first-run", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        await browser.connect()
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
            await page.cdp("Emulation.setFocusEmulationEnabled", {"enabled": True})
            await page.js("window.__errors = []; addEventListener('error', e => __errors.push(e.message)); "
                          "addEventListener('unhandledrejection', e => __errors.push(String(e.reason)))")
            await page.until("!document.getElementById('meetbtn').disabled", 15)

            # ---- keyboard only: Settings, then the start sheet ----
            await page.js("document.getElementById('settingsbtn').focus()")
            await key(page, "Enter")
            # Focus lands on the sheet's first control, whichever that is (the sheet has changed since "pref-mode" was first).
            first = await page.until("document.getElementById('settingssheet').classList.contains('open') && "
                                     "document.getElementById('settingssheet').contains(document.activeElement) && "
                                     "(document.activeElement.id || document.activeElement.textContent.trim().slice(0, 30) || document.activeElement.tagName)", 4)
            stays = True
            for _ in range(8):
                await key(page, "Tab")
                stays = stays and await in_sheet(page, "settingssheet")
            await key(page, "Tab", shift=True)
            stays = stays and await in_sheet(page, "settingssheet")
            await key(page, "Escape")
            back = await focused(page)
            closed = not await page.js("document.getElementById('settingssheet').classList.contains('open')")
            check("keyboard: Settings opens on Enter with focus inside, Tab stays inside, Escape closes and focus returns",
                  bool(first) and stays and closed and back == "settingsbtn", first=first, stays=stays, back=back)

            await page.js("document.getElementById('meetbtn').focus()")
            await key(page, "Enter")
            first = await page.until("document.getElementById('meetsheet').classList.contains('open') && document.activeElement.id", 4)
            order, inside = [], True
            for _ in range(9):
                await key(page, "Tab")
                order.append(await focused(page))
                inside = inside and await in_sheet(page, "meetsheet")
            check("keyboard: the start sheet focuses the context field and Tab walks its controls in order, inside the sheet",
                  first == "meetbrief" and inside and "Next" in order and "Cancel" in order,
                  first=first, order=order)
            await key(page, "Escape")
            check("Escape closes the start sheet (step 1)", not await page.js("document.getElementById('meetsheet').classList.contains('open')"))

            # ---- no Soniox key: the consent step says why, and Start stays disabled ----
            await page.js("""window.__realFetch = window.fetch; window.fetch = async (u, o) => {
                const r = await __realFetch(u, o);
                if (String(u).endsWith('/voice/meeting') && o && /"vendors"/.test(o.body)) {
                  const d = await r.clone().json(); d.soniox = false; return new Response(JSON.stringify(d), {status: 200}); }
                return r; }""")
            await page.js("openMeeting()")
            await page.until("document.getElementById('meetsheet').classList.contains('open')", 4)
            await page.js("meetingConsent()")
            reason = await page.until("document.getElementById('meeterr2').textContent", 6)
            await page.js("document.getElementById('meetconsent').click()")
            locked = await page.js("document.getElementById('meetstart').disabled && document.getElementById('meetconsent').disabled")
            await page.shot("qa-01-no-soniox")
            check("no Soniox key: Start stays disabled and the sheet says why", bool(locked) and "Soniox key" in (reason or ""),
                  reason=reason, locked=locked)
            await key(page, "Escape")
            check("Escape closes the consent step", not await page.js("document.getElementById('meetsheet').classList.contains('open')"))
            await page.js("window.fetch = window.__realFetch")

            # ---- a participating meeting with a linked session ----
            await page.js("openMeeting()")
            await page.until("document.querySelectorAll('#meetsessions input').length", 5)
            await page.js("document.querySelector('input[name=mmode][value=participating]').click(); "
                          "document.getElementById('meetbrief').value = 'Pricing launch sync.'; meetingConsent()")
            await page.until("document.getElementById('meetstep2').style.display === 'flex'", 8)
            await page.js("document.getElementById('meetconsent').click(); document.getElementById('meetstart').click()")
            on = await page.until("document.body.classList.contains('meeting') && document.getElementById('meetwhat').textContent", 10)
            caption = await page.until("document.getElementById('caption').hidden", 3)
            check("in a meeting the live caption of the main recognizer is hidden (the transcript holds the room's words)", bool(caption))
            check("a participating meeting starts with the linked session", on == "Meeting · Participating"
                  and call("/voice/status")["meeting"]["sessions"] == ["pricing"], banner=on)
            live = await page.js("document.getElementById('meetbar').getAttribute('aria-live')")
            check("screen readers: the banner's ticking clock is not a live region", live is None, aria_live=live)

            start = time.time()
            await room(browser, [(None, "Pointe, that's me.")])
            await room(browser, ROOM)

            # ---- Look it up: only on click; the answer arrives as a note ----
            ask = await page.until("""(() => { const b = [...document.querySelectorAll('#notelist li.question button')]
                                         .find(x => /^Look it up/.test(x.textContent)); return b ? b.textContent : ''; })()""", 70, 1)
            await asyncio.sleep(12)
            early = [n for n in call("/voice/notes?since=0")["notes"] if n["kind"] == "answer"]
            check("a question a linked session can answer gets a Look it up button, and nothing is looked up before the click",
                  bool(ask) and not early, button=ask, early=[n["text"][:80] for n in early])
            if ask:
                await page.js("""[...document.querySelectorAll('#notelist li.question button')].find(x => /^Look it up/.test(x.textContent)).click()""")
                busy = await page.until("[...document.querySelectorAll('#notelist .busy')].map(x => x.textContent).join()", 3, 0.2)
                answer = await page.until("[...document.querySelectorAll('#notelist li.answer .x')].map(x => x.textContent).join(' | ')", 120, 1)
                await page.shot("qa-02-lookup-answer")
                check("Look it up shows it is working, then the answer lands as a note", bool(busy) and bool(answer),
                      busy=busy, answer=(answer or "")[:200])
                check("the answer holds the session's number", "3.2" in (answer or ""), answer=(answer or "")[:200])

            # ---- Not now on the first raised hand ----
            hand_at = time.time()
            await room(browser, RISKY, pause=1.5)
            hand = await wait_hand(page, 90)
            await page.shot("qa-03-hand")
            thoughts = len([n for n in call("/voice/notes?since=0")["notes"] if n["kind"] == "thought"])
            quiet_at = time.time()
            await page.js("[...document.querySelectorAll('#hand button')].find(x => x.textContent === 'Not now').click()")
            gone = await page.until("document.getElementById('hand').hidden", 4)
            await asyncio.sleep(5)
            later = len([n for n in call("/voice/notes?since=0")["notes"] if n["kind"] == "thought"])
            check("Not now: the hand goes away, it stays quiet, and no note is added for it",
                  bool(hand) and bool(gone) and not browser.speaker.speech_spans(since=quiet_at) and later == thoughts,
                  hand=hand, thoughts=(thoughts, later))
            hand_at = time.time() if hand else hand_at

            # ---- chips, That was me, renaming ----
            chips = await page.js("[...document.querySelectorAll('#speakers .chip')].map(x => x.textContent)")
            await page.js("document.querySelector('#notes .filters button[data-f=transcript]').click()")
            await page.until("document.querySelectorAll('#notelist li.turn').length >= 4", 10)
            owner_label = next((s["label"] for s in call("/voice/status")["meeting"]["speakers"] if s["is_owner"]), None)
            clicked = await page.js("""(() => { const li = [...document.querySelectorAll('#notelist li.turn')]
                                        .find(x => /release note/.test(x.textContent) && x.querySelector('button'));
                                      if (!li) return false; li.querySelector('button').click(); return true; })()""")
            await asyncio.sleep(2)
            moved = next((s["label"] for s in call("/voice/status")["meeting"]["speakers"] if s["is_owner"]), None)
            check("That was me: the owner moves to that turn's speaker", clicked and moved not in (None, owner_label),
                  before=owner_label, after=moved)
            mine = next((t["speaker"] for t in call("/voice/meeting/transcript")["turns"] if "move on" in t["text"].lower()), None)
            await page.until("""[...document.querySelectorAll('#notelist li.turn')].some(x => /move on/.test(x.textContent) && x.querySelector('button'))""", 6)
            await page.js("""(() => { const li = [...document.querySelectorAll('#notelist li.turn')]
                                  .find(x => /move on/.test(x.textContent) && x.querySelector('button')); if (li) li.querySelector('button').click(); })()""")
            await asyncio.sleep(2)
            restored = next((s["label"] for s in call("/voice/status")["meeting"]["speakers"] if s["is_owner"]), None)
            check("That was me on your own turn makes that speaker the owner, and the chip follows",
                  restored == mine and await page.until("[...document.querySelectorAll('#speakers .chip.you')].length === 1", 4),
                  restored=restored, yours=mine)
            await page.js("document.querySelector('#notes .filters button[data-f=all]').click()")

            other = next((s for s in call("/voice/status")["meeting"]["speakers"] if not s["is_owner"] and s.get("name") == f"Speaker {s['label']}"), None)
            if other:
                await page.js(f"""[...document.querySelectorAll('#speakers .chip')].find(x => x.textContent === 'Speaker {other["label"]}').click()""")
                editing = await page.until("document.activeElement && document.activeElement.closest('#speakers') && document.activeElement.tagName === 'INPUT'", 3)
                await page.cdp("Input.insertText", {"text": "Sam"})
                await key(page, "Enter")
                renamed = await page.until("[...document.querySelectorAll('#speakers .chip')].some(x => x.textContent === 'Sam')", 5)
                check("renaming a speaker from its chip", bool(editing) and bool(renamed),
                      chips=await page.js("[...document.querySelectorAll('#speakers .chip')].map(x => x.textContent)"))
            else:
                check("renaming a speaker from its chip", False, chips=chips, note="no unnamed speaker to rename")

            # ---- typed questions in both modes; mode switches both ways ----
            typed_at = time.time()
            await page.js("""(() => { const box = document.getElementById('typed'); box.value = 'Pointe, when does the pricing page go live?';
                                   document.getElementById('compose').requestSubmit(); })()""")
            spoke = None
            for _ in range(40):
                spoke = browser.speaker.speech_spans(since=typed_at)
                if spoke:
                    break
                await asyncio.sleep(0.5)
            check("participating: a typed question is answered aloud to the room", bool(spoke))
            for _ in range(80):  # its answer runs ten to twenty seconds: the listening check must not hear its tail
                if not browser.speaker.speech_spans(since=time.time() - 3):
                    break
                await asyncio.sleep(0.5)

            await page.js("document.getElementById('mm-listening').click()")
            listening = await page.until("document.getElementById('meetwhat').textContent === 'Meeting · Listening' && "
                                         "document.getElementById('mm-listening').getAttribute('aria-pressed') === 'true' && "
                                         "document.getElementById('typed').placeholder", 6)
            check("switching to Listening updates the banner, the pressed state and the box's hint",
                  listening == "Ask Pointe (the answer is a note)…", hint=listening)
            typed_at = time.time()
            await page.js("""(() => { const box = document.getElementById('typed'); box.value = 'Who owns the release note?';
                                   document.getElementById('compose').requestSubmit(); })()""")
            asked = await page.until("[...document.querySelectorAll('#notelist li .x')].some(x => /You asked: Who owns the release note/.test(x.textContent))", 10)
            await asyncio.sleep(20)
            check("listening: a typed question becomes a note, and it says nothing",
                  bool(asked) and not browser.speaker.speech_spans(since=typed_at), asked=asked)
            await page.js("document.getElementById('mm-participating').click()")
            back_to = await page.until("document.getElementById('meetwhat').textContent === 'Meeting · Participating' && "
                                       "document.getElementById('typed').placeholder", 6)
            check("switching back to Participating", back_to == "Ask Pointe (it answers the room)…", hint=back_to)

            # ---- screen-reader names, narrow screens, hundreds of notes, Hebrew ----
            unnamed = await page.js("""[...document.querySelectorAll('#meetbar button, #notes button, .dock button, .sheetbox button, .sheetbox input, .sheetbox select, .sheetbox textarea')]
                .filter(b => !(b.getAttribute('aria-label') || b.textContent.trim() || (b.labels && [...b.labels].some(l => l.textContent.trim())) || b.placeholder))
                .map(b => b.outerHTML.slice(0, 80))""")
            dialogs = await page.js("""[...document.querySelectorAll('.sheetbox')].map(d => d.getAttribute('role') === 'dialog' && d.getAttribute('aria-modal') === 'true'
                && !!document.getElementById(d.getAttribute('aria-labelledby')))""")
            pressed = await page.js("[...document.querySelectorAll('#meetbar .seg button, #notes .filters button')].every(b => b.hasAttribute('aria-pressed'))")
            check("screen readers: every control has a name, the sheets are labelled modal dialogs, toggles say pressed",
                  not unnamed and all(dialogs) and pressed, unnamed=unnamed, dialogs=dialogs, pressed=pressed)

            for width in (760, 390):
                await page.cdp("Emulation.setDeviceMetricsOverride", {"width": width, "height": 844, "deviceScaleFactor": 1, "mobile": width < 500})
                await asyncio.sleep(1.2)
                fit = await page.js("""(() => { const r = id => document.getElementById(id).getBoundingClientRect();
                    return {page: document.documentElement.scrollWidth <= innerWidth + 1, bar: r('meetbar').right <= innerWidth + 1,
                            end: [...document.querySelectorAll('#meetbar .end')][0].getBoundingClientRect().right <= innerWidth + 1,
                            notes: r('notelist').width > 200, dock: document.querySelector('.dock').getBoundingClientRect().right <= innerWidth + 1}; })()""")
                await page.shot(f"qa-04-narrow-{width}")
                check(f"narrow layout at {width} px: nothing spills sideways, the banner and End stay on screen",
                      all(fit.values()), fit=fit)
            await page.cdp("Emulation.clearDeviceMetricsOverride")
            await asyncio.sleep(1)

            perf = await page.js("""(async () => {
                const real = window.fetch, longword = 'x'.repeat(3000);
                const fake = Array.from({length: 400}, (_, i) => ({id: 100000 + i, kind: ['thought', 'question', 'action', 'decision'][i % 4],
                  at: Date.now() / 1000, updated: 0, state: 'open', meta: {}, speakers: [], session: null,
                  text: i === 7 ? longword : i === 9 ? 'ההחלטה: דנה כותבת את הודעת השחרור עד יום רביעי.' : `Note ${i}: a decision about the launch, the tests and the alerts.`}));
                window.fetch = async (u, o) => { const r = await real(u, o);
                  if (String(u).includes('/voice/notes?')) { const d = await r.clone().json(); d.notes = d.notes.concat(fake);
                    return new Response(JSON.stringify(d), {status: 200}); } return r; };
                window.__notesFake = () => { window.fetch = real; };
                const t0 = performance.now(); notesVersion = -2; await loadNotes(-3); const first = performance.now() - t0;
                const t1 = performance.now(); renderNotes(); const again = performance.now() - t1;
                const list = document.getElementById('notelist');
                const he = [...list.querySelectorAll('li .x')].find(x => x.textContent.startsWith('ההחלטה'));
                const long = [...list.querySelectorAll('li .x')].find(x => x.textContent === longword);
                list.scrollTop = list.scrollHeight;
                return {count: list.children.length, first_ms: Math.round(first), again_ms: Math.round(again),
                        scrolls: list.scrollHeight > list.clientHeight, sideways: list.scrollWidth > list.clientWidth + 1,
                        rtl: he && getComputedStyle(he).direction, long_fits: long && long.scrollWidth <= long.clientWidth + 1};
            })()""")
            await asyncio.sleep(0.5)
            await page.shot("qa-05-many-notes")
            check("hundreds of notes: the list renders fast, re-renders cheaply, scrolls, and long text wraps",
                  perf and perf["count"] >= 400 and perf["first_ms"] < 400 and perf["again_ms"] < 60 and perf["scrolls"]
                  and not perf["sideways"] and perf["long_fits"], perf=perf)
            check("Hebrew notes render right to left", perf and perf["rtl"] == "rtl", rtl=perf and perf["rtl"])
            await page.js("""__notesFake(); [...document.querySelectorAll('#notelist li')].filter(li => +li.dataset.id >= 100000).forEach(li => li.remove());
                             for (const id of [...notesById.keys()]) if (id >= 100000) { notesById.delete(id); shownNotes.delete('n' + id); } notesVersion = -1""")
            check("a long meeting's clock reads hours", await page.js("clock(3725)") == "1:02:05", clock=await page.js("clock(3725)"))

            # ---- a second tab ----
            made = await page.cdp("Target.createTarget", {"url": url})
            await asyncio.sleep(4)
            pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=2).read())
            second = next(p for p in pages if p.get("id") == made.get("targetId"))
            async with connect(second["webSocketDebuggerUrl"], max_size=None) as socket2:
                tab2 = Page(socket2)
                seen = await tab2.until("document.body.classList.contains('meeting') && document.querySelectorAll('#notelist li:not(.empty)').length", 10)
                status = call("/voice/status")
                check("a second tab shows the same meeting and does not take over the call",
                      bool(seen) and status["meeting"]["on"] and status["connected"], notes=seen)
            await page.cdp("Target.closeTarget", {"targetId": made["targetId"]})
            await asyncio.sleep(2)
            check("closing the second tab leaves the meeting running in the first",
                  call("/voice/status")["meeting"]["on"] and await page.js("document.body.classList.contains('meeting')"))

            # ---- the call drops and comes back ----
            turns_before = call("/voice/status")["meeting"]["turns"]
            await browser.close()
            dropped = await page.until("document.getElementById('meetsub').textContent.includes('The call dropped')", 15)
            await page.shot("qa-06-call-dropped")
            check("when the call drops, the meeting stays on and the banner says nothing is heard until a reconnect",
                  bool(dropped) and call("/voice/status")["meeting"]["on"])
            browser = Browser(echo_gain=0.5)
            await browser.connect()
            await asyncio.sleep(8)
            await room(browser, [(DANA, "Back again. The refunds flow still uses the old prices, someone has to fix that.")])
            more = 0
            for _ in range(60):  # a turn closes when the speaker pauses long enough or the next one starts
                heard = [t for t in call("/voice/meeting/transcript")["turns"] if "back again" in t["text"].lower()]
                more = call("/voice/status")["meeting"]["turns"] - turns_before
                if heard:
                    break
                await asyncio.sleep(1)
            cleared = await page.until("!document.getElementById('meetsub').textContent.includes('The call dropped')", 10)
            refunds = await page.until("[...document.querySelectorAll('#notelist li .x')].some(x => /refund/i.test(x.textContent))", 60, 1)
            check("after a reconnect the meeting keeps hearing the room and the notes catch up",
                  bool(heard) and bool(cleared) and bool(refunds), new_turns=more, heard=[t["text"][:60] for t in heard], refunds_note=refunds)

            # ---- Type it instead on the second hand ----
            await asyncio.sleep(max(0, hand_at + 122 - time.time()))
            await room(browser, RISKY2, pause=1.5)
            hand = await wait_hand(page, 120)
            before = {n["id"] for n in call("/voice/notes?since=0")["notes"]}
            typed_at = time.time()
            await page.js("[...document.querySelectorAll('#hand button')].find(x => x.textContent === 'Type it instead').click()")
            gone = await page.until("document.getElementById('hand').hidden", 4)
            added = await page.until("[...document.querySelectorAll('#notelist li.thought')].length", 5)
            await asyncio.sleep(3)
            new = [n for n in call("/voice/notes?since=0")["notes"] if n["id"] not in before and n["kind"] == "thought"]
            check("Type it instead: the hand becomes a note and it stays quiet",
                  bool(hand) and bool(gone) and bool(new) and not browser.speaker.speech_spans(since=typed_at),
                  hand=hand, note=[n["text"][:100] for n in new], added=added)
            hand_at = time.time() if hand else hand_at

            # ---- the G key on the third hand ----
            await asyncio.sleep(max(0, hand_at + 122 - time.time()))
            await room(browser, RISKY3, pause=1.5)
            hand = await wait_hand(page, 120)
            await page.js("document.activeElement && document.activeElement.blur()")
            let_at = time.time()
            await key(page, "g")
            spoke = None
            for _ in range(40):
                spoke = browser.speaker.speech_spans(since=let_at)
                if spoke:
                    break
                await asyncio.sleep(0.5)
            check("G lets a raised hand speak", bool(hand) and bool(spoke) and await page.js("document.getElementById('hand').hidden"),
                  hand=hand)
            await asyncio.sleep(10)

            # ---- end; Escape on the end sheet; the end bar ----
            await page.js("document.querySelector('#meetbar .end').click(); document.querySelector('#meetbar .end').click()")  # asks, then ends
            ended = await page.until("document.getElementById('endsheet').classList.contains('open') && document.activeElement.id", 120, 1)
            await page.shot("qa-07-end")
            check("the end sheet opens with focus on its heading", ended == "end-h", focus=ended)
            await key(page, "Escape")
            endbar = await page.until("!document.getElementById('endsheet').classList.contains('open') && "
                                      "getComputedStyle(document.getElementById('endbar')).display === 'flex'", 4)
            await page.shot("qa-08-ended-notes")
            check("Escape closes the end sheet; the notes stay on screen with Summary and Close notes", bool(endbar))
            await page.js("[...document.querySelectorAll('#endbar button')].find(x => x.textContent === 'Summary').click()")
            again = await page.until("document.getElementById('endsheet').classList.contains('open')", 3)
            await key(page, "Escape")
            await page.js("document.getElementById('closenotes').click()")
            talk = await page.until("!document.body.classList.contains('meetend') && getComputedStyle(document.getElementById('talk')).display !== 'none'", 4)
            check("Summary reopens the end sheet; Close notes returns to the conversation", bool(again) and bool(talk))

            # ---- a second meeting: end while a hand is raised ----
            call("/voice/meeting", {"action": "discard"})
            await page.js("openMeeting()")
            await page.until("document.getElementById('meetsheet').classList.contains('open')", 4)
            await page.js("document.querySelector('input[name=mmode][value=participating]').click(); meetingConsent()")
            await page.until("document.getElementById('meetstep2').style.display === 'flex'", 8)
            await page.js("document.getElementById('meetconsent').click(); document.getElementById('meetstart').click()")
            await page.until("document.body.classList.contains('meeting')", 10)
            await asyncio.sleep(2)
            clean = await page.js("[...document.querySelectorAll('#notelist li:not(.empty)')].map(li => li.className + ': ' + li.querySelector('.x').textContent.slice(0, 80) + ' @' + li.dataset.id)")
            since = call("/voice/status")["meeting"]["since"]
            old = [f"{n['kind']} {n['id']} at {round(n['at'] - since, 1)}s" for n in call("/voice/notes?since=0")["notes"]
                   if n["at"] >= since - 2]
            check("a new meeting starts with an empty notes list", not clean, leftover=clean, near_start=old)
            await room(browser, RISKY4, pause=1.5)
            hand = await wait_hand(page, 90)
            end_at = time.time()
            await page.js("document.querySelector('#meetbar .end').click(); document.querySelector('#meetbar .end').click()")  # asks, then ends
            ended = await page.until("document.getElementById('endsheet').classList.contains('open')", 120, 1)
            ended_at = time.time()
            spans = [(round(a - end_at, 1), round(b - end_at, 1)) for a, b in browser.speaker.speech_spans(since=end_at - 1)]
            hidden = await page.js("document.getElementById('hand').hidden")
            check("ending while a hand is raised: the meeting ends, the hand is gone, it did not speak the hand",
                  bool(hand) and bool(ended) and hidden and not [x for x in spans if x[0] < ended_at - end_at - 1],
                  hand=hand, hidden=hidden, spans=spans, end_took=round(ended_at - end_at, 1))
            await page.js("discardMeeting(); discardMeeting()")  # the first click asks
            await asyncio.sleep(1)

            # ---- a third meeting: the daemon restarts in the middle ----
            call("/voice/meeting", {"action": "start", "mode": "listening", "consent": True})
            await page.until("document.body.classList.contains('meeting')", 10)
            await room(browser, [(DANA, "Quick note before the restart: the launch stays on Thursday.")])
            await browser.close()
            stop_daemon()
            down = await page.until("document.getElementById('meetsub').textContent.includes('not responding')", 20)
            await page.shot("qa-09-daemon-down")
            assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
            told = await page.until("!document.body.classList.contains('meeting') && !document.getElementById('endsheet').classList.contains('open') "
                                    "&& document.getElementById('problem').textContent", 30)
            await page.shot("qa-10-after-restart")
            stale = await page.js("document.getElementById('endsheet').classList.contains('open')")
            await asyncio.sleep(3)  # the next polls must not wipe it
            told = await page.js("(() => { const p = document.getElementById('problem'); return p.offsetParent ? p.textContent : ''; })()")
            check("daemon restart mid-meeting: the page says it is not responding, then that the meeting stopped and notes were not saved",
                  bool(down) and "Pointe restarted" in (told or "") and not stale, down=down, told=told, stale_end_sheet=stale)
            errors = await page.js("window.__errors || []")
            check("no page errors through all of it", not errors, errors=errors)
    finally:
        chrome.terminate()
        try:
            await browser.close()
        except Exception:
            pass
        stop_daemon()
        print(f"\nscreenshots: {SHOTS}")
        print(f"{sum(r['ok'] for r in results)}/{len(results)} passed (page meeting QA)")


asyncio.run(main())
