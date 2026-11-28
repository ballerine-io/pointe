"""Addressed speech on the page (ui.html, ui_addressed.html): the microphone switch's third choice, between Always on
and push to talk, and the state line that says how to talk. Headless Chrome against the stub Mac (tests/page_rig.py);
skipped where that Chrome is not installed (CI on Linux).

uv run --locked pytest -q tests/test_addressed_page.py
"""

import asyncio
import base64
import os
import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import addressed  # noqa: E402
from page_rig import CHROME, ROOT, Browser, StubMac  # noqa: E402
from test_thinking_page import DIAL, _status, _until  # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")
SHOTS = os.environ.get("POINTE_ADDRESSED_SHOTS")

SWITCH = """(() => ({order: [...document.querySelectorAll('.micmode [role=radio]')].map(b => [b.id.replace('micmode-', ''), b.textContent, b.getAttribute('aria-checked')]),
  options: [...document.getElementById('pref-mic').options].map(o => [o.value, o.textContent]),
  state: document.getElementById('state').textContent, kind: document.body.dataset.state,
  fits: (r => r.width > 0 && r.left >= 0 && r.right <= innerWidth + 1)(document.querySelector('.micmode').getBoundingClientRect()),
  cut: [...document.querySelectorAll('.micmode [role=radio]')].some(b => b.scrollWidth > b.clientWidth + 1)}))()"""


async def _run(script, status=None, width=1280, shot=None):
    stub = await StubMac().start()
    stub.status = status or _status()
    try:
        async with Browser() as browser:
            page = await browser.open(stub.url)
            await page.cdp("Emulation.setDeviceMetricsOverride", {"width": width, "height": 874 if width < 600 else 900, "deviceScaleFactor": 2, "mobile": width < 600})
            assert await page.eval(DIAL) == "live"
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


def _on():
    s = _status()
    s["ptt"]["mode"], s["addressed"] = "addressed", {"on": True, "open": False, "dropped": 0}
    return s


@pytest.mark.parametrize("width", [1280, 402])
def test_the_switch_has_the_mode_between_always_on_and_push_to_talk(width):
    async def look(page, stub):
        return await page.eval(SWITCH)
    got = asyncio.run(_run(look, width=width))
    assert [o[0] for o in got["order"]] == ["always", "addressed", "ptt"]
    assert got["order"][1][1] == addressed.COPY["short"] and got["order"][0][2] == "true"
    assert [o[0] for o in got["options"]] == ["always", "addressed", "ptt"] and got["options"][1][1] == addressed.COPY["setting"]
    assert got["fits"] and not got["cut"], f"three choices fit the dock at {width} pixels"


def test_choosing_it_tells_the_mac_and_the_state_line_says_how_to_talk():
    async def choose(page, stub):
        await page.eval("document.getElementById('micmode-addressed').click(); true")
        got = await _until(page, f"(() => {{ const g = {SWITCH}; return g.state === {addressed.COPY['idle']!r} && g; }})()")
        return got or await page.eval(SWITCH), [body for path, body, _ in stub.posts if path == "/voice/prefs"]
    got, posts = asyncio.run(_run(choose, shot="page-addressed"))
    assert posts == [{"microphone": "addressed"}]
    assert got["state"] == "Say “Pointe” to talk" and got["kind"] == "live"
    assert [o[2] for o in got["order"]] == ["false", "true", "false"]


def test_after_the_name_alone_the_line_says_listening_and_speaking_still_comes_first():
    async def line(page, stub):
        return await _until(page, "document.getElementById('state').textContent !== 'Connecting…' && document.getElementById('state').textContent")
    s = _on()
    s["addressed"]["open"] = True
    assert asyncio.run(_run(line, status=s)) == "Listening"
    s = _on()
    s["speaking"] = "bot"
    assert asyncio.run(_run(line, status=s)) == "Speaking…"


def test_settings_shows_what_the_mode_does_only_when_it_is_chosen():
    async def hint(page, stub):
        stub.prefs = {**getattr(stub, "prefs", {}), "microphone": "addressed"}
        await page.eval("openSettings(); true")
        await asyncio.sleep(0.8)
        shown = await page.eval("[document.getElementById('pref-mic').value, !document.getElementById('pref-mic-hint').hidden, document.getElementById('pref-mic-hint').textContent]")
        await page.eval("(() => { const m = document.getElementById('pref-mic'); m.value = 'always'; m.dispatchEvent(new Event('change')); })()")
        return shown, await page.eval("!document.getElementById('pref-mic-hint').hidden")
    (value, shown, words), after = asyncio.run(_run(hint, status=_on()))
    assert words == addressed.COPY["hint"]
    assert (value, shown) in (("addressed", True), ("always", False)) and after is False


def test_the_words_are_the_same_on_the_page_and_in_the_apps():
    page = (ROOT / "pointe" / "ui_addressed.html").read_text()
    swift = (ROOT / "apps" / "PointeKit" / "Sources" / "PointeUI" / "Addressed.swift").read_text()
    for key, words in addressed.COPY.items():
        assert words in page.replace('\\"', '"'), f"{key}: the page does not say {words!r}"
        assert words in swift, f"{key}: the apps do not say {words!r}"
