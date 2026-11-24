"""The version the page and the app show comes from the plugin manifest, and the three places that carry a version agree."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_orchestrator import client_for, d  # noqa: E402,F401  (d is a fixture)

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_pyproject_and_lock_agree():
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    pyproject = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    lock = re.search(r'^name = "pointe"\nversion = "([^"]+)"', (ROOT / "uv.lock").read_text(), re.M).group(1)
    assert manifest == pyproject == lock


def test_the_apps_carry_the_manifest_version():
    """The iPhone app and the Mac app are released with the plugin and show its version (docs/releasing.md)."""
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    for project in ("apps/ios/Pointe.xcodeproj", "apps/macos/PointeMac.xcodeproj"):
        text = (ROOT / project / "project.pbxproj").read_text()
        versions = set(re.findall(r"MARKETING_VERSION = ([0-9.]+);", text))
        assert versions == {manifest}, f"{project}: MARKETING_VERSION is {sorted(versions)}, the manifest says {manifest}"
        builds = set(re.findall(r"CURRENT_PROJECT_VERSION = ([0-9]+);", text))
        assert len(builds) == 1, f"{project}: Debug and Release disagree on CURRENT_PROJECT_VERSION"
    generator = (ROOT / "apps" / "macos" / "tools" / "make_project.py").read_text()
    assert f'VERSION, BUILD = "{manifest}"' in generator, "apps/macos/tools/make_project.py writes the Mac project: its VERSION moves too"


def test_the_changelog_has_a_line_for_the_manifest_version():
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    assert f"- **{manifest}** (" in (ROOT / "CHANGELOG.md").read_text(), f"CHANGELOG.md: add a line for {manifest} (docs/releasing.md)"


def test_status_carries_the_manifest_version(d):
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    assert d.VERSION == manifest
    assert client_for(d).get("/voice/status").json()["version"] == manifest


def test_status_names_the_call_protocol_so_the_app_can_tell_a_mac_too_old_or_too_new(d):
    """The app compares these with its own (PhoneProtocol in ConnectionProblem.swift): a Mac older than the oldest it
    works with says "update the plugin", one that no longer serves this app says "update the app"."""
    import phone

    got = client_for(d).get("/voice/status").json()
    assert got["phone_protocol"] == phone.PROTOCOL and got["oldest_phone_protocol"] == phone.OLDEST_APP_PROTOCOL
    assert 1 <= phone.OLDEST_APP_PROTOCOL <= phone.PROTOCOL
    problem = (ROOT / "apps" / "PointeKit" / "Sources" / "PointeUI" / "ConnectionProblem.swift").read_text()
    wire = (ROOT / "apps" / "PointeKit" / "Sources" / "PointeKit" / "Wire.swift").read_text()
    assert "static let app = Wire.protocolVersion" in problem
    assert f"public static let protocolVersion = {phone.PROTOCOL}" in wire, "the app speaks the protocol this Mac speaks"


def test_status_says_beta_exactly_while_the_major_version_is_0(d):
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    assert client_for(d).get("/voice/status").json()["beta"] is manifest.startswith("0.")


def test_page_shows_the_version_from_status():
    page = (ROOT / "pointe" / "ui.html").read_text()
    assert 'id="ver"' in page and "status.version + (status.beta ? ' beta' : '')" in page and "text('ver', ver)" in page
