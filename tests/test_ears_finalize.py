"""Soniox stt-rt-v6 holds some whole sentences open until about 3 s after the speech: after a silence the call asks it
for the words (`finalize`), once, and the settle still decides the turn (turns.finalize_due)."""

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import turns  # noqa: E402
from test_orchestrator import d  # noqa: E402,F401  (d is a fixture)

FIN = '{"type": "finalize"}'
NORMAL = turns.LEVELS["normal"]  # as shipped: the d fixture shortens it for other tests
NOW = 1000.0


@pytest.mark.parametrize("pending,voiced,ended,asked,now,due", [
    (True, False, NOW - 0.7, 0.0, NOW, True),  # words open, 0.7 s of silence
    (True, False, NOW - 0.6, 0.0, NOW, False),  # not yet
    (False, False, NOW - 3.0, 0.0, NOW, False),  # nothing held: Soniox ended it already
    (True, True, NOW - 3.0, 0.0, NOW, False),  # the user talks again
    (True, False, NOW - 3.0, NOW - 2.5, NOW, False),  # asked already in this silence
    (True, False, NOW - 0.8, NOW - 1.0, NOW, False),  # a new silence, but the last ask is too recent
    (True, False, NOW - 0.8, NOW - 2.5, NOW, True),  # a new silence after the gap
])
def test_when_the_held_words_are_asked_for(pending, voiced, ended, asked, now, due):
    assert turns.finalize_due(pending, voiced, ended, asked, now, "normal") is due


def test_the_ask_comes_when_a_whole_sentence_s_settle_would_end():
    assert turns.finalize_after("normal") == pytest.approx(0.7)
    assert turns.finalize_after("patient") == pytest.approx(1.5)  # a patient user keeps the longer pause
    assert turns.finalize_after("quick") == pytest.approx(0.2)  # never sooner than Soniox's 0.2 s


class Ws:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(message)


def _call(d, monkeypatch, mode="always"):
    from pipecat.services.soniox.stt import SonioxSTTService

    d.PREFS.update({"microphone": mode, "turns.patience": "normal"})
    monkeypatch.setitem(d.turns.LEVELS, "normal", NORMAL)
    stt = SonioxSTTService.__new__(SonioxSTTService)  # no key, no connection: only its socket is used
    stt._websocket = Ws()
    gate, ears = d.PttGate(stt), d.SonioxEars()
    monkeypatch.setattr(d.FrameProcessor, "process_frame", lambda self, f, dirn: asyncio.sleep(0))
    monkeypatch.setattr(ears, "create_task", lambda coro, name=None: asyncio.get_running_loop().create_task(coro))

    async def nowhere(*a, **k):
        pass
    gate.push_frame = ears.push_frame = nowhere
    gate.broadcast_interruption = ears.broadcast_interruption = nowhere
    d.state.user_started_at, d.state.user_stopped_at, d.state.unfinalized = 0.0, 0.0, False
    return gate, ears, stt._websocket


async def _interim(d, ears, text):
    from pipecat.frames.frames import InterimTranscriptionFrame

    await d.SonioxEars.process_frame(ears, InterimTranscriptionFrame(text=text, user_id="u", timestamp="t"),
                                     d.FrameDirection.DOWNSTREAM)


async def _final(d, ears, text):
    from pipecat.frames.frames import TranscriptionFrame

    await d.SonioxEars.process_frame(ears, TranscriptionFrame(text=text, user_id="u", timestamp="t"),
                                     d.FrameDirection.DOWNSTREAM)


def test_words_soniox_holds_after_a_silence_are_asked_for_once(d, monkeypatch):
    gate, ears, ws = _call(d, monkeypatch)
    start = time.time()

    async def go():
        d.state.user_started_at = start
        await _interim(d, ears, "Find the file that defines the user permissions.")
        d.state.user_stopped_at = start + 2.0  # the voice detector: stopped, 0.2 s after the sound
        await gate.tick(start + 2.4)
        assert ws.sent == []  # 0.6 s of silence: Soniox may still end it itself
        await gate.tick(start + 2.6)
        await gate.tick(start + 3.5)
        assert ws.sent == [FIN]  # once, at 0.7 s of silence
        await _final(d, ears, "Find the file that defines the user permissions.")
        assert d.state.unfinalized is False
    asyncio.run(go())


def test_nothing_is_asked_while_the_user_talks_or_after_soniox_ended_the_words(d, monkeypatch):
    gate, ears, ws = _call(d, monkeypatch)
    start = time.time()

    async def go():
        d.state.user_started_at = start + 1.0  # talking again: the stop before it does not count
        d.state.user_stopped_at = start
        await _interim(d, ears, "Run the tests in")
        await gate.tick(start + 1.5)
        await _final(d, ears, "Run the tests in the billing package.")  # Soniox's own <end>
        d.state.user_stopped_at = start + 4.0
        await gate.tick(start + 5.0)
    asyncio.run(go())
    assert ws.sent == []


def test_a_press_keeps_its_own_finalize(d, monkeypatch):
    gate, ears, ws = _call(d, monkeypatch, mode="ptt")
    start = time.time()

    async def go():
        d.state.ptt.press(start, collect=True)
        d.state.user_started_at = start
        await _interim(d, ears, "What time zone is Lisbon in?")
        d.state.user_stopped_at = start + 1.0
        await gate.tick(start + 2.0)  # the press is open: its release asks for the words
    asyncio.run(go())
    assert ws.sent == []


def test_other_ears_are_never_asked(d, monkeypatch):
    d.PREFS.update({"microphone": "always"})
    ws = Ws()
    gate = d.PttGate(type("Stt", (), {"_websocket": ws})())
    start = time.time()
    d.state.user_started_at, d.state.user_stopped_at, d.state.unfinalized = start, start + 1.0, True
    asyncio.run(gate.tick(start + 3.0))
    assert ws.sent == []
