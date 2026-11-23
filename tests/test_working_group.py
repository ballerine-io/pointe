"""The working group's logo row on site/pointe/index.html is written by tools/working_group.py from
site/pointe/working-group.json: only teams that gave consent, a loop from six teams on, a still row below that.
tests/fixtures/working_group/ holds ten invented teams and is never deployed."""

import copy
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import working_group as wg  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "working_group"
TEN = json.loads((FIXTURE / "teams-10.json").read_text())


def test_the_page_shows_what_the_json_says():
    subprocess.run([sys.executable, str(ROOT / "tools" / "working_group.py"), "--check"], cwd=ROOT, check=True)


def test_every_team_on_the_page_gave_consent_and_says_why_the_field_is_there():
    data = json.loads(wg.DATA.read_text())
    assert "consent" in data["_consent"] and "maintainer" in data["_maintainer"]
    consented = [t for t in data["teams"] if t.get("consent") is True]
    shown = re.findall(r'aria-label="([^"]+)"', wg.render(data, wg.SITE))
    others = [t for t in consented if not t.get("maintainer")]
    assert shown == ([t["name"] for t in consented] if others else [])


def test_the_maintainer_alone_shows_no_row_and_leaves_no_space():
    data = json.loads(wg.DATA.read_text())
    alone = {"teams": [t for t in data["teams"] if t.get("maintainer")]}
    assert alone["teams"] and wg.render(alone, wg.SITE) == ""
    text = wg.page(wg.PAGE.read_text(), alone, wg.SITE)
    assert f"{wg.BEGIN}\n      {wg.END}" in text and "wg-logos" not in text


def test_the_first_other_team_brings_the_row_with_the_maintainer_in_it():
    first = dict(TEN["teams"][0])
    maintainer = {"name": "Maintainer", "logo": first["logo"], "consent": True, "maintainer": True}
    out = wg.render({"teams": [maintainer, first]}, FIXTURE)
    assert "wg-static" in out and re.findall(r'aria-label="([^"]+)"', out) == ["Maintainer", "Acme Labs"]


def test_a_team_without_consent_is_not_shown():
    out = wg.render(TEN, FIXTURE)
    assert "Unconsented Co" not in out and out.count('class="wg-logo"') == 20
    data = copy.deepcopy(TEN)
    for t in data["teams"]:
        t.pop("consent")
    assert wg.render(data, FIXTURE) == ""


def test_six_teams_or_more_loop_and_the_copy_is_hidden_from_readers_and_the_tab_order():
    out = wg.render(TEN, FIXTURE)
    assert "wg-marquee" in out and "--n: 10" in out
    first, second = re.findall(r'<ul class="wg-list"[^>]*>.*?</ul>', out)
    assert 'aria-hidden="true"' in second and "aria-hidden" not in first
    assert re.sub(r' tabindex="-1"', "", second.replace(' aria-hidden="true"', "")) == first


def test_fewer_than_six_sit_still_in_one_row():
    data = copy.deepcopy(TEN)
    data["teams"] = data["teams"][:5]
    out = wg.render(data, FIXTURE)
    assert "wg-static" in out and out.count('class="wg-list"') == 1


def test_a_logo_must_be_a_file_under_img_logos():
    for logo in ("img/logos/missing.svg", "../img/logos/acme-labs.svg", "img/elsewhere.svg"):
        data = {"teams": [{"name": "X", "logo": logo, "consent": True}]}
        with pytest.raises(ValueError):
            wg.render(data, FIXTURE)


def test_the_loop_stops_for_hover_focus_and_reduced_motion():
    css = (ROOT / "site" / "pointe" / "style.css").read_text()
    assert ".wg-marquee:hover .wg-track, .wg-marquee:focus-within .wg-track { animation-play-state: paused; }" in css
    reduced = css[css.index("@media (prefers-reduced-motion: reduce) {\n  .wg-marquee"):]
    assert "animation: none" in reduced and ".wg-list[aria-hidden] { display: none; }" in reduced
