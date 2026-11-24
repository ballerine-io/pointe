"""The documentation on the site (site/pointe/docs/) is written by tools/build_docs.py from docs/ and three root files:
it is never edited by hand, every page in its nav exists, and every link between pages, and every #anchor, lands."""

import importlib.util
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

spec = importlib.util.spec_from_file_location("build_docs", ROOT / "tools" / "build_docs.py")
build_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_docs)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.links = set(), []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        for name in ("href", "src"):
            if attrs.get(name):
                self.links.append(attrs[name])


def parsed(path: Path) -> Links:
    links = Links()
    links.feed(path.read_text())
    return links


def doc_pages() -> list[Path]:
    return sorted(build_docs.OUT.rglob("index.html"))


def test_the_pages_are_what_the_generator_writes():
    assert build_docs.main(["--check"]) == 0, "run: uv run --locked python tools/build_docs.py"


def test_every_nav_entry_is_a_file_and_a_page():
    for path in build_docs.pages():
        assert (ROOT / path).is_file(), f"{path}: in the nav of tools/build_docs.py, missing from the repository"
        assert (build_docs.OUT / build_docs.url_dir(path) / "index.html").is_file(), path
    assert len(set(build_docs.pages())) == len(build_docs.pages()), "a page is in the nav twice"


def test_every_feature_page_is_in_the_nav():
    listed = set(build_docs.pages())
    for page in sorted((ROOT / "docs" / "features").glob("*.md")):
        assert f"docs/features/{page.name}" in listed, f"docs/features/{page.name}: add it to FEATURES in tools/build_docs.py"


def test_every_link_on_a_docs_page_lands_on_a_page_and_its_anchor():
    """A link between docs pages must reach a file the site serves, and a #anchor an id on that page. A failure here is
    usually a moved section or a renamed heading in docs/: fix the link there, then rebuild."""
    broken = []
    for page in doc_pages() + [SITE / "pointe" / "features" / "index.html"]:  # the features page links into the docs
        for link in parsed(page).links:
            parts = urlsplit(link)
            if parts.scheme or link.startswith("//") or link.startswith("mailto:"):
                continue
            target = (page.parent / parts.path).resolve() if parts.path else page
            if target.is_dir():
                target = target / "index.html"
            where = f"{page.relative_to(SITE)}: {link}"
            if not target.is_file() or SITE.resolve() not in target.parents:
                broken.append(f"{where} (no such file)")
            elif parts.fragment and target.suffix == ".html" and parts.fragment not in parsed(target).ids:
                broken.append(f"{where} (no #{parts.fragment} there)")
    assert not broken, "\n".join(broken)


def test_every_repository_link_in_the_docs_names_a_file_that_exists():
    """Links to files the site does not render go to GitHub: the file must exist, or the link is dead there too."""
    missing = []
    for page in doc_pages():
        for link in parsed(page).links:
            prefix = next((p for p in (f"{build_docs.GITHUB}/blob/main/", f"{build_docs.GITHUB}/tree/main/") if link.startswith(p)), None)
            if prefix:
                path = urlsplit(link[len(prefix):]).path
                if not (ROOT / path).exists():
                    missing.append(f"{page.relative_to(SITE)}: {path}")
    assert not missing, "\n".join(missing)


def test_the_pages_load_nothing_from_another_host():
    for page in doc_pages():
        text = page.read_text()
        assert not re.search(r"<(?:script|link|img|iframe|source|video|audio)\b[^>]*\b(?:src|href|srcset)=[\"'](?:https?:)?//", text), page


def test_markdown_constructs_render_as_on_github():
    """What Python-Markdown would get wrong without tools/build_docs.py's preparation: fenced code inside a numbered
    list item, a list right under a paragraph, a nested list at two spaces, GitHub's anchors, and Hebrew marked."""
    source = ("# Title\n\nIntro.\nSteps:\n- one\n  - nested\n- two\n\n1. Clone\n\n   ```\n   git clone x && cd x\n   ```\n\n"
              "2. Test\n\n## Drive & walk mode\n\n## What's `new`?\n\n## What's `new`?\n\nSay \"מצב נהיגה\" to start.\n")
    page = build_docs.Page.__new__(build_docs.Page)
    page.path, page.dir, page.source, page.title, page.headings, page.assets = "docs/x.md", "x", source, "", [], set()
    body = page._render()
    assert "<ul>\n<li>one<ul>" in body.replace("\n<ul>", "<ul>") or "<li>one\n<ul>" in body, body
    assert '<ol>' in body and 'git clone x &amp;&amp; cd x' in body and body.index("<ol>") < body.index("<pre>"), body
    assert 'start="2"' not in body, "the code block split the numbered list"
    assert [h[1] for h in page.headings] == ["drive--walk-mode", "whats-new", "whats-new-1"]
    assert '<span lang="he" dir="rtl">מצב נהיגה</span>' in body
    assert page.title == "Title" and page.description == "Intro. Steps:"


def test_a_page_that_moved_redirects_to_where_it_went():
    """Reading mode became the mute button (0.8.3): its docs address still lands, on a page that exists."""
    rules = [line.split() for line in (SITE / "_redirects").read_text().splitlines() if line.strip() and not line.startswith("#")]
    moved = {old: (new, code) for old, new, code in rules}
    for old in ("/pointe/docs/features/reading-mode", "/pointe/docs/features/reading-mode/"):
        assert moved.get(old) == ("/pointe/docs/features/mute/", "301"), moved
    for new, _code in moved.values():
        assert (SITE / new.strip("/") / "index.html").is_file(), new
    assert not (SITE / "pointe" / "docs" / "features" / "reading-mode").exists()  # a file there would win over the redirect
