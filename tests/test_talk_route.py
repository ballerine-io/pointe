"""POST /voice/talk: push to talk from outside the call (`pointe talk`, bound to a system-wide shortcut). Offline: the
daemon's HTTP app with the gate driven directly, as in test_ptt.py.

uv run pytest -q tests/test_talk_route.py
"""

import inspect
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_orchestrator import client_for, d  # noqa: E402,F401  (d is a fixture)
from test_ptt import _gate  # noqa: E402


@pytest.fixture(autouse=True)
def _always_on_after():
    yield
    if "daemon" in sys.modules:
        sys.modules["daemon"].PREFS.update({"microphone": "always"})


class _Link:
    """The call's WebSocket, as the route sees it: what it told the client."""

    def __init__(self):
        self.sent = []

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


def _call_up(d, monkeypatch, mode="ptt"):
    gate, pushed, _ = _gate(d, monkeypatch, mode=mode)
    d.state.conn = SimpleNamespace(ptt=gate)
    d.state.call_socket = _Link()
    return gate, pushed, d.state.call_socket


def test_always_on_is_refused_in_plain_words(d, monkeypatch):
    _call_up(d, monkeypatch, mode="always")
    r = client_for(d).post("/voice/talk", json={"action": "toggle"})
    assert r.status_code == 409 and "Always on" in r.json()["detail"] and "Push to talk" in r.json()["detail"]
    assert not d.state.ptt.open


def test_no_call_is_refused_in_plain_words(d):
    d.PREFS.update({"microphone": "ptt"})
    d.state.conn = None
    r = client_for(d).post("/voice/talk", json={"action": "on"})
    assert r.status_code == 409 and r.json()["detail"].startswith("No call is up")


def test_toggle_opens_then_closes_the_gate_and_the_status_and_the_client_follow(d, monkeypatch):
    gate, pushed, link = _call_up(d, monkeypatch)
    c = client_for(d)
    assert c.post("/voice/talk", json={"action": "toggle"}).json() == {"open": True, "mode": "ptt"}
    assert c.get("/voice/status").json()["ptt"]["open"] is True
    assert any(isinstance(f, d.UserSpeakingFrame) for f in pushed)  # the same rules as a press from a client
    assert link.sent[-1] == {"type": "ptt", "open": True, "by": "shortcut"}  # the client is told to send its audio
    assert c.post("/voice/talk", json={"action": "toggle"}).json() == {"open": False, "mode": "ptt"}
    after = c.get("/voice/status").json()["ptt"]
    assert after["open"] is False and after["closed_why"] == "released"
    assert link.sent[-1] == {"type": "ptt", "open": False, "by": "shortcut"}


def test_on_and_off_are_idempotent_and_an_empty_body_toggles(d, monkeypatch):
    _, _, link = _call_up(d, monkeypatch)
    c = client_for(d)
    assert c.post("/voice/talk", json={"action": "on"}).json()["open"] is True
    assert c.post("/voice/talk", json={"action": "on"}).json()["open"] is True
    assert c.post("/voice/talk", json={"action": "off"}).json()["open"] is False
    assert c.post("/voice/talk", json={"action": "off"}).json()["open"] is False
    assert c.post("/voice/talk").json()["open"] is True
    assert len(link.sent) == 5
    assert c.post("/voice/talk", json={"action": "hold"}).status_code == 400


def test_the_phone_key_and_no_key_are_refused(d, monkeypatch):
    from fastapi.testclient import TestClient

    _call_up(d, monkeypatch)
    phone_client = TestClient(d.app, base_url="http://127.0.0.1:7860")  # no page cookie
    key = {"authorization": f"Bearer {d.phone.phone_key(d.STATE_DIR)}"}
    assert phone_client.post("/voice/talk", headers=key, json={"action": "on"}).status_code == 403
    assert phone_client.post("/voice/talk", json={"action": "on"}).status_code == 403
    assert not d.state.ptt.open
    token = {"authorization": f"Bearer {(d.STATE_DIR / 'token').read_text().strip()}"}  # the CLI's: what pointe talk sends
    assert phone_client.post("/voice/talk", headers=token, json={"action": "on"}).json()["open"] is True


def test_the_status_shows_the_command_to_bind_on_this_mac_only(d):
    c = client_for(d)
    command = c.get("/voice/status").json()["talk_command"]
    assert command == f"{shlex.quote(str(d.STATE_DIR / 'bin' / 'pointe'))} talk"  # the stable launcher, not the cache path
    from fastapi.testclient import TestClient

    phone_client = TestClient(d.app, base_url="http://127.0.0.1:7860")
    key = {"authorization": f"Bearer {d.phone.phone_key(d.STATE_DIR)}"}
    assert phone_client.get("/voice/status", headers=key).json()["talk_command"] is None


def test_startup_writes_a_launcher_for_this_checkout_and_rewrites_it_for_the_next(d, tmp_path):
    """A plugin update moves the checkout: the Shortcut keeps running ~/.claude-voice/bin/pointe, which the daemon
    points at wherever it runs from now."""
    launcher = tmp_path / "state" / "bin" / "pointe"
    for root in (tmp_path / "cache" / "1.1.0", tmp_path / "cache" / "1.2.0"):
        (root / "bin").mkdir(parents=True)
        (root / "bin" / "pointe").write_text("#!/bin/sh\necho \"$(dirname \"$0\") $*\"\n")
        (root / "bin" / "pointe").chmod(0o755)
        assert d._write_launcher(root, launcher) == launcher
        assert launcher.read_text().startswith("#!/bin/sh\n") and not launcher.is_symlink()
        assert launcher.stat().st_mode & 0o777 == 0o755 and launcher.parent.stat().st_mode & 0o777 == 0o700
        ran = subprocess.run([str(launcher), "talk", "on"], capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
        assert ran.stdout.strip() == f"{root / 'bin'} talk on", ran  # the current checkout's pointe, with the arguments
    assert d.LAUNCHER == d.STATE_DIR / "bin" / "pointe"
    assert "_write_launcher()" in inspect.getsource(d._with_housekeeping)  # startup is where it is written
