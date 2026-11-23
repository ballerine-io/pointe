"""A switch to a setup that cannot start is refused before anything changes, and says why. QA round 2: the page's Use
this setup with the OpenAI key missing stopped Pointe for good and stayed on "Switching"; from Fully local, Voice stays
on your Mac was refused for a missing Anthropic key that was saved (Fully local reads no key), and the page said nothing."""

import json

import pytest

from test_orchestrator import d  # noqa: F401


@pytest.fixture
def client(d, monkeypatch):
    from fastapi.testclient import TestClient

    ran = []
    monkeypatch.setattr(d, "_run_on_the_mac", lambda *commands: ran.append(commands))
    return TestClient(d.app, base_url="http://127.0.0.1:7860", cookies={"pointe_local": d.PAGE_KEY}), ran


def _saved(d, monkeypatch, *vendors):
    monkeypatch.setattr(d.vendors, "_stored", lambda vendor, keep=True: "made-up" if vendor in vendors else None)


def test_use_this_setup_with_its_key_missing_is_refused_and_says_which_key(d, client, monkeypatch):
    c, ran = client
    _saved(d, monkeypatch, "soniox", "anthropic")
    got = c.post("/voice/setup", json={"id": "openai"})
    assert got.status_code == 409 and not ran
    assert "OpenAI key" in got.json()["detail"] and "keeps running" in got.json()["detail"]


def test_use_this_setup_with_its_keys_saved_switches(d, client, monkeypatch):
    c, ran = client
    _saved(d, monkeypatch, "openai")
    assert c.post("/voice/setup", json={"id": "openai"}).json() == {"ok": True} and len(ran) == 1


def test_from_fully_local_the_saved_anthropic_key_counts_for_voice_stays_local(d, client, monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_VOICE_STATE", str(tmp_path))
    (tmp_path / "config.json").write_text(json.dumps({"local_only": True, "setup": "local"}))
    _saved(d, monkeypatch, "anthropic")
    monkeypatch.setattr(d.local, "supported_voice", lambda: None)
    assert d.vendors.local_only() and d.vendors.key("anthropic") is None  # the running Fully local still reads no key
    assert d.local.voice_refused() is None
    c, ran = client
    assert c.post("/voice/setup", json={"id": "voice-local"}).json() == {"ok": True} and len(ran) == 1


def test_voice_stays_local_with_no_text_key_is_refused_on_the_page(d, client, monkeypatch):
    _saved(d, monkeypatch)
    monkeypatch.setattr(d.local, "supported_voice", lambda: None)
    c, ran = client
    got = c.post("/voice/setup", json={"id": "voice-local"})
    assert got.status_code == 409 and "pointe key anthropic" in got.json()["detail"] and not ran


def test_saved_never_keeps_the_key_in_this_process(d, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    class Found:
        returncode, stdout = 0, "made-up\n"
    monkeypatch.setattr(d.vendors.subprocess, "run", lambda *a, **k: Found())
    assert d.vendors.saved("openai")
    import os
    assert "OPENAI_API_KEY" not in os.environ
