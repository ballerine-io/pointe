"""Registration, click-to-switch and the localhost guard, through the daemon's HTTP app."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _client(tmp_path):
    (tmp_path / "token").write_text("secret")
    os.environ["CLAUDE_VOICE_STATE"] = str(tmp_path)
    import daemon
    from fastapi.testclient import TestClient

    daemon.TOKEN = "secret"
    daemon.REGISTRY.sessions.clear()
    daemon.REGISTRY.active_id = None
    return daemon, TestClient(daemon.app, base_url="http://127.0.0.1:7860", cookies={"pointe_local": daemon.PAGE_KEY})


def _register(client, sid, name, token="secret"):
    return client.post("/voice/register", headers={"authorization": f"Bearer {token}"},
                       json={"id": sid, "name": name, "cwd": "/tmp", "pid": os.getpid(), "transcript": "/tmp/none"})


def test_register_requires_the_token(tmp_path):
    _, client = _client(tmp_path)
    assert _register(client, "a", "alpha/main", token="wrong").status_code == 403
    assert _register(client, "a", "alpha/main").json() == {"name": "alpha/main", "active": True}


def test_click_switches_the_active_session(tmp_path):
    _, client = _client(tmp_path)
    _register(client, "a", "alpha/main"), _register(client, "b", "beta/main")
    assert client.get("/voice/status").json()["active"] == "alpha/main"
    assert client.post("/voice/switch", json={"name": "beta/main"}).json() == {"active": "beta/main"}
    assert client.get("/voice/status").json()["active"] == "beta/main"
    assert client.post("/voice/switch", json={"name": "nope"}).status_code == 404


def test_other_web_pages_cannot_switch(tmp_path):
    _, client = _client(tmp_path)
    _register(client, "a", "alpha/main"), _register(client, "b", "beta/main")
    r = client.post("/voice/switch", json={"name": "beta/main"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert client.get("/voice/status").json()["active"] == "alpha/main"


def test_session_mode_pins_routing_and_toggle_works(tmp_path):
    import asyncio
    daemon, client = _client(tmp_path)
    _register(client, "a", "alpha/main"), _register(client, "b", "beta/main")
    assert client.post("/voice/mode", json={"mode": "session"}).json() == {"mode": "session"}
    daemon.state.last_utterance = "tell beta to run the tests"  # a name, but session mode ignores it
    targets, how = asyncio.run(daemon._route("run the tests"))
    assert [t.name for t in targets] == ["alpha/main"] and how == "session mode"
    assert client.post("/voice/mode", json={"mode": "orchestrator"}).json() == {"mode": "orchestrator"}
    targets, how = asyncio.run(daemon._route("run the tests"))
    assert [t.name for t in targets] == ["beta/main"] and how == "named"
    assert client.post("/voice/mode", json={"mode": "chaos"}).status_code == 400


def test_click_rename(tmp_path):
    _, client = _client(tmp_path)
    _register(client, "a", "alpha/main"), _register(client, "b", "beta/main")
    assert client.post("/voice/rename", json={"name": "alpha/main", "new_name": "pricing"}).json() == {"name": "pricing"}
    assert client.post("/voice/rename", json={"name": "beta/main", "new_name": "pricing"}).status_code == 409
    assert client.post("/voice/rename", json={"name": "beta/main", "new_name": "<b>"}).status_code == 400
    names = [s["name"] for s in client.get("/voice/status").json()["sessions"]]
    assert names == ["pricing", "beta/main"]


def test_context_and_token_count_follow_the_models_usage_report(tmp_path):
    import asyncio

    from pipecat.frames.frames import MetricsFrame
    from pipecat.metrics.metrics import LLMTokenUsage, LLMUsageMetricsData
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.frame_processor import FrameDirection

    daemon, client = _client(tmp_path)
    daemon.state.context = LLMContext([{"role": "user", "content": "[voice connected] hi"}])
    daemon.state.tokens = None
    usage = LLMTokenUsage(prompt_tokens=12345, completion_tokens=67, total_tokens=12412)
    tap = daemon.BotSpeechTap()

    async def push(frame, direction=FrameDirection.DOWNSTREAM):
        pass

    tap.push_frame = push
    tap._FrameProcessor__check_started = lambda frame: True
    asyncio.run(tap.process_frame(MetricsFrame(data=[LLMUsageMetricsData(processor="llm", value=usage)]),
                                  FrameDirection.DOWNSTREAM))
    body = client.get("/voice/context").json()
    assert body["tokens"]["context"] == 12345 and body["tokens"]["reply"] == 67
    assert body["messages"] == [{"role": "user", "content": "[voice connected] hi"}]
    assert client.get("/voice/status").json()["tokens"]["context"] == 12345


def test_journal_survives_pipecat_removing_log_sinks_at_startup(tmp_path, monkeypatch):
    from loguru import logger

    daemon, _ = _client(tmp_path)
    monkeypatch.setattr(daemon, "JOURNAL", tmp_path / "journal.jsonl")
    monkeypatch.setattr(daemon, "_journal_sink", None)
    logger.remove()  # what pipecat.runner.run.main() does before serving
    daemon._start_journal()
    monkeypatch.setattr(daemon.REGISTRY, "path", tmp_path / "sessions.json")
    daemon._apply_mode("orchestrator")  # logs from the daemon module, as a call does
    assert '"event": "mode -> orchestrator"' in (tmp_path / "journal.jsonl").read_text()


def test_the_call_reports_token_usage():
    import daemon

    assert daemon.VOICE_PARAMS.enable_usage_metrics  # without it Gemini's usage never leaves the service


def test_text_sent_to_the_model_is_recorded_as_the_users_turn(tmp_path):
    import asyncio

    from pipecat.frames.frames import InputTextRawFrame
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.frame_processor import FrameDirection

    daemon, client = _client(tmp_path)
    daemon.state.context = LLMContext([])
    tap, passed = daemon.ContextUserTap(), []

    async def push(frame, direction=FrameDirection.DOWNSTREAM):
        passed.append(frame)

    tap.push_frame = push
    tap._FrameProcessor__check_started = lambda frame: True
    asyncio.run(tap.process_frame(InputTextRawFrame(text="what is Mika doing"), FrameDirection.DOWNSTREAM))
    assert passed == []  # the assistant aggregator would fold it into the bot's next message
    body = client.get("/voice/context").json()
    assert body["messages"] == [{"role": "user", "content": "what is Mika doing"}]
    kinds = {r["kind"]: r for r in body["breakdown"]}
    assert kinds["user speech"]["count"] == 1 and kinds["instructions"]["est_tokens"] > 0


def test_a_page_event_reaches_the_journal_cleaned(tmp_path, monkeypatch):
    daemon, client = _client(tmp_path)
    monkeypatch.setattr(daemon, "JOURNAL", tmp_path / "journal.jsonl")
    monkeypatch.setattr(daemon, "_journal_sink", None)
    daemon._start_journal()
    assert client.post("/voice/page-event", json={"event": "phone layout: media key pause\n" + "x" * 500}).status_code == 200
    line = (tmp_path / "journal.jsonl").read_text().splitlines()[-1]
    event = json.loads(line)["event"]
    assert event.startswith("page: phone layout: media key pause ") and len(event) <= 206
    forged = client.post("/voice/page-event", json={"event": "x"}, headers={"origin": "https://evil.example"})
    assert forged.status_code == 403


def test_a_failure_reaches_the_page_without_the_key(tmp_path, monkeypatch):
    daemon, client = _client(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value")
    daemon._start_journal()
    daemon.logger.error("x" * 190 + " sk-secret-value")  # cut after masking: never part of a key
    assert "sk-" not in client.get("/voice/status").json()["problem"]
    daemon.logger.error("brain failed: AuthenticationError: bad key sk-secret-value")
    problem = client.get("/voice/status").json()["problem"]
    assert "AuthenticationError" in problem and "sk-secret-value" not in problem
    monkeypatch.setattr(daemon, "PROBLEM_SHOWN_SECS", -1.0)
    assert client.get("/voice/status").json()["problem"] is None


def test_the_address_with_the_page_key_stays_out_of_the_log(tmp_path):
    import logging

    daemon, _ = _client(tmp_path)
    daemon._start_journal()
    assert logging.getLogger("uvicorn.access").disabled
