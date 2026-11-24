"""Writes the menu bar images and the accent colour:
    python3 apps/macos/tools/make_menu_icons.py docs/brand apps/macos/PointeMac/Assets.xcassets

The menu bar item is 18 points high, so it is the favicon drawing (docs/brand/logo.md: three rings, 48 dots and the
point, for 16 to 32 px), unchanged, in one ink and without the favicon's squircle: a template image takes the menu
bar's colour, the one-ink use the brand rules allow. MenuOff is the same drawing at 45%, for "no call"; everything else
about the state is said beside it (a count, a microphone), never by redrawing the mark.
"""

import json
import re
import sys
from pathlib import Path

CIRCLE = re.compile(r'<circle cx="([\d.]+)" cy="([\d.]+)" r="([\d.]+)" fill="[^"]+"/>')


def template(source: str, alpha: float) -> str:
    dots = "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#000" fill-opacity="{alpha}"/>' for x, y, r in CIRCLE.findall(source))
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 100 100">{dots}</svg>\n'


def main(brand: Path, catalog: Path) -> None:
    info = {"author": "xcode", "version": 1}
    source = (brand / "favicon.svg").read_text()
    assert len(CIRCLE.findall(source)) == 49, "favicon.svg: 48 dots and the point"
    (catalog / "Contents.json").write_text(json.dumps({"info": info}, indent=2) + "\n")
    for name, alpha in {"MenuOff": 0.45, "MenuLive": 1}.items():
        folder = catalog / f"{name}.imageset"
        folder.mkdir(exist_ok=True)
        (folder / f"{name}.svg").write_text(template(source, alpha))
        (folder / "Contents.json").write_text(json.dumps({
            "images": [{"idiom": "mac", "filename": f"{name}.svg"}], "info": info,
            "properties": {"preserves-vector-representation": True, "template-rendering-intent": "template"}}, indent=2, sort_keys=True) + "\n")
    # The brand's accent (assets/theme.json, "accent"): light #C24F0D, dark #FF8C4A.
    accent = catalog / "AccentColor.colorset"
    accent.mkdir(exist_ok=True)

    def colour(r: str, g: str, b: str) -> dict:
        return {"color-space": "srgb", "components": {"red": r, "green": g, "blue": b, "alpha": "1.000"}}

    (accent / "Contents.json").write_text(json.dumps({"colors": [
        {"idiom": "universal", "color": colour("0xC2", "0x4F", "0x0D")},
        {"idiom": "universal", "appearances": [{"appearance": "luminosity", "value": "dark"}], "color": colour("0xFF", "0x8C", "0x4A")},
    ], "info": info}, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
