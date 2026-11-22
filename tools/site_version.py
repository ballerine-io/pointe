"""Write the plugin's version into the site: every `<span data-version>…</span>` in site/**/*.html gets the version in
.claude-plugin/plugin.json. site/deploy.sh runs this before a deploy, and tests/test_site.py fails while a page is
stale, so the site cannot show an old version.

    python3 tools/site_version.py           write
    python3 tools/site_version.py --check   exit 1 and name the pages that are stale
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPAN = re.compile(r"(<span data-version>)([^<]*)(</span>)")


def version() -> str:
    return json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]


def pages() -> list[Path]:
    return sorted((ROOT / "site").rglob("*.html"))


def stale() -> list[Path]:
    return [p for p in pages() if any(m.group(2) != version() for m in SPAN.finditer(p.read_text()))]


def write() -> list[Path]:
    changed = stale()
    for page in changed:
        page.write_text(SPAN.sub(lambda m: m.group(1) + version() + m.group(3), page.read_text()))
    return changed


if __name__ == "__main__":
    if "--check" in sys.argv:
        old = stale()
        for page in old:
            print(f"{page.relative_to(ROOT)}: not at {version()}; run python3 tools/site_version.py")
        sys.exit(1 if old else 0)
    for page in write():
        print(f"{page.relative_to(ROOT)}: {version()}")
