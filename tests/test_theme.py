"""Ballerine Brand Guidelines V6 on both surfaces: one source, no drift (docs/design/brand-v6.md).

assets/theme.json holds the theme choices, every colour token for light and dark, the pinned font files and the
harness marks. The page (ui.html) and the iPhone app (ios/Pointe/Brand.swift) each carry their own copy, because the
page must render with no build step and the app must compile with no resource lookup; these tests read both and fail
when either differs from the source. They also hold the things a restyle can quietly break: the fonts come from this
Mac and nowhere else, at their pinned hashes; text meets WCAG AA on every surface it sits on, in both themes; and the
session list is grouped by machine, with a harness mark on every row, the same way on both.
"""

import asyncio
import hashlib
import json
import os
import plistlib
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_rig import CHROME, ROOT, Browser, StubMac, fixture, free_port  # noqa: E402
from test_orchestrator import client_for, d  # noqa: E402,F401  (d is a fixture)

THEME = json.loads((ROOT / "assets" / "theme.json").read_text())
PAGE = (ROOT / "ui.html").read_text()
BRAND = (ROOT / "apple" / "PointeKit" / "Sources" / "PointeUI" / "Brand.swift").read_text()
needs_chrome = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")


# ---------- colours ----------

def rgba(value: str) -> tuple[int, int, int, float]:
    """'#RRGGBB' or 'rgba(r,g,b,a)' as (r, g, b, a)."""
    value = value.strip()
    if value.startswith("#"):
        return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16), 1.0)
    r, g, b, a = re.fullmatch(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)", value).groups()
    return (int(r), int(g), int(b), float(a))


def source(mode: str) -> dict:
    return {name: rgba(v[mode]) for name, v in THEME["tokens"].items()}


def page_tokens(selector: str) -> dict:
    block = re.search(re.escape(selector) + r" \{\n(.*?)\n  \}", PAGE, re.S).group(1)
    found = dict(re.findall(r"^\s*--([\w-]+): ([^;]+);", block, re.M))
    return {k: rgba(v) for k, v in found.items() if k in THEME["tokens"]}


def app_tokens() -> dict:
    """Brand.swift's `static let name = Color(light: 0xRRGGBB[, a], dark: 0xRRGGBB[, a])` lines, by kebab-case name."""
    block = BRAND[BRAND.index("// theme tokens"):BRAND.index("// end of theme tokens")]
    out = {}
    for name, lhex, la, dhex, da in re.findall(
            r"static let (\w+) = Color\(light: 0x([0-9A-F]{6})(?:, ([\d.]+))?, dark: 0x([0-9A-F]{6})(?:, ([\d.]+))?\)", block):
        kebab = re.sub(r"(?<=[a-z])(?=[A-Z])", "-", name).lower()

        def one(h, a):
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), float(a) if a else 1.0)
        out[kebab] = {"light": one(lhex, la), "dark": one(dhex, da)}
    return out


def same(a: dict, b: dict) -> list:
    """Names whose colour differs. A fully clear colour has no hue to compare."""
    return sorted(k for k in a.keys() | b.keys()
                  if a.get(k) != b.get(k) and not (a.get(k) and b.get(k) and a[k][3] == 0 == b[k][3]))


def test_the_page_carries_the_source_tokens_for_light_and_dark():
    assert same(page_tokens("  :root"), source("light")) == []
    assert same(page_tokens("  :root[data-theme=dark]"), source("dark")) == []


def test_the_app_carries_the_source_tokens_for_light_and_dark():
    app = app_tokens()
    assert same({k: v["light"] for k, v in app.items()}, source("light")) == []
    assert same({k: v["dark"] for k, v in app.items()}, source("dark")) == []


def test_no_colour_of_the_old_system_is_left_on_either_surface():
    """Navy, the old orange, pure black text and the serif are V5 and earlier; a hex outside the tokens is a drift."""
    swift = "".join(p.read_text() for p in (ROOT / "apple" / "PointeKit" / "Sources" / "PointeUI").glob("*.swift"))
    for old in ("#FF4F1F", "#0E1622", "#0A0F17", "#152031", "Playfair", "New York", "'Inter'"):
        assert old not in PAGE, old
    assert "design: .serif" not in swift and ".italic()" not in swift
    assert "preferredColorScheme(.dark)" not in swift
    styles = "".join(re.findall(r"<style>(.*?)</style>", PAGE, re.S))
    styles = re.sub(r"url\(\"data:[^\"]*\"\)", "", styles)  # inline icons carry their own strokes
    allowed = {v[m].upper() for v in THEME["tokens"].values() for m in ("light", "dark") if v[m].startswith("#")} | {"#FFF", "#000"}
    stray = sorted({h.upper() for h in re.findall(r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b", styles)} - allowed)
    assert stray == [], f"hex colours in the page's CSS that are not tokens: {stray}"


# ---------- contrast ----------

def luminance(c) -> float:
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2])


def over(fg, bg):
    """fg composited on an opaque bg."""
    a = fg[3]
    return tuple(round(fg[i] * a + bg[i] * (1 - a)) for i in range(3)) + (1.0,)


def contrast(fg, bg) -> float:
    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# text token -> the surfaces it is set on. Body-size text needs 4.5:1 (WCAG 2.2 AA, 1.4.3).
TEXT_ON = {
    "text": ["bg", "surface", "card", "raised", "raised2", "group", "cell", "tint"],
    "muted": ["bg", "surface", "card", "raised", "group", "cell", "tint"],
    "dim": ["bg", "surface", "card", "raised", "group", "cell"],
    "accent": ["bg", "surface", "card", "cell"],
    "success-text": ["bg", "surface", "card", "cell"],
    "danger-text": ["bg", "surface", "card", "raised", "cell"],
    "on-orange": ["orange"],
    "on-primary": ["primary"],
}
# marks that are not text (a status dot, the mic, an outline that says "selected") need 3:1 (1.4.11)
MARK_ON = {"orange": ["bg", "surface", "card", "cell"], "success": ["bg", "surface", "card", "cell"], "danger": ["bg", "surface", "card", "cell"]}


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_text_meets_wcag_aa_on_every_surface_it_sits_on(mode):
    t = source(mode)
    failing = []
    for wanted, pairs in ((4.5, TEXT_ON), (3.0, MARK_ON)):
        for fg, grounds in pairs.items():
            for ground in grounds:
                bg = over(t[ground], t["bg"])  # a translucent surface (the tint) sits on the page colour
                ratio = contrast(over(t[fg], bg), bg)
                if ratio < wanted:
                    failing.append(f"{mode}: {fg} on {ground} is {ratio:.2f}:1, needs {wanted}")
    assert failing == []


def test_white_on_the_danger_fill_is_readable():
    assert contrast((255, 255, 255, 1.0), source("light")["danger"]) >= 4.5  # Hang up, End meeting


# ---------- the theme choice ----------

def test_both_surfaces_offer_the_same_theme_choices_with_the_same_default_and_words():
    choices, default, labels = THEME["choices"], THEME["default"], THEME["labels"]
    assert choices == ["system", "light", "dark"] and default == "system"
    # the page
    assert re.search(r"const THEMES = \[([^\]]*)\]", PAGE).group(1).replace("'", "").split(", ") == choices
    assert re.search(r"THEME_DEFAULT = '(\w+)'", PAGE).group(1) == default
    assert dict(re.findall(r'id="theme-(\w+)" onclick="setTheme\(\'\w+\'\)">([^<]+)<', PAGE)) == labels
    assert "localStorage.getItem('pointe.theme')" in PAGE and 'data-section="g-appearance"' in PAGE
    # the app
    theme = BRAND[BRAND.index("enum Theme"):BRAND.index("struct HarnessMark")]
    assert re.search(r"case (\w+(?:, \w+)*)\n", theme).group(1).split(", ") == choices
    assert re.search(r"static let fallback = Theme\.(\w+)", theme).group(1) == default
    assert dict(re.findall(r'case \.(\w+): "(\w+)"', theme)) == labels
    assert re.search(r'static let key = "pointe\.theme"', theme)
    assert re.search(r'static let setting = "Appearance"', theme) and ">Appearance</button>" in PAGE
    settings = (ROOT / "apple" / "PointeKit" / "Sources" / "PointeUI" / "CallSettings.swift").read_text()
    assert 'accessibilityIdentifier("appearanceSetting")' in settings  # reachable from the app's Settings (the ••• button)
    assert "preferredColorScheme(Theme.stored(theme).scheme)" in (ROOT / "apple" / "PointeKit" / "Sources" / "PointeUI" / "PointeRoot.swift").read_text()


@needs_chrome
def test_the_page_follows_the_system_until_a_choice_is_made_and_keeps_the_choice():
    async def run():
        stub = await StubMac(free_port()).start()
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                await page.wait_for_page()
                seen = {}
                for system in ("dark", "light"):
                    await page.cdp("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": system}]})
                    await asyncio.sleep(0.2)
                    seen[system] = await page.eval("[themeChoice(), document.documentElement.dataset.theme, getComputedStyle(document.body).backgroundColor]")
                await page.eval("setTheme('dark')")
                seen["chosen"] = await page.eval("[themeChoice(), document.documentElement.dataset.theme, localStorage.getItem('pointe.theme'),"
                                                 " document.getElementById('theme-dark').classList.contains('on')]")
                await page.eval("setTheme('nonsense')")
                seen["refused"] = await page.eval("themeChoice()")
                return seen
        finally:
            await stub.stop()
    seen = asyncio.run(run())
    assert seen["dark"] == ["system", "dark", "rgb(10, 4, 0)"]
    assert seen["light"] == ["system", "light", "rgb(255, 255, 255)"]
    assert seen["chosen"] == ["dark", "dark", "dark", True]  # a choice beats the system (light here)
    assert seen["refused"] == "dark"


# ---------- fonts ----------

def test_the_font_files_are_the_pinned_ones_on_both_surfaces_with_their_licence():
    files = THEME["files"]
    assert sorted(files) == sorted(f"{face}.ttf" for family in THEME["fonts"].values() for face in family["weights"].values())
    for folder in (ROOT / "assets" / "fonts", ROOT / "apple" / "PointeKit" / "Sources" / "PointeUI" / "Resources" / "Fonts"):
        assert sorted(p.name for p in folder.glob("*.ttf")) == sorted(files), folder
        for name, sha in files.items():
            assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == sha, f"{folder.name}/{name}"
        for licence in ("OFL-BricolageGrotesque.txt", "OFL-InstrumentSans.txt"):
            assert "SIL OPEN FONT LICENSE Version 1.1" in (folder / licence).read_text(), licence
    third_party = (ROOT / "THIRD_PARTY.md").read_text()
    assert "Bricolage Grotesque" in third_party and "Instrument Sans" in third_party and "OFL-1.1" in third_party


def test_the_app_registers_exactly_the_bundled_fonts():
    """The fonts are the shared module's resources, registered by it at launch for both apps: every .ttf in its bundle,
    which the test above holds to the pinned files. Neither app lists them in its Info.plist."""
    assert 'Bundle.module.urls(forResourcesWithExtension: "ttf"' in BRAND and "CTFontManagerRegisterFontsForURL" in BRAND
    assert "Brand.registerFonts()" in (ROOT / "apple" / "PointeKit" / "Sources" / "PointeUI" / "PointeRoot.swift").read_text()
    assert '.process("Resources")' in (ROOT / "apple" / "PointeKit" / "Package.swift").read_text()
    with open(ROOT / "ios" / "Pointe" / "Info.plist", "rb") as f:
        assert "UIAppFonts" not in plistlib.load(f)
    for family in THEME["fonts"].values():
        for face in family["weights"].values():
            assert f'"{face}"' in BRAND, face


def test_the_page_loads_its_fonts_from_this_mac_only():
    faces = re.findall(r"@font-face \{ font-family: '([^']+)'; font-weight: (\d+);.*?src: url\('([^']+)'\)", PAGE, re.S)
    want = sorted((family["family"], weight, f"/voice/font/{face}.ttf")
                  for family in THEME["fonts"].values() for weight, face in family["weights"].items())
    assert sorted(faces) == want
    assert "fonts.googleapis.com" not in PAGE and "fonts.gstatic.com" not in PAGE
    assert PAGE.count("unicode-range:") == len(faces)  # Latin only: Hebrew goes to the system font behind it
    assert re.search(r"--font: 'Instrument Sans', -apple-system, system-ui", PAGE)


def test_the_daemon_serves_a_pinned_font_and_nothing_else(d, monkeypatch):
    client = client_for(d)
    name, sha = next(iter(THEME["files"].items()))
    got = client.get(f"/voice/font/{name}")
    assert got.status_code == 200 and got.headers["content-type"] == "font/ttf"
    assert hashlib.sha256(got.content).hexdigest() == sha
    assert client.get("/voice/font/theme.json").status_code == 404
    assert client.get("/voice/font/..%2Ftheme.json").status_code == 404
    monkeypatch.setattr(d, "_fonts", lambda: {name: "0" * 64})  # a file that is not the pinned one is not served
    assert client.get(f"/voice/font/{name}").status_code == 404


# ---------- sessions: grouped by machine, a harness mark on every row ----------

def test_both_surfaces_carry_the_same_harness_marks():
    want = {k: (v["name"], v["glyph"]) for k, v in THEME["harnesses"].items()}
    page = re.search(r"const HARNESSES = \{(.*?)\};", PAGE, re.S).group(1)
    assert {k: (n, g) for k, n, g in re.findall(r"'?([\w-]+)'?: \{name: '(\w+)', glyph: '(\w)'\}", page)} == want
    marks = (ROOT / "apple" / "PointeKit" / "Sources" / "PointeKit" / "Harness.swift").read_text()  # one table, for both apps
    assert dict((k, (n, g)) for k, n, g in re.findall(r'"([\w-]+)": \(name: "(\w+)", glyph: "(\w)"\)', marks)) == want
    assert "typealias Harness = PointeKit.Harness" in (ROOT / "apple" / "PointeKit" / "Sources" / "PointeUI" / "Shared.swift").read_text()
    # the same words for a screen reader, and no vendor logo on either: the marks are letters (docs/design/brand-v6.md)
    assert "'runs on ' + h.name" in PAGE and 'accessibilityLabel("runs on \\(mark.name)")' in BRAND
    sessions = (ROOT / "apple" / "PointeKit" / "Sources" / "PointeUI" / "Sessions.swift").read_text()
    assert sessions.count("HarnessMark(harness: s.harness") == 2  # the strip and the Sessions sheet
    assert "harnessMark(x), tools" in PAGE


def machines_status(machines: int, offline: str | None = None) -> dict:
    s = fixture(sessions=6, machines=machines)
    for i, row in enumerate(s["sessions"]):
        row["harness"] = ["claude-code", "codex", "opencode", "pi", "claude-code", "codex"][i]
        if offline and row["machine"] == offline:
            row["online"] = False
    for m in s["machines"]:
        if m["name"] == offline:
            m["online"] = False
    return s


LIST = """(() => [...document.querySelectorAll('#list > *')].map(e => e.classList.contains('mh')
    ? {machine: e.querySelector('.mn').textContent, state: e.querySelector('.ml').getAttribute('aria-label'), away: e.classList.contains('away')}
    : {session: e.querySelector('.nm').firstChild.textContent, harness: e.querySelector('.hmark').dataset.harness,
       label: e.querySelector('.hmark').getAttribute('aria-label'), glyph: e.querySelector('.hmark .hg').textContent,
       tip: e.querySelector('.hmark').title, tag: e.querySelector('.tag').textContent,
       cut: e.querySelector('.nm').scrollWidth > e.querySelector('.nm').clientWidth}))()"""


async def _list(status: dict) -> list:
    stub = await StubMac(free_port()).start()
    stub.status = status
    try:
        async with Browser() as browser:
            page = await browser.open(stub.url)
            await page.wait_for_page()
            return await page.eval(LIST)
    finally:
        await stub.stop()


@needs_chrome
def test_the_page_groups_sessions_by_named_machine_with_a_harness_mark_on_each():
    rows = asyncio.run(_list(machines_status(3)))
    heads = [r for r in rows if "machine" in r]
    assert [h["machine"] for h in heads] == ["studio", "devbox", "laptop"]  # this Mac first, each by its own name
    assert all(h["state"] == "online" and not h["away"] for h in heads)
    under, group = {}, None
    for r in rows:
        if "machine" in r:
            group = r["machine"]
        else:
            under.setdefault(group, []).append(r)
    assert sorted(under) == ["devbox", "laptop", "studio"] and sum(len(v) for v in under.values()) == 6
    sessions = [r for r in rows if "session" in r]
    for r in sessions:
        mark = THEME["harnesses"][r["harness"]]
        assert (r["glyph"], r["label"], r["tip"]) == (mark["glyph"], f"runs on {mark['name']}", mark["name"])
        assert not r["cut"], f"{r['session']} is cut short: the name gets the row's width, the agent is a mark"
    assert {r["harness"] for r in sessions} == {"claude-code", "codex", "opencode", "pi"}


@needs_chrome
def test_one_machine_shows_no_machine_header_and_still_marks_each_session():
    status = fixture(sessions=3, machines=1)
    for row in status["sessions"]:
        row["harness"] = "claude-code"
    rows = asyncio.run(_list(status))
    assert [r for r in rows if "machine" in r] == [] and len(rows) == 3
    assert all((r["glyph"], r["label"]) == ("C", "runs on Claude") for r in rows)


@needs_chrome
def test_an_offline_machine_keeps_its_header_and_says_so():
    rows = asyncio.run(_list(machines_status(3, offline="devbox")))
    heads = {r["machine"]: r for r in rows if "machine" in r}
    assert (heads["devbox"]["state"], heads["devbox"]["away"]) == ("offline", True)
    assert (heads["studio"]["state"], heads["laptop"]["state"]) == ("online", "online")
    after = rows[rows.index(heads["devbox"]) + 1:]
    assert after[0]["tag"] == "offline" and "session" in after[0]  # its sessions stay listed under it, marked offline
