"""The brain dump on the page (ui.html), rendered in a headless Chrome against the stub Mac (tests/page_rig.py): the panel
while dumping shows every thought and the live line; Done posts done and the review sheet opens with the prompt, the To:
picker (Orchestrator first, then the sessions; preselected where the user was when the dump started) and Send; Send takes
two clicks and posts the session or the orchestrator; a pinned session that is gone is said; Add more, Discard (two clicks)
and Close do what they say; the
dock button reads Brain dump, Done, Review; the Drive button is gone and the drive bar still shows while drive mode is on.
Skipped where that Chrome is not installed (CI on Linux).

uv run pytest -q tests/test_brain_dump_page.py
"""

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_rig import CHROME, Browser, StubMac, fixture, free_port  # noqa: E402

needs_chrome = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")
SHOTS = Path(os.environ.get("POINTE_SHOTS", "/tmp/brain-dump-shots/web"))
THOUGHTS = ["so the checkout keeps timing out for some customers",
            "I think it's the retry loop, it retries five times with no backoff",
            "we must not touch the tax service this sprint"]


ORCHESTRATOR = {"orchestrator": True, "session": None, "gone": None}


def dumping(thoughts=THOUGHTS, state="dumping", prompt=None, **more) -> dict:
    return {"id": "d1", "state": state, "since": time.time() - 60, "thoughts": [{"text": t, "at": time.time()} for t in thoughts],
            "dropped": 0, "prompt": prompt, "target": None, "problem": None, "resumed": False, "fallback": False,
            "send_to": ORCHESTRATOR, **more}


PROMPT = {"goal": "stop the checkout timing out for some customers", "context": ["the retry loop retries five times with no backoff"],
          "constraints": ["we must not touch the tax service this sprint"], "open_questions": [],
          "text": "Goal\nstop the checkout timing out for some customers\n\n"
                  "Context\n- the retry loop retries five times with no backoff\n\nConstraints\n- we must not touch the tax service this sprint"}


async def _page(status):
    stub = await StubMac(free_port()).start()
    stub.status = status
    browser = Browser()
    await browser.__aenter__()
    page = await browser.open(stub.url)
    await asyncio.sleep(1.2)
    return stub, browser, page


async def _close(stub, browser):
    await browser.__aexit__(None, None, None)
    await stub.stop()


async def _shot(page, name: str) -> None:
    import base64
    SHOTS.mkdir(parents=True, exist_ok=True)
    data = (await page.cdp("Page.captureScreenshot", {"format": "png"}))["data"]
    (SHOTS / f"{name}.png").write_bytes(base64.b64decode(data))


async def _until(page, expression: str, timeout: float = 5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = await page.eval(expression)
        if value:
            return value
        await asyncio.sleep(0.2)
    return await page.eval(expression)


def _posts(stub, path="/voice/dump"):
    return [body for p, body, _ in stub.posts if p == path]


@needs_chrome
def test_the_panel_shows_every_thought_the_live_line_and_the_buttons():
    async def run():
        status = fixture(sessions=2, connected=True)
        status["brain_dump"], status["monologue"], status["hearing"] = dumping(), {"since": 0, "said": " ".join(THOUGHTS)}, "and maybe the cache"
        stub, browser, page = await _page(status)
        try:
            shown = await _until(page, "!document.getElementById('dump').hidden")
            got = await page.eval("""({items: [...document.querySelectorAll('#dump-list li')].map(x => x.textContent),
                                      hearing: $('dump-hearing').textContent, title: $('state').textContent, label: $('listen-label').textContent,
                                      done: $('dump-done').textContent, lede: $('dump-lede').textContent, hint: $('dump-hint').textContent,
                                      compose: getComputedStyle($('compose')).display, sheet: $('dumpsheet').classList.contains('open')})""")
            await _shot(page, "web-1-dumping")
            assert shown and got["items"] == THOUGHTS, got
            assert got["hearing"] == "and maybe the cache" and got["label"] == "Done" and got["done"] == "Done"  # the title needs the page's own call: e2e
            assert got["lede"] == "Talk freely. Nothing is sent until you say so."
            assert got["hint"] == "When you're done: tap Done, or say “done” or “over to you”."
            assert not got["sheet"]
            # structuring: the button waits, the line says so
            stub.status["brain_dump"]["state"] = "structuring"
            waiting = await _until(page, "$('dump-done').textContent === 'Structuring your thoughts…' && $('dump-hearing').textContent === 'Structuring your thoughts…'")
            assert waiting
        finally:
            await _close(stub, browser)

    asyncio.run(run())


@needs_chrome
def test_done_opens_the_review_and_send_takes_two_clicks_and_names_the_session():
    async def run():
        status = fixture(sessions=3, connected=True)
        status["brain_dump"] = dumping()
        stub, browser, page = await _page(status)
        try:
            await _until(page, "!document.getElementById('dump').hidden")
            await page.eval("document.getElementById('dump-done').click()")
            opened = await _until(page, "document.getElementById('dumpsheet').classList.contains('open')", 6)
            assert opened and _posts(stub)[-1] == {"action": "done"}
            got = await page.eval("""(setTheme('light'), {text: $('dump-text').value, h: $('dumprev-h').textContent, send: $('dump-send').textContent,
                                      sendLabel: $('dump-send').getAttribute('aria-label'), to: $('dump-to').querySelector('span').textContent,
                                      primaries: [...document.querySelectorAll('#dumpsheet button')].filter(b => getComputedStyle(b).backgroundColor === 'rgb(10, 4, 0)').map(b => b.id),
                                      discardRed: getComputedStyle($('dump-discard2')).color, discardInRow: !!$('dump-discard2').closest('.row'),
                                      options: [...$('dump-session').options].map(o => o.value), picked: $('dump-session').value,
                                      label: $('listen-label').textContent, panel: $('dump').hidden, fallback: $('dump-fallback').hidden})""")
            await _shot(page, "web-2-review")
            assert got["text"].startswith("Goal\n" + THOUGHTS[0] + "\n\nContext\n- " + THOUGHTS[1]) and "Brain dump from" not in got["text"]
            assert got["h"].startswith("Your brain dump, structured") and got["label"] == "Review" and got["panel"] and got["fallback"]
            assert got["options"] == ["", "s0-shop", "s1-api", "s2-mobile"] and got["picked"] == ""  # orchestrator mode: the orchestrator
            assert got["to"] == "To:" and got["send"] == "Send" and got["sendLabel"] == "Send to Orchestrator"  # the picker says where, Send says what
            assert got["primaries"] == ["dump-send"] and got["discardRed"] == "rgb(200, 58, 55)" and not got["discardInRow"]  # one primary (ink); Discard apart, destructive
            # pick another session, then send: the first click asks, the second posts
            await page.eval("$('dump-session').value = 's1-api'; $('dump-session').dispatchEvent(new Event('change'))")
            await page.eval("document.getElementById('dump-send').click()")
            asked = await page.eval("({text: $('dump-send').textContent, armed: $('dump-send').classList.contains('sure')})")
            await _shot(page, "web-2b-armed")
            assert asked == {"text": "Tap again to send", "armed": True} and not [b for b in _posts(stub) if b.get("action") == "send"]
            await page.eval("document.getElementById('dump-send').click()")
            sent = await _until(page, "$('dump-ok').textContent.startsWith('Sent to s1-api')", 6)
            await _shot(page, "web-3-sent")
            assert sent and [b for b in _posts(stub) if b.get("action") == "send"] == [{"action": "send", "session": "s1-api"}]
            gone = await _until(page, "!document.getElementById('dumpsheet').classList.contains('open') && $('listen-label').textContent === 'Brain dump'", 6)
            assert gone
        finally:
            await _close(stub, browser)

    asyncio.run(run())


def _picker(page):
    return page.eval("""({options: [...$('dump-session').options].map(o => [o.value, o.textContent]), picked: $('dump-session').value,
                          sendLabel: $('dump-send').getAttribute('aria-label'), gone: $('dump-gone').hidden ? null : $('dump-gone').textContent,
                          lede: document.querySelector('#dumpsheet .lede').textContent})""")


@needs_chrome
def test_the_picker_lists_the_orchestrator_first_and_defaults_to_it_in_orchestrator_mode():
    async def run():
        status = fixture(sessions=2, connected=True)
        status["brain_dump"] = dumping(state="review", prompt=dict(PROMPT))
        stub, browser, page = await _page(status)
        try:
            assert await _until(page, "document.getElementById('dumpsheet').classList.contains('open')", 6)
            got = await _picker(page)
            await _shot(page, "web-4-orchestrator")
            assert got["options"] == [["", "Orchestrator"], ["s0-shop", "s0-shop"], ["s1-api", "s1-api"]], got
            assert got["picked"] == "" and got["sendLabel"] == "Send to Orchestrator" and got["gone"] is None
            assert got["lede"] == "In your words. Edit it, add more, or send it."
            await page.eval("document.getElementById('dump-send').click()")
            await page.eval("document.getElementById('dump-send').click()")
            sent = await _until(page, "$('dump-ok').textContent === 'Sent to Orchestrator.'", 6)
            assert sent and [b for b in _posts(stub) if b.get("action") == "send"] == [{"action": "send", "to": "orchestrator"}]
        finally:
            await _close(stub, browser)

    asyncio.run(run())


@needs_chrome
def test_the_picker_defaults_to_the_pinned_session_and_the_users_pick_survives_a_refresh():
    async def run():
        status = fixture(sessions=3, connected=True)
        status["brain_dump"] = dumping(state="review", prompt=dict(PROMPT), send_to={"orchestrator": False, "session": "s1-api", "gone": None})
        stub, browser, page = await _page(status)
        try:
            assert await _until(page, "document.getElementById('dumpsheet').classList.contains('open')", 6)
            got = await _picker(page)
            assert got["picked"] == "s1-api" and got["sendLabel"] == "Send to s1-api" and got["options"][0] == ["", "Orchestrator"], got
            await page.eval("$('dump-session').value = ''; $('dump-session').dispatchEvent(new Event('change'))")
            stub.status["sessions"] = stub.status["sessions"][:2]  # a refresh that redraws the picker keeps the user's choice
            assert await _until(page, "$('dump-session').options.length === 3", 4)
            assert (await _picker(page))["picked"] == ""
            await page.eval("document.getElementById('dump-send').click()")
            await page.eval("document.getElementById('dump-send').click()")
            assert await _until(page, "$('dump-ok').textContent === 'Sent to Orchestrator.'", 6)
            assert [b for b in _posts(stub) if b.get("action") == "send"] == [{"action": "send", "to": "orchestrator"}]
        finally:
            await _close(stub, browser)

    asyncio.run(run())


@needs_chrome
def test_a_pinned_session_that_is_gone_falls_back_to_the_orchestrator_and_the_sheet_says_so():
    async def run():
        status = fixture(sessions=2, connected=True)
        status["brain_dump"] = dumping(state="review", prompt=dict(PROMPT), send_to={"orchestrator": True, "session": None, "gone": "river-lantern"})
        stub, browser, page = await _page(status)
        try:
            assert await _until(page, "document.getElementById('dumpsheet').classList.contains('open')", 6)
            got = await _picker(page)
            await _shot(page, "web-5-gone")
            assert got["picked"] == "" and got["gone"] == "river-lantern is gone, so this goes to the orchestrator.", got
            await page.eval("$('dump-session').value = 's0-shop'; $('dump-session').dispatchEvent(new Event('change'))")
            assert (await _picker(page))["gone"] is None  # picked a session: the note no longer applies
        finally:
            await _close(stub, browser)

    asyncio.run(run())


@needs_chrome
def test_an_edit_goes_with_the_send_and_add_more_discard_and_close_do_what_they_say():
    async def run():
        status = fixture(sessions=2, connected=True)
        status["brain_dump"] = dumping(state="review", prompt=dict(PROMPT), fallback=True, resumed=True)
        stub, browser, page = await _page(status)
        try:
            opened = await _until(page, "document.getElementById('dumpsheet').classList.contains('open')", 6)
            assert opened and await page.eval("!$('dump-fallback').hidden")
            assert await page.eval("$('dump-text').value") == PROMPT["text"]
            # an edit: posted on change, and again before a send if it changed
            await page.eval("$('dump-text').value = 'Goal: fix the retry loop'; $('dump-text').dispatchEvent(new Event('change'))")
            await asyncio.sleep(0.6)
            assert {"action": "edit", "text": "Goal: fix the retry loop"} in _posts(stub)
            assert (await _until(page, "$('dump-text').value === 'Goal: fix the retry loop'", 4))
            # Add more: back to dumping, the sheet closes
            await page.eval("document.getElementById('dump-more').click()")
            more = await _until(page, "!document.getElementById('dump').hidden && !document.getElementById('dumpsheet').classList.contains('open')", 6)
            assert more and {"action": "more"} in _posts(stub)
            assert await page.eval("[...document.querySelectorAll('#dump-list li')].length") == 3
            # Done again: review; Close keeps it away; Review in the dock brings it back
            await page.eval("document.getElementById('dump-done').click()")
            await _until(page, "document.getElementById('dumpsheet').classList.contains('open')", 6)
            await page.eval("closeDump()")
            closed = await _until(page, "!document.getElementById('dumpsheet').classList.contains('open') && $('listen-label').textContent === 'Review'", 4)
            assert closed
            await page.eval("document.getElementById('listen').click()")
            assert await _until(page, "document.getElementById('dumpsheet').classList.contains('open')", 4)
            # Discard: the first click asks
            await page.eval("document.getElementById('dump-discard2').click()")
            assert await page.eval("$('dump-discard2').textContent") == "Discard the dump?" and {"action": "discard"} not in _posts(stub)
            await page.eval("document.getElementById('dump-discard2').click()")
            gone = await _until(page, "$('listen-label').textContent === 'Brain dump' && !document.getElementById('dumpsheet').classList.contains('open')", 6)
            assert gone and {"action": "discard"} in _posts(stub)
        finally:
            await _close(stub, browser)

    asyncio.run(run())


@needs_chrome
def test_the_dock_starts_a_dump_and_the_drive_button_is_gone_but_the_bar_still_shows():
    async def run():
        status = fixture(sessions=1, connected=True)
        stub, browser, page = await _page(status)
        try:
            got = await page.eval("({label: $('listen-label').textContent, drive: !!document.getElementById('drivebtn'), fn: typeof toggleDrive, "
                                  "more: DOCK_MORE.includes('drivebtn'), bar: $('drivebar').hidden})")
            assert got == {"label": "Brain dump", "drive": False, "fn": "undefined", "more": False, "bar": True}
            await page.eval("document.getElementById('listen').click()")
            at_once = await page.eval("!document.getElementById('dump').hidden && $('listen-label').textContent === 'Done'")  # before the Mac answers
            assert at_once and _posts(stub) == [{"action": "start"}]
            assert await _until(page, "status.brain_dump && status.brain_dump.state === 'dumping'", 4)
            stub.status["drive"] = {"on": True, "since": time.time(), "how": "voice", "pending": []}
            bar = await _until(page, "!$('drivebar').hidden && document.body.classList.contains('driving') && $('drive-line').textContent.length > 0", 4)
            assert bar
        finally:
            await _close(stub, browser)

    asyncio.run(run())
