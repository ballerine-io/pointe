"""Write the working group's logo row on site/pointe/index.html from site/pointe/working-group.json.

    python3 tools/working_group.py           rewrite the row between the markers
    python3 tools/working_group.py --check   exit 1 if the page differs from what this would write

Only a team with "consent": true is shown, and the row only once a team other than the maintainer is in it (the
maintainer is credited elsewhere on the page). Six or more scroll in an endless loop (the list twice, the copy hidden from
assistive technology and from the tab order); fewer sit still in one centered row. The logos are masks filled with the
page's own colour, so every logo is monochrome in light and dark. Standard library only.
"""

import html
import json
import math
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site" / "pointe"
DATA = SITE / "working-group.json"
PAGE = SITE / "index.html"
BEGIN = "<!-- working-group:begin (tools/working_group.py writes this from site/pointe/working-group.json; edit it there) -->"
END = "<!-- working-group:end -->"
SCROLL_FROM = 6  # fewer than this: a static row; an endless loop of one to five logos repeats them on screen
# Equal visual weight: every logo gets the same area, so a long wordmark is lower and a square mark smaller than its
# cell, within the cell's height and width.
AREA, MAX_H, MAX_W = 1400, 28, 72


def aspect(path: Path) -> float:
    """Width over height, from an SVG's viewBox or a PNG's header."""
    if path.suffix == ".svg":
        box = re.search(r'viewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)', path.read_text())
        if box:
            return float(box[1]) / float(box[2])
    elif path.suffix == ".png":
        w, h = struct.unpack(">II", path.read_bytes()[16:24])
        return w / h
    raise ValueError(f"{path.name}: a logo is an SVG with a viewBox, or a PNG")


def size(ratio: float) -> tuple[int, int]:
    h = min(MAX_H, math.sqrt(AREA / ratio), MAX_W / ratio)
    return round(h * ratio), round(h)


def teams(data: dict, base: Path) -> list[dict]:
    """The teams that may be shown, each checked: a name, and a logo file under img/logos/."""
    shown = []
    for t in data["teams"]:
        if t.get("consent") is not True:
            continue
        name, logo = t["name"].strip(), t["logo"]
        if not name:
            raise ValueError("a team without a name")
        if not logo.startswith("img/logos/") or ".." in logo or not (base / logo).is_file():
            raise ValueError(f"{name}: the logo must be a file under img/logos/, not {logo!r}")
        shown.append({"name": name, "logo": logo, "url": t.get("url"), "size": size(aspect(base / logo)),
                      "maintainer": t.get("maintainer") is True})
    return shown


def item(t: dict, copy: bool) -> str:
    w, h = t["size"]
    logo = (f'<span class="wg-logo" role="img" aria-label="{html.escape(t["name"])}" '
            f'style="--logo: url({html.escape(t["logo"])}); width: {w}px; height: {h}px"></span>')
    if t["url"]:
        tab = ' tabindex="-1"' if copy else ""
        logo = f'<a href="{html.escape(t["url"])}"{tab}>{logo}</a>'
    return f"<li>{logo}</li>"


def render(data: dict, base: Path) -> str:
    shown = teams(data, base)
    if all(t["maintainer"] for t in shown):
        return ""
    one = "".join(item(t, False) for t in shown)
    if len(shown) < SCROLL_FROM:
        lists = f'<ul class="wg-list">{one}</ul>'
        kind = "wg-static"
        wrap = "wg-logos wg-logos--static"
    else:
        copy = "".join(item(t, True) for t in shown)
        lists = f'<ul class="wg-list">{one}</ul><ul class="wg-list" aria-hidden="true">{copy}</ul>'
        kind = "wg-marquee"
        wrap = "wg-logos"
    return (f'<div class="{wrap}">\n'
            f'        <p class="small wg-label" id="wg-label">Built with engineers from:</p>\n'
            f'        <div class="wg-viewport {kind}" style="--n: {len(shown)}" role="group" aria-labelledby="wg-label">'
            f'<div class="wg-track">{lists}</div></div>\n'
            f'      </div>')


def page(text: str, data: dict, base: Path) -> str:
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    row = render(data, base)
    return f"{head}{BEGIN}\n      {row + chr(10) + '      ' if row else ''}{END}{tail}"


def main(argv: list[str]) -> int:
    want = page(PAGE.read_text(), json.loads(DATA.read_text()), SITE)
    if "--check" in argv:
        if PAGE.read_text() != want:
            print("site/pointe/index.html: run python3 tools/working_group.py", file=sys.stderr)
            return 1
        return 0
    PAGE.write_text(want)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
