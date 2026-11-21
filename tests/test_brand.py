"""The Chorus mark is one set of files (docs/brand/, rules in docs/brand/logo.md) copied to each surface that cannot
reach that folder: the page, the site, the iPhone app. These tests fail when a copy drifts from its source."""
import base64
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "docs" / "brand"
SITE = ROOT / "site" / "pointe" / "brand"
XCASSETS = ROOT / "ios" / "Pointe" / "Assets.xcassets"
CIRCLE = re.compile(r'<circle cx="([\d.]+)" cy="([\d.]+)" r="([\d.]+)" fill="([^"]+)"/>')


def png_header(path: Path) -> tuple[int, int, int]:
    """(width, height, colour type) from the IHDR chunk: 2 is RGB, 6 is RGB with alpha."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR", path
    width, height, _, colour = struct.unpack(">IIBB", data[16:26])
    return width, height, colour


def test_the_site_and_the_app_carry_the_brand_sources_byte_for_byte():
    for name in ("favicon.svg", "logo-small.svg", "logo-small-on-dark.svg", "lockup-small.svg", "lockup-small-on-dark.svg"):
        assert (SITE / name).read_bytes() == (BRAND / name).read_bytes(), name
    mark = XCASSETS / "ChorusMark.imageset"
    assert (mark / "chorus-mark.svg").read_bytes() == (BRAND / "logo-small.svg").read_bytes()
    assert (mark / "chorus-mark-dark.svg").read_bytes() == (BRAND / "logo-small-on-dark.svg").read_bytes()
    looks = json.loads((mark / "Contents.json").read_text())
    assert looks["properties"]["preserves-vector-representation"] is True
    assert [i.get("appearances", [{}])[0].get("value") for i in looks["images"]] == [None, "dark"]


def test_the_page_header_mark_is_the_small_drawing_in_the_text_colour_with_the_orange_point():
    page, source = CIRCLE.findall((ROOT / "assets" / "logo.svg").read_text()), CIRCLE.findall((BRAND / "logo-small.svg").read_text())
    assert [c[:3] for c in page] == [c[:3] for c in source], "the same geometry as docs/brand/logo-small.svg"
    assert [c[3] for c in page] == ["currentColor"] * 6 + ["#FF5A01"]
    assert 'class="logo"' in (ROOT / "assets" / "logo.svg").read_text() and 'aria-hidden="true"' in (ROOT / "assets" / "logo.svg").read_text()
    assert '<div class="brand">{{LOGO}}<div><div class="name">Pointe</div>' in (ROOT / "ui.html").read_text()


def test_the_page_icons_are_inline_and_the_same_bytes_as_the_site_ones():
    html = (ROOT / "ui.html").read_text()
    for rel, kind, name in (("icon", "svg+xml", "favicon.svg"), ("icon", "png", "favicon-32.png"), ("apple-touch-icon", "png", "apple-touch-icon.png")):
        found = re.findall(rf'<link rel="{rel}"[^>]*href="data:image/{re.escape(kind)};base64,([A-Za-z0-9+/=]+)"', html)
        assert len(found) == 1, name
        assert base64.b64decode(found[0]) == (SITE / name).read_bytes(), name


def test_every_pointe_site_page_has_the_icons_and_the_lockup_in_its_header():
    for page in ("index.html", "roadmap/index.html", "contribute/index.html"):
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
