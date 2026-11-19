"""Every Soniox real-time stream asks for the one model in vendors.SONIOX_RT_MODEL: read from the start message each
stream sends, not from the constant, since pipecat's SonioxSTTService has a default of its own (stt-rt-v5)."""

import asyncio
import json
import re
import sys
from pathlib import Path

import pytest
import websockets.asyncio.client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import daemon  # noqa: E402  (imported at collection, under conftest's state dir)
import meeting  # noqa: E402
import vendors  # noqa: E402


class Socket:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


@pytest.fixture
def socket(monkeypatch):
    sock = Socket()

    async def connect(*args, **kwargs):
        return sock

    monkeypatch.setattr(websockets.asyncio.client, "connect", connect)
    monkeypatch.setenv("SONIOX_API_KEY", "test-key")
    for env in ("CLAUDE_VOICE_LOCAL_ONLY", "CLAUDE_VOICE_VOICE_LOCAL"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(vendors, "voice_local", lambda: False)
    monkeypatch.setattr(vendors, "local_only", lambda: False)
    return sock


def start_message(sock: Socket) -> dict:
    return json.loads(next(m for m in sock.sent if isinstance(m, str) and m.startswith("{")))


def test_the_model_is_v6():
    assert vendors.SONIOX_RT_MODEL == "stt-rt-v6"  # Soniox removes stt-rt-v5 on 2026-12-15


def test_the_ears_ask_for_it_with_their_endpoint_and_language_settings(socket):
    stt = vendors.build_ears("soniox", ["Pointe"])

    async def go():
        stt._websocket_connect = websockets.asyncio.client.connect
        await stt._connect_websocket()
    asyncio.run(go())
    sent = start_message(socket)
    assert sent["model"] == vendors.SONIOX_RT_MODEL
    assert sent["enable_endpoint_detection"] is True  # Soniox decides the turn's end, not pipecat's VAD
    assert sent["endpoint_sensitivity"] == -0.5 and sent["max_endpoint_delay_ms"] == 2500
    assert sorted(sent["language_hints"]) == ["en", "he"]  # pipecat de-duplicates them through a set


def test_the_echo_guards_mirror_asks_for_it(socket):
    ears = daemon.MirrorEars(["Pointe"])

    async def go():
        await ears._open(24000)
        await ears._close()
    asyncio.run(go())
    sent = start_message(socket)
    assert sent["model"] == vendors.SONIOX_RT_MODEL and sent["language_hints"] == ["en", "he"]


def test_meeting_ears_ask_for_it(socket):
    ears = meeting.MeetingEars("test-key", 16000, ["Pointe"], lambda *a: None)

    async def go():
        await ears.open()
        await ears.close()
    asyncio.run(go())
    sent = start_message(socket)
    assert sent["model"] == vendors.SONIOX_RT_MODEL and sent["enable_speaker_diarization"] is True


def test_no_other_code_the_daemon_runs_names_a_soniox_realtime_model():
    named = {str(p.relative_to(ROOT)) for p in ROOT.glob("*.py") if re.search(r"stt-rt-v\d", p.read_text())}
    assert named == {"vendors.py"}
