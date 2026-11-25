"""The Thinking state, the working state and their two settings on the page (ui.html, ui_thinking.html), in a headless
Chrome against the stub Mac (tests/page_rig.py). Skipped where that Chrome is not installed (CI on Linux).

- From the end of the owner's turn to the reply the state line says "Thinking…", not "Listening"; while a session has
  their request it says "<session> is working…". Speaking… and Writing… come first when they hold.
- The call's own link says "thinking" the moment the turn is taken: the line changes within 150 ms, not at the next poll.
- The mute button stays beside the line; the skip button shows only while Pointe speaks.
- Reduce Motion stops the dot's animation.
- Settings has the waiting sound and the progress updates, loaded from the Mac and saved with the rest.

uv run --locked pytest -q tests/test_thinking_page.py
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
import progress  # noqa: E402
import thinking  # noqa: E402
from page_rig import CHROME, Browser, StubMac, fixture, free_port  # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")
SHOTS = Path(os.environ.get("POINTE_SHOTS", "/tmp/parity-shots"))

DIAL = """(async () => {
  await startCall();
  for (let i = 0; i < 50 && call.state === 'connecting'; i++) await new Promise(r => setTimeout(r, 100));
  return call.state;
})()"""

LINE = """(() => { const st = document.getElementById('state'), mute = document.getElementById('mutebtn'),
  skip = document.getElementById('skipbtn'), dot = document.querySelector('.top .dot'), cs = getComputedStyle(dot); return {
  state: st.textContent, kind: document.body.dataset.state, mute: mute.getClientRects().length > 0,
  beside: mute.previousElementSibling === st, skip: skip.getClientRects().length > 0,
  dot: cs.backgroundColor, anim: cs.animationName, loops: cs.animationIterationCount, said: document.getElementById('statesay').textContent}; })()"""


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
        await asyncio.sleep(0.1)
    return await page.eval(expression)


async def _shot(page, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    for look in ("light", "dark"):
        await page.cdp("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": look}]})
        await asyncio.sleep(0.3)
        data = (await page.cdp("Page.captureScreenshot", {"format": "png"}))["data"]
        (SHOTS / f"{name}-{look}.png").write_bytes(base64.b64decode(data))


def _status(phase=None, speaking=None, writing=False):
    s = fixture(sessions=2, connected=True)
    s["talk"] = [{"id": 1, "who": "user", "text": "What did billing say?", "typed": False, "corrected": False},
                 {"id": 2, "who": "assistant", "text": "Billing finished: all 12 tests pass.", "typed": False, "corrected": False},
                 {"id": 3, "who": "user", "text": "Ask it to run the migration on the staging copy.", "typed": False, "corrected": False}]
    s["phase"], s["speaking"] = phase, speaking
    s["reading"] = {"on": writing, "held": None, "read_through": -1, "writing": writing}
    return s


THINKING = {"name": "thinking", "session": None, "since": 0}
WORKING = {"name": "working", "session": "s1-api", "since": 0}


async def _line(status, shot: str | None = None, want: str | None = None, before=None):
    stub, browser, page = await _page(status)
    try:
        if before:
            await page.eval(before)
        assert await page.eval(DIAL) == "live"
        got = await _until(page, f"(() => {{ const g = {LINE}; return g.state === {json.dumps(want)} && g; }})()") if want \
            else await page.eval(LINE)
        if shot:
            await _shot(page, shot)
        return got or await page.eval(LINE)
    finally:
        await _close(stub, browser)


# ---------- the states ----------

def test_from_the_end_of_the_turn_the_line_says_thinking_not_listening():
    got = asyncio.run(_line(_status(THINKING), "page-thinking", thinking.COPY["thinking"]))
    assert got["state"] == "Thinking…" and got["kind"] == "thinking", got
    assert got["mute"] and got["beside"] and not got["skip"], got  # mute stays beside the line; nothing to skip yet
    assert got["anim"] == "think" and got["loops"] == "infinite", got


def test_while_a_session_has_the_request_the_line_names_it():
    got = asyncio.run(_line(_status(WORKING), "page-working", thinking.COPY["working"].format(session="s1-api")))
    assert got["state"] == "s1-api is working…" and got["kind"] == "working", got
    assert got["mute"] and not got["skip"], got


def test_listening_speaking_and_writing_are_as_before_and_come_first():
    listening = asyncio.run(_line(_status(), "page-listening", "Listening"))
    assert listening["state"] == "Listening" and listening["kind"] == "live"
    # A status caught between two events: Pointe already speaks, the phase is a moment old.
    speaking = asyncio.run(_line(_status(THINKING, speaking="bot"), "page-speaking", mute.COPY["speaking"]))
    assert speaking["state"] == "Speaking…" and speaking["skip"], speaking
    writing = asyncio.run(_line(_status(THINKING, writing=True), "page-writing", mute.COPY["writing"],
                                before="localStorage.setItem('pointe.reading', '1'); true"))
    assert writing["state"] == "Writing…" and not writing["skip"], writing
    assert len({listening["dot"], speaking["dot"]}) == 2  # your turn is green, Pointe's is orange


def test_thinking_is_pointes_turn_and_working_is_the_sessions():
    think = asyncio.run(_line(_status(THINKING), want="Thinking…"))
    speak = asyncio.run(_line(_status(speaking="bot"), want="Speaking…"))
    work = asyncio.run(_line(_status(WORKING), want="s1-api is working…"))
    listen = asyncio.run(_line(_status(), want="Listening"))
    assert think["dot"] == speak["dot"] and work["dot"] == listen["dot"] and think["dot"] != listen["dot"]
    assert think["anim"] != speak["anim"]  # told apart without colour


def test_hearing_you_does_not_hide_thinking():
    s = _status(THINKING)
    s["speaking"] = "user"  # the last words are under 1.2 s old when the turn is taken
    assert asyncio.run(_line(s, want="Thinking…"))["state"] == "Thinking…"


def test_push_to_talk_shows_thinking_and_keeps_its_own_label_over_working():
    s = _status(THINKING)
    s["ptt"]["mode"] = "ptt"
    assert asyncio.run(_line(s, want="Thinking…"))["state"] == "Thinking…"
    s = _status(WORKING)
    s["ptt"]["mode"] = "ptt"
    got = asyncio.run(_line(s))
    assert "working" not in got["state"], got  # the line says how to talk; the session's own row says it works


def test_reduce_motion_stops_the_dot():
    async def run():
        stub, browser, page = await _page(_status(THINKING))
        try:
            await page.cdp("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})
            assert await page.eval(DIAL) == "live"
            return await _until(page, f"(() => {{ const g = {LINE}; return g.state === 'Thinking…' && g; }})()")
        finally:
            await _close(stub, browser)
    got = asyncio.run(run())
    assert got["state"] == "Thinking…" and got["loops"] == "1", got  # the words carry the state


# ---------- the call's own link says it at once ----------

WATCH = """(() => { window.seen = null; window.told = null;
  call.ws.addEventListener('message', e => { if (typeof e.data === 'string' && e.data.includes('"phase"')) window.told = performance.now(); });
  new MutationObserver(() => { if (!window.seen && document.getElementById('state').textContent === 'Thinking…') window.seen = performance.now(); })
    .observe(document.getElementById('state'), {childList: true, characterData: true, subtree: true});
  return true; })()"""


def test_the_line_changes_within_150_ms_of_the_turn_being_taken():
    async def run():
        stub, browser, page = await _page(_status())
        try:
            assert await page.eval(DIAL) == "live"
            await _until(page, "document.getElementById('state').textContent === 'Listening'")
            await page.eval(WATCH)
            await stub.call_ws.send_str(json.dumps({"type": "phase", "name": "thinking", "session": None}))
            took = await _until(page, "window.seen && window.told && {ms: window.seen - window.told}", 3)
            stub.status["phase"] = THINKING  # the next poll agrees
            await asyncio.sleep(1.2)
            held = await page.eval("document.getElementById('state').textContent")
            said = await page.eval("document.getElementById('statesay').textContent")
            stub.status["phase"], stub.status["speaking"] = None, "bot"
            spoke = await _until(page, "document.getElementById('state').textContent === 'Speaking…' && 'Speaking…'")
            return took, held, spoke, said
        finally:
            await _close(stub, browser)
    took, held, spoke, said = asyncio.run(run())
    assert took and took["ms"] <= 150, took
    assert held == "Thinking…" and spoke == "Speaking…"
    assert said != "Thinking…"  # a screen reader is not told each turn: it would talk over the voice


def test_a_link_message_the_status_never_confirms_does_not_stick():
    async def run():
        stub, browser, page = await _page(_status())
        try:
            assert await page.eval(DIAL) == "live"
            await stub.call_ws.send_str(json.dumps({"type": "phase", "name": "thinking", "session": None}))
            shown = await _until(page, "document.getElementById('state').textContent === 'Thinking…' && 'Thinking…'", 2)
            back = await _until(page, "document.getElementById('state').textContent === 'Listening' && 'Listening'", 4)
            return shown, back
        finally:
            await _close(stub, browser)
    assert asyncio.run(run()) == ("Thinking…", "Listening")  # an "mm-hm": the status never said thinking


# ---------- drive mode's big line ----------

def test_drive_modes_line_says_thinking():
    async def run():
        stub, browser, page = await _page(_status())
        try:
            return await page.eval("""[driveLine({drive: {pending: []}, phase: {name: 'thinking'}, speaking: null, sessions: [], connected: true}),
              driveLine({drive: {pending: []}, phase: {name: 'thinking'}, speaking: 'bot', sessions: [], connected: true})]""")
        finally:
            await _close(stub, browser)
    assert asyncio.run(run()) == ["Thinking", "Speaking"]


# ---------- settings ----------

FIELDS = """(() => { const cue = document.getElementById('pref-cue'), posted = document.getElementById('pref-progress'); return {
  cue: cue.checked, posted: posted.checked, cueLabel: cue.closest('label').innerText.trim(), postedLabel: posted.closest('label').innerText.trim(),
  cueHint: document.getElementById('pref-cue-hint').innerText.trim(), postedHint: document.getElementById('pref-progress-hint').innerText.trim(),
  shown: cue.getClientRects().length > 0 && posted.getClientRects().length > 0}; })()"""


def test_settings_has_the_waiting_sound_on_and_the_progress_updates_off_and_saves_both():
    async def run():
        stub, browser, page = await _page(fixture(sessions=1, connected=True))
        try:
            await page.eval("(async () => { await openSettings(); settingsJump('g-turns'); return true; })()")
            before = await _until(page, f"(() => {{ const g = {FIELDS}; return g.shown && g; }})()")
            await page.eval("document.getElementById('pref-cue').scrollIntoView({block: 'center'}); true")
            await asyncio.sleep(0.3)
            await _shot(page, "page-settings")
            await page.eval("document.getElementById('pref-cue').click(); document.getElementById('pref-progress').click(); true")
            await page.eval("(async () => { await saveSettings(); return true; })()")
            await asyncio.sleep(0.5)
            return before, [body for path, body, _ in stub.posts if path == "/voice/prefs"]
        finally:
            await _close(stub, browser)
    before, posts = asyncio.run(run())
    assert before["cue"] is True and before["posted"] is False, before  # the daemon's defaults
    assert before["cueLabel"] == thinking.COPY["cue"] and before["cueHint"] == thinking.COPY["cue_hint"], before
    assert before["postedLabel"] == progress.COPY["setting"] and before["postedHint"] == progress.COPY["hint"], before
    assert posts and posts[-1]["thinking.cue"] is False and posts[-1]["progress.spoken"] is True, posts


def test_a_mac_from_before_the_settings_shows_the_defaults():
    async def run():
        stub, browser, page = await _page(fixture(sessions=1, connected=True))
        try:
            stub.old_prefs = True
            await page.eval("(async () => { await openSettings(); settingsJump('g-turns'); return true; })()")
            return await _until(page, f"(() => {{ const g = {FIELDS}; return g.shown && g; }})()")
        finally:
            await _close(stub, browser)
    got = asyncio.run(run())
    assert got["cue"] is True and got["posted"] is False
