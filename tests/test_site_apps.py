"""The app cards on site/pointe/index.html come from site/pointe/apps.json (tools/apps_status.py): while an app waits,
its card says so and offers a notify link, and a link it already has is labelled as opening soon; once open, it links
the https address in the file."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import apps_status  # noqa: E402

DATA = json.loads(apps_status.DATA.read_text())
WAITING = {"notify_url": "https://github.com/example/notify", "mac": {"status": "coming-soon", "download_url": ""},
           "iphone": {"status": "opening-soon", "testflight_url": ""}}
OPEN = {"notify_url": "https://github.com/example/notify",
        "mac": {"status": "open", "download_url": "https://example.com/Pointe-0.8.0.dmg", "version": "0.8.0", "size": "4.3 MB"},
        "iphone": {"status": "open", "testflight_url": "https://testflight.apple.com/join/EXAMPLE1"}}


def test_the_page_shows_what_the_json_says():
    subprocess.run([sys.executable, str(ROOT / "tools" / "apps_status.py"), "--check"], cwd=ROOT, check=True)


def test_waiting_apps_say_soon_and_link_only_to_the_notify_page():
    out = apps_status.render(WAITING)
    assert "Coming soon" in out and "Opening soon" in out
    assert out.count('href="https://github.com/example/notify"') == 2
    assert ".dmg\"" not in out and "testflight.apple.com" not in out and "btn--primary" not in out
    assert 'data-status="coming-soon"' in out and 'data-status="opening-soon"' in out


def test_open_apps_link_their_download_and_drop_the_soon_label():
    out = apps_status.render(OPEN)
    assert 'href="https://example.com/Pointe-0.8.0.dmg">Download for Mac (.dmg)</a>' in out
    assert 'href="https://testflight.apple.com/join/EXAMPLE1">Join the iPhone beta</a>' in out
    assert "soon" not in out and "notify" not in out


def test_one_app_can_open_before_the_other():
    data = copy.deepcopy(WAITING)
    data["iphone"] = OPEN["iphone"]
    out = apps_status.render(data)
    assert "Join the iPhone beta</a>" in out and "Coming soon" in out and "Opening soon" not in out


def test_a_waiting_app_with_its_link_says_it_opens_soon_and_still_offers_the_notify_link():
    data = copy.deepcopy(WAITING)
    data["iphone"]["testflight_url"] = "https://testflight.apple.com/join/EXAMPLE1"
    out = apps_status.render(data)
    assert 'href="https://testflight.apple.com/join/EXAMPLE1">Join the iPhone beta (opens soon)</a>' in out
    assert 'data-status="opening-soon"' in out and out.count("Get notified") == 2 and "btn--primary" not in out


@pytest.mark.parametrize("app,key,url", [("mac", "download_url", ""), ("iphone", "testflight_url", "http://example.com/x")])
def test_an_open_app_needs_an_https_link(app, key, url):
    data = copy.deepcopy(OPEN)
    data[app][key] = url
    with pytest.raises(ValueError, match="https"):
        apps_status.render(data)


def test_an_unknown_status_is_refused():
    data = copy.deepcopy(WAITING)
    data["mac"]["status"] = "soon"
    with pytest.raises(ValueError, match="status"):
        apps_status.render(data)


def test_the_page_renders_in_both_states(tmp_path, monkeypatch):
    page = tmp_path / "index.html"
    page.write_text(apps_status.PAGE.read_text())
    monkeypatch.setattr(apps_status, "PAGE", page)
    for state, shown in ((OPEN, "Join the iPhone beta</a>"), (WAITING, "Opening soon")):
        monkeypatch.setattr(apps_status, "DATA", tmp_path / "apps.json")
        (tmp_path / "apps.json").write_text(json.dumps(state))
        assert apps_status.main([]) == 0 and apps_status.main(["--check"]) == 0
        text = page.read_text()
        assert shown in text and text.count(apps_status.BEGIN) == 1 and text.count(apps_status.END) == 1


def test_the_slack_invite_shows_in_the_working_group_and_the_footer_and_goes_when_emptied(tmp_path, monkeypatch):
    page = tmp_path / "index.html"
    page.write_text(apps_status.PAGE.read_text())
    monkeypatch.setattr(apps_status, "PAGE", page)
    monkeypatch.setattr(apps_status, "DATA", tmp_path / "apps.json")
    url = "https://join.slack.com/t/example/shared_invite/EXAMPLE"
    for slack_url, count in ((url, 2), ("", 0)):
        (tmp_path / "apps.json").write_text(json.dumps({**WAITING, "slack_url": slack_url}))
        assert apps_status.main([]) == 0
        text = page.read_text()
        assert text.count(f'href="{url}"') == count and ("Join the community on Slack" in text) == bool(count)
    working_group = text[text.index('id="working-group"'):text.index("</section>", text.index('id="working-group"'))]
    assert apps_status.marks("slack-wg")[0] in working_group and apps_status.marks("slack-footer")[0] in text[text.index("<footer"):]


def test_while_the_mac_waits_the_hero_leads_with_install_and_the_nav_has_no_download():
    out = apps_status.hero(WAITING)
    assert out.startswith('<p class="hero-cta"><a class="btn btn--primary" href="#install">Install</a>') and ".dmg" not in out
    assert apps_status.nav(WAITING) == ""


def test_once_the_mac_is_open_the_hero_and_the_nav_download_it_with_its_version_and_size():
    out = apps_status.hero(OPEN)
    assert out.index('data-mac-only href="https://example.com/Pointe-0.8.0.dmg">Download for Mac</a>') < out.index(">Install</a>")
    assert '<a class="btn" href="#install">Install</a>' in out, "Install steps back: one primary button per device"
    assert 'data-not-mac hidden href="#install">Get it on your Mac</a>' in out
    assert "Pointe 0.8.0 · macOS 15+ · 4.3 MB" in out
    assert '<p class="small app-meta">Pointe 0.8.0 · macOS 15+ · 4.3 MB</p>' in apps_status.render(OPEN)
    assert "app-meta" not in apps_status.render(WAITING)
    assert 'href="https://example.com/Pointe-0.8.0.dmg" data-mac-only>Download</a>' in apps_status.nav(OPEN)
    assert 'MACOSX_DEPLOYMENT_TARGET": "15.0"' in (ROOT / "apps" / "macos" / "tools" / "make_project.py").read_text()


def test_an_open_mac_needs_its_version_and_size():
    data = copy.deepcopy(OPEN)
    del data["mac"]["size"]
    with pytest.raises(ValueError, match="version and size"):
        apps_status.hero(data)


def test_the_page_swaps_the_mac_download_for_get_it_on_your_mac_on_other_devices():
    text = apps_status.PAGE.read_text()
    script = text[text.index("The Mac download, on a Mac only"):]
    assert "[data-mac-only]" in script and "[data-not-mac]" in script and "maxTouchPoints" in script
    assert "/mac/i.test(" in script, "Chromium says macOS, Safari MacIntel: the test must not care about case"
    for name in ("hero-cta", "nav-download"):
        assert text.count(apps_status.marks(name)[0]) == 1


def test_a_slack_link_must_be_https():
    with pytest.raises(ValueError, match="slack_url"):
        apps_status.slack({"slack_url": "http://example.com"}, "slack-wg")


def test_the_page_no_longer_says_in_review_with_apple():
    assert "in review with Apple" not in apps_status.PAGE.read_text()


def test_the_deploy_script_writes_the_cards_before_it_deploys():
    script = (ROOT / "site" / "deploy.sh").read_text()
    assert script.index("python3 tools/apps_status.py") < script.index("exec npx")


SYSTEM_PYTHON = Path("/usr/bin/python3")


@pytest.mark.skipif(not SYSTEM_PYTHON.exists() or sys.platform != "darwin", reason="macOS's own python3 is not here")
def test_the_generator_runs_on_the_python_macos_ships():
    """site/deploy.sh runs `python3 tools/apps_status.py`: on a Mac with no newer Python that is macOS's 3.9."""
    got = subprocess.run([str(SYSTEM_PYTHON), "-I", str(ROOT / "tools" / "apps_status.py"), "--check"], cwd=ROOT,
                         capture_output=True, text=True, timeout=60)
    assert got.returncode == 0, got.stderr[-400:]


def test_the_app_store_link_leads_and_testflight_stays_as_the_early_channel():
    data = copy.deepcopy(OPEN)
    data["iphone"]["app_store_url"] = "https://apps.apple.com/app/id1"
    out = apps_status.render(data)
    assert 'href="https://apps.apple.com/app/id1">Get it on the App Store</a>' in out
    assert 'href="https://testflight.apple.com/join/EXAMPLE1">TestFlight</a>' in out
    assert "Join the iPhone beta" not in out


def test_an_app_store_link_must_be_https():
    data = copy.deepcopy(OPEN)
    data["iphone"]["app_store_url"] = "http://apps.apple.com/app/id1"
    with pytest.raises(ValueError):
        apps_status.render(data)
