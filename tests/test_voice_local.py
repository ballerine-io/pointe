"""Voice stays on your Mac: ears and mouth local, text models in the cloud. No audio may reach a vendor, whatever keys
exist: every cloud audio client is made to fail here, and the setup must still build its whole call."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daemon  # noqa: E402  (imported at collection, under conftest's state dir)
import local  # noqa: E402
import vendors  # noqa: E402

EVERY_KEY = {"GOOGLE_API_KEY": "g", "OPENAI_API_KEY": "o", "ANTHROPIC_API_KEY": "a", "SONIOX_API_KEY": "s",
             "ELEVENLABS_API_KEY": "e"}


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_VOICE_STATE", str(tmp_path))
    for env in ("CLAUDE_VOICE_LOCAL_ONLY", "CLAUDE_VOICE_VOICE_LOCAL", "CLAUDE_VOICE_LOCAL_URL", "CLAUDE_VOICE_BRAIN",
                "CLAUDE_VOICE_READER", "CLAUDE_VOICE_CHECKER", "CLAUDE_VOICE_EARS", "CLAUDE_VOICE_MOUTH", *EVERY_KEY):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(vendors, "_clients", {})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 44, "", ""))  # no Keychain
    return tmp_path


@pytest.fixture
def every_key(monkeypatch):
    for env, value in EVERY_KEY.items():
        monkeypatch.setenv(env, value)


def voice_local_on(state):
    local.write_voice_config()
    assert vendors.voice_local()


CLOUD_AUDIO = [
    ("pipecat.services.soniox.stt", "SonioxSTTService"),
    ("pipecat.services.soniox.tts", "SonioxTTSService"),
    ("pipecat.services.google.gemini_live.stt", "GeminiSTTService"),
    ("pipecat.services.google.tts", "GeminiTTSService"),
    ("pipecat.services.openai.stt", "OpenAIRealtimeSTTService"),
    ("pipecat.services.openai.tts", "OpenAITTSService"),
    ("pipecat.services.openai.realtime.llm", "OpenAIRealtimeLLMService"),
    ("pipecat.services.elevenlabs.stt", "ElevenLabsRealtimeSTTService"),
    ("pipecat.services.elevenlabs.tts", "ElevenLabsHttpTTSService"),
]


@pytest.fixture
def no_cloud_audio(monkeypatch):
    """Constructing any cloud speech client, or opening any WebSocket, fails the test."""
    import importlib

    def refuse(name):
        def init(self, *a, **k):
            raise AssertionError(f"a cloud audio client was constructed: {name}")
        return init

    for module, cls in CLOUD_AUDIO:
        monkeypatch.setattr(getattr(importlib.import_module(module), cls), "__init__", refuse(cls))

    async def no_socket(*a, **k):
        raise AssertionError(f"a WebSocket was opened: {a[:1]}")

    import websockets.asyncio.client

    monkeypatch.setattr(websockets.asyncio.client, "connect", no_socket)


def test_ears_and_mouth_are_local_and_the_brain_stays_in_the_cloud(state, every_key):
    voice_local_on(state)
    s = vendors.resolve("brain")
    assert s.ears == vendors.LOCAL and s.mouth == local.VOICE_MOUTH
    assert s.brain == vendors.BRAIN_ORDER[0] and s.reader == vendors.READER_ORDER[0]
    assert s.checker == vendors.CHECKER_ORDER[0]  # the Gemini gate, text only


def test_only_the_brains_key_is_needed(state, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    voice_local_on(state)
    s = vendors.resolve("brain")
    assert s.brain.startswith("anthropic:") and s.checker.startswith("anthropic:") and s.ears == vendors.LOCAL


def test_audio_only_keys_are_never_read(state, every_key):
    voice_local_on(state)
    assert vendors.key("soniox") is None and vendors.key("elevenlabs") is None
    assert not vendors.has("soniox")  # so neither the echo-guard mirror nor meeting ears can start
    assert vendors.key("anthropic") == "a" and vendors.key("gemini") == "g"


@pytest.mark.parametrize("role,value", [("ears", "soniox"), ("ears", "gemini"), ("mouth", "elevenlabs:eleven_v4_turbo"),
                                        ("mouth", "gemini:gemini-3.8-flash-lite-tts")])
def test_a_cloud_ear_or_mouth_is_refused_never_used(state, every_key, role, value):
    voice_local_on(state)
    config = json.loads((state / "config.json").read_text())
    (state / "config.json").write_text(json.dumps({**config, role: value}))
    with pytest.raises(SystemExit, match="Voice stays on your Mac"):
        vendors.resolve("brain")


def test_the_environment_cannot_put_ears_back_in_the_cloud(state, every_key, monkeypatch):
    voice_local_on(state)
    monkeypatch.setenv("CLAUDE_VOICE_EARS", "soniox")
    with pytest.raises(SystemExit, match="Voice stays on your Mac"):
        vendors.resolve("brain")


def test_a_realtime_front_that_hears_the_audio_is_refused(state, every_key):
    voice_local_on(state)
    with pytest.raises(SystemExit, match="Voice stays on your Mac"):
        vendors.resolve("gemini")


def test_building_a_cloud_ear_or_mouth_directly_is_refused(state, every_key, no_cloud_audio):
    voice_local_on(state)
    for vendor in ("soniox", "gemini", "openai", "elevenlabs"):
        with pytest.raises(SystemExit, match="Voice stays on your Mac"):
            vendors.build_ears(vendor, [])
    for choice in ("elevenlabs:eleven_v4_turbo", "gemini:x", "openai:gpt-4o-mini-tts", "soniox:tts-rt-v2"):
        with pytest.raises(SystemExit, match="Voice stays on your Mac"):
            vendors.build_mouth(choice, 24000, None)


def test_the_whole_call_builds_with_every_key_present_and_no_cloud_audio_client(state, every_key, no_cloud_audio,
                                                                               monkeypatch):
    pytest.importorskip("mlx_whisper", reason="the local extra on Apple silicon")
    voice_local_on(state)
    monkeypatch.setattr(daemon, "_setup", None)
    monkeypatch.setattr(daemon, "EARS", "auto")
    ears, mirror, stt = daemon._call_ears()
    assert mirror == [] and stt in ears
    assert type(stt).__name__ == "MLXWhisperEars"
    mouth = vendors.build_mouth(daemon.setup().mouth, daemon.MIRROR_RATE, None)
    assert type(mouth).__name__ == "KokoroMLXTTSService"


def test_the_mirror_stream_refuses_to_connect(state, every_key, no_cloud_audio):
    voice_local_on(state)
    with pytest.raises(vendors.CloudAudioRefused):
        asyncio.run(daemon.MirrorEars([])._open(24000))


def test_meeting_ears_refuse_to_connect(state, every_key, no_cloud_audio):
    import meeting

    voice_local_on(state)
    ears = meeting.MeetingEars("s", 16000, [], lambda *a: None)
    with pytest.raises(vendors.CloudAudioRefused):
        asyncio.run(ears.open())


def test_meeting_mode_says_why_it_is_off(state, every_key, monkeypatch):
    voice_local_on(state)
    monkeypatch.setattr(daemon.state, "conn", object())
    monkeypatch.setattr(daemon.state, "mic_gate", object())
    monkeypatch.setattr(daemon.state, "meeting", None)
    monkeypatch.setattr(daemon.state, "meeting_starting", False)
    why = asyncio.run(daemon.start_meeting("listening"))
    assert why and "Voice stays on your Mac" in why


def test_fully_local_mode_is_voice_local_too(state, every_key):
    local.write_config()
    assert vendors.voice_local()


def test_pointe_local_voice_keeps_other_settings_and_off_restores_them(state):
    before = {"brain": "anthropic:claude-sonnet-5-5", "approvals": "terminal", "mouth": "elevenlabs:eleven_v4_turbo"}
    (state / "config.json").write_text(json.dumps(before))
    local.write_voice_config()
    now = json.loads((state / "config.json").read_text())
    assert now["brain"] == before["brain"] and now["approvals"] == "terminal"
    assert now["voice_local"] is True and now["ears"] == "local" and now["mouth"] == local.VOICE_MOUTH
    local.restore_config()
    assert json.loads((state / "config.json").read_text()) == before


def test_from_fully_local_to_voice_local_the_text_models_go_back_to_the_cloud(state, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    local.write_config()
    local.write_voice_config()
    config = json.loads((state / "config.json").read_text())
    assert "local_only" not in config and not str(config.get("brain", "")).startswith("local:")
    assert vendors.resolve("brain").brain.startswith("anthropic:")


def test_pointe_local_voice_without_a_text_key_says_which_key_to_add(state, capsys, monkeypatch):
    monkeypatch.setattr(local, "supported_voice", lambda: None)
    assert local.main(["voice"]) == 1
    assert "pointe key anthropic" in capsys.readouterr().out
    assert not (state / "config.json").exists()


def test_status_names_the_setup(state, every_key, monkeypatch):
    voice_local_on(state)
    monkeypatch.setattr(local, "cached_bytes", lambda repo: 1_000_000_000)
    monkeypatch.setattr(local, "kokoro_bytes", lambda: 0)
    assert "Voice stays on your Mac: on" in "\n".join(local.status_lines())


def test_doctor_names_the_setup_and_what_leaves_the_mac(state, every_key, capsys, monkeypatch):
    import doctor

    voice_local_on(state)
    monkeypatch.setattr(local, "cached_bytes", lambda repo: 1)
    monkeypatch.setattr(local, "kokoro_bytes", lambda: 1)
    doctor.main()
    out = capsys.readouterr().out
    assert "Voice stays on your Mac" in out and "text only" in out
    assert "Next key" not in out  # no Soniox or ElevenLabs upsell: their keys are never read here


def test_preflight_passes_with_only_an_anthropic_key(state, monkeypatch):
    import doctor

    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    voice_local_on(state)
    assert doctor.preflight() == 0


def test_the_mlx_mouth_streams_a_sentence_as_it_is_made(monkeypatch):
    """The generator runs in its own thread; each segment it yields is sent at once, as 16-bit audio at the call's rate."""
    import numpy as np

    import kokoro_mlx

    class Fake:
        def generate(self, text, voice, lang_code, speed, verbose):
            assert lang_code == "a" and voice == "af_heart"
            for n in (2400, 4800):
                yield type("R", (), {"audio": np.full(n, 0.5, dtype=np.float32)})()

    monkeypatch.setattr(kokoro_mlx, "_model", lambda: Fake())
    tts = kokoro_mlx.KokoroMLXTTSService(sample_rate=24000, voice="af_heart")

    async def run():
        tts._sample_rate = 24000
        return [f async for f in tts.run_tts("Hello there.", "ctx")]

    frames = [f for f in asyncio.run(run()) if type(f).__name__ == "TTSAudioRawFrame"]
    assert sum(len(f.audio) for f in frames) // 2 == 7200 and frames[0].sample_rate == 24000


def test_british_voices_use_the_british_pipeline():
    import kokoro_mlx

    assert kokoro_mlx.lang_code("bf_emma") == "b" and kokoro_mlx.lang_code("af_heart") == "a"


def test_the_mouth_loads_kokoro_from_the_downloaded_folder(monkeypatch, tmp_path):
    """mlx-audio guesses the model type from a folder's name; a snapshot folder is named by a hash, so it is told."""
    mlx_audio_utils = pytest.importorskip("mlx_audio.tts.utils", reason="the local extra on Apple silicon")
    import huggingface_hub

    import kokoro_mlx

    seen = {}
    monkeypatch.setattr(kokoro_mlx, "_loaded", None)
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda repo, local_files_only: str(tmp_path / "a71e4d38"))
    monkeypatch.setattr(mlx_audio_utils, "load_model", lambda path, **k: seen.update(path=path, **k) or "model")
    assert kokoro_mlx._model() == "model" and seen["model_type"] == "kokoro"


def test_onnxruntime_telemetry_is_off_while_the_voice_stays_local(state, monkeypatch):
    monkeypatch.delenv("ORT_DISABLE_TELEMETRY", raising=False)
    vendors.quiet_native_telemetry()
    assert "ORT_DISABLE_TELEMETRY" not in __import__("os").environ  # other setups: unchanged, until decided
    voice_local_on(state)
    vendors.quiet_native_telemetry()
    assert __import__("os").environ["ORT_DISABLE_TELEMETRY"] == "1"


def test_the_daemon_turns_it_off_before_any_import_of_onnxruntime():
    source = (Path(__file__).resolve().parents[1] / "daemon.py").read_text()
    assert source.index("vendors.quiet_native_telemetry()") < min(
        source.index(m) for m in ("import speaker", "import vocabulary", "from pipecat", "import phone"))
