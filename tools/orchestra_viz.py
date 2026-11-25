#!/usr/bin/env python3
"""Draw the "orchestra" illustration on Pointe's site: one voice on the hub Mac, sessions of several coding agents on
several machines, and what travels between them (docs/multi-machine.md, docs/harnesses.md).

It writes the figure between the two `orchestra` comment marks in site/pointe/index.html: one drawing for a wide screen
and one for a narrow one, from the same machines and sessions. site/pointe/viz/viz.css styles it and viz.js plays it.
The rings of dots are the Chorus logo's own (docs/brand/logo.svg), read from that file. The drawing as written here is
the still: what shows with no script, and with reduced motion.

    python3 tools/orchestra_viz.py          rewrite the figure in site/pointe/index.html
    python3 tools/orchestra_viz.py --check  fail if the page's figure differs from what this draws
"""
import json
import math
import re
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "site" / "pointe" / "index.html"
BEGIN, END = "<!-- orchestra:begin (tools/orchestra_viz.py draws this; edit it there) -->", "<!-- orchestra:end -->"
HARNESSES = json.loads((ROOT / "assets" / "theme.json").read_text())["harnesses"]

# Invented names. A session's state is one of the page's own tags: working, idle, approve.
MACHINES = [
    {"name": "studio", "os": "this Mac", "rtt": "", "sessions": [("shop", "claude-code", "working"), ("docs", "opencode", "idle"),
                                                                ("river-lantern", "codex", "idle")]},
    {"name": "devbox", "os": "Linux", "rtt": "23 ms", "sessions": [("billing", "codex", "working"), ("ingest", "claude-code", "working")]},
    {"name": "laptop", "os": "macOS", "rtt": "41 ms", "sessions": [("notes", "opencode", "approve"), ("api", "claude-code", "idle")]},
]
STATES = {"idle": "idle", "working": "working", "approve": "approve"}
SAID = ("You", "Ask billing on devbox to run the tests.")
ASK = ("notes · laptop", "needs approval", "npm test")


def n(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".")


def route(points, r=12) -> str:
    """A path through the points with each corner rounded."""
    d = [f"M{n(points[0][0])} {n(points[0][1])}"]
    for i in range(1, len(points) - 1):
        (ax, ay), (bx, by), (cx, cy) = points[i - 1], points[i], points[i + 1]
        la, lc = math.hypot(ax - bx, ay - by), math.hypot(cx - bx, cy - by)
        k = min(r, la / 2, lc / 2)
        d.append(f"L{n(bx + (ax - bx) / la * k)} {n(by + (ay - by) / la * k)}")
        d.append(f"Q{n(bx)} {n(by)} {n(bx + (cx - bx) / lc * k)} {n(by + (cy - by) / lc * k)}")
    d.append(f"L{n(points[-1][0])} {n(points[-1][1])}")
    return "".join(d)


def rings(cx, cy, scale):
    """The logo's five rings of dots and its point, around (cx, cy)."""
    dots = re.findall(r'cx="([\d.]+)" cy="([\d.]+)" r="([\d.]+)" fill="(#\w+)"', (ROOT / "docs" / "brand" / "logo.svg").read_text())
    by_r = {}
    for x, y, r, fill in dots:
        if fill.upper() != "#FF5A01":
            by_r.setdefault(float(r), []).append((float(x) - 50, float(y) - 50))
    out = [f'<g class="o-rings" style="transform-origin:{n(cx)}px {n(cy)}px">']
    for i, r in enumerate(sorted(by_r, reverse=True)):
        circles = "".join(f'<circle cx="{n(cx + x * scale)}" cy="{n(cy + y * scale)}" r="{n(r * scale)}"/>' for x, y in by_r[r])
        out.append(f'<g class="o-ring" data-ring="{i}">{circles}</g>')
    out.append("</g>")
    out.append(f'<circle class="o-halo" cx="{n(cx)}" cy="{n(cy)}" r="{n(4.8 * scale)}" style="transform-origin:{n(cx)}px {n(cy)}px"/>')
    out.append(f'<circle class="o-point" cx="{n(cx)}" cy="{n(cy)}" r="{n(4.8 * scale)}" style="transform-origin:{n(cx)}px {n(cy)}px"/>')
    return "".join(out)


def row(x, y, w, h, session, agent_x, last):
    name, harness, state = session
    mid = y + h / 2
    mark = HARNESSES[harness]
    out = [f'<g class="o-row" data-s="{name}" data-state="{state}">',
           f'<rect class="o-row-hot" x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}"/>',
           f'<rect class="o-row-bar" x="{n(x)}" y="{n(y)}" width="2" height="{n(h)}"/>']
    for s in STATES:
        out.append(f'<circle class="o-st o-is-{s}" cx="{n(x + 15)}" cy="{n(mid)}" r="3"/>')
    out.append(f'<text class="o-nm" x="{n(x + 28)}" y="{n(mid + 4.6)}">{escape(name)}</text>')
    out.append(f'<text class="o-ag" x="{n(x + agent_x)}" y="{n(mid + 4.2)}">{escape(mark["name"])}</text>')
    for s, word in STATES.items():
        out.append(f'<text class="o-tag o-is-{s}" x="{n(x + w - 14)}" y="{n(mid + 4.2)}" text-anchor="end">{word}</text>')
    if not last:
        out.append(f'<path class="o-hair" d="M{n(x + 12)} {n(y + h)}H{n(x + w - 12)}"/>')
    out.append("</g>")
    return "".join(out)


def header(x, y, w, machine, right=""):
    name = machine["name"]
    out = [f'<circle class="o-live" cx="{n(x + 15)}" cy="{n(y + 18)}" r="3"/>',
           f'<text class="o-mn" x="{n(x + 27)}" y="{n(y + 22.4)}">{name}</text>',
           f'<text class="o-os" x="{n(x + 27 + len(name) * 7.3 + 8)}" y="{n(y + 22)}">{machine["os"]}</text>']
    if right or machine["rtt"]:
        out.append(f'<text class="o-os o-num" x="{n(x + w - 14)}" y="{n(y + 22)}" text-anchor="end">{right or machine["rtt"]}</text>')
    return "".join(out)


def machine(x, y, w, m, row_h, agent_x, clip, hub=None):
    """A machine: a card with its header and its sessions, the rows clipped to the card's corners. The hub's card is
    taller: `hub` is (height, where its sessions start, the words at the right of its header). Returns (svg, height)."""
    top = 36 if not hub else hub[1] - y
    h = top + row_h * len(m["sessions"]) + 4 if not hub else hub[0]
    rx = 16 if hub else 12
    box = f'x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" rx="{rx}"'
    out = [f'<g class="o-mach" data-m="{m["name"]}">', f'<clipPath id="{clip}-{m["name"]}"><rect {box}/></clipPath>',
           f'<rect class="{"o-hub" if hub else "o-card"}" {box}/>', f'<g clip-path="url(#{clip}-{m["name"]})">']
    for i, s in enumerate(m["sessions"]):
        out.append(row(x, y + top + i * row_h, w, row_h, s, agent_x, i == len(m["sessions"]) - 1))
    out.append("</g>" + header(x, y, w, m, hub[2] if hub else "") + f'<path class="o-hair" d="M{n(x)} {n(y + top)}H{n(x + w)}"/>'
               f'<rect class="o-lit" {box}/></g>')
    return "".join(out), h


def link(name, points, start=0.0):
    """A wire you can see (from `start` along the first leg), its lit copy, and the whole route the dots follow."""
    (ax, ay), (bx, by) = points[0], points[1]
    leg = math.hypot(bx - ax, by - ay)
    seen = [(ax + (bx - ax) / leg * start, ay + (by - ay) / leg * start)] + points[1:]
    return (f'<path class="o-wire" d="{route(seen)}"/><path class="o-wire-hot" data-wire="{name}" d="{route(seen)}"/>'
            f'<path class="o-route" data-route="{name}" d="{route(points)}"/>')


def port(x, y):
    return f'<circle class="o-port" cx="{n(x)}" cy="{n(y)}" r="3"/>'


def trail(points):
    """Still dots along a straight run, largest at the front: a wave caught on its way."""
    (ax, ay), (bx, by) = points
    sizes = [4, 3.5, 3, 2.6, 2.2, 1.9]
    return "".join(f'<circle class="o-dot" cx="{n(bx + (ax - bx) * i / 6.2)}" cy="{n(by + (ay - by) * i / 6.2)}" r="{r}" opacity="{n(1 - i * .13)}"/>'
                   for i, r in enumerate(sizes))


def notification(x, y, w, compact=False):
    who, what, cmd = ASK
    if compact:  # one row: the words on the left, the two buttons on the right
        bw, bh, by = 52, 26, y + 5
        return (f'<g class="o-notif"><rect class="o-ncard" x="{n(x)}" y="{n(y)}" width="{n(w)}" height="36" rx="10"/>'
                f'<text class="o-nwho" x="{n(x + 11)}" y="{n(y + 15.5)}">{who}</text>'
                f'<text class="o-nwhat" x="{n(x + 11)}" y="{n(y + 28.5)}">{what} <tspan class="o-ncmd">{cmd}</tspan></text>'
                f'<rect class="o-deny" x="{n(x + w - 2 * bw - 10)}" y="{n(by)}" width="{bw}" height="{bh}" rx="8"/>'
                f'<text class="o-btn-t" x="{n(x + w - 1.5 * bw - 10)}" y="{n(by + 17)}" text-anchor="middle">Deny</text>'
                f'<g class="o-approve" style="transform-origin:{n(x + w - bw / 2 - 5)}px {n(by + bh / 2)}px">'
                f'<rect x="{n(x + w - bw - 5)}" y="{n(by)}" width="{bw}" height="{bh}" rx="8"/>'
                f'<text class="o-btn-t" x="{n(x + w - bw / 2 - 5)}" y="{n(by + 17)}" text-anchor="middle">Approve</text></g></g>')
    bw = (w - 22) / 2
    by = y + 62
    return (f'<g class="o-notif"><rect class="o-ncard" x="{n(x)}" y="{n(y)}" width="{n(w)}" height="94" rx="10"/>'
            f'<text class="o-nwho" x="{n(x + 9)}" y="{n(y + 18)}">{who}</text>'
            f'<text class="o-nwhat" x="{n(x + 9)}" y="{n(y + 33)}">{what}</text>'
            f'<text class="o-ncmd" x="{n(x + 9)}" y="{n(y + 50)}">{cmd}</text>'
            f'<rect class="o-deny" x="{n(x + 8)}" y="{n(by)}" width="{n(bw)}" height="24" rx="7"/>'
            f'<text class="o-btn-t" x="{n(x + 8 + bw / 2)}" y="{n(by + 16)}" text-anchor="middle">Deny</text>'
            f'<g class="o-approve" style="transform-origin:{n(x + w - 8 - bw / 2)}px {n(by + 12)}px">'
            f'<rect x="{n(x + w - 8 - bw)}" y="{n(by)}" width="{n(bw)}" height="24" rx="7"/>'
            f'<text class="o-btn-t" x="{n(x + w - 8 - bw / 2)}" y="{n(by + 16)}" text-anchor="middle">Approve</text></g></g>')


def small_mark(cx, cy, s):
    """The logo's compact drawing (docs/brand/logo-small.svg): four rings of dots, fading outward, and the point."""
    dots = re.findall(r'cx="([\d.]+)" cy="([\d.]+)" r="([\d.]+)" fill="(#\w+)"(?: opacity="([\d.]+)")?',
                      (ROOT / "docs" / "brand" / "logo-small.svg").read_text())
    return "".join(f'<circle class="{"o-mpoint" if f.upper() == "#FF5A01" else "o-mdot"}" cx="{n(cx + (float(x) - 50) * s)}" '
                   f'cy="{n(cy + (float(y) - 50) * s)}" r="{n(float(r) * s)}"{f' opacity="{o}"' if o else ""}/>'
                   for x, y, r, f, o in dots)


def wide():
    W, H, cx, cy = 1176, 496, 444, 240
    hub_x, hub_w, node_x, node_w, elbow = 224, 440, 808, 366, 736
    out = [f'<svg class="o-svg o-wide" viewBox="0 0 {W} {H}" aria-hidden="true" focusable="false">']
    list_y = cy + 114
    out.append(machine(hub_x, 1, hub_w, MACHINES[0], 44, 176, "w", (H - 2, list_y, "the hub: holds the call"))[0])
    nodes, y = [], 0
    hs = [36 + 44 * len(m["sessions"]) + 4 for m in MACHINES[1:]]
    tops = [cy - 26 - hs[0], cy + 26]
    mids = [tops[0] + hs[0] / 2, tops[1] + hs[1] / 2]
    for m, top in zip(MACHINES[1:], tops):
        nodes.append(machine(node_x, top, node_w, m, 44, 176, "w")[0])
    # the phone
    px, pw, ph = 6, 132, 252
    py = cy - ph / 2
    out.append(f'<text class="o-os" x="{n(px + pw / 2)}" y="{n(py - 14)}" text-anchor="middle">iPhone app</text>')
    # wires under the cards' edges
    out.append(link("phone", [(cx, cy), (px + pw, cy)], 104))
    out.append(link("devbox", [(cx, cy), (elbow, cy), (elbow, mids[0]), (node_x, mids[0])], 104))
    out.append(link("laptop", [(cx, cy), (elbow, cy), (elbow, mids[1]), (node_x, mids[1])], 104))
    out.append(link("studio", [(cx, cy), (cx, list_y)], 104))
    out.extend(nodes)
    out.append(f'<g class="o-phone"><rect class="o-phone-body" x="{px}" y="{n(py)}" width="{pw}" height="{ph}" rx="24"/>'
               f'<rect class="o-island" x="{n(px + pw / 2 - 17)}" y="{n(py + 10)}" width="34" height="8" rx="4"/>'
               + small_mark(px + pw / 2, py + 62, .3) +
               f'<text class="o-ph-t" x="{n(px + pw / 2)}" y="{n(py + 102)}" text-anchor="middle">On the call</text>'
               f'<text class="o-ph-s" x="{n(px + pw / 2)}" y="{n(py + 118)}" text-anchor="middle">7 sessions · 3 machines</text>'
               + notification(px + 9, py + 144, pw - 18) + "</g>")
    out.append(port(px + pw, cy) + port(node_x, mids[0]) + port(node_x, mids[1]) + port(hub_x + hub_w, cy) + port(hub_x, cy) + port(cx, list_y))
    out.append(rings(cx, cy, 2.1))
    out.append('<g class="o-still">' + trail([(cx + 112, cy), (hub_x + hub_w - 14, cy)])
               + f'<text class="o-note" x="{n(cx + 104)}" y="{n(cy - 12)}">to billing, by name</text>'
               + trail([(cx - 112, cy), (hub_x + 14, cy)])
               + f'<text class="o-note" x="{n(cx - 104)}" y="{n(cy - 12)}" text-anchor="end">to your phone</text></g>')
    out.append('<g class="o-trains"></g></svg>')
    return "".join(out), (hub_x / W, hub_w / W, 46 / H)


def tall():
    W, cx, cy = 358, 179, 262
    gx, gw = 20, 318  # the cards; the wires run in the margins beside them
    out = []
    # the phone, as its notification row
    out.append(f'<g class="o-phone"><rect class="o-card" x="{gx}" y="1" width="{gw}" height="62" rx="12"/>'
               f'<rect class="o-phone-body" x="{gx + 14}" y="14" width="20" height="36" rx="5"/>'
               f'<rect class="o-island" x="{gx + 20}" y="18" width="8" height="2.5" rx="1.25"/>'
               f'<text class="o-mn" x="{gx + 46}" y="28">iPhone app</text>'
               f'<text class="o-ph-s" x="{gx + 46}" y="45">On the call · 7 sessions · 3 machines</text>'
               + notification(gx + 42, 13, gw - 50, compact=True) + "</g>")
    hub_y = 80
    list_y = cy + 82
    hub_h = list_y - hub_y + 3 * 38 + 6
    out.append(machine(gx, hub_y, gw, MACHINES[0], 38, 158, "t", (hub_h, list_y, "the hub"))[0])
    y = hub_y + hub_h + 14
    nodes, mids = [], []
    for m in MACHINES[1:]:
        svg, h = machine(gx, y, gw, m, 38, 158, "t")
        nodes.append(svg)
        mids.append(y + h / 2)
        y += h + 12
    H = y - 12 + 1
    out.append(link("phone", [(cx, cy), (W - 8, cy), (W - 8, 32), (gx + gw, 32)], 78))
    out.append(link("devbox", [(cx, cy), (8, cy), (8, mids[0]), (gx, mids[0])], 78))
    out.append(link("laptop", [(cx, cy), (8, cy), (8, mids[1]), (gx, mids[1])], 78))
    out.append(link("studio", [(cx, cy), (cx, list_y)], 70))
    out.extend(nodes)
    out.append(port(gx + gw, 32) + port(gx, mids[0]) + port(gx, mids[1]) + port(gx, cy) + port(gx + gw, cy) + port(cx, list_y))
    out.append(rings(cx, cy, 1.5))
    out.append('<g class="o-still">' + trail([(cx - 82, cy), (gx + 8, cy)])
               + f'<text class="o-note" x="{n(cx - 78)}" y="{n(cy - 10)}" text-anchor="end">to billing</text>'
               + trail([(cx + 82, cy), (gx + gw - 8, cy)])
               + f'<text class="o-note" x="{n(cx + 78)}" y="{n(cy - 10)}">to your phone</text></g>')
    out.append('<g class="o-trains"></g></svg>')
    return f'<svg class="o-svg o-tall" viewBox="0 0 {W} {n(H)}" aria-hidden="true" focusable="false">' + "".join(out), ((gx) / W, gw / W, (hub_y + 40) / H)


DESCRIPTION = (
    "A diagram of Pointe across three machines. In the middle is the hub, a Mac named studio, which holds the call: an orange "
    "point, your voice, with rings of dots around it. The hub runs three sessions: shop on Claude Code, docs on OpenCode and "
    "river-lantern on Codex. Two other machines are joined to it as nodes: devbox, a Linux host, runs billing on Codex and "
    "ingest on Claude Code; laptop, another Mac, runs notes on OpenCode and api on Claude Code. An iPhone is joined to the "
    "same hub. Three things happen in turn. One: you say “Ask billing on devbox to run the tests”, a wave of dots goes from "
    "the point to devbox, billing starts working, and its report comes back and is spoken. Two: notes on laptop needs "
    "approval; the request travels to the hub, is read out, and shows on the phone with Deny and Approve; a tap on Approve "
    "travels back to laptop. Three: you ask “What's going on everywhere?” and Pointe answers machine by machine."
)
SCENES = [
    ("Send by name", "Say a session's name, and the machine's when two share it. Pointe sends your words there and speaks the report when it ends."),
    ("Approve from anywhere", "A permission prompt on any machine comes to the hub. It is read out, and shown on the page and the phone: say yes, or tap."),
    ("Ask about all of them", "“What's going on everywhere?” is answered machine by machine, from the record Pointe keeps of each session."),
]


def figure() -> str:
    w_svg, (wl, ww, wt) = wide()
    t_svg, (tl, tw, tt) = tall()
    pct = lambda v: n(v * 100) + "%"
    who, line = SAID
    tabs = "".join(f'<li data-scene="{i}"><b>{escape(t)}</b><span>{escape(d)}</span></li>' for i, (t, d) in enumerate(SCENES))
    return (f'{BEGIN}\n'
            f'<figure class="orch" data-orch data-phone="ask" aria-labelledby="orch-desc">\n'
            f'<p id="orch-desc" class="o-vh">{escape(DESCRIPTION)}</p>\n'
            f'<div class="o-stage" style="--wl:{pct(wl)};--ww:{pct(ww)};--wt:{pct(wt)};--tl:{pct(tl)};--tw:{pct(tw)};--tt:{pct(tt)}">\n'
            f'<p class="o-say" aria-hidden="true"><span class="o-who">{who}</span><span class="o-line">{escape(line)}</span></p>\n'
            f'{w_svg}\n{t_svg}\n</div>\n'
            f'<figcaption><ol class="o-tabs">{tabs}</ol>\n'
            f'<p class="small o-foot"><span>A drawing of how the parts connect, not a recording. The names are invented. '
            f'A node has no microphone, no models and no keys.</span></p></figcaption>\n'
            f'</figure>\n{END}')


def main() -> int:
    page = PAGE.read_text()
    a, b = page.index(BEGIN), page.index(END) + len(END)
    drawn = page[:a] + figure() + page[b:]
    if "--check" in sys.argv:
        if drawn != page:
            print("site/pointe/index.html: the orchestra figure is stale; run python3 tools/orchestra_viz.py", file=sys.stderr)
            return 1
        return 0
    PAGE.write_text(drawn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
