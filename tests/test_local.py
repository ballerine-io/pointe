"""Fully local mode: with it on, no key is read and nothing is sent to a vendor; `pointe local` sets it up and can undo it."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import local  # noqa: E402
import vendors  # noqa: E402


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_VOICE_STATE", str(tmp_path))
    for env in ("CLAUDE_VOICE_LOCAL_ONLY", "CLAUDE_VOICE_LOCAL_URL", "CLAUDE_VOICE_BRAIN", "CLAUDE_VOICE_READER",
                "CLAUDE_VOICE_CHECKER", "CLAUDE_VOICE_EARS", "CLAUDE_VOICE_MOUTH"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(vendors, "_clients", {})
    return tmp_path


def no_keychain(*args, **kwargs):
    raise AssertionError(f"the Keychain was read in local-only mode: {args}")


def test_local_only_reads_no_key_from_the_environment_or_the_keychain(state, monkeypatch):
    (state / "config.json").write_text(json.dumps({"local_only": True}))
    monkeypatch.setenv("GOOGLE_API_KEY", "would-send-audio-out")
    monkeypatch.setenv("SONIOX_API_KEY", "would-send-audio-out")
    monkeypatch.setattr(subprocess, "run", no_keychain)
    assert vendors.key("gemini") is None and vendors.key("soniox") is None
    assert not vendors.has("soniox")  # so no mirror ears and no meeting ears go to Soniox
    assert vendors.has(vendors.LOCAL)


def test_local_only_from_the_environment(state, monkeypatch):
    monkeypatch.setenv("CLAUDE_VOICE_LOCAL_ONLY", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert vendors.key("openai") is None


def test_local_only_refuses_a_cloud_role_instead_of_using_it(state, monkeypatch):
    (state / "config.json").write_text(json.dumps({"local_only": True, "brain": "anthropic:claude-sonnet-5-5"}))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    with pytest.raises(SystemExit, match="local"):
        vendors.pick("CLAUDE_VOICE_BRAIN", vendors.BRAIN_ORDER)


def test_the_config_written_by_pointe_local_runs_every_role_with_zero_keys(state, monkeypatch):
    monkeypatch.setattr(subprocess, "run", no_keychain)
    local.write_config()
    s = vendors.resolve("brain")
    assert {s.brain, s.reader, s.checker} == {f"local:{local.TEXT_MODEL}"}
    assert s.ears == "local" and s.mouth.startswith("local")


def test_the_local_server_url_comes_from_the_config(state):
    local.write_config()
    assert str(vendors._local().base_url).rstrip("/") == local.url()


def test_the_environment_still_points_text_models_elsewhere(state, monkeypatch):
    local.write_config()
    monkeypatch.setenv("CLAUDE_VOICE_LOCAL_URL", "http://127.0.0.1:1234/v1")
    assert str(vendors._local().base_url).rstrip("/") == "http://127.0.0.1:1234/v1"


def test_pointe_local_keeps_other_settings_and_off_restores_the_previous_choice(state):
    before = {"brain": "gemini:gemini-3.8-flash", "approvals": "terminal"}
    (state / "config.json").write_text(json.dumps(before))
    local.write_config()
    now = json.loads((state / "config.json").read_text())
    assert now["approvals"] == "terminal" and now["local_only"] is True and now["brain"].startswith("local:")
    local.write_config()  # a second run must not overwrite the saved choice with the local one
    local.restore_config()
    assert json.loads((state / "config.json").read_text()) == before


def test_off_without_a_saved_choice_drops_only_the_local_settings(state):
    local.write_config()
    local.restore_config()
    assert json.loads((state / "config.json").read_text()) == {}


def test_status_says_what_is_missing_and_the_command_that_fixes_it(state, monkeypatch):
    monkeypatch.setattr(local, "cached_bytes", lambda repo: 0)
    monkeypatch.setattr(local, "kokoro_bytes", lambda: 0)
    lines = local.status_lines()
    text = "\n".join(lines)
    assert "off" in lines[0] and "pointe local" in text
    assert local.TEXT_MODEL in text and "not downloaded" in text


def test_status_when_on_reports_the_server(state, monkeypatch):
    local.write_config()
    monkeypatch.setattr(local, "cached_bytes", lambda repo: 2_000_000_000)
    monkeypatch.setattr(local, "kokoro_bytes", lambda: 340_000_000)
    monkeypatch.setattr(local, "answering", lambda *a: False)
    text = "\n".join(local.status_lines())
    assert "on" in text.splitlines()[0] and "not running" in text and "2.0 GB" in text


def test_preflight_with_no_key_offers_the_local_mode(state, monkeypatch, capsys):
    import doctor

    monkeypatch.setattr(vendors, "key", lambda vendor: None)
    assert doctor.preflight() == 1
    assert "pointe local" in capsys.readouterr().out


def test_preflight_in_local_mode_fails_in_words_when_the_server_is_down(state, monkeypatch, capsys):
    import doctor

    local.write_config()
    monkeypatch.setattr(local, "answering", lambda *a: False)
    assert doctor.preflight() == 1
    assert "pointe local" in capsys.readouterr().out


def test_preflight_in_local_mode_passes_with_zero_keys(state, monkeypatch):
    import doctor

    local.write_config()
    monkeypatch.setattr(subprocess, "run", no_keychain)
    monkeypatch.setattr(local, "answering", lambda *a: True)
    assert doctor.preflight() == 0


def test_local_ears_use_the_model_pointe_local_downloads():
    assert local.EARS_MODEL == vendors.LOCAL_EARS_MODEL


def test_the_daemon_restarts_the_server_on_the_port_pointe_local_chose(state, monkeypatch):
    monkeypatch.setenv("CLAUDE_VOICE_LOCAL_PORT", "7984")
    local.write_config()
    monkeypatch.delenv("CLAUDE_VOICE_LOCAL_PORT")
    assert local.port() == 7984


def test_doctor_in_local_mode_reports_the_measured_local_setup_not_a_key_to_buy(state, monkeypatch, capsys):
    import doctor

    local.write_config()
    monkeypatch.setattr(local, "answering", lambda *a: True)
    monkeypatch.setattr(local, "cached_bytes", lambda repo: 1)
    monkeypatch.setattr(local, "kokoro_bytes", lambda: 1)
    monkeypatch.setattr(sys, "argv", ["doctor.py"])
    doctor.main()
    out = capsys.readouterr().out
    assert doctor.LOCAL_MEASURED in out and "Next key" not in out and "Start with one Gemini key" not in out
    assert "@@" not in doctor.LOCAL_MEASURED


def test_a_local_text_call_keeps_the_callers_length_limit(state, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    seen = {}

    async def create(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="yes"))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(vendors, "_clients", {vendors.LOCAL: client})
    assert asyncio.run(vendors.text("local:m", "is this what they asked?", max_tokens=16)) == "yes"
    assert seen["max_tokens"] == 16  # the gate's 5 s budget: an unbounded local answer can run past it


@pytest.mark.skipif(sys.platform != "darwin" or __import__("platform").machine() != "arm64", reason="MLX: Apple silicon only")
def test_local_ears_on_apple_silicon_need_no_faster_whisper(monkeypatch):
    """The local extra installs mlx-whisper only, there: pipecat's Whisper module imports faster-whisper first, and the
    first live call died on it."""
    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # import fails, as when it is not installed
    for name in [m for m in sys.modules if m.startswith("pipecat.services.whisper")]:
        monkeypatch.delitem(sys.modules, name)
    ears = vendors._local_ears()
    assert ears._settings.model == vendors.LOCAL_EARS_MODEL


@pytest.mark.skipif(sys.platform != "darwin" or __import__("platform").machine() != "arm64", reason="MLX: Apple silicon only")
def test_local_ears_load_from_disk_without_asking_the_hub(monkeypatch):
    huggingface_hub = pytest.importorskip("huggingface_hub", reason="needs the local extra")

    asked = []

    def snapshot_download(repo, local_files_only=False, **kwargs):
        asked.append(local_files_only)
        return "/models/whisper-turbo"

    monkeypatch.setattr(huggingface_hub, "snapshot_download", snapshot_download)
    assert vendors._local_ears().model_path == "/models/whisper-turbo" and asked == [True]


def test_the_text_model_server_starts_offline(state, monkeypatch, tmp_path):
    seen = {}

    class Proc:
        pid = 1

        def poll(self):
            return None

    def popen(args, **kwargs):
        seen.update(kwargs["env"])
        return Proc()

    bin_ = tmp_path / "server"
    bin_.write_text("")
    monkeypatch.setattr(local, "server_bin", lambda: bin_)
    monkeypatch.setattr(local.subprocess, "Popen", popen)
    monkeypatch.setattr(local, "answering", lambda *a: bool(seen))
    monkeypatch.setattr(local, "_warm", lambda m: True)
    monkeypatch.setenv("GOOGLE_API_KEY", "x")
    (state / "local").mkdir()
    assert local.start(quiet=True)
    assert seen["HF_HUB_OFFLINE"] == "1" and "GOOGLE_API_KEY" not in seen


def test_a_small_mac_is_refused_the_default_model_but_may_choose_its_own(monkeypatch):
    monkeypatch.setattr(local.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(local.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(local.subprocess, "run", lambda *a, **k: __import__("types").SimpleNamespace(stdout=str(16 * 2**30)))
    assert "16 GB" in local.supported()
    assert local.supported("mlx-community/some-small-model") is None


def test_a_downloaded_model_is_counted_without_the_local_extra(tmp_path, monkeypatch):
    """After pointe local off, the daemon's sync removes huggingface_hub; the models it downloaded are still on disk."""
    import builtins

    real_import = builtins.__import__

    def no_hub(name, *a, **k):
        if name.startswith("huggingface_hub"):
            raise ImportError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_hub)
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    repo = tmp_path / "models--mlx-community--whisper-large-v3-turbo"
    store, snapshot = repo / "blobs" / "78", repo / "snapshots" / "rev1"
    store.mkdir(parents=True)
    snapshot.mkdir(parents=True)
    (store / "weights").write_bytes(b"x" * 1000)
    (snapshot / "model.safetensors").symlink_to(store / "weights")
    (repo / "blobs" / "weights.ee45.incomplete").write_bytes(b"x")  # left by a download that was resumed later
    assert local.cached_bytes("mlx-community/whisper-large-v3-turbo") == 1000
    assert local.cached_bytes("mlx-community/not-here") == 0
