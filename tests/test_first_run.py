"""A stranger's first run: the bin scripts find uv where its installer puts it, work before the first download, and a
wrong key is named as a wrong key. The error texts are the vendors' own, captured with made-up keys."""

import asyncio
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]

import daemon  # noqa: E402
import doctor  # noqa: E402
import vendors  # noqa: E402

FAKE_UV = """#!/bin/sh
echo "$@" >> "$HOME/uv-calls"
"""


@pytest.fixture
def stranger(tmp_path):
    """A HOME where uv's installer put uv (~/.local/bin), and a PATH that does not include it, nor node."""
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    uv = home / ".local" / "bin" / "uv"
    uv.write_text(FAKE_UV)
    uv.chmod(0o755)
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "CLAUDE_VOICE_STATE": str(tmp_path / "state"),
           "CLAUDE_VOICE_DAEMON_PORT": "7979"}
    return SimpleNamespace(home=home, env=env, calls=lambda: (home / "uv-calls").read_text() if (home / "uv-calls").exists() else "")


def run(script: str, *args: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([str(ROOT / "bin" / script), *args], env=env, capture_output=True, text=True, timeout=30)


def test_doctor_finds_uv_where_its_installer_put_it(stranger):
    out = run("voice-doctor", env=stranger.env)
    assert "MISSING  uv" not in out.stdout
    assert "doctor.py" in stranger.calls()


def test_doctor_does_not_call_node_missing(stranger):
    out = run("voice-doctor", env=stranger.env)
    assert "MISSING  node" not in out.stdout
    assert "node" in out.stdout  # still said, as optional


def test_pointe_key_finds_uv_and_installs_what_it_needs(stranger):
    run("pointe", "key", "gemini", env=stranger.env)
    calls = stranger.calls()
    assert "keys.py" in calls
    assert calls.splitlines()[0].startswith("sync --locked")  # before the first download there is nothing to run unsynced


@pytest.mark.parametrize("command,arg", [("pair", "--help"), ("join", "opencode"), ("leave", "opencode")])
def test_every_python_command_syncs_first(stranger, command, arg):
    run("pointe", command, arg, env=stranger.env)  # join --help and leave --help print their line and run nothing
    calls = stranger.calls().splitlines()
    assert calls and calls[0].startswith("sync --locked") and len(calls) == 2  # the cache satisfied it: no second sync


def test_daemon_finds_uv_where_its_installer_put_it(stranger):
    run("voice-daemon", "ensure", env=stranger.env)
    assert "sync --locked" in stranger.calls()


def test_no_key_advice_points_to_the_keychain_window_not_a_terminal():
    assert "pointe key gemini" in doctor.NO_KEY
    assert "/pointe:setup" in doctor.NO_KEY
    assert doctor.NO_KEY.index("pointe key gemini") < doctor.NO_KEY.index("GOOGLE_API_KEY=")  # the environment is the last resort


REFUSALS = {
    "gemini": "GeminiSTTService#1 exception (/x/claude-config/plugins/cache/pointe/.venv/google/genai/errors.py:220): "
              "Error setting up processor: 1007 None. API key not valid. Please pass a valid API key.",
    "soniox": "SonioxSTTService#0 error: Error: 401 (_receive_messages) - Incorrect API key provided. You can get an API key "
              "at https://console.soniox.com",
    "elevenlabs": 'ElevenLabsHttpTTSService#0 error: ElevenLabs API error: {"detail":{"type":"authentication_error",'
                  '"code":"unauthorized","message":"Invalid API key","status":"invalid_api_key"}}',
}


@pytest.mark.parametrize("vendor", REFUSALS)
def test_a_refused_key_is_named_with_its_vendor(vendor):
    assert vendors.refused_key(REFUSALS[vendor]) == vendor


@pytest.mark.parametrize("text", [
    "Error code: 401 - {'type': 'error', 'error': {'type': 'authentication_error', 'message': 'invalid x-api-key'}}",
    "Error code: 401 - Incorrect API key provided: SYNTHETI****0001.",
])
def test_a_text_model_refusal_is_recognized_without_a_vendor_name(text):
    assert vendors.refused_key(text) == ""


@pytest.mark.parametrize("text", ["voice: GeminiSTTService#1 can no longer do its job", "notes on app failed: ClientError",
                                  "gemini is out of quota or rate limited; openai answers for ten minutes"])
def test_other_errors_are_not_a_refused_key(text):
    assert vendors.refused_key(text) is None


def note(text: str) -> None:
    daemon._note_problem(SimpleNamespace(record={"message": text}))


def test_the_page_names_the_refused_key_and_keeps_it_over_what_follows(monkeypatch):
    monkeypatch.setattr(daemon, "_problem", (0.0, ""))
    note(REFUSALS["gemini"])
    note("voice: GeminiSTTService#1 can no longer do its job")
    note("ElevenLabsHttpTTSService#0 error: TTS context 1b3e completed with no audio")
    shown = daemon.current_problem()
    assert "gemini key was refused" in shown and "pointe key gemini" in shown


def test_a_text_model_refusal_reaches_the_page(monkeypatch):
    monkeypatch.setattr(daemon, "_problem", (0.0, ""))
    note(vendors.refused_help("anthropic"))
    note("notes on demo-app failed: AuthenticationError")
    assert "anthropic key was refused" in daemon.current_problem()


def test_other_problems_still_show(monkeypatch):
    monkeypatch.setattr(daemon, "_problem", (0.0, ""))
    note("notes on demo-app failed: TimeoutError")
    assert daemon.current_problem() == "notes on demo-app failed: TimeoutError"


@pytest.mark.parametrize("step", ["text", "step"])
def test_a_text_model_refusal_is_logged_with_its_vendor(monkeypatch, step):
    class AuthenticationError(Exception):
        pass

    async def refuse(*_):
        raise AuthenticationError("Error code: 401 - {'type': 'error', 'error': {'type': 'authentication_error'}}")

    monkeypatch.setitem(vendors._TEXT if step == "text" else vendors._STEP, "anthropic", refuse)
    logged = []
    monkeypatch.setattr(vendors.logger, "error", logged.append)
    call = vendors.text("anthropic:claude-haiku-5-5", "hi") if step == "text" else vendors.step("anthropic:claude-haiku-5-5", "", [], [])
    with pytest.raises(AuthenticationError):
        asyncio.run(call)
    assert logged == [vendors.refused_help("anthropic")]


def test_a_keyless_doctor_says_one_thing_to_do(monkeypatch, capsys):
    monkeypatch.setattr(vendors, "key", lambda vendor: None)
    monkeypatch.setattr(vendors, "config", lambda: {})
    for env in [*vendors.KEY_ENVS, "CLAUDE_VOICE_BRAIN", "CLAUDE_VOICE_READER", "CLAUDE_VOICE_CHECKER", "CLAUDE_VOICE_EARS",
                "CLAUDE_VOICE_MOUTH"]:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(sys, "argv", ["doctor.py"])
    doctor.main()
    out = capsys.readouterr().out
    assert "security add-generic-password" not in out
    assert out.count("pointe key gemini") == 1


def refusing_check(stranger):
    """uv as in the stranger's HOME, except that local.py's check refuses this Mac (no key, or not Apple silicon)."""
    uv = stranger.home / ".local" / "bin" / "uv"
    uv.write_text(FAKE_UV + 'case "$*" in *"local.py check"*) exit 1 ;; esac\n')


def test_pointe_local_checks_the_mac_and_key_before_installing_the_local_libraries(stranger):
    refusing_check(stranger)
    out = run("pointe", "local", "voice", env=stranger.env)
    assert out.returncode != 0
    assert "local.py check voice" in stranger.calls()
    assert "--extra local" not in stranger.calls()  # 1.1 GB of libraries, for a Mac that cannot use them


def test_pointe_local_says_what_it_installs_before_installing_it(stranger):
    out = run("pointe", "local", env=stranger.env)
    calls = stranger.calls()
    assert calls.index("local.py check") < calls.index("--extra local")
    assert "about 290 MB" in out.stdout + out.stderr


@pytest.mark.parametrize("command", ["off", "stop", "status"])
def test_pointe_local_off_stop_and_status_install_nothing(stranger, command):
    run("pointe", "local", command, env=stranger.env)
    assert "local.py" in stranger.calls() and "--extra local" not in stranger.calls()


def test_a_refusal_that_names_no_vendor_keeps_the_one_that_did(monkeypatch):
    monkeypatch.setattr(daemon, "_problem", (0.0, ""))
    note(vendors.refused_help("anthropic"))
    note("brain failed: AuthenticationError: Error code: 401 - {'type': 'error', 'error': {'type': "
         "'authentication_error', 'message': 'Invalid bearer token'}}")
    assert "anthropic key was refused" in daemon.current_problem()
