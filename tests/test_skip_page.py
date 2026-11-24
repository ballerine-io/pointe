"""The skip button on the page (ui.html, ui_skip.html), in a headless Chrome against the stub Mac (tests/page_rig.py).
Skipped where that Chrome is not installed (CI on Linux).

One button beside the status line, after the mute button, only while Pointe speaks. The two never overlap. A tap asks
the daemon (POST /voice/skip) and drops what this browser still holds to play.

uv run --locked pytest -q tests/test_skip_page.py
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import skip  # noqa: E402
from page_rig import CHROME  # noqa: E402
from test_mute_page import DIAL, _close, _page, _posts, _shot, _speaking_status, _until  # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")

BTNS = """(() => { const k = document.getElementById('skipbtn'), m = document.getElementById('mutebtn'),
  st = document.getElementById('state'), a = k.getBoundingClientRect(), b = m.getBoundingClientRect(); return {
  state: st.textContent, shown: k.getClientRects().length > 0, label: k.getAttribute('aria-label'), title: k.title,
  afterMute: k.previousElementSibling === m && k.parentElement === st.parentElement,
  gap: Math.round(a.left - b.right), sameRow: Math.abs((a.top + a.bottom) / 2 - (b.top + b.bottom) / 2) < 3,
  size: [Math.round(a.width), Math.round(a.height)], muteShown: m.getClientRects().length > 0}; })()"""


def test_the_words_are_the_daemons():
    page = (Path(__file__).resolve().parents[1] / "pointe" / "ui_skip.html").read_text()
    for key, words in skip.COPY.items():
        assert f"{key}: '{words}'" in page, key


def test_skip_shows_only_while_pointe_speaks_and_sits_after_the_mute_button():
    async def run():
        stub, browser, page = await _page(_speaking_status())
        try:
            assert await page.eval(DIAL) == "live"
            got = await _until(page, f"(() => {{ const g = {BTNS}; return g.shown && g; }})()")
            await _shot(page, "page-skip")
            stub.status["speaking"] = None
            quiet = await _until(page, f"(() => {{ const g = {BTNS}; return !g.shown && g; }})()")
            return got, quiet
        finally:
            await _close(stub, browser)
    got, quiet = asyncio.run(run())
    assert got and got["state"] == "Speaking…" and got["label"] == got["title"] == skip.COPY["skip"], got
    assert got["afterMute"] and got["sameRow"] and got["muteShown"], got
    assert 4 <= got["gap"] <= 16, f"the two buttons touch or drift apart: {got}"
    assert got["size"] == [32, 32], got
    assert quiet and quiet["muteShown"], "with nothing being said there is nothing to skip; the mute button stays"


def test_a_tap_asks_the_daemon_and_stops_what_this_browser_still_plays():
    async def run():
        stub, browser, page = await _page(_speaking_status())
        try:
            assert await page.eval(DIAL) == "live"
            await _until(page, f"(() => {{ const g = {BTNS}; return g.shown && g; }})()")
            await page.eval("window.flushed = 0; const port = call.player.port, real = port.postMessage.bind(port);"
                            "port.postMessage = m => { if (m === 'flush') window.flushed++; real(m); }; true")
            await page.eval("document.getElementById('skipbtn').click()")
            gone = await _until(page, f"(() => {{ const g = {BTNS}; return !g.shown && g.state !== 'Speaking…' && g; }})()")
            return gone, _posts(stub, "/voice/skip"), await page.eval("window.flushed")
        finally:
            await _close(stub, browser)
    gone, posts, flushed = asyncio.run(run())
    assert posts == [{}], posts
    assert flushed == 1, "the audio this browser already held kept playing"
    assert gone, "the button stayed, or the line still says Speaking…"


def test_a_narrow_screen_gives_both_buttons_a_fingers_target_side_by_side():
    async def run():
        stub, browser, page = await _page(_speaking_status())
        try:
            await page.cdp("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 2, "mobile": True})
            assert await page.eval(DIAL) == "live"
            got = await _until(page, f"(() => {{ const g = {BTNS}; return g.shown && g; }})()")
            fits = await page.eval("document.getElementById('skipbtn').getBoundingClientRect().right <= innerWidth")
            await _shot(page, "page-skip-phone")
            return got, fits
        finally:
            await _close(stub, browser)
    got, fits = asyncio.run(run())
    assert got["size"] == [44, 44] and got["gap"] >= 4 and got["sameRow"] and fits, got
