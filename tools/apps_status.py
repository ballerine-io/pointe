"""Write the app cards on site/pointe/index.html (the Mac download and the iPhone beta), the hero's buttons and the top
nav's Download link, and the community Slack links (in the working group and the footer), from site/pointe/apps.json.

    python3 tools/apps_status.py           rewrite each block between its markers
    python3 tools/apps_status.py --check   exit 1 if the page differs from what this would write

A card links its download when its status is "open", and then only to an https address. While it waits, it shows a link
to be notified, and either its "soon" label or, when the waiting app already has its https link (a TestFlight link exists
before Apple's beta review admits testers), a button that says it opens soon. A missing link is never clicked. Once the Mac
download is open, the hero leads with "Download for Mac" and its line (version, macOS, size: apps.json's mac.version and
mac.size), the nav gets Download, and a visitor on another device sees "Get it on your Mac" instead (a script on the page
swaps them; without it everyone sees the download). Standard library only.
"""

from __future__ import annotations  # macOS's own python3 (3.9) runs this from site/deploy.sh: `str | None` needs it

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site" / "pointe"
DATA = SITE / "apps.json"
PAGE = SITE / "index.html"
BLOCKS = ("apps", "hero-cta", "nav-download", "slack-wg", "slack-footer")
MAC_NEEDS = "macOS 15+"  # the Mac app's MACOSX_DEPLOYMENT_TARGET (apps/macos/tools/make_project.py)


def marks(name: str) -> tuple[str, str]:
    return f"<!-- {name}:begin (tools/apps_status.py writes this from site/pointe/apps.json; edit it there) -->", f"<!-- {name}:end -->"


BEGIN, END = marks("apps")
WAITING = {"mac": ("coming-soon", "Coming soon"), "iphone": ("opening-soon", "Opening soon")}


def state(data: dict, app: str, key: str) -> tuple[bool, str | None]:
    """Whether the app is open, and its link: required and https when open, optional (but https) while it waits."""
    status, url = data[app]["status"], data[app].get(key, "")
    if status not in ("open", WAITING[app][0]):
        raise ValueError(f"apps.json: {app} status must be \"open\" or \"{WAITING[app][0]}\", not {status!r}")
    if url and not url.startswith("https://") or status == "open" and not url:
        raise ValueError(f"apps.json: {app}'s {key} must be an https address{' when it is open' if not url else ''}")
    return status == "open", url or None


def card(app: str, kicker: str, title: str, line: str, opened: bool, url: str | None, label: str, soon_label: str, notify: str,
         meta: str = "") -> str:
    extra = f'<p class="small app-meta">{meta}</p>' if opened and meta else ""
    notify_link = f'<a class="link" href="{html.escape(notify)}">Get notified on GitHub →</a>'
    if opened:
        cta = f'<a class="btn btn--primary" href="{html.escape(url)}">{label}</a>'
    elif url:
        cta = f'<a class="btn" href="{html.escape(url)}">{soon_label}</a>{notify_link}'
    else:
        cta = f'<span class="app-soon">{WAITING[app][1]}</span>{notify_link}'
    return (f'<div class="app-card" data-app="{app}" data-status="{"open" if opened else WAITING[app][0]}">'
            f'<p class="kicker">{kicker}</p><h3 class="h3">{title}</h3><p class="body">{line}</p>'
            f'<p class="app-cta">{cta}</p>{extra}</div>')


def render(data: dict) -> str:
    notify = data["notify_url"]
    return "\n".join([
        card("mac", "Mac", "Download for Mac (.dmg)", "Drag to Applications, open, and Pointe sets itself up.",
             *state(data, "mac", "download_url"), "Download for Mac (.dmg)", "Download for Mac (.dmg) (coming soon)", notify,
             mac_line(data)),
        card("iphone", "iPhone", "iPhone beta on TestFlight", "The same call in your pocket. Pair it with one QR code on the Mac.",
             *state(data, "iphone", "testflight_url"), "Join the iPhone beta", "Join the iPhone beta (opens soon)", notify),
    ])


def mac_line(data: dict) -> str:
    """ "Pointe 0.8.1 · macOS 15+ · 4.3 MB": under the hero's button and on the card, once the Mac download is open."""
    if not state(data, "mac", "download_url")[0]:
        return ""
    mac = data["mac"]
    if not mac.get("version") or not mac.get("size"):
        raise ValueError("apps.json: an open mac needs its version and size, for the line under the button")
    return html.escape(f"Pointe {mac['version']} · {MAC_NEEDS} · {mac['size']}")


def hero(data: dict) -> str:
    """The hero's buttons: with the Mac download open, it leads (Install and the film follow), with its line under them."""
    opened, url = state(data, "mac", "download_url")
    install = '<a class="btn{}" href="#install">Install</a>'.format("" if opened else " btn--primary")
    watch = '<a class="btn" href="#with">Watch it work<span class="btn-meta">&nbsp;· 1&nbsp;min</span></a>'
    if not opened:
        return f'<p class="hero-cta">{install}{watch}</p>'
    line = mac_line(data)
    return (f'<p class="hero-cta"><a class="btn btn--primary" data-mac-only href="{html.escape(url)}">Download for Mac</a>'
            f'<a class="btn btn--primary" data-not-mac hidden href="#install">Get it on your Mac</a>{install}{watch}</p>\n'
            f'<p class="small hero-dl" data-mac-only>{line}</p>')


def nav(data: dict) -> str:
    opened, url = state(data, "mac", "download_url")
    return f'<a href="{html.escape(url)}" data-mac-only>Download</a><a href="#install" data-not-mac hidden>Download</a>' if opened else ""


def slack(data: dict, where: str) -> str:
    """The community invite: a link in the working group, one line in the footer; nothing when slack_url is empty."""
    url = data.get("slack_url", "")
    if not url:
        return ""
    if not url.startswith("https://"):
        raise ValueError("apps.json: slack_url must be an https address")
    url = html.escape(url)
    if where == "slack-wg":
        return f'<a class="link" href="{url}">Join the community on Slack →</a>'
    return f'<p class="small">Questions, ideas, what broke: <a href="{url}">join the community on Slack</a>.</p>'


def page(text: str, data: dict) -> str:
    for name in BLOCKS:
        begin, end = marks(name)
        head, rest = text.split(begin, 1)
        _, tail = rest.split(end, 1)
        indent = head[head.rindex("\n") + 1:]
        body = {"apps": render, "hero-cta": hero, "nav-download": nav}.get(name, lambda d: slack(d, name))(data)
        lines = "".join(f"{indent}{line}\n" for line in body.split("\n") if line)
        text = f"{head}{begin}\n{lines}{indent}{end}{tail}"
    return text


def main(argv: list[str]) -> int:
    data = json.loads(DATA.read_text())
    text = PAGE.read_text()
    want = page(text, data)
    if "--check" in argv:
        if want != text:
            print("site/pointe/index.html: the app cards differ from site/pointe/apps.json; run python3 tools/apps_status.py")
            return 1
        return 0
    PAGE.write_text(want)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
