"""Session tones on the page (ui.html, ui_tones.html): the setting in Settings, Turn taking, off unless the Mac says on,
saved with the rest; and a session's row names its tone when the Mac sends one. Headless Chrome against the stub Mac
(tests/page_rig.py); skipped where that Chrome is not installed (CI on Linux).

uv run --locked pytest -q tests/test_tones_page.py
"""

import asyncio
import base64
import os
import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tones  # noqa: E402
from page_rig import CHROME, Browser, StubMac, fixture  # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")
SHOTS = os.environ.get("POINTE_TONES_SHOTS")

MARKS = """[...document.querySelectorAll('#list .s')].map(r => [r.querySelector('.nm').textContent, r.querySelector('.hmark').textContent,
  r.querySelector('.hmark').getAttribute('aria-label'), r.querySelector('.nm').scrollWidth > r.querySelector('.nm').clientWidth])"""


async def _run(script, on=False, toned=False, shot=None):
    stub = await StubMac().start()
    stub.status = fixture(sessions=3, connected=True)
    stub.tones = on
    if toned:
        for i, row in enumerate(stub.status["sessions"]):
            row["harness"] = ["claude-code", "codex", "opencode"][i]
            row["tone"] = {"index": i, "name": tones.PALETTE[i].name} if i < 2 else None
    try:
        async with Browser() as browser:
            page = await browser.open(stub.url)
            await asyncio.sleep(0.6)
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


async def _settings(page, stub):
    await page.eval("openSettings().then(() => settingsJump('g-turns')); true")
    await asyncio.sleep(0.9)
    return await page.eval("[document.getElementById('pref-tones').checked, document.getElementById('pref-tones-hint').textContent, "
                           "document.getElementById('pref-tones').closest('label').textContent.trim()]")


def test_the_setting_is_off_unless_the_mac_says_on_and_says_what_it_does():
    assert asyncio.run(_run(_settings, shot="page-tones-settings")) == [False, tones.COPY["hint"], tones.COPY["setting"]]
    assert asyncio.run(_run(_settings, on=True))[0] is True


def test_turning_it_on_is_saved_with_the_rest():
    async def save(page, stub):
        await _settings(page, stub)
        await page.eval("document.getElementById('pref-tones').click(); true")
        await page.eval("[...document.querySelectorAll('#settingssheet button')].find(b => b.textContent.trim() === 'Done').click(); true")
        await asyncio.sleep(0.8)
        return [body for path, body, _ in stub.posts if path == "/voice/prefs"]
    posts = asyncio.run(_run(save))
    assert posts and posts[-1]["reports.tones"] is True


def test_a_sessions_row_names_its_tone_when_the_mac_sends_one():
    async def rows(page, stub):
        return await page.eval(MARKS)
    got = asyncio.run(_run(rows, on=True, toned=True, shot="page-tones-rows"))
    assert [r[1] for r in got] == ["Claude · tone: rise", "Codex · tone: fall", "OpenCode"]
    assert [r[2] for r in got] == ["runs on Claude", "runs on Codex", "runs on OpenCode"]
    assert not any(r[3] for r in got), "the session's name is still whole beside it"
    plain = asyncio.run(_run(rows))
    assert all("tone" not in r[1] for r in plain), "no tone from the Mac: the row is as before"
