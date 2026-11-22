"""The site: its version text comes from the plugin manifest, and its pages are in English only."""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

spec = importlib.util.spec_from_file_location("site_version", ROOT / "tools" / "site_version.py")
site_version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site_version)


def test_every_version_on_the_site_is_the_manifest_version():
    assert site_version.stale() == [], "run python3 tools/site_version.py (site/deploy.sh does, before a deploy)"
    for page in ("index.html", "pointe/index.html", "pointe/features/index.html"):
        assert site_version.SPAN.search((SITE / page).read_text()), f"{page}: its version is a <span data-version>"


def test_no_page_states_the_current_version_outside_a_generated_span():
    """A version typed by hand goes stale. Versions named for a past measurement ("since 1.14.5") are history."""
    for page in site_version.pages():
        text = site_version.SPAN.sub("", page.read_text())
        assert not re.search(r"\b[Vv]ersion\s+\d+\.\d+", text), f"{page.relative_to(ROOT)}: use <span data-version>"


def test_the_tool_writes_the_manifest_version_into_a_stale_page(tmp_path, monkeypatch):
    page = tmp_path / "site" / "x.html"
    page.parent.mkdir()
    page.write_text("<p>Version <span data-version>0.0.1</span>.</p>")
    monkeypatch.setattr(site_version, "ROOT", tmp_path)
    monkeypatch.setattr(site_version, "version", lambda: "9.9.9")
    assert site_version.stale() == [page]
    site_version.write()
    assert page.read_text() == "<p>Version <span data-version>9.9.9</span>.</p>" and site_version.stale() == []


def test_the_site_is_in_english_only():
    """No Hebrew in any page: not in the copy, and not in the words an image's alt text reads out of a screenshot.
    The screenshots come from the apps' `-demoEnglish` data and the page rig's English fixtures (docs/design/parity.md)."""
    hebrew = re.compile(r"[֐-׿יִ-ﭏ]")
    for page in site_version.pages():
        found = hebrew.search(page.read_text())
        assert not found, f"{page.relative_to(ROOT)}: Hebrew text at offset {found.start()}"


def test_the_deploy_script_writes_the_version_first():
    script = (SITE / "deploy.sh").read_text()
    assert script.index("python3 tools/site_version.py") < script.index("exec npx")
