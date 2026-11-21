"""A stand-in for the Mac that talks: the call's WebSocket gets bot audio the way the daemon sends it (40 ms of 24 kHz
PCM, 25 messages a second, paced in real time) and a ping every 2 s, and every pong's delay is printed. Measures what
the daemon's keep_alive sees while the bot speaks to the phone. Serves the paired certificate on the TLS port, so the
app's pinning accepts it. Made-up content only.

    python talking_mac.py <state dir> <port> <seconds of speech> [busy|plain] [downlink kbit/s]

Prints `pong <id> <ms>` per answered ping, `missed <id>` for a ping unanswered after 12 s, and at the end
`done max_ms=<n> missed=<n> pongs=<n> silence_ms=<n>`: silence is the longest wait for a pong of either kind (an answer
or the app's own keep-alive, phone.py version 4), which the daemon closes the call after 12 s of.
"""

import asyncio
import json
import random
import ssl
import struct
import sys
import time
from pathlib import Path

from aiohttp import WSMsgType, web

STATE, PORT, SPEECH_SECS = Path(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])
BUSY = len(sys.argv) > 4 and sys.argv[4] == "busy"  # a full screen: sessions, a long conversation, live words
# A link slower than the bot's voice (24 kHz PCM is 384 kbit/s): what reaches the phone through a weak Twingate path.
DOWN_KBPS = float(sys.argv[5]) if len(sys.argv) > 5 and float(sys.argv[5]) > 0 else None
CHUNK_SECS, RATE, PING_SECS, DEAD_AFTER_SECS = 0.04, 24000, 2.0, 12.0
# Fresh noise in every chunk, not a tone: the app asks for per-message deflate, which squeezes a repeated chunk to
# nothing, and speech does not compress like that.
NOISE = random.Random(7)


def voice() -> bytes:
    return struct.pack(f"<{int(RATE * CHUNK_SECS)}h", *[NOISE.randint(-800, 800) for _ in range(int(RATE * CHUNK_SECS))])


STATUS = {"connected": True, "mode": "orchestrator", "polish": False, "hearing": "", "talk": [],
          "sessions": [{"name": "pricing", "working": False, "waiting": False, "needs": None}]}
delays: list[int] = []
missed: list[int] = []
silence = [0.0]


async def phone(request: web.Request) -> web.WebSocketResponse:
    if request.headers.get("Authorization") != f"Bearer {(STATE / 'phone_key').read_text().strip()}":
        raise web.HTTPForbidden()
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    sent: dict[int, float] = {}
    print("phone connected", flush=True)

    async def pings() -> None:
        n = 0
        while not ws.closed:
            n += 1
            sent[n] = time.monotonic()
            await ws.send_str(json.dumps({"type": "ping", "id": n, "rtt_ms": None}))
            for old, at in list(sent.items()):
                if time.monotonic() - at > DEAD_AFTER_SECS:
                    missed.append(old)
                    print(f"missed {old}", flush=True)
                    del sent[old]
            await asyncio.sleep(PING_SECS)

    async def speech() -> None:
        await asyncio.sleep(3)
        start = time.monotonic()
        n = 0
        while not ws.closed and time.monotonic() - start < SPEECH_SECS:
            await ws.send_bytes(voice())
            n += 1
            await asyncio.sleep(max(0.0, start + n * CHUNK_SECS - time.monotonic()))  # real time, as pipecat paces it
        print(f"speech over after {n} chunks", flush=True)

    tasks = [asyncio.create_task(pings()), asyncio.create_task(speech())]
    last = time.monotonic()
    async for message in ws:
        if message.type == WSMsgType.TEXT:
            body = json.loads(message.data)
            if body.get("type") == "pong":
                silence[0] = max(silence[0], time.monotonic() - last)
                last = time.monotonic()
            if body.get("type") == "pong" and body.get("id") in sent:
                ms = round((time.monotonic() - sent.pop(body["id"])) * 1000)
                delays.append(ms)
                print(f"pong {body['id']} {ms}", flush=True)
    silence[0] = max(silence[0], time.monotonic() - last)
    for t in tasks:
        t.cancel()
    return ws


def busy_status() -> dict:
    """What a working day looks like on the phone: eight sessions, twelve turns, and the user's words changing on each
    poll, so every status differs from the last."""
    tick = int(time.time() * 5)
    turns = [{"id": i, "who": "user" if i % 2 else "assistant",
              "text": f"Turn {i}: the pricing rollout needs the checklist from Dana, the staging deploy is green, and the "
                      f"billing migration waits on review number {i * 7}. " * 2} for i in range(12)]
    sessions = [{"name": f"session-{i}", "working": i % 2 == 0, "waiting": False, "needs": "a review" if i % 3 == 0 else None}
                for i in range(8)]
    return {**STATUS, "sessions": sessions, "talk": turns, "hearing": f"and then the next thing {tick}"}


async def handle(request: web.Request) -> web.Response:
    if request.path == "/voice/status":
        return web.json_response(busy_status() if BUSY else STATUS)
    return web.json_response({"ok": True})


async def throttled(inner: int) -> None:
    """The app's port, in front of the real one: bytes to the phone at DOWN_KBPS at most, bytes from it untouched."""
    async def pipe(reader, writer, rate: float | None) -> None:
        try:
            while data := await reader.read(4096):
                writer.write(data)
                await writer.drain()
                if rate:
                    await asyncio.sleep(len(data) * 8 / (rate * 1000))
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()

    async def client(reader, writer) -> None:
        up_reader, up_writer = await asyncio.open_connection("127.0.0.1", inner)
        await asyncio.gather(pipe(reader, up_writer, None), pipe(up_reader, writer, DOWN_KBPS))

    for host in ("127.0.0.1", "::1"):
        await asyncio.start_server(client, host, PORT)


async def main() -> None:
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(STATE / "tls" / "cert.pem", STATE / "tls" / "key.pem")
    app = web.Application()
    app.router.add_get("/voice/phone", phone)
    app.router.add_route("*", "/{tail:.*}", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    if DOWN_KBPS:
        await web.TCPSite(runner, "127.0.0.1", PORT + 1000, ssl_context=context).start()
        await throttled(PORT + 1000)
    else:
        for host in ("127.0.0.1", "::1"):
            await web.TCPSite(runner, host, PORT, ssl_context=context).start()
    print("talking mac up", flush=True)
    try:
        await asyncio.sleep(SPEECH_SECS + 25)
    finally:
        print(f"done max_ms={max(delays, default=-1)} missed={len(missed)} pongs={len(delays)} "
              f"silence_ms={round(silence[0] * 1000)}", flush=True)


asyncio.run(main())
