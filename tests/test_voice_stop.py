"""A spoken "stop" ends the running turn through the harness, never as a message read after it.

Claude Code has no supported way for another process to cut a running turn: the plugin's PreToolUse and PostToolUse
hook (bin/voice-stop-hook) returns "continue": false at the next tool step. Codex and OpenCode cut it at once
(tests/test_codex.py, tests/test_opencode.py). A stop is never a yes.

uv run pytest -q tests/test_voice_stop.py
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import guards  # noqa: E402
import harnesses  # noqa: E402
from harnesses.claude_code import ClaudeCode, stop_flag  # noqa: E402
from test_orchestrator import add, d, fake_conn, record_dispatch  # noqa: E402,F401  (d is a fixture)

HOOK = Path(__file__).resolve().parents[1] / "bin" / "voice-stop-hook"


@pytest.mark.parametrize("said", ["Stop.", "stop it now, please", "Cancel that.", "Hold on.", "hold on, stop that",
                                  "Abort it.", "kill that job", "עצור"])
def test_a_stop_is_a_stop(said):
    assert guards.stop_intent(said) == "stop"


@pytest.mark.parametrize("said", ["Stop, and delete the files it made.", "No wait, write them to the archive folder.",
                                  "Cancel that and run the linter instead.", "Hang on, change of plan: use port 9000."])
def test_a_stop_with_more_ends_the_turn_and_leaves_a_request(said):
    assert guards.stop_intent(said) == "redirect"


@pytest.mark.parametrize("said", ["tell billing to stop retrying failed jobs", "Make the poller stop when it is empty",
                                  "wait", "wait, what is it?", "Wait, did it go live?", "hold on, let me think",
                                  "stop asking", "okay, cool", "yeah, go on", "keep going", "yes", "go ahead"])
def test_these_are_not_a_stop(said):
    assert guards.stop_intent(said) is None


@pytest.mark.parametrize("said", ["Stop.", "Cancel that.", "Hold on.", "hold on, stop that", "Abort it.", "Hang on.",
                                  "No wait, write them to the archive folder.", "Stop, stop, stop."])
def test_a_stop_never_approves(said):
    assert guards.permission_answer(said) != "allow"
    assert guards.consent(said) != "allow"


def _working(d, harness="claude-code", tmp=None):
    s = add(d, "a", "ledger", harness=harness, transcript=str(tmp / "c0ffee-1234.jsonl") if tmp else "/tmp/none.jsonl")
    d.REGISTRY.active_id = s.id
    s.busy = True
    d.state.conn = fake_conn()
    return s


class Speaker:
    def __init__(self):
        self.said: list[str] = []

    async def _speak(self, text, request_id=None):
        self.said.append(text)


def test_a_spoken_stop_leaves_a_next_step_stop_for_claude_code_and_sends_nothing(d, monkeypatch, tmp_path):
    monkeypatch.setattr(harnesses.HOST, "state_dir", tmp_path)
    s = _working(d, tmp=tmp_path)
    sent = record_dispatch(d, monkeypatch)
    d.state.front = Speaker()
    asyncio.run(d.on_user_utterance("Stop."))
    flag = tmp_path / "stop" / "c0ffee-1234"
    assert flag.exists() and s.stop_asked_at is not None
    assert d.state.utterance_spent and sent == []
    assert d.state.front.said == ["Stopping ledger after the step it's on."]


def test_a_stop_goes_through_the_harness_that_can_cut_the_turn(d, monkeypatch):
    s = _working(d, harness="codex")
    cut = []

    async def interrupt(session):
        cut.append(session.name)
        return True

    monkeypatch.setattr(harnesses.get("codex"), "interrupt", interrupt)
    d.state.front = Speaker()
    asyncio.run(d.on_user_utterance("cancel that"))
    assert cut == ["ledger"] and d.state.front.said == ["Stopped ledger."]
    assert s.stop_asked_at is None


def test_a_stop_with_nothing_running_is_left_to_the_conversation(d, monkeypatch):
    s = _working(d, harness="codex")
    s.busy = False
    cut = []

    async def interrupt(session):
        cut.append(session.name)
        return True

    monkeypatch.setattr(harnesses.get("codex"), "interrupt", interrupt)
    asyncio.run(d.on_user_utterance("Stop."))
    assert cut == [] and not d.state.utterance_spent


def test_a_redirect_waits_for_the_stop_to_land_before_its_request_goes(d, monkeypatch, tmp_path):
    monkeypatch.setattr(harnesses.HOST, "state_dir", tmp_path)
    s = _working(d, tmp=tmp_path)
    d.state.front = Speaker()
    asyncio.run(d.on_user_utterance("No wait, write them to the archive folder."))
    assert not d.state.utterance_spent  # the brain sends the rest
    assert any("new request" in text for text, _ in d.state.conn.injector.fed)
    delivered = []

    async def deliver(target, message):
        delivered.append((time.time(), message))
        return True

    monkeypatch.setattr(d, "deliver", deliver)

    async def scenario():
        dispatch = asyncio.create_task(d._dispatch(s, "write the rest to archive"))
        await asyncio.sleep(0.5)
        assert delivered == []  # Claude Code would read it inside the turn being stopped
        flag = stop_flag(s, s.transcript)
        flag.rename(flag.with_name(flag.name + ".taken"))  # what the hook does
        await asyncio.wait_for(asyncio.create_task(d._watch_stop(s, s.stop_asked_at)), 2)
        await asyncio.wait_for(dispatch, 2)

    asyncio.run(scenario())
    assert [m for _, m in delivered] == ["write the rest to archive"] and s.stop_asked_at is None


def test_a_turn_that_ends_on_its_own_drops_its_stop(d, monkeypatch, tmp_path):
    monkeypatch.setattr(harnesses.HOST, "state_dir", tmp_path)
    s = _working(d, tmp=tmp_path)
    assert asyncio.run(ClaudeCode().interrupt(s))
    s.stop_asked_at = time.time()
    d._clear_stop(s)
    assert not (tmp_path / "stop" / "c0ffee-1234").exists() and s.stop_asked_at is None


def _hook(state: Path, event: dict) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_VOICE")}
    env["CLAUDE_VOICE_STATE"] = str(state)
    return subprocess.run([str(HOOK)], input=json.dumps(event), capture_output=True, text=True, env=env,
                          timeout=10).stdout


def test_the_hook_ends_the_turn_once_for_its_own_session_only(tmp_path):
    pre = {"hook_event_name": "PreToolUse", "session_id": "c0ffee-1234", "tool_name": "Bash"}
    assert _hook(tmp_path, pre) == ""  # nothing waiting: no decision, the normal flow
    (tmp_path / "stop").mkdir()
    (tmp_path / "stop" / "other-5678").write_text("1")
    assert _hook(tmp_path, pre) == ""  # another session's stop
    (tmp_path / "stop" / "c0ffee-1234").write_text("1")
    out = json.loads(_hook(tmp_path, pre))
    assert out["continue"] is False and out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert (tmp_path / "stop" / "c0ffee-1234.taken").exists()
    assert _hook(tmp_path, pre) == ""  # taken once
    (tmp_path / "stop" / "c0ffee-1234").write_text("1")
    post = json.loads(_hook(tmp_path, {**pre, "hook_event_name": "PostToolUse"}))
    assert post == {"continue": False, "stopReason": "Stopped: the user said stop to the voice."}


def test_every_harness_declares_how_it_stops():
    assert harnesses.get("claude-code").capabilities()["interrupt"] == "next_step"
    assert harnesses.get("opencode").capabilities()["interrupt"] == "now"
    assert harnesses.get("codex").capabilities()["interrupt"] == "now"
