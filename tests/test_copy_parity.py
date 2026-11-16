"""Words the page and the iPhone app share, and where the page shows them (docs/design/ux-review-web.md, "Left as it is").

Each string lives in a dictionary on each side: ui.html's MEETING_COPY, CONNECT_COPY and LOCK_COPY; the app's
MeetingCopy, ConnectCopy and VoiceLockCopy. The hold's words (TURNS_COPY, TurnsCopy) are checked in test_turn_taking.py.
"""

import asyncio
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_rig import CHROME, Browser, StubMac, fixture, free_port  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "ui.html").read_text()


def _page(name: str) -> dict:
    block = PAGE[PAGE.index(f"const {name} = {{"):]
    block = block[:block.index("};")]
    return {k: v.replace("\\'", "'") for k, v in re.findall(r"(\w+): '((?:[^'\\]|\\.)*)'", block)}


def _app(file: str, name: str) -> dict:
    swift = (ROOT / "ios" / "Pointe" / file).read_text()
    block = swift[swift.index(f"enum {name}"):]
    block = block[:block.index("\n}\n")]
    return dict(re.findall(r'static let (\w+) = "((?:[^"\\]|\\.)*)"', block))


def test_the_page_and_the_app_share_these_words():
    assert _page("MEETING_COPY")["lede"] == _app("Meeting.swift", "MeetingCopy")["lede"] \
        == "Pointe sits in and takes notes for you. It stays quiet unless you let it speak."
    assert _page("CONNECT_COPY")["typeLaterTap"] == _app("Connect.swift", "ConnectCopy")["typeLaterTap"] \
        == "Once connected, tap the keyboard to type"
    assert _page("LOCK_COPY")["needsVoice"] == _app("VoiceLock.swift", "VoiceLockCopy")["needsVoice"] \
        == "Enrol your voice to use the other levels."
    assert "never answers every remark" not in PAGE


SHOWN = """(() => ({hint: document.getElementById('connect-hint').textContent, lede: document.getElementById('meet-lede').textContent,
  why: document.getElementById('vl-levelwhy').textContent, whyShown: document.getElementById('vl-levelwhy').offsetHeight > 0}))()"""


@pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")
def test_the_page_shows_them_where_they_apply():
    """"Or type below" is true only where the box is below: on a phone it is folded behind the keyboard button. The
    lock levels above Off say why they are off while there is no voiceprint."""
    async def run():
        stub = await StubMac(free_port()).start()
        stub.status = fixture(sessions=2, talk=0, connected=True)
        out = {}
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                for width in (390, 1440):  # the box folds when the page opens on a narrow screen
                    await page.cdp("Emulation.setDeviceMetricsOverride", {"width": width, "height": 844, "deviceScaleFactor": 1, "mobile": False})
                    await page.cdp("Page.navigate", {"url": stub.url})
                    await asyncio.sleep(0.5)
                    await page.wait_for_page()
                    for live in (False, True):
                        await page.eval(f"(async () => {{ call.state = '{'live' if live else 'off'}'; await refresh(); render(); return true; }})()")
                        await asyncio.sleep(0.4)
                        out[(width, live)] = await page.eval(SHOWN)
                await page.eval("(async () => { await openSettings(); settingsJump('voicelock'); return true; })()")
                await asyncio.sleep(0.6)
                out["none"] = await page.eval(SHOWN)
                stub.status["voice_lock"].update(enrolled=True, level="approvals", devices=[{"device": "MacBook Pro Microphone"}])
                await asyncio.sleep(1.2)
                out["enrolled"] = await page.eval(SHOWN)
        finally:
            await stub.stop()
        return out
    got = asyncio.run(run())
    assert got[(1440, False)]["hint"] == "Or type below once connected"
    assert got[(1440, True)]["hint"] == "Or type below · Press Space to mute"
    assert got[(390, False)]["hint"] == "Once connected, tap the keyboard to type"
    assert got[(390, True)]["hint"] == "Or tap the keyboard to type"
    assert got[(1440, False)]["lede"] == "Pointe sits in and takes notes for you. It stays quiet unless you let it speak."
    assert got["none"]["why"] == "Enrol your voice to use the other levels." and got["none"]["whyShown"], got["none"]
    assert got["enrolled"]["why"] == "" and not got["enrolled"]["whyShown"], got["enrolled"]
