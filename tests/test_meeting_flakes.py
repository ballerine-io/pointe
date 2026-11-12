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
