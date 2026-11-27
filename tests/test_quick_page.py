"""Quick settings on the page (ui_quick.html) and the words the page, both apps and the daemon share. The page tests run
headless Chrome against the stub Mac (tests/page_rig.py); they skip where that Chrome is not installed.

uv run --locked pytest -q tests/test_quick_page.py --runslow
"""

import asyncio
import base64
import os
import re
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import quick  # noqa: E402
from page_rig import CHROME, Browser, StubMac, fixture, free_port  # noqa: E402

chrome = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")
SHOTS = os.environ.get("POINTE_QUICK_SHOTS")
PART = (ROOT / "pointe" / "ui_quick.html").read_text()


def _page_copy() -> dict:
    block = PART[PART.index("const QUICK_COPY = {"):]
    block = block[:block.index("};")]
    found = re.findall(r"""(\w+): (?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")""", block)
    return {k: (single or double).replace("\\'", "'") for k, single, double in found}


def _app_copy() -> dict:
    swift = (ROOT / "apps" / "PointeKit" / "Sources" / "PointeUI" / "QuickSettings.swift").read_text()
    block = swift[swift.index("enum QuickCopy"):]
    block = block[:block.index("\n}\n")]
    return dict(re.findall(r'static let (\w+) = "((?:[^"\\]|\\.)*)"', block))


def test_the_page_and_both_apps_say_the_same_words_as_the_daemon():
    assert _page_copy() == quick.COPY
    assert _app_copy() == quick.COPY


async def _run(script, status=None, width=1280, shot=None):
    stub = await StubMac(free_port()).start()
    stub.status = fixture(sessions=2, talk=2, connected=True)
    stub.status.update(status or {})
    try:
        async with Browser() as browser:
            page = await browser.open(stub.url)
            await page.cdp("Emulation.setDeviceMetricsOverride", {"width": width, "height": 860, "deviceScaleFactor": 1, "mobile": False})
            await page.cdp("Page.navigate", {"url": stub.url})
            await asyncio.sleep(0.6)
            await page.wait_for_page()
            got = await script(page, stub)
            if shot and SHOTS:
                for look in ("light", "dark"):
                    await page.cdp("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": look}]})
                    await asyncio.sleep(0.3)
                    data = (await page.cdp("Page.captureScreenshot", {"format": "png"}))["data"]
                    Path(SHOTS, f"{shot}-{look}.png").write_bytes(base64.b64decode(data))
            return got
    finally:
        await stub.stop()


ROW = """(() => { const c = id => document.getElementById(id);
  return {where: c('quickrow').parentElement.className || c('quickrow').parentElement.id,
          length: c('qs-length').textContent, speed: c('qs-speed').hidden ? null : c('qs-speed').textContent,
          polish: c('qs-polish').getAttribute('aria-checked'), whisper: c('qs-whisper').getAttribute('aria-checked'),
          label: c('qs-length').getAttribute('aria-label')}; })()"""


@chrome
def test_the_row_shows_each_value_in_the_top_bar():
    async def row(page, stub):
        return await page.eval(ROW)
    status = {"polish": True, "quick": {"length": "detailed", "speeds": {"page": 1.1, "iphone": 0.8}, "speed_shown": True, "by_voice": None}}
    got = asyncio.run(_run(row, status, shot="page-quick-row"))
    assert got == {"where": "top", "length": "Detailed", "speed": "1.1×", "polish": "true", "whisper": "false",
                   "label": "Reply length, Detailed"}  # the page's own speed, not the iPhone's


@chrome
def test_a_voice_with_no_speed_number_has_no_speed_chip():
    async def row(page, stub):
        return await page.eval(ROW)
    got = asyncio.run(_run(row, {"quick": {"length": "concise", "speeds": {}, "speed_shown": False, "by_voice": None}}))
    assert got["speed"] is None and got["length"] == "Concise"


@chrome
def test_the_menu_says_what_each_level_does_and_a_pick_is_saved():
    async def pick(page, stub):
        await page.eval("document.getElementById('qs-length').click(); true")
        await asyncio.sleep(0.3)
        menu = await page.eval("""[...document.querySelectorAll('#qs-pop .qopt')].map(b => [b.querySelector('b').textContent,
          b.querySelector('span').textContent, b.getAttribute('aria-checked')]).concat([[document.activeElement.id,
          document.querySelector('#qs-pop .qfoot').textContent]])""")
        await page.eval("document.getElementById('qs-opt-length-thorough').click(); true")
        await asyncio.sleep(0.9)
        shown = await page.eval(ROW)
        await page.eval("document.getElementById('qs-speed').click(); true")
        await asyncio.sleep(0.3)
        speeds = await page.eval("[...document.querySelectorAll('#qs-pop .qopt b')].map(b => b.textContent)")
        await page.eval("document.getElementById('qs-opt-speed-1_2').click(); true")
        await asyncio.sleep(0.9)
        return menu, shown, speeds, [body for path, body, _ in stub.posts if path == "/voice/prefs"], await page.eval(ROW)
    menu, shown, speeds, posts, after = asyncio.run(_run(pick, shot="page-quick-menu"))
    assert menu[:4] == [["Brief", quick.COPY["briefHint"], "false"], ["Concise", quick.COPY["conciseHint"], "true"],
                        ["Detailed", quick.COPY["detailedHint"], "false"], ["Thorough", quick.COPY["thoroughHint"], "false"]]
    assert menu[4] == ["qs-opt-length-concise", quick.COPY["lengthSay"]]  # the keyboard lands on the current level
    assert shown["length"] == "Thorough"
    assert speeds == ["Slowest", "Slower", "Normal", "Faster", "Fastest"]
    assert posts == [{"replies.length": "thorough"}, {"voice.speed": {"page": 1.2}}]  # only this page's speed is sent
    assert after["speed"] == "1.2×"


@chrome
def test_a_toggle_chip_flips_on_one_click():
    async def flip(page, stub):
        await page.eval("document.getElementById('qs-polish').click(); document.getElementById('qs-whisper').click(); true")
        await asyncio.sleep(0.9)
        return [body for path, body, _ in stub.posts if path == "/voice/prefs"], await page.eval(ROW)
    posts, row = asyncio.run(_run(flip))
    assert {"polish": True} in posts and {"whisper": True} in posts
    assert row["polish"] == "true" and row["whisper"] == "true"


@chrome
def test_a_change_by_voice_makes_its_chip_glow():
    async def glow(page, stub):
        stub.status["quick"] = {**stub.status["quick"], "length": "brief", "by_voice": {"key": "replies.length", "at": time.time()}}
        for _ in range(20):
            await asyncio.sleep(0.1)
            if await page.eval("document.getElementById('qs-length').classList.contains('glow')"):
                return True
        return False
    assert asyncio.run(_run(glow)) is True


@chrome
def test_on_a_narrow_screen_the_row_is_one_group_in_more():
    async def narrow(page, stub):
        await page.eval("openSheet('moresheet'); true")
        await asyncio.sleep(0.4)
        return await page.eval("[document.getElementById('quickrow').parentElement.id, document.querySelector('#quickrow .qhead').offsetHeight > 0, "
                               "getComputedStyle(document.querySelector('#qs-polish .qw')).display !== 'none']")
    assert asyncio.run(_run(narrow, width=390, shot="page-quick-more")) == ["more-list", True, True]  # with its words
