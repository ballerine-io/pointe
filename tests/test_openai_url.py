"""OpenAI models from another host (docs/features/openai-url.md): Azure OpenAI and other servers that speak OpenAI's API.
The OpenAI key then belongs to that host, so it is sent nowhere else: text models only, never OpenAI's audio."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import keys  # noqa: E402
import vendors  # noqa: E402

HOST = "https://example-resource.openai.azure.com/openai/v1/"


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_VOICE_STATE", str(tmp_path))
    for env in [*vendors.KEY_ENVS, "CLAUDE_VOICE_BRAIN", "CLAUDE_VOICE_READER", "CLAUDE_VOICE_CHECKER", "CLAUDE_VOICE_EARS",
                "CLAUDE_VOICE_MOUTH", "CLAUDE_VOICE_LOCAL_ONLY", "CLAUDE_VOICE_VOICE_LOCAL", "CLAUDE_VOICE_OPENAI_URL"]:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 44, "", ""))
    monkeypatch.setattr(vendors, "_clients", {})
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-openai")

    def configure(**values):
        (tmp_path / "config.json").write_text(json.dumps(values))
    return configure


def test_without_the_setting_the_client_goes_to_openai(state):
    assert vendors.openai_url() is None
    assert "api.openai.com" in str(vendors._openai().base_url)


def test_the_text_client_uses_the_configured_host(state):
    state(openai_url=HOST)
    assert str(vendors._openai().base_url) == HOST


def test_the_environment_wins_over_the_file(state, monkeypatch):
    state(openai_url="https://other.example.com/v1/")
    monkeypatch.setenv("CLAUDE_VOICE_OPENAI_URL", HOST)
    assert vendors.openai_url() == HOST


@pytest.mark.parametrize("bad", ["http://example-resource.openai.azure.com/openai/v1/", "example.com/v1", "ftp://example.com"])
def test_a_host_without_https_is_refused_so_the_key_never_travels_in_the_clear(state, bad):
    state(openai_url=bad)
    with pytest.raises(SystemExit, match="https"):
        vendors.openai_url()


def test_ears_and_mouth_never_fall_to_openai_when_its_key_belongs_to_another_host(state, monkeypatch):
    state(openai_url=HOST, brain="openai:my-deployment", reader="openai:my-deployment", checker="openai:my-deployment")
    with pytest.raises(SystemExit):
        vendors.pick("CLAUDE_VOICE_EARS", vendors.EARS_ORDER)
    monkeypatch.setenv("SONIOX_API_KEY", "synthetic-soniox")
    assert vendors.pick("CLAUDE_VOICE_EARS", vendors.EARS_ORDER) == "soniox"
    assert vendors.pick("CLAUDE_VOICE_MOUTH", vendors.MOUTH_ORDER).split(":")[0] == "soniox"
    assert vendors.pick("CLAUDE_VOICE_BRAIN", vendors.BRAIN_ORDER) == "openai:my-deployment"


@pytest.mark.parametrize("env,choice", [("CLAUDE_VOICE_EARS", "openai"), ("CLAUDE_VOICE_MOUTH", "openai:gpt-4o-mini-tts")])
def test_asking_for_openai_audio_by_name_is_refused(state, monkeypatch, env, choice):
    state(openai_url=HOST)
    monkeypatch.setenv(env, choice)
    with pytest.raises(SystemExit, match="text models only"):
        vendors.pick(env, vendors.EARS_ORDER if env.endswith("EARS") else vendors.MOUTH_ORDER)


def test_the_audio_builders_refuse_too(state):
    state(openai_url=HOST)
    with pytest.raises(SystemExit, match="text models only"):
        vendors.build_ears("openai", [])
    with pytest.raises(SystemExit, match="text models only"):
        vendors.build_mouth("openai:gpt-4o-mini-tts", 24000, None)


def test_the_key_check_asks_for_the_model_the_person_configured(state, monkeypatch):
    state(openai_url=HOST, checker="openai:my-small-deployment", brain="openai:my-deployment")
    asked = []

    async def fake(model, *rest):
        asked.append(model)
        return "ok"
    monkeypatch.setitem(vendors._TEXT, "openai", fake)
    assert keys.check("openai") == (True, "The openai key works.")
    assert asked == ["my-small-deployment"]


def test_the_key_check_keeps_the_default_model_without_the_setting(state, monkeypatch):
    asked = []

    async def fake(model, *rest):
        asked.append(model)
        return "ok"
    monkeypatch.setitem(vendors._TEXT, "openai", fake)
    assert keys.check("openai")[0]
    assert asked == [next(c for c in vendors.CHECKER_ORDER if c.startswith("openai:")).split(":", 1)[1]]


def test_the_doctor_names_the_host(state, capsys):
    import doctor
    state(openai_url=HOST, brain="openai:my-deployment", reader="openai:my-deployment", checker="openai:my-deployment",
          ears="soniox", mouth="soniox:tts-rt-v2")
    doctor.main()
    assert "example-resource.openai.azure.com" in capsys.readouterr().out
