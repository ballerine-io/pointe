"""The phone's call link through a bad network, measured: the daemon's own socket_call and pipecat transport, a stand-in
bot instead of ears, brain and mouth, a stand-in phone that speaks the wire protocol like the app, and tests/netshaper.py
between them. No vendor, no key, no microphone: the audio is synthetic.

The phone comes in two kinds, so a run can measure before and after: `old` is the iPhone app 1.23.1 (protocol 4: PCM,
a redial 2, 4, 8, 16 s apart, a new call each time, a typed line sent once with no id) and `new` the app since protocol
5 (calllink.py: the call resumed, ADPCM, redials 0.25 s on with jitter, a typed line resent with its id).

    uv run --locked python -I tests/net_bench.py <scenario> <old|new> [repository root]

The root is the checkout whose daemon is measured (default: this one): pass a checkout of an older version to measure
it with the same phone and the same network. Prints one JSON line of measurements. tests/test_bad_network.py runs the
scenarios against this checkout and holds them to bounds. "page" and "app" are what those clients hear of the voice as
it arrived (tests/playout_sim.py); POINTE_NET_BEFORE=1 measures 0.10.0: the voice paced as pipecat paces it, one chunk
ahead (phone.SEND_LEAD_SECS), heard by the page and the apps as they were.
"""

import asyncio
import audioop
import json
import math
import os
import random
import struct
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT_BASE = int(os.environ.get("POINTE_NET_PORT", "9740"))  # the daemon here, the shaper at +1 (9700-9799 is ours)
UP_RATE, DOWN_RATE, CHUNK = 16000, 24000, 0.02


@dataclass
class Scenario:
    profile: str
    reply_secs: float = 12.0  # how long the bot talks after each typed line
    lines: int = 3  # typed lines, one every `every` seconds from 2 s in
    every: float = 14.0
    events: list = field(default_factory=list)  # (at secs, "outage=5" | "switch" | "profile=x")
    secs: float = 45.0
    lines_at: list | None = None  # or exactly when

    def times(self) -> list[float]:
        return self.lines_at if self.lines_at is not None else [2 + n * self.every for n in range(self.lines)]


SCENARIOS = {
    "clean": Scenario("lan"),
    "outage": Scenario("slow", events=[(8.0, "outage=5")]),
    "outage10": Scenario("far", events=[(8.0, "outage=10")]),
    "switch": Scenario("slow", events=[(8.0, "switch")]),
    "bad": Scenario("bad"),
    "capped": Scenario("capped", reply_secs=15.0, lines=2, every=20.0),
    "lossy": Scenario("lossy"),
    "edge": Scenario("edge", reply_secs=10.0, lines=2, every=20.0),
    # tests/test_bad_network.py: short, so the offline suite can run them. A line typed during the outage, one after.
    "t-outage": Scenario("slow", reply_secs=6.0, lines_at=[2.0, 6.0, 16.0], events=[(4.0, "outage=7")], secs=26.0),
    "t-switch": Scenario("slow", reply_secs=6.0, lines_at=[2.0, 13.0], events=[(4.0, "switch")], secs=21.0),
    "t-capped": Scenario("capped", reply_secs=8.0, lines_at=[2.0, 12.0], secs=22.0),
    "t-lead": Scenario("lan", reply_secs=6.0, lines_at=[2.0], secs=10.0),
    "t-relay": Scenario("relay", reply_secs=8.0, lines_at=[2.0, 14.0], secs=24.0),
    "relay": Scenario("relay", reply_secs=10.0, lines=5, every=16.0, secs=82.0),
}


class Phone:
    """The app's side of the link, as the app does it."""

    def __init__(self, kind: str, port: int, key: str):
        self.kind, self.port, self.key = kind, port, key
        self.new = kind == "new"
        self.rng = random.Random(3)
        self.ws = None
        self.wanted = True
        self.token = None
        self.down_codec = self.up_codec = "pcm16"
        self.connects = 0
        self.refused = []  # close codes of dials that did not become a call
        self.down_secs = 0.0  # bot audio received
        self.up_secs = 0.0  # microphone audio captured while a socket was up
        self.up_dropped = 0.0  # of it, dropped by the send-side cap
        self.sent_secs = 0.0  # on this socket
        self.rtt = 0.0
        self.uplink = Uplink()
        self.heard_at = 0.0
        self.answered = 0
        self.player = Player()
        self.arrivals: list[float] = []  # when each chunk of the bot's voice came in
        self.offline_since: float | None = None
        self.offline_secs = 0.0
        self.ended_with: str | None = None

    async def run(self) -> None:
        import websockets

        retries = 0
        while self.wanted:
            self.connects += 1
            try:
                ws = await asyncio.wait_for(websockets.connect(
                    f"ws://127.0.0.1:{self.port}/voice/phone", additional_headers={"Authorization": f"Bearer {self.key}"},
                    ping_interval=None, max_size=None, compression=None, open_timeout=None), 15)
            except Exception as e:
                code = None
                self.refused.append(f"dial: {type(e).__name__}")
            else:
                self.ws = ws
                retries = 0  # the app counts from 0 again once a socket opens (Call's didOpen)
                await self._hello()
                code = await self._serve(ws)
                self.ws = None
            if not self.wanted:
                break
            self._went_offline()
            if code in (4401, 1008):
                self.ended_with = "refused"
                break
            if code == 4409 and retries == 0 and not self.new:
                # 1.23.1: the Mac accepts, then closes 4409 while it still holds the dead call; the open had reset
                # the count, so Call.refusal reads it as a first try and ends the call: "A call is already up".
                self.ended_with = "busy"
                break
            retries += 1
            if self.new:  # Redial in Call.swift: soon, then backing off, with jitter so a fleet does not dial in step
                base = min(8.0, 0.25 * 2 ** (retries - 1))
                delay = base / 2 + self.rng.uniform(0, base / 2)
            else:
                delay = min(16, 2 ** retries)
            await asyncio.sleep(delay)

    async def _hello(self) -> None:
        caps = ["ptt"] + (["resume", "adpcm"] if self.new else [])
        hello = {"type": "hello", "protocol": 5 if self.new else 4, "device": "iPhone", "capabilities": caps}
        if self.new and self.token:
            hello["resume"] = self.token
        self.up_codec = "pcm16"
        self.sent_secs, self.uplink = 0.0, Uplink()
        self.heard_at = time.monotonic()
        await self.ws.send(json.dumps(hello))

    async def _serve(self, ws) -> int | None:
        """Until this socket ends: its close code, or None when the phone gave up on it (6 s of silence)."""
        tasks = [asyncio.create_task(t) for t in (self._receive(ws), self._mic(ws), self._alive(ws), self._watch(ws))]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        result = next(iter(done)).result() if done else None
        try:
            await asyncio.wait_for(ws.close(code=4000 if self.new else 1000), 1)  # 1.23.1 closes a redial with 1000
        except Exception:
            pass
        return result

    async def _receive(self, ws) -> int | None:
        import websockets

        try:
            async for message in ws:
                self.heard_at = time.monotonic()
                self._came_back()
                if isinstance(message, bytes):
                    pcm = adpcm_decode(message) if self.down_codec == "adpcm" else message
                    secs = len(pcm) / 2 / DOWN_RATE
                    self.down_secs += secs
                    self.arrivals.append(self.heard_at)
                    self.player.arrive(secs)
                    continue
                m = json.loads(message)
                if m.get("type") == "ping":
                    self.rtt = (m.get("rtt_ms") or 0) / 1000
                    if isinstance(m.get("heard_ms"), int):
                        self.uplink.heard(self.sent_secs, m["heard_ms"] / 1000)
                    pong = {"type": "pong", "id": m["id"]}
                    if self.new:
                        pong["ahead_ms"] = round(self.player.ahead() * 1000)
                    await ws.send(json.dumps(pong))
                    self.answered = max(self.answered, m["id"])
                elif m.get("type") == "call" and self.new:
                    self.token = m.get("resume")
                    self.down_codec = m.get("codec", "pcm16")
                    if self.down_codec == "adpcm":
                        await ws.send(json.dumps({"type": "codec", "up": "adpcm"}))
                        self.up_codec = "adpcm"
                elif m.get("type") == "interrupt":
                    self.player.flush()
        except websockets.ConnectionClosed as e:
            return e.rcvd.code if e.rcvd else 1006
        return 1006

    async def _mic(self, ws) -> None:
        state, n = None, 0
        start = time.monotonic()
        while True:
            pcm = _noise(int(UP_RATE * CHUNK), n)
            n += 1
            if self.up_codec == "adpcm":
                body, after = audioop.lin2adpcm(pcm, 2, state or (0, 0))
                message = struct.pack("<hBB", *(state or (0, 0)), 0) + body
                state = after
            else:
                message = pcm
            self.up_secs += CHUNK
            # The app's uplink check (Uplink in Call.swift): audio sent and not yet taken by the Mac, by its pings.
            if self.new and self.uplink.full(self.sent_secs, self.rtt):
                self.up_dropped += CHUNK
            else:
                await ws.send(message)
                self.sent_secs += CHUNK
            await asyncio.sleep(max(0.0, start + n * CHUNK - time.monotonic()))

    async def _alive(self, ws) -> None:
        while True:
            await asyncio.sleep(2)
            body = {"type": "pong", "id": self.answered, "alive": True}
            if self.new:
                body["ahead_ms"] = round(self.player.ahead() * 1000)
            await ws.send(json.dumps(body))

    async def _watch(self, ws) -> None:
        while time.monotonic() - self.heard_at < 6:  # Call.deadAfter
            await asyncio.sleep(0.25)
        return None

    def _went_offline(self) -> None:
        if self.offline_since is None:
            self.offline_since = time.monotonic()

    def _came_back(self) -> None:
        if self.offline_since is not None:
            self.offline_secs += time.monotonic() - self.offline_since
            self.offline_since = None


class Uplink:
    """The app's uplink check, as Uplink in apps/PointeKit/Sources/PointeKit/LinkPolicy.swift does it."""

    FULL, CLEAR = 1.5, 0.5

    def __init__(self):
        self.on_the_way = 0.0
        self.dropping = False

    def heard(self, sent: float, heard: float) -> None:
        self.on_the_way = max(0.0, sent - heard)

    def full(self, sent: float, rtt: float) -> bool:
        limit = (self.CLEAR if self.dropping else self.FULL) + rtt
        self.dropping = self.on_the_way > limit
        return self.dropping


class Player:
    """The phone's speaker: plays what arrives at the voice's own pace, starting once 80 ms are in. A gap is the
    speaker running dry while a reply is still coming."""

    PRIME = 0.08

    def __init__(self):
        self.until = 0.0  # when what is queued finishes playing
        self.underruns = 0
        self.gap_secs = 0.0
        self.playing = False
        self.last_arrival = 0.0
        self.timeline: list[tuple[float, float]] = []  # (arrival, when what is queued then finishes)

    def arrive(self, secs: float) -> None:
        now = time.monotonic()
        if self.playing and now > self.until:
            if now - self.until < 1.5:  # a reply still coming; a longer silence is a new one
                self.underruns += 1
                self.gap_secs += now - self.until
            self.playing = False
        if not self.playing:
            self.until = now + self.PRIME
            self.playing = True
        self.until += secs
        self.last_arrival = now
        self.timeline.append((now, self.until))

    def ahead(self) -> float:
        return max(0.0, self.until - time.monotonic())

    def flush(self) -> None:
        self.until, self.playing = 0.0, False


def adpcm_decode(message: bytes) -> bytes:
    predictor, index, _ = struct.unpack_from("<hBB", message)
    return audioop.adpcm2lin(message[4:], 2, (predictor, index))[0]


def _noise(samples: int, n: int) -> bytes:
    """Speech-like: a voiced tone that moves, with noise, so neither deflate nor ADPCM finds it trivial."""
    r = random.Random(n)
    return struct.pack(f"<{samples}h", *(int(6000 * math.sin((n * samples + i) * (0.05 + 0.02 * math.sin(n / 7)))
                                              + r.randint(-1200, 1200)) for i in range(samples)))


# ---------- the daemon side ----------

def load_daemon(root: Path):
    state = Path(tempfile.mkdtemp(prefix="cv-net-state-"))
    (state / "token").write_text("net-bench")
    (state / "first-hello").write_text("")
    os.environ.update(CLAUDE_VOICE_STATE=str(state), POINTE_LINK_DIR=str(state / "link"), CLAUDE_VOICE_SKIP_KEY_CHECK="1")
    sys.path[0:0] = [str(root / "pointe"), str(root)]  # the modules are in pointe/; at the top in an older checkout
    import vendors

    vendors._stored = lambda vendor, keep=True: f"made-up-{vendor}-key"  # never the Keychain: these keys reach nothing
    import harnesses.claude_code

    harnesses.claude_code.ROSTER = False
    harnesses.claude_code.DEFAULT_HOME = state / "claude-home"
    harnesses.claude_code.MANAGED_SETTINGS = state / "managed-settings.json"
    import mac

    mac.SYSTEM = False
    import daemon

    daemon.COPY_SESSIONS = False
    return daemon


class Bot:
    """Instead of ears, brain and mouth: each typed line gets `reply_secs` of speech, made faster than real time as a
    voice service makes it; the transport paces it out, as it does for the real voice."""

    def __init__(self, d, reply_secs: float):
        self.d, self.reply_secs = d, reply_secs
        self.calls = 0
        self.heard_secs = 0.0  # microphone audio that reached the pipeline
        self.said_secs = 0.0
        self.replies: list[float] = []  # when each reply began

    async def run_call(self, transport) -> None:
        from pipecat.frames.frames import InputAudioRawFrame, InputTextRawFrame, OutputAudioRawFrame
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.processors.frame_processor import FrameProcessor

        d, bot = self.d, self
        bot.calls += 1

        class Speaker(FrameProcessor):
            async def process_frame(self, frame, direction):
                await super().process_frame(frame, direction)
                if isinstance(frame, InputAudioRawFrame):
                    bot.heard_secs += len(frame.audio) / 2 / frame.sample_rate
                    return
                if isinstance(frame, InputTextRawFrame):
                    self.create_task(self._say())
                await self.push_frame(frame, direction)

            async def _say(self):
                bot.replies.append(time.monotonic())
                n = int(bot.reply_secs / 0.04)
                for k in range(n):
                    await self.push_frame(OutputAudioRawFrame(audio=_noise(int(DOWN_RATE * 0.04), 10_000 + k),
                                                              sample_rate=DOWN_RATE, num_channels=1))
                    bot.said_secs += 0.04
                    await asyncio.sleep(0.005)

        injector = d.FeedInjector()
        pipeline = Pipeline([transport.input(), injector, Speaker(), transport.output()])
        voice = d.PipelineWorker(pipeline, name="voice", params=d.VOICE_PARAMS, idle_timeout_secs=3600)
        runner = d.WorkerRunner(handle_sigint=False)
        await runner.add_workers(voice)

        @transport.event_handler("on_client_connected")
        async def connected(_t, _c):
            d.state.conn = d.Connection(injector=injector, voice=voice, runner=runner, workers={}, ptt=None)

        @transport.event_handler("on_client_disconnected")
        async def disconnected(_t, _c):
            d.state.conn = None
            await runner.cancel()

        await runner.run()
        if d.state.conn is not None and d.state.conn.runner is runner:
            d.state.conn = None


async def serve(d, port: int):
    import uvicorn
    from fastapi import FastAPI, Request, WebSocket

    app = FastAPI()

    @app.websocket("/voice/phone")
    async def phone_route(websocket: WebSocket):
        await d.socket_call(websocket, "phone")

    @app.post("/voice/say")
    async def say(request: Request):
        return await d.say_by_typing(request)

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off",
                                           access_log=False))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    return server, task


async def typed(phone: Phone, port: int, text: str, n: int) -> dict:
    """Send one typed line as the app does; how long until the Mac said it took it."""
    import aiohttp

    start = time.monotonic()
    body = {"text": text} | ({"client_id": f"line-{n}"} if phone.new else {})
    tries = 0
    async with aiohttp.ClientSession() as http:
        while True:
            tries += 1
            try:
                timeout = aiohttp.ClientTimeout(total=8 if phone.new else 60)  # URLSession's default is 60 s
                async with http.post(f"http://127.0.0.1:{port}/voice/say", json=body, timeout=timeout) as r:
                    if r.status == 200:
                        return {"ack_secs": round(time.monotonic() - start, 2), "tries": tries}
                    if not phone.new:
                        return {"ack_secs": None, "tries": tries, "status": r.status}
            except Exception as e:
                if not phone.new:
                    return {"ack_secs": None, "tries": tries, "error": type(e).__name__}
            if tries >= 6 or time.monotonic() - start > 40:
                return {"ack_secs": None, "tries": tries}
            await asyncio.sleep(min(4.0, 0.5 * 2 ** (tries - 1)))


async def bench(d, name: str, kind: str) -> dict:
    sys.path.insert(0, str(HERE))
    from netshaper import Shaper

    scenario = SCENARIOS[name]
    port = PORT_BASE
    before = os.environ.get("POINTE_NET_BEFORE") == "1"
    if before:
        d.phone.SEND_LEAD_SECS = 0.04  # pipecat's own pacing: one 40 ms chunk ahead
    d.state.conn = None
    bot = Bot(d, scenario.reply_secs)
    d.run_call = bot.run_call
    d.KEEP_AWAKE.update = _nothing
    key = d.phone.phone_key(d.STATE_DIR)
    server, task = await serve(d, port)
    shaper = await Shaper(port + 1, port, scenario.profile).start()
    phone = Phone(kind, port + 1, key)
    runner = asyncio.create_task(phone.run())
    start = time.monotonic()
    acks: list[dict] = []

    async def events():
        for at, what in scenario.events:
            await asyncio.sleep(max(0.0, start + at - time.monotonic()))
            if what.startswith("outage="):
                shaper.outage(float(what.split("=")[1]))
            elif what == "switch":
                shaper.switch()

    async def line(n: int, at: float):
        await asyncio.sleep(max(0.0, start + at - time.monotonic()))
        acks.append({"n": n} | await typed(phone, port + 1, f"tell me about the rollout, part {n + 1}", n))

    tasks = [asyncio.create_task(events())] + [asyncio.create_task(line(n, at)) for n, at in enumerate(scenario.times())]
    await asyncio.sleep(scenario.secs)
    elapsed = time.monotonic() - start
    up_behind = phone.up_secs - phone.up_dropped - bot.heard_secs
    phone.wanted = False
    for t in tasks + [runner]:
        t.cancel()
    if phone.ws is not None:
        try:
            await asyncio.wait_for(phone.ws.close(code=1000), 2)
        except Exception:
            pass
    link = getattr(d.state, "call_link", None)
    if link is not None:  # a hang-up stuck behind a slow uplink: end the call here, as the Mac's own close would
        await link.close()
    await asyncio.sleep(0.5)
    await shaper.stop()
    server.should_exit = True
    await asyncio.wait([task], timeout=5)
    # How late each reply finished playing, against a perfect link: it began when asked and played straight through.
    late = []
    bounds = bot.replies + [float("inf")]
    for i, began in enumerate(bot.replies):
        heard = [until for at, until in phone.player.timeline if began <= at < bounds[i + 1]]
        if heard:
            late.append(round(max(heard) - (began + scenario.reply_secs), 2))
    if phone.offline_since is not None:
        phone.offline_secs += time.monotonic() - phone.offline_since
    heard = _heard(phone.arrivals, bot.replies, scenario.reply_secs, before)
    return {
        "scenario": name, "phone": kind, "profile": scenario.profile, "secs": round(elapsed, 1),
        "calls": bot.calls, "call_drops": max(0, bot.calls - 1) + (1 if phone.ended_with else 0),
        "ended_with": phone.ended_with,
        "dials": phone.connects, "reconnects_per_min": round((phone.connects - 1) * 60 / elapsed, 2),
        "offline_secs": round(phone.offline_secs, 1),
        "underruns": phone.player.underruns, "gap_secs": round(phone.player.gap_secs, 2),
        "bot_said_secs": round(bot.said_secs, 1), "phone_heard_secs": round(phone.down_secs, 1),
        "reply_late_secs": late,
        "up_behind_secs": round(up_behind, 2), "up_dropped_secs": round(phone.up_dropped, 2),
        "typed_ack_secs": [a.get("ack_secs") for a in sorted(acks, key=lambda a: a["n"])],
        "typed_tries": [a.get("tries") for a in sorted(acks, key=lambda a: a["n"])], "replies": len(bot.replies),
        "segments_lost": shaper.lost,
        "lead_secs": getattr(d.phone, "SEND_LEAD_SECS", 0.0), **heard,
    }


def _heard(arrivals: list[float], replies: list[float], reply_secs: float, before: bool) -> dict:
    """What the page and the apps hear of the voice as it arrived (tests/playout_sim.py), and how far ahead of its
    playing the first reply came in at most: the cushion the transport's pacing gives a client."""
    from playout_sim import CHUNK as SIM_CHUNK, hear

    if not arrivals or not replies:
        return {}
    arrived = [(at, max(i for i, began in enumerate(replies) if began <= at)) for at in arrivals if at >= replies[0]]
    talk = [(began, reply_secs) for began in replies]
    first = [at for at, reply in arrived if reply == 0]
    ahead = max((k + 1) * SIM_CHUNK - (at - first[0]) for k, at in enumerate(first)) if first else 0.0
    out = {"ahead_max_secs": round(ahead, 2)}
    for client in ("page", "app"):
        r = hear(client, talk, arrived, before)
        out[client] = {"gaps_per_min": r.gaps_per_min, "gap_ms_per_min": r.gap_ms_per_min, "first_sound_ms": r.first_sound_ms}
    return out


async def _nothing(*_a, **_k):
    return None


def main(argv: list[str]) -> None:
    name, kind = argv[0], argv[1]
    root = Path(argv[2]).resolve() if len(argv) > 2 else HERE.parent
    d = load_daemon(root)
    import logging

    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level=os.environ.get("POINTE_NET_LOG", "WARNING"))
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    print(json.dumps(asyncio.run(bench(d, name, kind))), flush=True)
    os._exit(0)  # a socket the shaper left half-open must not keep the process up


if __name__ == "__main__":
    main(sys.argv[1:])
