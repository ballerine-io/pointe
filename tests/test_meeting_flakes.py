"""Meeting e2e flakes, each as the scenario the instrumented runs showed."""

import asyncio
import sys
from pathlib import Path

from websockets.exceptions import ConnectionClosedOK
from websockets.frames import Close

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import meeting as meetings  # noqa: E402

CHUNK = 3200  # 100 ms of 16 kHz 16-bit audio


def _ears(fail_on: set[int]):
    """MeetingEars on fake sockets. The first socket's send raises (Soniox closed the stream) on the chunk numbers in
    `fail_on`; later sockets take everything."""
    socks = []

    class Sock:
        def __init__(self, n):
            self.n, self.sent = n, []

        async def send(self, data):
            if self.n == 0 and isinstance(data, bytes) and len(self.sent) in fail_on:
                raise ConnectionClosedOK(Close(1000, ""), None)
            self.sent.append(data)

        async def close(self):
            pass

    class Up(meetings.MeetingEars):
        async def open(self):
            self._ws = Sock(len(socks))
            socks.append(self._ws)
            self._sent.clear()
            self._sent_ms = 0.0
            self.connected = self._opened = True

    return Up("k", 16000, [], None), socks


def test_audio_a_stream_closed_on_before_finalising_it_goes_to_the_next_stream():
    """Instrumented run 2: Soniox closed the new meeting stream twice within 2 s of its start, and the owner's "Pointe,
    that's me" sent in that window was never transcribed. The unfinalised audio, and the chunk whose send failed, now
    go to the next stream."""
    ears, socks = _ears(fail_on={2})
    a, b, c = b"a" * CHUNK, b"b" * CHUNK, b"c" * CHUNK

    async def go():
        await ears.open()
        for pcm in (a, b, c):
            await ears.send(pcm)
        await asyncio.sleep(0.05)
        await ears.close()
    asyncio.run(go())
    assert len(socks) == 2 and b"".join(socks[1].sent) == a + b + c, [len(x) for x in socks[1].sent]


def test_audio_the_dead_stream_already_finalised_is_not_sent_again():
    ears, socks = _ears(fail_on={2})
    a, b, c = b"a" * CHUNK, b"b" * CHUNK, b"c" * CHUNK

    async def go():
        await ears.open()
        await ears.send(a)
        await ears.send(b)
        await asyncio.sleep(0.02)
        ears._heard_until([{"text": " so", "is_final": True, "end_ms": 100}])  # the first 100 ms came back as words
        await ears.send(c)
        await asyncio.sleep(0.05)
        await ears.close()
    asyncio.run(go())
    assert b"".join(socks[1].sent) == b + c


def test_the_owners_reconnect_starts_clean():
    """"Reconnect the audio" asks for a fresh stream: nothing of the old one is replayed."""
    ears, socks = _ears(fail_on=set())

    async def go():
        await ears.open()
        await ears.send(b"a" * CHUNK)
        await asyncio.sleep(0.02)
        await ears.reconnect()
        await ears.send(b"b" * CHUNK)
        await asyncio.sleep(0.05)
        await ears.close()
    asyncio.run(go())
    assert socks[1].sent == [b"b" * CHUNK]


def test_why_soniox_closed_the_stream_is_logged(monkeypatch):
    """Its error message (a code and a reason, never room words) was dropped, so a closed stream had no cause."""
    from loguru import logger
    lines = []
    sink = logger.add(lambda msg: lines.append(msg.record["message"]), level="WARNING")

    class Ws:
        def __aiter__(self):
            async def gen():
                yield '{"error_code": 429, "error_message": "Too many concurrent requests."}'
            return gen()

    ears = meetings.MeetingEars("k", 16000, [], None)
    try:
        asyncio.run(ears._receive(Ws()))
    finally:
        logger.remove(sink)
    assert any("429" in x and "Too many concurrent requests" in x for x in lines), lines


def test_unheard_audio_is_handed_over_once_when_both_the_reader_and_the_sender_see_the_close():
    ears, _ = _ears(fail_on=set())
    a = b"a" * CHUNK

    async def go():
        await ears.open()
        await ears.send(a)
        await asyncio.sleep(0.02)
    asyncio.run(go())
    ears._requeue_unheard()
    ears._requeue_unheard()
    assert list(ears._queue) == [a]


# ---------- the bot's echo and the owner's claim, as the instrumented meeting e2e showed them ----------

import time  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from test_orchestrator import d  # noqa: E402,F401  (d is a fixture)
from test_wave1_bugs import _bot_said_then_room_turn  # noqa: E402
from test_meeting_daemon import _meeting_ready, _start  # noqa: E402


def test_a_claim_closing_in_one_turn_with_the_bots_echo_is_heard(d, monkeypatch):
    """Soniox can file the bot's echo and the owner's "Pointe, that's me" under one label in one turn. Most of its words
    are then the bot's, and the late-echo check took the whole turn, claim included, as echo: no log line, no owner."""
    bot = "I'd keep going, briefly. The refund pricing issue and the alerts question are still open."
    m, turns = _bot_said_then_room_turn(d, monkeypatch, bot, bot + " Pointe, that's me.", "5")
    # Heard, not taken as echo. With no voiceprint a claim moves no seat (Mythos review AV-2): it is answered with the tap.
    assert m.owner == "1" and any(n.text == d.OWNER_BY_TAP for n in d.NOTES.items), (m.owner, [t.who for t in turns])


def test_the_bots_words_from_just_before_the_meeting_are_its_echo_in_it(d, monkeypatch):
    """Seen in the e2e: the permission read-out, spoken between two meetings, came back in the next meeting's stream as
    "Pricing wants to." under a new label: a person, since only speech inside a meeting was compared."""
    monkeypatch.setattr(d, "ECHO", d.EchoGuard())
    _meeting_ready(d, monkeypatch)

    async def push_frame(frame, *a):
        pass

    asyncio.run(d.BrainFront._speak(SimpleNamespace(push_frame=push_frame), "Pricing wants to delete the build folder. Should it?"))
    d.ECHO.bot_started()
    d.ECHO.bot_stopped()
    monkeypatch.setattr(d.ECHO, "stopped_at", time.time() - 9)
    _start(d, "participating")
    m = d.state.meeting
    turns = m.hear([{"is_final": True, "text": " Pricing wants to.", "speaker": "2"}], m.since + 1)
    turns += m.tick(m.since + 5)
    for t in turns:
        asyncio.run(d._on_meeting_turn(m, t))
    assert turns[0].who == "Pointe" and "2" not in [s["label"] for s in m.speakers()], m.speakers()


def test_the_bots_echo_with_a_word_misheard_is_still_the_bot(d, monkeypatch):
    """Instrumented run 6: Soniox heard the bot's "...שמתקנים ובודקים החזרים" as "...שמתקנים או רק אם החזרים" (one word
    as three), so exact word pairs covered 5 of 9 words and the bot's tail became a new speaker after the reconnect."""
    bot = "הייתי דוחה, או משיק רק אחרי שמתקנים ובודקים החזרים."
    m, turns = _bot_said_then_room_turn(d, monkeypatch, bot, "או משיק רק אחרי שמתקנים או רק אם החזרים—", "1:1")
    assert turns[0].who == "Pointe", [t.who for t in turns]


def test_a_participant_using_a_few_of_the_bots_words_is_still_a_participant(d, monkeypatch):
    m, turns = _bot_said_then_room_turn(d, monkeypatch, "The refunds flow still uses the old prices and was never tested.",
                                        "I tested the refunds myself last week, they work.", "3")
    assert turns[0].who != "Pointe"


def test_the_bots_read_out_of_a_file_name_is_its_echo_as_the_voice_said_it(d, monkeypatch):
    bot = "cv repo echo wants to run: cat test_pricing.py then python3 pytest. Should it?"
    m, turns = _bot_said_then_room_turn(d, monkeypatch, bot, "Cat test underscore pricing dot py, then python three pytest.", "4")
    assert turns[0].who == "Pointe", [t.who for t in turns]
