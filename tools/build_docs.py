"""Write the documentation pages of the site, site/pointe/docs/, from the Markdown in docs/ (and three root files).

    uv run --locked python tools/build_docs.py           write them
    uv run --locked python tools/build_docs.py --check   exit 1 if any page is not what this would write, or is extra
                                                          (tests/test_docs_site.py runs it)

The Markdown stays the source: GitHub shows the same files. The conversion uses Python-Markdown (`markdown`), which
is already locked as a dependency of pipecat-ai (docs/security/dependencies-allowlist.txt), so nothing new is
installed; that is why it runs under `uv run --locked` and not the bare python3 of the other site tools. Where
Python-Markdown and GitHub differ on what these docs use, the text is adjusted before conversion: fenced code is
taken out first (so it may sit inside a list item), a list that starts right under a paragraph gets the blank line
GitHub does not need, and lists nest at two spaces. Heading anchors follow GitHub's rules, so a link to
`phone.md#pairing` lands where it does on GitHub. Links to a rendered page become the page's address on the site;
links to any other file in the repository go to it on GitHub. Hebrew voice phrases quoted in the docs are marked
`lang="he"`, the only Hebrew the site may hold (tests/test_site.py). The output has no date in it: the same docs
write the same pages.
"""

import html
import posixpath
import re
import shutil
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site" / "pointe"
OUT = SITE / "docs"
GITHUB = "https://github.com/ballerine-io/pointe"
ORIGIN = "https://eng.ballerine.com/pointe/"

def _features() -> list[str]:
    """The features index, then each feature page in the order the index lists it, then any page it does not list."""
    index = (ROOT / "docs" / "features" / "README.md").read_text()
    pages = sorted(p.name for p in (ROOT / "docs" / "features").glob("*.md") if p.name != "README.md")
    listed = [name for name in dict.fromkeys(re.findall(r"\]\(([\w-]+\.md)(?:#[^)]*)?\)", index)) if name in pages]
    return ["features/README.md"] + [f"features/{name}" for name in listed + [p for p in pages if p not in listed]]


FEATURES = _features()

# (section, [source paths: under docs/, or a root file given as "/NAME.md"])
NAV = [
    ("Overview", ["README.md"]),
    ("Getting started", ["getting-started.md", "install.md", "mac-app.md"]),
    ("Connect your phone", ["phone.md", "phone/wifi.md", "phone/tailscale.md", "phone/twingate.md", "phone/cloudflare.md",
                            "iphone-app.md"]),
    ("Models and setups", ["models.md", "setups.md", "benchmarks.md"]),
    ("Architecture", ["architecture.md", "how-it-works.md", "harnesses.md", "multi-machine.md", "cloud-sessions.md"]),
    ("Features", FEATURES),
    ("Contributing", ["/CONTRIBUTING.md", "releasing.md", "/SECURITY.md"]),
]
# Docs with a page of their own elsewhere on the site.
ELSEWHERE = {"docs/benchmarks/README.md": "benchmarks/", "docs/benchmarks/hlk.md": "benchmarks/hlk/",
             "docs/benchmarks/actions.md": "benchmarks/actions/"}
COPIED = {".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp"}  # files a page shows, copied next to it

HEBREW = "֐-׿יִ-ﭏ"
HEBREW_RUN = re.compile(f"[{HEBREW}]+(?:[ \u05f3\u05f4-]+[{HEBREW}]+)*")  # one phrase: words, spaces, geresh, maqaf
FENCE = re.compile(r"^(\s*)(```+|~~~+)\s*([\w+-]*)\s*$")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")


def repo_path(source: str) -> str:
    """docs/x.md for "x.md", NAME.md for "/NAME.md"."""
    return source[1:] if source.startswith("/") else f"docs/{source}"


def pages() -> list[str]:
    """Every rendered file, as a repository path, in nav order."""
    return [repo_path(s) for _, sources in NAV for s in sources]


def url_dir(path: str) -> str:
    """The page's folder under site/pointe/docs: "" for the docs home, "phone/wifi" for docs/phone/wifi.md."""
    if path.startswith("docs/"):
        stem = path[len("docs/"):-len(".md")]
        if stem == "README":
            return ""
        return stem[:-len("/README")] if stem.endswith("/README") else stem
    return path[:-len(".md")].lower()


def asset_out(path: str) -> str:
    """Where a copied file goes under site/pointe/docs."""
    return path[len("docs/"):] if path.startswith("docs/") else f"_repo/{path}"


def slug(text: str, seen: dict[str, int]) -> str:
    """GitHub's heading anchor: lower case, punctuation dropped, each space a hyphen, repeats numbered."""
    base = re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")
    n = seen.get(base, 0)
    seen[base] = n + 1
    return base if n == 0 else f"{base}-{n}"


def _prepare(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Take fenced code out (kept by index), and give a list under a paragraph the blank line Python-Markdown needs."""
    lines, out, blocks = text.split("\n"), [], []
    i = 0
    while i < len(lines):
        m = FENCE.match(lines[i])
        if m:
            indent, mark, lang = m.groups()
            body, i = [], i + 1
            while i < len(lines) and not (lines[i].strip().startswith(mark[0] * len(mark))
                                          and lines[i].strip().strip(mark[0]) == ""):
                line = lines[i]
                body.append(line[len(indent):] if line.startswith(indent) else line.lstrip())
                i += 1
            i += 1
            blocks.append((lang, "\n".join(body)))
            out += ["", f"{indent}PTDOCSCODE{len(blocks) - 1}X", ""]
            continue
        line = lines[i]
        if LIST_ITEM.match(line) and out and out[-1].strip() and not LIST_ITEM.match(out[-1]) \
                and not out[-1].lstrip().startswith(("|", ">")) and not re.match(r"^\s*#", out[-1]):
            out.append("")
        out.append(line)
        i += 1
    return "\n".join(out), blocks


def _code(lang: str, body: str) -> str:
    cls = f' class="language-{html.escape(lang)}"' if lang else ""
    return (f'<div class="dx-code"><pre><code{cls}>{html.escape(body)}</code></pre>'
            '<button class="dx-copy" type="button" hidden>Copy</button></div>')


def _hebrew(fragment: str) -> str:
    """Mark each run of Hebrew in the text (never inside a tag) as Hebrew, right to left."""
    parts = re.split(r"(<[^>]+>)", fragment)
    return "".join(p if p.startswith("<") else HEBREW_RUN.sub(lambda m: f'<span lang="he" dir="rtl">{m.group(0)}</span>', p)
                   for p in parts)


def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment))


class Page:
    def __init__(self, path: str):
        self.path = path
        self.dir = url_dir(path)
        self.source = (ROOT / path).read_text()
        self.title = ""
        self.description = ""
        self.headings: list[tuple[int, str, str]] = []  # (level, id, text)
        self.assets: set[str] = set()
        self.body = self._render()

    def _link(self, target: str, attribute: str) -> str:
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith(("#", "//")):
            return target
        raw, _, anchor = target.partition("#")
        if not raw:
            return target
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(self.path), raw))
        here = posixpath.join("docs", self.dir) if self.dir else "docs"
        hash_ = f"#{anchor}" if anchor else ""
        if resolved in pages():
            there = posixpath.join("docs", url_dir(resolved)) if url_dir(resolved) else "docs"
            return posixpath.relpath(there, here) + "/" + hash_
        if resolved in ELSEWHERE:
            return posixpath.relpath(ELSEWHERE[resolved].rstrip("/"), here) + "/" + hash_
        on_disk = ROOT / resolved
        if attribute == "src" and on_disk.suffix.lower() in COPIED and on_disk.is_file():
            self.assets.add(resolved)
            return posixpath.relpath(posixpath.join("docs", asset_out(resolved)), here)
        kind = "tree" if on_disk.is_dir() else "blob"
        return f"{GITHUB}/{kind}/main/{resolved}{hash_}"

    def _render(self) -> str:
        text, blocks = _prepare(self.source)
        converter = markdown.Markdown(extensions=["tables", "sane_lists"], tab_length=2, output_format="html")
        body = converter.convert(text)
        body = re.sub(r"<p>\s*PTDOCSCODE(\d+)X\s*</p>|PTDOCSCODE(\d+)X",
                      lambda m: _code(*blocks[int(m.group(1) or m.group(2))]), body)
        body = re.sub(r'\b(href|src|srcset)="([^"]*)"', lambda m: f'{m.group(1)}="{self._link(html.unescape(m.group(2)), m.group(1))}"',
                      body)
        seen: dict[str, int] = {}

        def heading(m: re.Match) -> str:
            level, inner = int(m.group(1)), m.group(2)
            ident = slug(_text(inner), seen)
            if level == 1 and not self.title:
                self.title = _text(inner).strip()
            elif level in (2, 3):
                self.headings.append((level, ident, _text(inner).strip()))
            return f'<h{level} id="{ident}">{inner}</h{level}>'

        body = re.sub(r"<h([1-6])>(.*?)</h\1>", heading, body, flags=re.S)
        body = body.replace("<table>", '<div class="dx-table"><table>').replace("</table>", "</table></div>")
        first = re.search(r"</h1>\s*<p>(.*?)</p>", body, re.S)
        words = re.sub(r"\s+", " ", HEBREW_RUN.sub("", _text(first.group(1)) if first else self.title)).strip()
        self.description = words if len(words) <= 160 else words[:157].rsplit(" ", 1)[0] + "…"
        return _hebrew(body)


def _nav(current: Page, all_pages: dict[str, Page]) -> str:
    here = posixpath.join("docs", current.dir) if current.dir else "docs"
    parts = []
    for section, sources in NAV:
        items = []
        for source in sources:
            page = all_pages[repo_path(source)]
            there = posixpath.join("docs", page.dir) if page.dir else "docs"
            href = posixpath.relpath(there, here) + "/"
            mark = ' aria-current="page"' if page is current else ""
            items.append(f'<li><a href="{href}"{mark}>{html.escape(page.title)}</a></li>')
        parts.append(f'<p class="dx-nav-h">{section}</p>\n<ul>\n' + "\n".join(items) + "\n</ul>")
    return "\n".join(parts)


def _outline(page: Page) -> str:
    if len(page.headings) < 2:
        return ""
    items = "\n".join(f'<li class="dx-l{level}"><a href="#{ident}">{_hebrew(html.escape(text))}</a></li>'
                      for level, ident, text in page.headings)
    return ('<aside class="dx-toc" aria-label="On this page">\n<details class="dx-fold" open data-fold="1080">'
            f'<summary>On this page</summary>\n<ul>\n{items}\n</ul>\n</details>\n</aside>')


def _pager(page: Page, order: list[Page]) -> str:
    i = order.index(page)
    here = posixpath.join("docs", page.dir) if page.dir else "docs"

    def link(other: Page, word: str, cls: str) -> str:
        there = posixpath.join("docs", other.dir) if other.dir else "docs"
        return (f'<a class="{cls}" href="{posixpath.relpath(there, here)}/"><span class="pg-small">{word}</span>'
                f'{html.escape(other.title)}</a>')

    prev = link(order[i - 1], "Previous", "dx-prev") if i > 0 else "<span></span>"
    nxt = link(order[i + 1], "Next", "dx-next") if i + 1 < len(order) else "<span></span>"
    return f'<nav class="dx-pager" aria-label="Previous and next">{prev}{nxt}</nav>'


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Pointe docs</title>
<meta name="description" content="{description}">
<meta name="referrer" content="no-referrer">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#FFFFFF" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0A0400" media="(prefers-color-scheme: dark)">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:image" content="{origin}social.png">
<meta property="og:url" content="{url}">
<meta name="twitter:card" content="summary_large_image">
<script>
  // The old address: Cloudflare Pages cannot redirect by host, so the page does it.
  if (location.hostname === 'pointe.ballerine.com') location.replace('{url}' + location.hash);
</script>
<link rel="icon" href="{up}brand/favicon.svg" type="image/svg+xml">
<link rel="icon" href="{up}brand/favicon-32.png" type="image/png" sizes="32x32">
<link rel="apple-touch-icon" href="{up}brand/apple-touch-icon.png">
<link rel="stylesheet" href="{up}style.css">
<link rel="stylesheet" href="{up}pages.css">
<link rel="stylesheet" href="{up}docs.css">
</head>
<body class="pg dx">
<a class="pg-skip" href="#main">Skip to content</a>
<header class="pg-wrap dx-wrap pg-header">
  <a class="pg-wordmark" href="{up}"><picture><source srcset="{up}brand/lockup-small-on-dark.svg" media="(prefers-color-scheme: dark)"><img src="{up}brand/lockup-small.svg" width="112" height="32" alt="Pointe"></picture></a>
  <nav aria-label="Pages">
    <a href="{up}features/">Features</a>
    <a href="{home}" aria-current="true">Docs</a>
    <a href="{up}benchmarks/">Benchmarks</a>
    <a href="{up}roadmap/">Roadmap</a>
    <a href="{up}contribute/">Contribute</a>
    <a class="pg-gh" href="https://github.com/ballerine-io/pointe">GitHub</a>
  </nav>
</header>
<div class="pg-wrap dx-wrap dx-grid">
<nav class="dx-side" aria-label="Documentation">
<details class="dx-fold" open data-fold="880">
<summary>Documentation</summary>
{nav}
</details>
</nav>
<main id="main" class="dx-main">
<article class="dx-doc">
{body}
</article>
<p class="pg-small dx-source">This page is <a href="{github}/blob/main/{path}">{path}</a> in the repository.</p>
{pager}
</main>
{outline}
</div>
<footer class="pg-footer">
  <div class="pg-wrap dx-wrap pg-footer-grid">
    <p class="pg-small">Built and open-sourced by <a href="{up}../">Ballerine Engineering</a>. MIT licensed.
      Community-supported, best effort, no SLA.</p>
    <nav aria-label="Project links" class="pg-footer-links">
      <a href="{up}">Pointe</a>
      <a href="{home}">Docs</a>
      <a href="{up}roadmap/">Roadmap</a>
      <a href="{up}contribute/">Contribute</a>
      <a href="https://github.com/ballerine-io/pointe">Source</a>
      <a href="https://github.com/ballerine-io/pointe/blob/main/CODE_OF_CONDUCT.md">Code of Conduct</a>
    </nav>
  </div>
</footer>
<script>
  // Narrow screens: the nav and the outline start folded, each below the width its column needs. Copy buttons appear only where the clipboard can be written.
  for (const d of document.querySelectorAll('[data-fold]')) {{
    const narrow = matchMedia(`(max-width: ${{d.dataset.fold}}px)`);
    const fold = () => {{ d.open = !narrow.matches; }};
    fold();
    narrow.addEventListener('change', fold);
  }}
  if (navigator.clipboard) for (const b of document.querySelectorAll('.dx-copy')) {{
    b.hidden = false;
    b.addEventListener('click', async () => {{
      try {{ await navigator.clipboard.writeText(b.previousElementSibling.innerText.replace(/\\n$/, '')); b.textContent = 'Copied'; }}
      catch {{ b.textContent = 'Press ⌘C'; }}
      setTimeout(() => {{ b.textContent = 'Copy'; }}, 1600);
    }});
  }}
</script>
</body>
</html>
"""


def build() -> dict[Path, bytes]:
    """Every file under site/pointe/docs, by path, as this would write it."""
    rendered = {path: Page(path) for path in pages()}
    order = [rendered[path] for path in pages()]
    files: dict[Path, bytes] = {}
    for page in order:
        here = posixpath.join("docs", page.dir) if page.dir else "docs"
        up = posixpath.relpath(".", here) + "/"
        home = posixpath.relpath("docs", here) + "/"
        url = ORIGIN + "docs/" + (page.dir + "/" if page.dir else "")
        text = TEMPLATE.format(title=html.escape(page.title), description=html.escape(page.description), origin=ORIGIN,
                               url=url, up=up, home=home, nav=_nav(page, rendered), body=page.body, github=GITHUB,
                               path=page.path, pager=_pager(page, order), outline=_outline(page))
        files[OUT / page.dir / "index.html"] = text.encode()
        for asset in page.assets:
            files[OUT / asset_out(asset)] = (ROOT / asset).read_bytes()
    return files


def main(argv: list[str]) -> int:
    for path in pages():
        if not (ROOT / path).is_file():
            print(f"{path}: in the nav of tools/build_docs.py, but not in the repository", file=sys.stderr)
            return 1
    files = build()
    existing = {p for p in OUT.rglob("*") if p.is_file()} if OUT.exists() else set()
    if "--check" in argv:
        stale = sorted(str(p.relative_to(ROOT)) for p in files if not p.exists() or p.read_bytes() != files[p])
        extra = sorted(str(p.relative_to(ROOT)) for p in existing - set(files))
        for p in stale:
            print(f"{p}: not what tools/build_docs.py writes", file=sys.stderr)
        for p in extra:
            print(f"{p}: not written by tools/build_docs.py", file=sys.stderr)
        return 1 if stale or extra else 0
    for p in existing - set(files):
        p.unlink()
    for directory in sorted({p.parent for p in existing}, key=lambda d: len(d.parts), reverse=True):
        if directory.exists() and not any(directory.iterdir()):
            shutil.rmtree(directory)
    for p, data in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists() or p.read_bytes() != data:
            p.write_bytes(data)
    print(f"wrote {len(files)} files under {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
