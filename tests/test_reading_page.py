"""Reading mode, the held-news badge and the multi-line composer on the page (ui.html, ui_reading.html), in a headless
Chrome against the stub Mac (tests/page_rig.py). Skipped where that Chrome is not installed (CI on Linux).

- Read in the dock: the browser keeps the choice, the call is dialled with it, the daemon is told, and the card shows;
  a change said by voice comes back on the call's socket and is kept.
- In reading mode each of Pointe's lines is marked Unread or Read; a click marks it read.
- Session mode: other sessions' news is a quiet count; it lists the items and Tell me asks for them. Another session's
  request stays on its card and can be approved.
- The box: Enter sends, Shift+Enter and Option+Enter start a new line, IME composition never sends, and the line breaks
  reach /voice/say.

uv run --locked pytest -q tests/test_reading_page.py
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
import reading  # noqa: E402
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


# ---------- reading mode ----------

CARD = "document.getElementById('readingcard').innerText"


def test_the_read_button_keeps_the_choice_tells_the_daemon_and_shows_the_card():
    async def run():
        stub, browser, page = await _page(fixture(sessions=2, connected=True))
        try:
            label0 = await page.eval("document.getElementById('reading-label').textContent")
            await page.eval("document.getElementById('readingbtn').click()")
            card = await _until(page, CARD)
            got = {"label0": label0, "card": card, "stored": await page.eval("localStorage.getItem('pointe.reading')"),
                   "label": await page.eval("document.getElementById('reading-label').textContent"),
                   "pressed": await page.eval("document.getElementById('readingbtn').getAttribute('aria-pressed')")}
            await page.eval("document.getElementById('reading-off').click()")
            await asyncio.sleep(0.6)
            got["after"] = await page.eval(CARD)
            got["storedAfter"] = await page.eval("localStorage.getItem('pointe.reading')")
            return got, _posts(stub, "/voice/reading")
        finally:
            await _close(stub, browser)
    got, posts = asyncio.run(run())
    assert got["label0"] == reading.COPY["button"] and got["label"] == reading.COPY["buttonOn"] and got["pressed"] == "true"
    assert reading.COPY["title"] in got["card"] and reading.COPY["body"] in got["card"]
    assert reading.COPY["back"] in got["card"] and reading.COPY["markRead"] in got["card"]
    assert got["stored"] == "1" and got["storedAfter"] == "0" and not got["after"].strip()
    assert posts == [{"on": True}, {"on": False}]


def test_with_no_call_the_browser_keeps_its_choice_and_shows_it():
    async def run():
        stub, browser, page = await _page(fixture(sessions=1))
        try:
            await page.eval("document.getElementById('readingbtn').click()")
            return await _until(page, CARD), await page.eval("document.getElementById('reading-label').textContent")
        finally:
            await _close(stub, browser)
    card, label = asyncio.run(run())
    assert reading.COPY["title"] in card and label == reading.COPY["buttonOn"]


def test_a_toggle_that_does_not_reach_the_mac_says_so():
    async def run():
        stub, browser, page = await _page(fixture(sessions=1, connected=True))
        try:
            await page.eval("const real = window.fetch; window.fetch = (u, o) => String(u).includes('/voice/reading') ? "
                            "Promise.reject(new TypeError('Failed to fetch')) : real(u, o); true")
            await page.eval("document.getElementById('readingbtn').click()")
            return await _until(page, "document.getElementById('problem').textContent")
        finally:
            await _close(stub, browser)
    assert asyncio.run(run()) == reading.COPY["failed"]


def test_drive_mode_holding_it_is_said_on_the_card():
    async def run():
        s = fixture(sessions=1, connected=True)
        s["reading"] = {"on": True, "held": "drive", "read_through": -1}
        stub, browser, page = await _page(s)
        try:
            return await _until(page, CARD)
        finally:
            await _close(stub, browser)
    assert reading.COPY["held"] in asyncio.run(run())


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


MARKS = """[...document.querySelectorAll('#talk li.bot')].map(li => ({
  mark: li.querySelector('.readmark')?.textContent || null, unread: li.classList.contains('unread')}))"""


def test_each_reply_is_marked_unread_or_read_and_a_click_reads_it():
    async def run():
        stub, browser, page = await _page(_talk_status())
        try:
            marks = await _until(page, MARKS)
            await _shot(page, "page-reading")
            await page.eval("document.querySelector('#talk li.bot.unread').click()")
            after = await _until(page, f"(() => {{ const m = {MARKS}; return m.every(x => !x.unread) && m; }})()")
            stub.status["reading"]["on"] = False
            off = await _until(page, f"(() => {{ const m = {MARKS}; return m.every(x => !x.mark) && m; }})()")
            return marks, after, off, _posts(stub, "/voice/read")
        finally:
            await _close(stub, browser)
    marks, after, off, posts = asyncio.run(run())
    assert marks == [{"mark": reading.COPY["read"], "unread": False}, {"mark": reading.COPY["unread"], "unread": True}]
    assert posts == [{"through": 4}] and after and off


def test_mark_all_read_on_the_card():
    async def run():
        stub, browser, page = await _page(_talk_status())
        try:
            await _until(page, CARD)
            await page.eval("document.getElementById('reading-markread').click()")
            await asyncio.sleep(0.5)
            return _posts(stub, "/voice/read")
        finally:
            await _close(stub, browser)
    assert asyncio.run(run()) == [{}]


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


WHERE = """(() => ({parent: document.getElementById('readingbtn').parentElement.id || document.getElementById('readingbtn').parentElement.className,
  before: document.getElementById('readingbtn').previousElementSibling?.id, more: !document.getElementById('morebtn').hidden}))()"""


def test_read_sits_beside_whisper_and_goes_to_more_only_when_the_dock_has_no_room():
    from test_ui_layout import LIVE, _run
    status = fixture(sessions=3, talk=2, connected=True)
    status["whisper"]["on"] = True
    status["challenge"] = {"id": "c1", "on": True, "plan": "Ship it.", "items": [], "verdict": None}
    wide, squeezed, back = _run([(1440, LIVE, WHERE), (1024, LIVE, WHERE), (1440, "", WHERE)], status)
    assert wide == {"parent": "dock-side right", "before": "whisperbtn", "more": False}
    assert squeezed["parent"] == "more-list" and squeezed["more"]  # "End challenge" and "Whispering" take its room
    assert back == wide
