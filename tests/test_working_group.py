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
    assert f"{wg.BEGIN}\n      {wg.END}" in text


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


def test_only_a_moving_row_has_the_pause_button():
    assert wg.render(TEN, FIXTURE).count('<button type="button" class="wg-pause" aria-pressed="false" '
                                         'aria-label="Pause the logos">') == 1
    five = {"teams": TEN["teams"][:5]}
    assert "wg-pause" not in wg.render(five, FIXTURE)


CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


@pytest.mark.skipif(not Path(CHROME).exists(), reason="headless Chrome is not installed here")
def test_the_pause_button_is_reachable_by_keyboard_and_stops_and_restarts_the_loop(tmp_path):
    """The real page, with the ten invented teams, in headless Chrome: the button takes focus from the tab order, and
    each press flips aria-pressed and the loop's animation state."""
    site = ROOT / "site" / "pointe"
    text = wg.page(wg.PAGE.read_text(), TEN, FIXTURE).replace("<head>", f'<head>\n<base href="{site.as_uri()}/">', 1)
    probe = """<script>
      const b = document.querySelector('.wg-pause'), track = document.querySelector('.wg-track'), out = [];
      const state = () => [b.getAttribute('aria-pressed'), getComputedStyle(track).animationPlayState];
      b.focus(); out.push(document.activeElement === b && b.tabIndex === 0, state());
      b.click(); out.push(state()); b.click(); out.push(state());
      document.body.dataset.out = JSON.stringify(out);
    </script></body>"""
    page = tmp_path / "index.html"
    page.write_text(text.replace("</body>", probe, 1))
    dom = subprocess.run([CHROME, "--headless=new", "--use-mock-keychain", "--password-store=basic", "--disable-gpu",
                          f"--user-data-dir={tmp_path / 'profile'}", "--allow-file-access-from-files", "--virtual-time-budget=2000",
                          "--dump-dom", page.as_uri()],
                         capture_output=True, text=True, timeout=60).stdout
    got = json.loads(re.search(r'data-out="([^"]*)"', dom)[1].replace("&quot;", '"'))
    assert got == [True, ["false", "running"], ["true", "paused"], ["false", "running"]]
