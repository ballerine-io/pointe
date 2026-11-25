"""The accessibility pass (docs/features/accessibility.md): the page's part, in a headless Chrome against the stub Mac
(tests/page_rig.py), and the rules the apps' sources must keep. The apps' own checks are
apps/ios/PointeUITests/AccessibilityUITests.swift, MotionTests.swift and apps/macos/e2e/smoke.py.

- Every control of the call screen has a name a screen reader can say.
- With `prefers-reduced-motion: reduce` nothing on the page moves by itself, and no scroll glides.
- In Swift every animation goes through Motion.swift, which is off with Reduce Motion.
- Every sound Pointe makes has something to see beside it (SOUNDS): a new sound without a row fails here.
- At 320 CSS pixels (a 1280 window at 400%, WCAG 1.4.10) the state line is whole.

uv run --locked pytest -q tests/test_accessibility.py
"""

import asyncio
import base64
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_rig import CHROME, ROOT, Browser, StubMac, free_port  # noqa: E402
from test_thinking_page import DIAL, THINKING, WORKING, _status, _until  # noqa: E402

needs_chrome = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")
SHOTS = os.environ.get("POINTE_A11Y_SHOTS")
PAGE = (ROOT / "pointe" / "ui.html").read_text()
SWIFT = [*(ROOT / "apps" / "PointeKit" / "Sources").rglob("*.swift"), *(ROOT / "apps" / "macos" / "PointeMac").glob("*.swift"),
         *(ROOT / "apps" / "ios" / "Pointe").rglob("*.swift")]


async def _on_page(status, script, reduce=False, width=None, live=True, shot=None):
    stub = await StubMac(free_port()).start()
    stub.status = status
    try:
        async with Browser() as browser:
            page = await browser.open(stub.url)
            if width:
                await page.cdp("Emulation.setDeviceMetricsOverride", {"width": width, "height": 720, "deviceScaleFactor": 2, "mobile": True})
            if reduce:
                await page.cdp("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})
            if live:
                assert await page.eval(DIAL) == "live"
            await asyncio.sleep(0.8)
            got = await script(page)
            if shot and SHOTS:
                for look in ("light", "dark"):
                    await page.cdp("Emulation.setEmulatedMedia", {"features": [
                        {"name": "prefers-color-scheme", "value": look}, *([{"name": "prefers-reduced-motion", "value": "reduce"}] if reduce else [])]})
                    await asyncio.sleep(0.3)
                    data = (await page.cdp("Page.captureScreenshot", {"format": "png"}))["data"]
                    Path(SHOTS, f"{shot}-{look}.png").write_bytes(base64.b64decode(data))
            return got
    finally:
        await stub.stop()


# ---------- names ----------

UNNAMED = """(() => { const shown = e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
  const name = e => (e.getAttribute('aria-label') || (e.getAttribute('aria-labelledby') || '').split(' ').map(i => (document.getElementById(i) || {}).textContent || '').join(' ')
    || (e.labels && [...e.labels].map(l => l.textContent).join(' ')) || e.textContent || e.title || e.placeholder || '').trim();
  return [...document.querySelectorAll('button, [role=button], [role=switch], input, select, textarea, a[href], [tabindex="0"]')]
    .filter(shown).filter(e => !name(e) || /^[\\W_]+$/.test(name(e))).map(e => e.id || e.outerHTML.slice(0, 80)); })()"""


@needs_chrome
@pytest.mark.parametrize("width", [1280, 402])
def test_every_control_of_the_call_screen_has_a_name(width):
    """A name of punctuation only ("×", "•••") is not one: it needs an aria-label."""
    async def unnamed(page):
        return await page.eval(UNNAMED)
    for status in (_status(), _status(THINKING), _status(speaking="bot")):
        assert asyncio.run(_on_page(status, unnamed, width=width)) == [], "controls a screen reader cannot name"


@needs_chrome
def test_the_state_line_is_said_to_a_screen_reader_when_it_changes():
    async def said(page):
        return await _until(page, "(() => { const e = document.getElementById('statesay'); return e.getAttribute('role') === 'status' && e.textContent; })()")
    assert asyncio.run(_on_page(_status(THINKING), said)).startswith("Thinking")


# ---------- Reduce Motion ----------

MOVING = """(() => document.getAnimations().filter(a => a.playState === 'running' && (a.effect.getComputedTiming().iterations === Infinity
  || a.effect.getComputedTiming().activeDuration > 50)).map(a => a.animationName || a.transitionProperty || '?'))()"""


@needs_chrome
def test_with_reduced_motion_nothing_on_the_page_moves_by_itself():
    async def moving(page):
        await asyncio.sleep(0.5)
        return await page.eval(MOVING)
    for status in (_status(THINKING), _status(WORKING), _status(speaking="bot")):
        assert asyncio.run(_on_page(status, moving)) != [], "the check sees motion when motion is allowed"
        assert asyncio.run(_on_page(status, moving, reduce=True, shot="page-reduce-motion-" + (status["phase"] or {}).get("name", "speaking"))) == []


def test_no_scroll_on_the_page_glides_when_motion_is_reduced():
    """CSS `scroll-behavior` does not reach a scroll a script asks to be smooth: each one asks glide() first."""
    assert "const glide = () => matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';" in PAGE
    assert re.findall(r"behavior: 'smooth'", PAGE) == [], "use behavior: glide()"
    assert "@media (prefers-reduced-motion: reduce)" in PAGE


def test_every_swift_animation_goes_through_motion_swift():
    """Motion.swift is the one place that starts an animation, and it does not with Reduce Motion on."""
    motion = next(p for p in SWIFT if p.name == "Motion.swift").read_text()
    assert "func withAnimation<Result>" in motion and "Motion.reducedNow ? nil : animation" in motion
    assert "accessibilityReduceMotion" in motion and "accessibilityDisplayShouldReduceMotion" in motion
    raw = re.compile(r"\.animation\(|\.symbolEffect\(|contentTransition\(\.symbolEffect|SwiftUI\.withAnimation|repeatForever")
    stray = [f"{p.relative_to(ROOT)}:{n}" for p in SWIFT if p.name != "Motion.swift"
             for n, line in enumerate(p.read_text().split("\n"), 1) if raw.search(line.split("//")[0])]
    assert stray == [], "an animation Reduce Motion would not stop: use .motion(_:value:), .pulsing(), .listeningWave() or .symbolSwap()"
    apps = [p for p in SWIFT if "PointeMac/" in str(p) or "/ios/Pointe/" in str(p)]
    assert not any("withAnimation" in p.read_text() for p in apps), "the apps' own targets do not have Motion's withAnimation"


# ---------- every sound has something to see ----------

# sound: (file, the line that plays it, file, what is on screen with it). Speech itself is the conversation's text; a
# haptic is always beside a change on screen (it is `sensoryFeedback` on that change).
SOUNDS = {
    "the waiting sound": ("pointe/daemon.py", "OutputAudioRawFrame(audio=thinking.cue_pcm(rate)", "pointe/thinking.py", '"thinking": "Thinking…"'),
    "the two-note chime": ("pointe/daemon.py", "OutputAudioRawFrame(audio=pcm.astype(np.int16).tobytes()",
                           "apps/PointeKit/Sources/PointeUI/CallTitle.swift", "if dumping { return BrainDumpCopy.state }"),
    "the page's mute tone": ("pointe/ui.html", "tones.createOscillator()", "pointe/ui.html", "function showMute()"),
    "the iPhone's chime when the Mac closes a press": ("apps/PointeKit/Sources/PointeUI/Call.swift", "AudioServicesPlaySystemSound(1113)",
                                                        "apps/PointeKit/Sources/PointeUI/CallTitle.swift", "TalkGate.closedLine(why"),
    "the Mac's chime when it closes a press": ("apps/PointeKit/Sources/PointeUI/Call.swift", 'NSSound(named: "Tink")',
                                               "apps/PointeKit/Sources/PointeUI/CallTitle.swift", "TalkGate.closedLine(why"),
    "an alert's sound": ("apps/PointeKit/Sources/PointeUI/Alerts.swift", "c.sound = .default", "apps/PointeKit/Sources/PointeUI/Alerts.swift", "c.body ="),
}
MAKES_SOUND = re.compile(r"OutputAudioRawFrame\(audio=|createOscillator\(|AudioServicesPlay\w+\(|NSSound[.(]|\.sound = |AVAudioPlayer\(")


def test_every_sound_has_something_to_see():
    for sound, (where, plays, shown_in, shows) in SOUNDS.items():
        assert plays in (ROOT / where).read_text(), f"{sound}: {where} no longer plays it this way; update SOUNDS"
        assert shows in (ROOT / shown_in).read_text(), f"{sound}: what is on screen with it is gone from {shown_in}"
    rows = {(where, plays) for where, plays, _, _ in SOUNDS.values()}
    sources = [*(ROOT / "pointe").glob("*.py"), *(ROOT / "pointe").glob("*.html"), *SWIFT]
    unlisted = [f"{p.relative_to(ROOT)}:{n}: {line.strip()[:90]}" for p in sources for n, line in enumerate(p.read_text().split("\n"), 1)
                if MAKES_SOUND.search(line) and not any(str(p.relative_to(ROOT)) == where and plays in line for where, plays in rows)]
    assert unlisted == [], "a sound with no row in SOUNDS: say what is on screen with it (docs/features/accessibility.md)"
    doc = (ROOT / "docs" / "features" / "accessibility.md").read_text()
    for sound in SOUNDS:
        assert sound in doc, f"docs/features/accessibility.md does not list {sound}"


# ---------- large text ----------

FITS = """(() => { const s = document.getElementById('state'), r = s.getBoundingClientRect(), m = document.getElementById('mutebtn').getBoundingClientRect();
  return {text: s.textContent, cut: s.scrollWidth > s.clientWidth + 1 || s.scrollHeight > s.clientHeight + 1, left: r.left, right: r.right,
          wide: innerWidth, sideways: document.documentElement.scrollWidth > innerWidth + 1, mute: m.width > 0 && m.right <= innerWidth + 1}; })()"""


@needs_chrome
def test_at_320_pixels_the_state_line_is_whole():
    async def fits(page):
        await _until(page, "document.getElementById('state').textContent.includes('working')")
        return await page.eval(FITS)
    status = _status({"name": "working", "session": "payments-reconciliation/main", "since": 0})
    got = asyncio.run(_on_page(status, fits, width=320, shot="page-320-state-line"))
    assert got["text"] == "payments-reconciliation/main is working…", got
    assert not got["cut"] and got["left"] >= 0 and got["right"] <= got["wide"] + 1, got
    assert got["mute"] and not got["sideways"], got
