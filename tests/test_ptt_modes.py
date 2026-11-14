"""Push to talk, held or tapped (docs/design/push-to-talk-modes.md). Offline.

Parity: the page and the iPhone app offer the same two styles with the same words, from the sources. The page's logic runs
in a headless Chrome against the stub Mac (tests/page_rig.py) with the microphone set to push to talk and the call marked
live (no socket: the control message is skipped, the model is the same); skipped where that Chrome is not installed.

uv run --locked pytest -q tests/test_ptt_modes.py
"""

import asyncio
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_rig import CHROME, ROOT, Browser, StubMac, fixture, free_port  # noqa: E402

PAGE = (ROOT / "ui.html").read_text()
SWIFT = (ROOT / "ios" / "Pointe" / "PushToTalk.swift").read_text()
needs_chrome = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")

STYLES = {"hold": "Hold to talk", "tap": "Tap to talk"}


# ---------- parity, from the sources ----------

def test_both_surfaces_offer_the_same_two_styles_with_the_same_words():
    select = re.search(r'<select id="pref-style">(.*?)</select>', PAGE, re.S).group(1)
    assert dict(re.findall(r'<option value="(\w+)">([^<]+)</option>', select)) == STYLES
    assert re.search(r"const PTT_STYLES = \{hold: 'Hold to talk', tap: 'Tap to talk'\};", PAGE)
    assert re.search(r"enum TalkStyle: String, CaseIterable \{\s*case hold, tap", SWIFT)
    assert 'self == .tap ? "Tap to talk" : "Hold to talk"' in SWIFT


def test_the_lines_are_the_same_on_both_surfaces():
    for line in ("Talking · tap to send", "Hold to talk · or choose Tap to talk in Settings", "Talk closed: no audio reached the Mac"):
        assert line in PAGE and line in SWIFT, line
    assert "'Sent'" in PAGE and 'sentLine = "Sent"' in SWIFT
    assert "Talk closed after 90 s: ${pttTap() ? 'tap' : 'press'} again" in PAGE
    assert 'Talk closed after 90 s: \\(style == .tap ? "tap" : "press") again' in SWIFT
    assert "PTT_SHORT_MS = 250" in PAGE and "shortPress: TimeInterval = 0.25" in SWIFT


def test_the_choice_is_kept_per_device_and_defaults_to_hold():
    assert "localStorage.getItem('pointe.pttStyle')" in PAGE and "localStorage.setItem('pointe.pttStyle', style)" in PAGE
    assert re.search(r"style: PTT_STYLES\[localStorage\.getItem\('pointe\.pttStyle'\)\] \? .* : 'hold'", PAGE)
    assert 'static let key = "talkStyle"' in SWIFT and "?? .hold" in SWIFT
    assert "Settings → Microphone → Talk button" in SWIFT


def test_the_daemon_is_not_involved():
    """One daemon setting, "microphone"; the style never reaches it."""
    sys.path.insert(0, str(ROOT))
    import prefs
    assert "microphone" in prefs.SCHEMA and not [k for k in prefs.SCHEMA if "style" in k or "tap" in k]
    assert "pttStyle" not in (ROOT / "daemon.py").read_text()


# ---------- the page's logic ----------

LIVE_PTT = "(() => { call.state = 'live'; status.ptt.mode = 'ptt'; pttFollow(status); showState(); return true; })()"
STATE = "document.getElementById('state').textContent"
RING = "(() => { const r = document.getElementById('mic').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()"


async def _page(style: str):
    status = fixture(connected=True)
    status["ptt"]["mode"] = "ptt"
    stub = await StubMac(free_port()).start()
    stub.status = status
    browser = Browser()
    await browser.__aenter__()
    page = await browser.open(stub.url)
    await page.eval(f"localStorage.setItem('pointe.pttStyle', '{style}'); true")
    await page.cdp("Page.reload")
    await page.wait_for_page()
    await page.cdp("Emulation.setFocusEmulationEnabled", {"enabled": True})
    await page.eval(LIVE_PTT)
    return stub, browser, page


async def _close(stub, browser):
    await browser.__aexit__(None, None, None)
    await stub.stop()


async def mouse(page, kind: str):
    x, y = await page.eval(RING)
    await page.cdp("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1})


async def key(page, kind: str, code: str = "Space", key_: str = " ", vk: int = 32):
    await page.cdp("Input.dispatchKeyEvent", {"type": kind, "key": key_, "code": code, "windowsVirtualKeyCode": vk})


@needs_chrome
def test_tap_to_talk_opens_on_one_press_and_sends_on_the_next_with_the_ring_and_the_key():
    async def run():
        stub, browser, page = await _page("tap")
        try:
            out = {"idle": await page.eval(STATE), "label": await page.eval("$('mic').getAttribute('aria-label')"),
                   "hint": await page.eval("$('keyhint').textContent"), "dock": await page.eval("$('micmode-ptt').textContent")}
            await mouse(page, "mousePressed")
            out["after_down"] = (await page.eval("pttOpen()"), await page.eval(STATE))
            await mouse(page, "mouseReleased")
            await asyncio.sleep(0.3)
            out["after_up"] = (await page.eval("pttOpen()"), await page.eval(STATE))  # still open: the lift is nothing
            await mouse(page, "mousePressed")
            out["second_down"] = (await page.eval("pttOpen()"), await page.eval(STATE))
            await mouse(page, "mouseReleased")
            await asyncio.sleep(0.8)
            out["settled"] = await page.eval(STATE)
            await key(page, "keyDown")
            out["key_down"] = await page.eval("pttOpen()")
            await key(page, "keyUp")
            await asyncio.sleep(0.1)
            out["key_up"] = await page.eval("pttOpen()")
            await key(page, "keyDown")
            await key(page, "keyUp")
            out["key_again"] = await page.eval("pttOpen()")
            out["muted"] = await page.eval("muted")
            return out
        finally:
            await _close(stub, browser)

    out = asyncio.run(run())
    assert out["idle"] == "Tap to talk" and out["label"] == "Tap to talk" and out["dock"] == "Tap to talk"
    assert out["hint"] == "Tap Space to talk, again to send · Caps Lock toggles"
    assert out["after_down"] == (True, "Talking · tap to send")
    assert out["after_up"] == (True, "Talking · tap to send")
    assert out["second_down"] == (False, "Sent")
    assert out["settled"] == "Tap to talk"
    assert out["key_down"] is True and out["key_up"] is True and out["key_again"] is False
    assert out["muted"] is False


@needs_chrome
def test_hold_to_talk_opens_at_the_press_and_a_tap_points_at_tap_to_talk():
    async def run():
        stub, browser, page = await _page("hold")
        try:
            out = {"idle": await page.eval(STATE), "hint": await page.eval("$('keyhint').textContent")}
            await mouse(page, "mousePressed")
            out["down"] = (await page.eval("pttOpen()"), await page.eval(STATE))
            await asyncio.sleep(0.4)
            await mouse(page, "mouseReleased")
            out["up"] = (await page.eval("pttOpen()"), await page.eval(STATE))
            await asyncio.sleep(0.8)
            out["settled"] = await page.eval(STATE)
            await mouse(page, "mousePressed")
            await mouse(page, "mouseReleased")
            out["tap"] = (await page.eval("pttOpen()"), await page.eval(STATE))
            await asyncio.sleep(2.2)
            out["tap_settled"] = await page.eval(STATE)
            await key(page, "keyDown")
            out["key_down"] = await page.eval("pttOpen()")
            await key(page, "keyUp")
            out["key_up"] = await page.eval("pttOpen()")
            return out
        finally:
            await _close(stub, browser)

    out = asyncio.run(run())
    assert out["idle"] == "Hold to talk" and out["hint"] == "Hold Space to talk · Caps Lock toggles"
    assert out["down"] == (True, "Talking")
    assert out["up"] == (False, "Sent")
    assert out["settled"] == "Hold to talk"
    assert out["tap"] == (False, "Hold to talk · or choose Tap to talk in Settings")
    assert out["tap_settled"] == "Hold to talk"
    assert out["key_down"] is True and out["key_up"] is False


@needs_chrome
def test_settings_shows_the_choice_and_saves_it_for_this_browser():
    async def run():
        stub, browser, page = await _page("hold")
        try:
            await page.eval("openSettings()")
            shown = await page.eval("$('pref-style').value")
            await page.eval("$('pref-style').value = 'tap'; saveSettings()")
            await asyncio.sleep(0.8)
            saved = (await page.eval("ptt.style"), await page.eval("localStorage.getItem('pointe.pttStyle')"), await page.eval(STATE))
            posted = [b for p, b, _ in stub.posts if p == "/voice/prefs"]
            return shown, saved, posted
        finally:
            await _close(stub, browser)

    shown, saved, posted = asyncio.run(run())
    assert shown == "hold"
    assert saved == ("tap", "tap", "Tap to talk")
    assert posted and all("style" not in k and "tap" not in str(v) for b in posted for k, v in b.items())  # the daemon is not told
