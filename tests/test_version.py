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


def test_status_carries_the_manifest_version(d):
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    assert d.VERSION == manifest
    assert client_for(d).get("/voice/status").json()["version"] == manifest


def test_page_shows_the_version_from_status():
    page = (ROOT / "ui.html").read_text()
    assert 'id="ver"' in page and "text('ver', status.version || '')" in page
