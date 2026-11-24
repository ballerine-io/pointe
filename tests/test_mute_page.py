"""The mute button, the held-news badge and the multi-line composer on the page (ui.html, ui_mute.html), in a headless
Chrome against the stub Mac (tests/page_rig.py). Skipped where that Chrome is not installed (CI on Linux).

- One mute toggle beside the call's status line: "Speaking…" while Pointe speaks, "Writing…" while it is muted and
  would have spoken. The browser keeps the choice, the call is dialled with it, the daemon is told; a change said by
  voice comes back on the call's socket and is kept. Muting flushes what the speakers still hold.
- No Read button, no Reading card, no Unread or Read marks.
- Session mode: other sessions' news is a quiet count; it lists the items and Tell me asks for them. Another session's
  request stays on its card and can be approved.
- The box: Enter sends, Shift+Enter and Option+Enter start a new line, IME composition never sends, and the line breaks
  reach /voice/say.

uv run --locked pytest -q tests/test_mute_page.py
"""

import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mute  # noqa: E402
import scope  # noqa: E402
from page_rig import CHROME, Browser, StubMac, fixture, free_port  # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")
SHOTS = Path(os.environ.get("POINTE_SHOTS", "/tmp/parity-shots"))


async def _page(status):
    stub = await StubMac(free_port()).start()
    stub.status = status
    browser = Browser()
    await browser.__aenter__()
    page = await browser.open(stub.url)
    await asyncio.sleep(0.8)
    return stub, browser, page


async def _close(stub, browser):
    await browser.__aexit__(None, None, None)
    await stub.stop()


async def _until(page, expression: str, timeout: float = 5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = await page.eval(expression)
        if value:
            return value
        await asyncio.sleep(0.15)
    return await page.eval(expression)


async def _shot(page, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    await page.cdp("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": "light"}]})
    await asyncio.sleep(0.3)
    data = (await page.cdp("Page.captureScreenshot", {"format": "png"}))["data"]
    (SHOTS / f"{name}.png").write_bytes(base64.b64decode(data))


def _posts(stub, path):
    return [body for p, body, _ in stub.posts if p == path]


def _talk_status():
    s = fixture(sessions=2, connected=True)
    s["talk"] = [{"id": 1, "who": "user", "text": "What did billing say?", "typed": False, "corrected": False},
                 {"id": 2, "who": "assistant", "text": "Billing finished: all 12 tests pass.", "typed": False,
                  "corrected": False, "unread": False},
                 {"id": 3, "who": "user", "text": "And the migration?", "typed": False, "corrected": False},
                 {"id": 4, "who": "assistant", "text": "It ran on the staging copy; production waits for your go.",
                  "typed": False, "corrected": False, "unread": True}]
    s["reading"] = {"on": True, "held": None, "read_through": 2}
    return s


# ---------- the mute button ----------

BTN = """(() => { const b = document.getElementById('mutebtn'), st = document.getElementById('state'); return {
  state: st.textContent, beside: b.previousElementSibling === st && b.parentElement === st.parentElement,
  gap: Math.round(b.getBoundingClientRect().left - st.getBoundingClientRect().right),
  sameRow: Math.abs((b.getBoundingClientRect().top + b.getBoundingClientRect().bottom) / 2
                    - (st.getBoundingClientRect().top + st.getBoundingClientRect().bottom) / 2) < 6,
  shown: b.getClientRects().length > 0, pressed: b.getAttribute('aria-pressed'), label: b.getAttribute('aria-label'),
  title: b.title, slash: !!b.querySelector('svg .slash'), stored: localStorage.getItem('pointe.reading')}; })()"""


def _speaking_status():
    s = _talk_status()
    s["reading"] = {"on": False, "held": None, "read_through": -1, "writing": False}
    s["speaking"] = "bot"
    return s


def _writing_status():
    s = _talk_status()
    s["reading"] = {"on": True, "held": None, "read_through": -1, "writing": True}
    return s


async def _on_a_call(page):
    """This page's own call is up: the status line is the call's."""
    state = await page.eval(DIAL)
    assert state == "live", state


def test_while_pointe_speaks_the_status_says_speaking_and_the_mute_button_sits_beside_it():
    async def run():
        stub, browser, page = await _page(_speaking_status())
        try:
            await _on_a_call(page)
            got = await _until(page, f"(() => {{ const g = {BTN}; return g.state === 'Speaking…' && g; }})()")
            await _shot(page, "page-speaking")
            await page.eval("document.getElementById('mutebtn').click()")
            after = await _until(page, f"(() => {{ const g = {BTN}; return g.pressed === 'true' && g; }})()")
            await page.eval("document.getElementById('mutebtn').click()")
            back = await _until(page, f"(() => {{ const g = {BTN}; return g.pressed === 'false' && g; }})()")
            return got, after, back, _posts(stub, "/voice/reading")
        finally:
            await _close(stub, browser)
    got, after, back, posts = asyncio.run(run())
    assert got and got["beside"] and got["sameRow"] and 0 <= got["gap"] <= 16, got
    assert got["shown"] and got["slash"] and got["pressed"] == "false" and got["label"] == mute.COPY["mute"], got
    assert after and after["label"] == mute.COPY["unmute"] and after["stored"] == "1", after
    assert back and back["label"] == mute.COPY["mute"] and back["stored"] == "0", back
    assert posts == [{"on": True}, {"on": False}]


def test_muted_the_status_says_writing_where_pointe_would_have_spoken():
    async def run():
        stub, browser, page = await _page(_writing_status())
        try:
            await page.eval("localStorage.setItem('pointe.reading', '1'); true")
            await _on_a_call(page)
            got = await _until(page, f"(() => {{ const g = {BTN}; return g.state === 'Writing…' && g; }})()")
            await _shot(page, "page-writing")
            last = await page.eval("[...document.querySelectorAll('#talk li.bot')].pop().textContent")
            stub.status["reading"]["writing"] = False
            quiet = await _until(page, "document.getElementById('state').textContent === 'Listening' && 'Listening'")
            return got, last, quiet, list(stub.calls)
        finally:
            await _close(stub, browser)
    got, last, quiet, calls = asyncio.run(run())
    assert got and got["pressed"] == "true" and got["label"] == mute.COPY["unmute"] and got["beside"], got
    assert "production waits for your go" in last  # the reply is on the page as text
    assert quiet == "Listening" and calls == ["reading=1"]


def test_there_is_no_read_button_no_reading_card_and_no_unread_marks():
    async def run():
        stub, browser, page = await _page(_writing_status())
        try:
            await _on_a_call(page)
            await _until(page, "document.querySelectorAll('#talk li.bot').length")
            return await page.eval("""({ids: ['readingbtn', 'readingcard', 'reading-label', 'reading-off', 'reading-markread']
              .filter(id => document.getElementById(id)), marks: document.querySelectorAll('.readmark, li.unread, li.read').length,
              text: document.body.innerText})""")
        finally:
            await _close(stub, browser)
    got = asyncio.run(run())
    assert got["ids"] == [] and got["marks"] == 0
    for gone in ("Reading mode", "Mark all read", "Talk again", "Unread"):
        assert gone not in got["text"], gone


def test_with_no_call_the_browser_keeps_its_choice_and_shows_it():
    async def run():
        stub, browser, page = await _page(fixture(sessions=1))
        try:
            await page.eval("document.getElementById('mutebtn').click()")
            return await _until(page, f"(() => {{ const g = {BTN}; return g.pressed === 'true' && g; }})()")
        finally:
            await _close(stub, browser)
    got = asyncio.run(run())
    assert got and got["stored"] == "1" and got["label"] == mute.COPY["unmute"] and got["shown"]


def test_a_toggle_that_does_not_reach_the_mac_says_so():
    async def run():
        stub, browser, page = await _page(fixture(sessions=1, connected=True))
        try:
            await page.eval("const real = window.fetch; window.fetch = (u, o) => String(u).includes('/voice/reading') ? "
                            "Promise.reject(new TypeError('Failed to fetch')) : real(u, o); true")
            await page.eval("document.getElementById('mutebtn').click()")
            return await _until(page, "document.getElementById('problem').textContent")
        finally:
            await _close(stub, browser)
    assert asyncio.run(run()) == mute.COPY["failed"]


def test_drive_mode_holding_it_is_said_on_the_button():
    async def run():
        s = fixture(sessions=1, connected=True)
        s["reading"] = {"on": True, "held": "drive", "read_through": -1, "writing": False}
        stub, browser, page = await _page(s)
        try:
            return await _until(page, f"(() => {{ const g = {BTN}; return g.pressed === 'true' && g; }})()")
        finally:
            await _close(stub, browser)
    got = asyncio.run(run())
    assert got and got["title"] == mute.COPY["held"], got


DIAL = """(async () => {
  await startCall();
  for (let i = 0; i < 50 && call.state === 'connecting'; i++) await new Promise(r => setTimeout(r, 100));
  return call.state;
})()"""


def test_the_call_is_dialled_with_the_choice_and_a_change_by_voice_is_kept():
    async def run():
        stub, browser, page = await _page(fixture(sessions=1))
        try:
            await page.eval("localStorage.setItem('pointe.reading', '1'); true")
            state = await page.eval(DIAL)
            await _until(page, "true")
            await stub.call_ws.send_str(json.dumps({"type": "reading", "on": False}))
            stored = await _until(page, "localStorage.getItem('pointe.reading') === '0' && '0'")
            await page.eval("endCall && endCall(); true")
            return state, list(stub.calls), stored
        finally:
            await _close(stub, browser)
    state, calls, stored = asyncio.run(run())
    assert state == "live" and calls == ["reading=1"] and stored == "0"


def test_muting_mid_speech_stops_what_the_speakers_still_hold():
    async def run():
        stub, browser, page = await _page(_speaking_status())
        try:
            await _on_a_call(page)
            await page.eval("window.flushed = []; const port = call.player.port, real = port.postMessage.bind(port); "
                            "port.postMessage = m => { window.flushed.push(m); real(m); }; true")
            await page.eval("document.getElementById('mutebtn').click()")
            flushed = await _until(page, "window.flushed.length && window.flushed")
            await page.eval("document.getElementById('mutebtn').click()")  # unmuting flushes nothing
            await asyncio.sleep(0.4)
            return flushed, await page.eval("window.flushed")
        finally:
            await _close(stub, browser)
    flushed, after = asyncio.run(run())
    assert flushed == ["flush"] and after == ["flush"]


# ---------- session mode: the held news ----------

def _held_status():
    s = fixture(sessions=3, connected=True, approval=True)
    s["mode"] = "session"
    s["held"] = {"count": 2, "line": scope.count_line(2), "approvals": 1,
                 "items": [{"session": "s1-api", "kind": "approval", "line": "needs your approval", "at": time.time() - 60},
                           {"session": "s2-mobile", "kind": "report", "line": "all 12 tests pass", "at": time.time() - 20}]}
    return s


def test_the_held_news_is_a_quiet_count_that_lists_its_items_and_tell_me_asks_for_them():
    async def run():
        stub, browser, page = await _page(_held_status())
        try:
            chip = await _until(page, "document.getElementById('heldnews')?.innerText")
            closed = await page.eval("document.getElementById('held-items')?.hidden")
            await page.eval("document.getElementById('held-chip').click()")
            items = await _until(page, "!document.getElementById('held-items').hidden && document.getElementById('held-items').innerText")
            await _shot(page, "page-held")
            await page.eval("document.getElementById('held-tell').click()")
            gone = await _until(page, "!document.getElementById('heldnews').innerText.trim()")
            return chip, closed, items, gone, _posts(stub, "/voice/held")
        finally:
            await _close(stub, browser)
    chip, closed, items, gone, posts = asyncio.run(run())
    assert scope.count_line(2) in chip and closed is True
    assert "s1-api · needs your approval" in items and "s2-mobile · all 12 tests pass" in items and scope.TELL in items
    assert posts == [{"action": "tell"}] and gone


def test_nothing_held_shows_nothing():
    async def run():
        stub, browser, page = await _page(fixture(sessions=2, connected=True))
        try:
            await asyncio.sleep(0.5)
            return await page.eval("document.getElementById('heldnews').innerText.trim()")
        finally:
            await _close(stub, browser)
    assert asyncio.run(run()) == ""


def test_another_sessions_request_stays_on_its_card_in_session_mode_and_can_be_approved():
    async def run():
        stub, browser, page = await _page(_held_status())
        try:
            shown = await _until(page, "document.querySelector('#attention .ask')?.innerText")
            ready = await _until(page, "!document.querySelector('#attention .ask .answer button.allow').disabled", 4)
            await page.eval("document.querySelector('#attention .ask .answer button.allow').click()")
            await asyncio.sleep(0.6)
            return shown, ready, _posts(stub, "/voice/approve")
        finally:
            await _close(stub, browser)
    shown, ready, posts = asyncio.run(run())
    assert "s1-api" in shown and "rm -rf build" in shown and ready
    assert posts and posts[0].get("request_id") == "perm-1"


# ---------- the box: new lines ----------

async def _key(page, modifiers: int = 0):
    """Enter, as a keyboard sends it (1 Alt/Option, 8 Shift)."""
    for kind in ("keyDown", "keyUp"):
        await page.cdp("Input.dispatchKeyEvent", {"type": kind, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13,
                                                  "nativeVirtualKeyCode": 13, "modifiers": modifiers,
                                                  **({"text": "\r"} if kind == "keyDown" else {})})


def test_shift_or_option_enter_starts_a_new_line_and_enter_sends_it_whole():
    async def run():
        stub, browser, page = await _page(fixture(sessions=1, connected=True))
        try:
            await _until(page, "!document.getElementById('typed').disabled")
            await page.eval("document.getElementById('typed').focus(); true")
            one = await page.eval("document.getElementById('typed').offsetHeight")
            await page.cdp("Input.insertText", {"text": "Rename the column to total_cents."})
            await _key(page, 8)
            await page.cdp("Input.insertText", {"text": "Then run the migration"})
            await _key(page, 1)
            await page.cdp("Input.insertText", {"text": "and the tests."})
            draft = await page.eval("({value: document.getElementById('typed').value, h: document.getElementById('typed').offsetHeight,"
                                    " tag: document.getElementById('typed').tagName})")
            await _shot(page, "page-composer")
            sent_before = _posts(stub, "/voice/say")
            await _key(page)
            await asyncio.sleep(0.6)
            after = await page.eval("({value: document.getElementById('typed').value, h: document.getElementById('typed').offsetHeight})")
            return one, draft, sent_before, _posts(stub, "/voice/say"), after
        finally:
            await _close(stub, browser)
    one, draft, before, sent, after = asyncio.run(run())
    typed = "Rename the column to total_cents.\nThen run the migration\nand the tests."
    assert draft["tag"] == "TEXTAREA" and draft["value"] == typed and draft["h"] > one  # it grew with the lines
    assert before == [] and sent == [{"text": typed}]
    assert after["value"] == "" and after["h"] == one


def test_enter_during_ime_composition_does_not_send():
    async def run():
        stub, browser, page = await _page(fixture(sessions=1, connected=True))
        try:
            await _until(page, "!document.getElementById('typed').disabled")
            await page.eval("""(() => { const t = document.getElementById('typed'); t.focus(); t.value = 'にほんご';
              t.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', isComposing: true, bubbles: true, cancelable: true}));
              t.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', keyCode: 229, bubbles: true, cancelable: true}));
              return true; })()""")
            await asyncio.sleep(0.5)
            return _posts(stub, "/voice/say"), await page.eval("document.getElementById('typed').value")
        finally:
            await _close(stub, browser)
    sent, value = asyncio.run(run())
    assert sent == [] and value == "にほんご"


def test_a_multi_line_message_shows_its_line_breaks():
    async def run():
        s = fixture(sessions=1, connected=True)
        s["talk"] = [{"id": 1, "who": "user", "text": "first line\nsecond line", "typed": True, "corrected": False}]
        stub, browser, page = await _page(s)
        try:
            return await _until(page, "(() => { const li = document.querySelector('#talk li.you .meant');"
                                      " return li && {text: li.innerText, ws: getComputedStyle(li).whiteSpace}; })()")
        finally:
            await _close(stub, browser)
    got = asyncio.run(run())
    assert got["text"] == "first line\nsecond line" and got["ws"] in ("pre-wrap", "pre-line", "break-spaces")


DOCK = """(() => ({read: !!document.getElementById('readingbtn'), more: !document.getElementById('morebtn').hidden,
  right: [...document.querySelector('.dock-side.right').children].map(b => b.id)}))()"""


def test_the_dock_has_no_read_button_and_more_shows_only_on_a_narrow_screen():
    from test_ui_layout import LIVE, _run
    status = fixture(sessions=3, talk=2, connected=True)
    status["whisper"]["on"] = True
    status["challenge"] = {"id": "c1", "on": True, "plan": "Ship it.", "items": [], "verdict": None}
    wide, squeezed, narrow = _run([(1440, LIVE, DOCK), (1024, LIVE, DOCK), (600, LIVE, DOCK)], status)
    assert wide == {"read": False, "more": False, "right": ["chlbtn", "whisperbtn", "typebtn", "sessbtn"]}
    assert squeezed == wide  # nothing leaves the dock for want of room now
    assert narrow["more"] and not narrow["read"]
