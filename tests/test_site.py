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


def test_the_beta_label_follows_the_major_version(tmp_path, monkeypatch):
    """Major version 0 is the beta: each <span data-beta> says "Beta", and says nothing from 1.0.0 on."""
    page = tmp_path / "site" / "x.html"
    page.parent.mkdir()
    page.write_text('<span class="beta" data-beta></span><span data-version>0.0.1</span>')
    monkeypatch.setattr(site_version, "ROOT", tmp_path)
    monkeypatch.setattr(site_version, "version", lambda: "0.8.0")
    site_version.write()
    assert page.read_text() == '<span class="beta" data-beta>Beta</span><span data-version>0.8.0</span>'
    monkeypatch.setattr(site_version, "version", lambda: "1.0.0")
    assert site_version.stale() == [page]
    site_version.write()
    assert page.read_text() == '<span class="beta" data-beta></span><span data-version>1.0.0</span>'


def test_the_site_headers_carry_the_beta_label():
    for page in ("index.html", "pointe/index.html"):
        assert site_version.BETA_SPAN.search((SITE / page).read_text()), f"{page}: a <span data-beta> in its header"


def test_the_site_is_in_english_only():
    """No Hebrew in any page: not in the copy, and not in the words an image's alt text reads out of a screenshot.
    The screenshots come from the apps' `-demoEnglish` data and the page rig's English fixtures (docs/design/parity.md).

    One exception, and a narrow one: the documentation (site/pointe/docs/, rendered from docs/ by tools/build_docs.py)
    quotes the Hebrew phrases Pointe answers to, because they are what a reader must say. There, and only there, Hebrew
    may stand inside a `<span lang="he" dir="rtl">` that the generator writes around each run; any other Hebrew on a docs
    page still fails."""
    hebrew = re.compile(r"[֐-׿יִ-ﭏ]")
    marked = re.compile(r'<span lang="he" dir="rtl">[^<]*</span>')
    docs = SITE / "pointe" / "docs"
    for page in site_version.pages():
        text = page.read_text()
        if docs in page.parents:
            text = marked.sub("", text)
        found = hebrew.search(text)
        assert not found, f"{page.relative_to(ROOT)}: Hebrew text at offset {found.start()}"


def test_the_deploy_script_writes_the_version_first():
    script = (SITE / "deploy.sh").read_text()
    assert script.index("python3 tools/site_version.py") < script.index("exec npx")


DAY = ["switch", "mac", "workout", "meeting", "drive", "night", "morning"]


def test_the_day_holds_every_beat_in_order_with_a_rail_that_matches_it():
    """The day story's beats run from morning to the next morning, the workout among them; the rail on a wide screen
    links each beat under the beat's own time and feature name, and the stage's grid has one column per beat."""
    page = (SITE / "pointe" / "index.html").read_text()
    day = page[page.index('<section id="day"'):page.index("</section>", page.index('<section id="day"'))]
    assert re.findall(r'<li class="beat" id="beat-([a-z]+)">', day) == DAY
    kickers = re.findall(r'<p class="kicker"><span class="when">([\d:]+)</span> ([^<]+)</p>', day)
    rail = re.findall(r'<a href="#beat-([a-z]+)"><span class="when">([\d:]+)</span> ([^<]+)</a>', day)
    assert [r[0] for r in rail] == DAY and [(r[1], r[2]) for r in rail] == kickers
    times = [t for t, _ in kickers][:-1]  # the last beat is the next morning
    assert times == sorted(times)
    css = (SITE / "pointe" / "style.css").read_text()
    assert f"repeat({len(DAY)}, minmax(0, 1fr)); column-gap: 10px; grid-column: 2; grid-row: 1 / span {len(DAY)};" in css
    assert css.count(f"grid-row: 1 / span {len(DAY)};") == 2


def test_a_beat_label_fits_one_line_on_a_phone():
    """On a phone each beat is a card 86% of a 375 px screen wide; its kicker (time and feature name, 11 px capitals)
    stays on one line up to about 24 characters."""
    page = (SITE / "pointe" / "index.html").read_text()
    for when, name in re.findall(r'<p class="kicker"><span class="when">([\d:]+)</span> ([^<]+)</p>', page):
        assert len(f"{when} {name}") <= 24, name


def test_with_pointe_holds_only_the_film():
    page = (SITE / "pointe" / "index.html").read_text()
    section = page[page.index('<section id="with"'):page.index("</section>", page.index('<section id="with"'))]
    assert section.count("data-film") == 1 and "workout" not in section and 'class="beat' not in section
