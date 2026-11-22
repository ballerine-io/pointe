"""The Chorus mark is one set of files (docs/brand/, rules in docs/brand/logo.md) copied to each surface that cannot
reach that folder: the page, the site, the iPhone app. These tests fail when a copy drifts from its source."""
import base64
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "docs" / "brand"
SITE = ROOT / "site" / "pointe" / "brand"
XCASSETS = ROOT / "ios" / "Pointe" / "Assets.xcassets"
CIRCLE = re.compile(r'<circle cx="([\d.]+)" cy="([\d.]+)" r="([\d.]+)" fill="([^"]+)"(?: opacity="[\d.]+")?/>')
SVG = re.compile(r"<svg\b.*?</svg>", re.S)
ORANGE = "#FF5A01"
# The rule (docs/brand/logo.md): many points on every surface, like the app icon. Dots around the orange point per drawing.
FULL, COMPACT, FAVICON = 120, 12 + 18 + 24 + 30, 10 + 16 + 22


def png_header(path: Path) -> tuple[int, int, int]:
    """(width, height, colour type) from the IHDR chunk: 2 is RGB, 6 is RGB with alpha."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR", path
    width, height, _, colour = struct.unpack(">IIBB", data[16:26])
    return width, height, colour


def test_the_site_and_the_app_carry_the_brand_sources_byte_for_byte():
    for name in ("favicon.svg", "logo-small.svg", "logo-small-on-dark.svg", "lockup-small.svg", "lockup-small-on-dark.svg"):
        assert (SITE / name).read_bytes() == (BRAND / name).read_bytes(), name
    mark = ROOT / "apple" / "PointeKit" / "Sources" / "PointeUI" / "Resources" / "Assets.xcassets" / "ChorusMark.imageset"  # one copy, for both apps
    assert (mark / "chorus-mark.svg").read_bytes() == (BRAND / "logo-small.svg").read_bytes()
    assert (mark / "chorus-mark-dark.svg").read_bytes() == (BRAND / "logo-small-on-dark.svg").read_bytes()
    looks = json.loads((mark / "Contents.json").read_text())
    assert looks["properties"]["preserves-vector-representation"] is True
    assert [i.get("appearances", [{}])[0].get("value") for i in looks["images"]] == [None, "dark"]


def test_the_page_header_mark_is_the_compact_drawing_in_the_text_colour_with_the_orange_point():
    page, source = CIRCLE.findall((ROOT / "assets" / "logo.svg").read_text()), CIRCLE.findall((BRAND / "logo-small.svg").read_text())
    assert [c[:3] for c in page] == [c[:3] for c in source], "the same geometry as docs/brand/logo-small.svg"
    assert [c[3] for c in page] == ["currentColor"] * COMPACT + [ORANGE]
    assert 'class="logo"' in (ROOT / "assets" / "logo.svg").read_text() and 'aria-hidden="true"' in (ROOT / "assets" / "logo.svg").read_text()
    assert '<div class="brand">{{LOGO}}<div><div class="name">Pointe</div>' in (ROOT / "ui.html").read_text()


def marks_in(text: str) -> list[int]:
    """For each colour mark (an <svg> with the orange point), how many dots sit around the point."""
    return [len(CIRCLE.findall(svg)) - 1 for svg in SVG.findall(text) if f'fill="{ORANGE}"' in svg]


def test_every_drawing_has_its_count_of_dots():
    for name in ("logo.svg", "logo-on-dark.svg", "logo-mono.svg", "lockup.svg", "lockup-on-dark.svg", "lockup-mono.svg"):
        assert len(CIRCLE.findall((BRAND / name).read_text())) - 1 == FULL, name
    for name in ("logo-small.svg", "logo-small-on-dark.svg", "lockup-small.svg", "lockup-small-on-dark.svg"):
        assert marks_in((BRAND / name).read_text()) == [COMPACT], name
    assert marks_in((BRAND / "favicon.svg").read_text()) == [FAVICON]


def test_no_surface_carries_a_mark_with_few_dots():
    """The six-dot small drawing is gone: every colour mark in the repository, file or inline, has at least the
    favicon's 48 dots. ui.html's inline icon is base64, so it is decoded first."""
    files = [ROOT / f for f in subprocess.run(["git", "ls-files", "*.svg", "*.html", "*.swift"], cwd=ROOT,
                                              capture_output=True, text=True, check=True).stdout.split()]
    files += [ROOT / "assets" / "logo.svg"]
    seen = 0
    for path in files:
        if not path.is_file():
            continue
        text = path.read_text(errors="ignore")
        text += "".join(base64.b64decode(b).decode(errors="ignore")
                        for b in re.findall(r"data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)", text))
        for dots in marks_in(text):
            seen += 1
            assert dots >= FAVICON, f"{path.relative_to(ROOT)}: a mark with {dots} dots"
    assert seen >= 20, "the scan found the marks"


def test_the_page_icons_are_inline_and_the_same_bytes_as_the_site_ones():
    html = (ROOT / "ui.html").read_text()
    for rel, kind, name in (("icon", "svg+xml", "favicon.svg"), ("icon", "png", "favicon-32.png"), ("apple-touch-icon", "png", "apple-touch-icon.png")):
        found = re.findall(rf'<link rel="{rel}"[^>]*href="data:image/{re.escape(kind)};base64,([A-Za-z0-9+/=]+)"', html)
        assert len(found) == 1, name
        assert base64.b64decode(found[0]) == (SITE / name).read_bytes(), name


def test_every_pointe_site_page_has_the_icons_and_the_lockup_in_its_header():
    for page in ("index.html", "roadmap/index.html", "contribute/index.html", "features/index.html"):
        path = ROOT / "site" / "pointe" / page
        html = path.read_text()
        refs = re.findall(r'(?:href|src|srcset)="([^"]*brand/[^"]+)"', html)
        assert {Path(r).name for r in refs} >= {"favicon.svg", "favicon-32.png", "apple-touch-icon.png", "lockup-small.svg",
                                               "lockup-small-on-dark.svg"}, page
        for ref in refs:
            assert (path.parent / ref).resolve().is_file(), f"{page}: {ref}"
        assert re.search(r'<a class="(?:pg-)?wordmark" href="[^"]+"><picture>.*?alt="Pointe"></picture></a>', html), page


def test_the_app_icon_has_light_dark_and_tinted_at_1024_without_alpha():
    icon = XCASSETS / "AppIcon.appiconset"
    images = json.loads((icon / "Contents.json").read_text())["images"]
    assert [i.get("appearances", [{}])[0].get("value") for i in images] == [None, "dark", "tinted"]
    for image in images:
        assert image["size"] == "1024x1024" and image["idiom"] == "universal"
        assert png_header(icon / image["filename"]) == (1024, 1024, 2), image["filename"]  # the App Store refuses alpha


def test_the_link_preview_is_one_image_in_both_places():
    assert png_header(ROOT / "docs" / "social-preview.png")[:2] == (1280, 640)
    assert (ROOT / "docs" / "social-preview.png").read_bytes() == (ROOT / "site" / "pointe" / "social.png").read_bytes()
    source = (ROOT / "docs" / "social-preview.html").read_text()
    assert "Stop typing to one agent." in source and "Built and open-sourced by Ballerine Engineering" in source
    assert "Ballerine" not in source.replace("Built and open-sourced by Ballerine Engineering", ""), "no Ballerine logo"


def test_the_site_drawing_of_the_call_carries_the_compact_mark_and_matches_its_generator():
    """site/pointe/index.html's orchestra figure draws the mark inside the phone from docs/brand/logo-small.svg, with
    the dots coloured by class (so the scan above, which looks for the orange fill, does not see it)."""
    html = (ROOT / "site" / "pointe" / "index.html").read_text()
    assert html.count('class="o-mdot"') == COMPACT and html.count('class="o-mpoint"') == 1
    subprocess.run([sys.executable, str(ROOT / "tools" / "orchestra_viz.py"), "--check"], cwd=ROOT, check=True)
