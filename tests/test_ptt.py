"""Push-to-talk: with the microphone set to push to talk, no audio passes the daemon's gate unless a press holds it open.
Offline: the gate, the serializer and the consent binding are driven directly.

uv run pytest -q tests/test_ptt.py
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import phone  # noqa: E402
import ptt  # noqa: E402
from test_orchestrator import _read_out_setup, client_for, d, verdicts  # noqa: E402,F401  (d is a fixture)

T0 = 1000.0


@pytest.fixture(autouse=True)
def _always_on_after():
    """The setting is saved: put it back, so no other test runs in push to talk."""
    yield
    if "daemon" in sys.modules:
        sys.modules["daemon"].PREFS.update({"microphone": "always"})


# ---------- the gate's truth table ----------

def test_always_on_passes_everything_and_push_to_talk_passes_nothing_until_pressed():
    assert ptt.Ptt().audio(640, "always", T0)
    p = ptt.Ptt()
    assert not p.audio(640, "ptt", T0 + 1)
    assert p.press(T0 + 2)
    assert p.audio(640, "ptt", T0 + 2.1)
    assert p.passed_bytes == 640 and p.dropped_bytes == 640


def test_release_keeps_a_tail_so_the_last_word_is_not_cut():
    p = ptt.Ptt()
    p.press(T0)
    assert p.release(T0 + 3)
    assert p.audio(640, "ptt", T0 + 3 + ptt.TAIL_SECS - 0.05)
    assert not p.audio(640, "ptt", T0 + 3 + ptt.TAIL_SECS + ptt.LINK_SLACK_SECS + 0.05)


def test_the_tail_ends_with_a_finalize_once():
    p = ptt.Ptt()
    p.press(T0)
    p.release(T0 + 1)
    assert p.tick("ptt", T0 + 1.1) == []
    assert p.tick("ptt", T0 + 2) == ["finalize"]
    assert p.tick("ptt", T0 + 3) == []


def test_a_press_held_too_long_closes_by_itself_and_says_why():
    p = ptt.Ptt()
    p.press(T0)
    for i in range(1, int(ptt.MAX_OPEN_SECS)):
        p.audio(640, "ptt", T0 + i)
        assert p.tick("ptt", T0 + i) == []
    assert "closed" in p.tick("ptt", T0 + ptt.MAX_OPEN_SECS + 0.1)
    assert not p.open and p.closed_why == "held too long"


def test_a_lost_release_closes_after_two_seconds_without_audio():
    p = ptt.Ptt()
    p.press(T0)
    p.audio(640, "ptt", T0 + 0.5)
    assert p.tick("ptt", T0 + 2.0) == []
    assert "closed" in p.tick("ptt", T0 + 0.5 + ptt.QUIET_LINK_SECS + 0.1)
    assert not p.open and p.closed_why == "no audio"


def test_always_on_never_auto_closes():
    p = ptt.Ptt()
    p.press(T0)
    assert p.tick("always", T0 + 500) == []


def test_switching_to_push_to_talk_mid_sentence_keeps_a_tail_and_finalizes():
    p = ptt.Ptt()
    assert p.audio(640, "always", T0)
    assert p.audio(640, "ptt", T0 + 0.1)  # the sentence already under way is finished, not cut
    assert not p.audio(640, "ptt", T0 + 1.5)
    assert "finalize" in p.tick("ptt", T0 + 1.5)


def test_a_second_press_while_open_is_not_a_new_press():
    p = ptt.Ptt()
    assert p.press(T0)
    assert not p.press(T0 + 1)
    assert p.opened_at == T0
    assert p.release(T0 + 2) and not p.release(T0 + 3)


def test_a_reconnect_starts_closed():
    p = ptt.Ptt()
    p.press(T0)
    p.audio(640, "ptt", T0)
    p.reset()
    assert not p.open and not p.audio(640, "ptt", T0 + 0.1) and p.passed_bytes == 0


def test_speech_in_a_press_began_at_the_press():
    p = ptt.Ptt()
    p.press(T0)
    assert p.speech_began(T0 + 2, "ptt") == T0
    assert p.speech_began(T0 + 2, "always") == T0 + 2
    p.release(T0 + 3)
    assert p.speech_began(T0 + 60, "ptt") == T0 + 60


def test_status_shows_the_truth():
    p = ptt.Ptt()
    p.press(T0)
    s = p.status("ptt")
    assert s["mode"] == "ptt" and s["open"] is True and s["opened_at"] == T0 and s["closed_why"] == ""
    json.dumps(s)


# ---------- the client's control message ----------

def test_the_socket_carries_a_ptt_control_and_ignores_garbage():
    ser = phone.PhoneSerializer()

    async def go(text):
        return await ser.deserialize(text)
    frame = asyncio.run(go(json.dumps({"type": "ptt", "open": True, "at": 123})))
    assert isinstance(frame, phone.PttFrame) and frame.open is True
    assert asyncio.run(go(json.dumps({"type": "ptt", "open": False}))).open is False
    for junk in ({"type": "ptt"}, {"type": "ptt", "open": "yes"}, {"type": "ptt", "open": 1}, {"type": "other"}):
        assert asyncio.run(go(json.dumps(junk))) is None


# ---------- the gate in the call ----------

def _gate(d, monkeypatch, mode="ptt", stt=None):
    d.PREFS.update({"microphone": mode})
    gate = d.PttGate(stt)
    pushed, interrupted = [], []

    async def push(frame, *a):
        pushed.append(frame)

    async def interrupt():
        interrupted.append(True)
    gate.push_frame = push
    gate.broadcast_interruption = interrupt
    monkeypatch.setattr(d.FrameProcessor, "process_frame", lambda self, f, dirn: asyncio.sleep(0))
    return gate, pushed, interrupted


def _audio(d):
    return d.InputAudioRawFrame(audio=b"\1\0" * 320, sample_rate=16000, num_channels=1)


async def _feed(d, gate, frame):
    await d.PttGate.process_frame(gate, frame, d.FrameDirection.DOWNSTREAM)


def test_no_audio_passes_the_gate_while_closed(d, monkeypatch):
    gate, pushed, _ = _gate(d, monkeypatch)
    asyncio.run(_feed(d, gate, _audio(d)))
    assert not any(isinstance(f, d.InputAudioRawFrame) for f in pushed)
    assert d.state.ptt.passed_bytes == 0


def test_a_press_opens_the_gate_and_binds_the_utterance_to_the_press(d, monkeypatch):
    gate, pushed, interrupted = _gate(d, monkeypatch)

    async def go():
        await _feed(d, gate, phone.PttFrame(open=True))
        await _feed(d, gate, _audio(d))
    before = time.time()
    asyncio.run(go())
    assert any(isinstance(f, d.InputAudioRawFrame) for f in pushed)
    assert any(isinstance(f, d.UserSpeakingFrame) for f in pushed)  # a press keeps a quiet push-to-talk call alive
    assert d.state.user_started_at >= before and not interrupted


def test_a_press_while_the_bot_speaks_interrupts_it(d, monkeypatch):
    gate, pushed, interrupted = _gate(d, monkeypatch)
    d.ECHO.speaking = True
    try:
        asyncio.run(_feed(d, gate, phone.PttFrame(open=True)))
    finally:
        d.ECHO.speaking = False
    assert interrupted


def test_always_on_ignores_presses(d, monkeypatch):
    gate, pushed, interrupted = _gate(d, monkeypatch, mode="always")
    asyncio.run(_feed(d, gate, _audio(d)))
    assert any(isinstance(f, d.InputAudioRawFrame) for f in pushed)


def test_release_finalizes_the_ears_after_the_tail(d, monkeypatch):
    sent = []

    class Ws:
        async def send(self, message):
            sent.append(message)
    gate, pushed, _ = _gate(d, monkeypatch, stt=SimpleNamespace(_websocket=Ws()))

    async def go():
        await _feed(d, gate, phone.PttFrame(open=True))
        await _feed(d, gate, phone.PttFrame(open=False))
        await gate.tick(time.time())
        assert sent == []  # the tail is still open
        await gate.tick(time.time() + 2)
    asyncio.run(go())
    assert sent == ['{"type": "finalize"}']


def test_a_release_with_nothing_said_does_not_leave_the_user_talking(d, monkeypatch):
    gate, _, _ = _gate(d, monkeypatch)

    async def go():
        await _feed(d, gate, phone.PttFrame(open=True))
        await _feed(d, gate, phone.PttFrame(open=False))
    asyncio.run(go())
    assert d.state.user_stopped_at >= d.state.user_started_at


def test_a_new_call_starts_closed(d, monkeypatch):
    d.PREFS.update({"microphone": "ptt"})
    d.state.ptt.press(time.time())
    d.PttGate(None)
    assert not d.state.ptt.open


# ---------- consent: a yes pressed before the read-out ended does not approve ----------

def _vad_start(d, monkeypatch):
    ears = d.SonioxEars()
    monkeypatch.setattr(d.FrameProcessor, "process_frame", lambda self, f, dirn: asyncio.sleep(0))

    async def push(*a):
        pass
    ears.push_frame = push
    asyncio.run(d.SonioxEars.process_frame(ears, d.VADUserStartedSpeakingFrame(), d.FrameDirection.DOWNSTREAM))


def test_a_yes_whose_press_began_before_the_read_out_ended_does_not_approve(d, monkeypatch):
    active, posts, said = _read_out_setup(d, monkeypatch)
    d.PREFS.update({"microphone": "ptt"})
    d.ECHO.stopped_at = time.time() - 3
    d.state.ptt.press(d.ECHO.stopped_at - 1)  # pressed while the read-out was still going
    _vad_start(d, monkeypatch)  # the voice starts well after the read-out ended
    asyncio.run(d.on_user_utterance("yes please"))
    # the request was heard: asked for the yes again in one line, not read again (test_reread_loop.py)
    assert verdicts(posts) == [] and said == ["I need the yes after I finish. Say it again."]


def test_a_yes_pressed_after_the_read_out_still_approves(d, monkeypatch):
    active, posts, said = _read_out_setup(d, monkeypatch)
    d.PREFS.update({"microphone": "ptt"})
    d.ECHO.stopped_at = time.time() - 3
    d.state.ptt.press(d.ECHO.stopped_at + 1)
    _vad_start(d, monkeypatch)
    asyncio.run(d.on_user_utterance("yes please"))
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "allow"}]


# ---------- the setting and the status ----------

def test_the_microphone_setting_is_a_pref_both_clients_share(d):
    c = client_for(d)
    assert c.get("/voice/prefs").json()["microphone"] == "always"
    assert c.post("/voice/prefs", json={"microphone": "ptt"}).json()["microphone"] == "ptt"
    assert c.post("/voice/prefs", json={"microphone": "hold"}).status_code == 400
    s = c.get("/voice/status").json()["ptt"]
    assert s["mode"] == "ptt" and s["open"] is False
    c.post("/voice/prefs", json={"microphone": "always"})


# ---------- a meeting: the room is heard without a press; the conversation still needs one ----------

def _in_meeting(d, monkeypatch):
    from test_meeting_daemon import FakeEars, _meeting_ready, _start
    _meeting_ready(d, monkeypatch)
    d.PREFS.update({"meeting.consented": True, "microphone": "ptt"})
    _start(d)
    return FakeEars.instances[-1]


def test_in_a_meeting_the_room_reaches_the_meeting_stream_without_a_press(d, monkeypatch):
    ears = _in_meeting(d, monkeypatch)
    ptt_gate, pushed, _ = _gate(d, monkeypatch)
    mic = d.MicGate()
    to_conversation = []

    async def onward(frame, *a):
        to_conversation.append(frame)
    mic.push_frame = onward

    async def go():
        await _feed(d, ptt_gate, _audio(d))
        for f in [f for f in pushed if isinstance(f, d.InputAudioRawFrame)]:
            await d.MicGate.process_frame(mic, f, d.FrameDirection.DOWNSTREAM)
    asyncio.run(go())
    assert ears.sent, "the room's audio must reach the meeting stream"
    assert not any(isinstance(f, d.InputAudioRawFrame) for f in to_conversation)
    status = client_for(d).get("/voice/status").json()["ptt"]
    assert status["room_heard"] is True and status["sent_bytes"] == 0 and status["room_bytes"] > 0


def test_room_audio_that_finds_no_meeting_stream_never_reaches_the_conversation_without_a_press(d, monkeypatch):
    _in_meeting(d, monkeypatch)
    d.state.meeting_ears = None  # the room's stream is reconnecting
    ptt_gate, pushed, _ = _gate(d, monkeypatch)
    mic = d.MicGate()
    to_conversation = []

    async def onward(frame, *a):
        to_conversation.append(frame)
    mic.push_frame = onward

    async def go():
        await _feed(d, ptt_gate, _audio(d))
        for f in [f for f in pushed if isinstance(f, d.InputAudioRawFrame)]:
            await d.MicGate.process_frame(mic, f, d.FrameDirection.DOWNSTREAM)
    asyncio.run(go())
    assert not any(isinstance(f, d.InputAudioRawFrame) for f in to_conversation)


def test_outside_a_meeting_the_status_says_the_room_is_not_heard(d):
    d.PREFS.update({"microphone": "ptt"})
    assert client_for(d).get("/voice/status").json()["ptt"]["room_heard"] is False
