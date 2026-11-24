"""The conversation's text on the page (ui.html) selects and copies as on any page, in a headless Chrome against the stub
Mac (tests/page_rig.py). Skipped where that Chrome is not installed (CI on Linux).

A drag selects words, in Pointe's lines and in your own; a drag in your own line is not the click that opens the fix
box; what only a screen reader hears ("Pointe: ") is not copied.

uv run --locked pytest -q tests/test_copy_page.py
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_rig import CHROME  # noqa: E402
from test_mute_page import _close, _page, _talk_status, _until  # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")

BOX = """(sel => { const r = document.querySelector(sel).getBoundingClientRect();
  return {left: r.left, right: r.right, top: r.top, bottom: r.bottom}; })"""


async def _drag(page, selector: str) -> None:
    """A real mouse drag across the line's text, from its start to near its end."""
    box = await page.eval(f"{BOX}({selector!r})")
    y = (box["top"] + box["bottom"]) / 2
    start, end = box["left"] + 18, box["right"] - 18
    await page.cdp("Input.dispatchMouseEvent", {"type": "mousePressed", "x": start, "y": y, "button": "left", "clickCount": 1})
    for step in range(1, 9):
        await page.cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": start + (end - start) * step / 8, "y": y, "button": "left", "buttons": 1})
    await page.cdp("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": end, "y": y, "button": "left", "clickCount": 1})
    await asyncio.sleep(0.2)


def test_a_drag_selects_the_words_of_pointes_line_and_they_copy():
    async def run():
        stub, browser, page = await _page(_talk_status())
        try:
            await _until(page, "document.querySelectorAll('#talk li.bot').length === 2")
            style = await page.eval("getComputedStyle(document.querySelector('#talk li.bot')).userSelect")
            await _drag(page, "#talk li.bot")
            picked = await page.eval("String(getSelection())")
            copied = await page.eval("""(() => { let got = null;
              document.addEventListener('copy', e => { got = String(getSelection()); }, {once: true});
              document.execCommand('copy'); return got; })()""")
            await page.eval("getSelection().selectAllChildren(document.querySelector('#talk li.bot')); true")
            whole = await page.eval("String(getSelection())")
            return style, picked, copied, whole
        finally:
            await _close(stub, browser)
    style, picked, copied, whole = asyncio.run(run())
    assert style != "none", "the conversation's text cannot be selected"
    assert len(picked) > 12 and picked in "Billing finished: all 12 tests pass.", repr(picked)
    assert copied == picked, "Copy did not get the selected words"
    assert whole == "Billing finished: all 12 tests pass.", f"a copy of the whole line carries what only a screen reader hears: {whole!r}"


def test_a_drag_in_your_own_line_selects_it_and_a_click_still_opens_the_fix():
    async def run():
        stub, browser, page = await _page(_talk_status())
        try:
            await _until(page, "document.querySelectorAll('#talk li.you').length === 2")
            await _drag(page, "#talk li.you")
            picked = await page.eval("String(getSelection())")
            fixing = await page.eval("!!document.querySelector('#talk textarea.fix')")
            await page.eval("getSelection().removeAllRanges(); true")
            box = await page.eval(f"{BOX}('#talk li.you')")
            x, y = (box["left"] + box["right"]) / 2, (box["top"] + box["bottom"]) / 2
            for kind in ("mousePressed", "mouseReleased"):
                await page.cdp("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1})
            clicked = await _until(page, "!!document.querySelector('#talk textarea.fix')", 2)
            return picked, fixing, clicked
        finally:
            await _close(stub, browser)
    picked, fixing, clicked = asyncio.run(run())
    assert len(picked) > 8 and picked in "What did billing say?", repr(picked)
    assert not fixing, "selecting words in your own line opened the fix box and lost the selection"
    assert clicked, "a plain click no longer opens the fix box"
