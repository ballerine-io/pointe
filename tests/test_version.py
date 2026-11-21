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
    """The iPhone app and the Mac app are released with the plugin and show its version (RELEASING.md)."""
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    for project in ("ios/Pointe.xcodeproj", "macos/PointeMac.xcodeproj"):
        text = (ROOT / project / "project.pbxproj").read_text()
        versions = set(re.findall(r"MARKETING_VERSION = ([0-9.]+);", text))
        assert versions == {manifest}, f"{project}: MARKETING_VERSION is {sorted(versions)}, the manifest says {manifest}"
        builds = set(re.findall(r"CURRENT_PROJECT_VERSION = ([0-9]+);", text))
        assert len(builds) == 1, f"{project}: Debug and Release disagree on CURRENT_PROJECT_VERSION"
    generator = (ROOT / "macos" / "tools" / "make_project.py").read_text()
    assert f'VERSION, BUILD = "{manifest}"' in generator, "macos/tools/make_project.py writes the Mac project: its VERSION moves too"


def test_the_changelog_has_a_line_for_the_manifest_version():
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    assert f"- **{manifest}** (" in (ROOT / "CHANGELOG.md").read_text(), f"CHANGELOG.md: add a line for {manifest} (RELEASING.md)"


def test_status_carries_the_manifest_version(d):
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    assert d.VERSION == manifest
    assert client_for(d).get("/voice/status").json()["version"] == manifest


def test_page_shows_the_version_from_status():
    page = (ROOT / "ui.html").read_text()
    assert 'id="ver"' in page and "text('ver', status.version || '')" in page
