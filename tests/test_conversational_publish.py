"""The suite pages (docs/benchmarks/, site/pointe/benchmarks/index.html) are written by bench/conversational/publish.py
from the five benchmarks' committed results; none is edited by hand, and the site page loads nothing from another host."""

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("conv_publish", ROOT / "bench" / "conversational" / "publish.py")
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)


def test_every_suite_page_matches_the_committed_results():
    for path, text in publish.build().items():
        assert path.read_text() == text, f"{path.relative_to(ROOT)}: run uv run --locked python bench/conversational/publish.py"


def test_published_pages_cite_builds_not_commit_hashes():
    """The runs predate the public history, so a commit hash on a page leads nowhere: a page names the build
    (bench/conversational/prerelease.json) and its date. Raw rows and FROZEN.json keep the hashes."""
    pages = [*(ROOT / "docs" / "benchmarks").rglob("*.md"), *(ROOT / "site" / "pointe" / "benchmarks").rglob("*.html"),
             *(ROOT / "bench" / "conversational").glob("*/*/RESULTS*.md"), *(ROOT / "bench" / "conversational").glob("*/*/README.md")]
    assert len(pages) > 15
    prerelease = json.loads((ROOT / "bench" / "conversational" / "prerelease.json").read_text())["builds"]
    for page in pages:
        text = page.read_text()
        for sha in prerelease:
            assert not re.search(rf"\b{sha[:7]}", text), f"{page.relative_to(ROOT)} cites {sha[:7]}: name the build instead"
        assert "2026-11-23" in text or "pre-release" not in text, page


def test_there_is_one_docs_page_per_benchmark_and_an_index():
    docs = ROOT / "docs" / "benchmarks"
    assert {p.name for p in docs.glob("*.md")} == {"README.md", *(f"{k}.md" for k in publish.ORDER)}
    index = (docs / "README.md").read_text()
    for k in publish.ORDER:
        assert f"({k}.md)" in index


def test_the_site_page_loads_nothing_from_another_host_and_is_in_the_nav():
    page = publish.PAGE.read_text()
    assert not re.search(r"<(?:script|link|img|iframe|source|video|audio)\b[^>]*\b(?:src|href)=[\"'](?:https?:)?//", page)
    assert "<span data-version>" in page
    for sub in ("index.html", "features/index.html", "roadmap/index.html", "contribute/index.html",
                "benchmarks/hlk/index.html", "benchmarks/actions/index.html"):
        assert re.search(r'<a href="[./]*benchmarks/"|<a href="\.\./"[^>]*>Benchmarks<', (ROOT / "site" / "pointe" / sub).read_text()), sub


def test_a_changed_result_changes_the_page(monkeypatch):
    """The pages are computed, not typed: a different count in a results file shows on the page."""
    real = publish.load

    def fake():
        d = real()
        d["routing"]["summary"]["pointe"]["correct"] = 42
        return d

    monkeypatch.setattr(publish, "load", fake)
    pages = publish.build()
    assert "42/60" in pages[publish.PAGE] and "42/60" not in publish.PAGE.read_text()
