"""pointe doctor tells what the running call sees, names a key out of quota, and knows a node. From QA runs: it said
"Pointe is ready" while the page said Cannot hear you over a refused key; an exhausted Gemini key was "ClientError" with
the fix "pointe setup"; on a node it asked for a Gemini key."""

import json
import os
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
import doctor  # noqa: E402
import keys  # noqa: E402
import vendors  # noqa: E402


class ClientError(Exception):
    pass


QUOTA = ClientError("429 RESOURCE_EXHAUSTED. You exceeded your current quota, please check your plan and billing details.")


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_VOICE_STATE", str(tmp_path))
    (tmp_path / "token").write_text("t")
    return tmp_path


def test_a_key_out_of_quota_is_named_with_its_fix_not_client_error(monkeypatch):
    monkeypatch.setattr(vendors, "key", lambda v: "made-up")

    async def text(*_a):
        raise QUOTA

    monkeypatch.setitem(vendors._TEXT, "gemini", text)
    import asyncio
    import urllib

    ok, said = keys._check("gemini", asyncio, urllib)
    assert ok is None and said == vendors.fault_help("quota", "gemini")
    assert "ClientError" not in said and "billing" in said


def test_an_audio_vendor_answering_429_is_named_too(monkeypatch):
    import asyncio
    import urllib

    monkeypatch.setattr(vendors, "key", lambda v: "made-up")

    class Opener:  # keys._check opens through an opener that refuses redirects (the key must not follow one)
        def open(self, *_a, **_k):
            raise urllib.error.HTTPError("https://api.example.invalid", 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: Opener())
    ok, said = keys._check("soniox", asyncio, urllib)
    assert ok is None and "Soniox" in said and "HTTP 429" not in said


def test_the_running_call_is_asked_only_when_this_state_dirs_daemon_runs(state, monkeypatch):
    asked = []
    monkeypatch.setattr(doctor.urllib.request, "urlopen", lambda *a, **k: asked.append(a) or (_ for _ in ()).throw(OSError()))
    assert doctor.running_status() is None and asked == []  # no daemon.pid: the port may be another state dir's Pointe
    (state / "daemon.pid").write_text(str(os.getpid()))
    assert doctor.running_status() is None and len(asked) == 1


def test_the_verdict_names_what_the_running_call_sees():
    status = {"needed": [], "fix": None}
    assert doctor.verdict(0, status, None, [], [("quota", "gemini")]) == [
        "Pointe is not ready: " + vendors.fault_help("quota", "gemini")]
    assert doctor.verdict(0, status, None, ["gemini"], [])[0] == "Pointe is not ready: the Gemini key was refused."
    assert doctor.verdict(0, status, None, [], [])[0].startswith("Pointe is ready")


def _node(state, live, monkeypatch):
    (state / "node.json").write_text(json.dumps({"hub": {"id": "h1", "name": "studio", "host": "studio.example.internal",
                                                         "fp": "ab" * 32}}))
    (state / "node_keys").mkdir()
    (state / "node_keys" / "h1").write_text("k")
    monkeypatch.setattr(doctor, "running_status", lambda: live)


def test_on_a_node_doctor_speaks_of_the_hub_not_a_key(state, monkeypatch, capsys):
    _node(state, {"node": True, "link": "up", "remote_taps": "readable_only"}, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["doctor.py"])
    assert doctor.main() == 0
    out = capsys.readouterr().out
    assert out.startswith("Pointe is ready as a node of studio") and "key" not in out.split("\n")[0].replace("no keys", "")
    assert "can be read out" in out


def test_a_node_that_is_not_running_says_how_to_start_it(state, monkeypatch, capsys):
    _node(state, None, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["doctor.py"])
    assert doctor.main() == 1
    assert "bin/voice-node ensure" in capsys.readouterr().out
