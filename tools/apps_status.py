"""Write the app cards on site/pointe/index.html (the Mac download and the iPhone beta), and the community Slack links
(in the working group and the footer), from site/pointe/apps.json.

    python3 tools/apps_status.py           rewrite each block between its markers
    python3 tools/apps_status.py --check   exit 1 if the page differs from what this would write

A card links its download when its status is "open", and then only to an https address. While it waits, it shows a link
to be notified, and either its "soon" label or, when the waiting app already has its https link (a TestFlight link exists
before Apple's beta review admits testers), a button that says it opens soon. A missing link is never clicked. Standard
library only.
"""

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site" / "pointe"
DATA = SITE / "apps.json"
PAGE = SITE / "index.html"
BLOCKS = ("apps", "slack-wg", "slack-footer")


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


def card(app: str, kicker: str, title: str, line: str, opened: bool, url: str | None, label: str, soon_label: str, notify: str) -> str:
    notify_link = f'<a class="link" href="{html.escape(notify)}">Get notified on GitHub →</a>'
    if opened:
        cta = f'<a class="btn btn--primary" href="{html.escape(url)}">{label}</a>'
    elif url:
        cta = f'<a class="btn" href="{html.escape(url)}">{soon_label}</a>{notify_link}'
    else:
        cta = f'<span class="app-soon">{WAITING[app][1]}</span>{notify_link}'
    return (f'<div class="app-card" data-app="{app}" data-status="{"open" if opened else WAITING[app][0]}">'
            f'<p class="kicker">{kicker}</p><h3 class="h3">{title}</h3><p class="body">{line}</p>'
            f'<p class="app-cta">{cta}</p></div>')


def render(data: dict) -> str:
    notify = data["notify_url"]
    return "\n".join([
        card("mac", "Mac", "Download for Mac (.dmg)", "Drag to Applications, open, and Pointe sets itself up.",
             *state(data, "mac", "download_url"), "Download for Mac (.dmg)", "Download for Mac (.dmg) (coming soon)", notify),
        card("iphone", "iPhone", "iPhone beta on TestFlight", "The same call in your pocket. Pair it with one QR code on the Mac.",
             *state(data, "iphone", "testflight_url"), "Join the iPhone beta", "Join the iPhone beta (opens soon)", notify),
    ])


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
        body = render(data) if name == "apps" else slack(data, name)
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
