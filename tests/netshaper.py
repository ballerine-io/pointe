"""A bad network between a client and a server on this Mac: a TCP proxy that delays, stalls, caps and cuts.

Made for the phone link (tests/test_bad_network.py, apps/ios/e2e/bad_network.py). It shapes TCP the way a weak path shows
up to the two ends, which only see a byte stream:

- latency and jitter: each segment arrives `latency` later, plus up to `jitter`, never before the one ahead of it;
- loss: a lost segment is sent again after a retransmission timeout, and everything behind it waits (head-of-line);
- a bandwidth cap per direction, with a bottleneck buffer: once it is full the proxy stops reading, so the sender's
  own buffers fill as behind a real slow link;
- an outage: nothing moves either way for N seconds, then what was held goes on after a retransmission timeout, as
  when a path comes back before TCP gives up; a connection opened during it gets no answer until it ends;
- a network switch: every open connection goes silent for good, without a reset (the old path is gone), and new
  ones work.

Nothing is downloaded and nothing leaves the Mac: it listens and connects on 127.0.0.1 only.

    python tests/netshaper.py <listen port> <target port> <profile> [at:what ...]

`what` is `outage=SECS`, `switch` or `profile=NAME`, `at` seconds after start: `20:outage=5 40:switch`.
"""

import asyncio
import random
import sys
import time
from dataclasses import dataclass, replace

SEGMENT = 1400


@dataclass(frozen=True)
class Profile:
    latency_ms: float = 0.0  # one way
    jitter_ms: float = 0.0
    loss: float = 0.0  # per segment
    down_kbps: float | None = None  # server to client
    up_kbps: float | None = None
    buffer_bytes: int = 64_000  # the bottleneck's queue: cellular links hold seconds


PROFILES = {
    "clean": Profile(),
    "lan": Profile(latency_ms=10, jitter_ms=5),
    "slow": Profile(latency_ms=150, jitter_ms=40, loss=0.01),
    "far": Profile(latency_ms=300, jitter_ms=120, loss=0.02),
    "bad": Profile(latency_ms=600, jitter_ms=200, loss=0.03, down_kbps=400, up_kbps=200),
    "lossy": Profile(latency_ms=250, jitter_ms=100, loss=0.05),
    "capped": Profile(latency_ms=200, jitter_ms=60, loss=0.01, down_kbps=160, up_kbps=120),
    "edge": Profile(latency_ms=400, jitter_ms=150, loss=0.02, down_kbps=80, up_kbps=60),
}


class _Pipe:
    """One direction of one connection: segments with the time each may be written."""

    def __init__(self, shaper: "Shaper", reader: asyncio.StreamReader, writer: asyncio.StreamWriter, down: bool):
        self.shaper, self.reader, self.writer, self.down = shaper, reader, writer, down
        self.queue: asyncio.Queue = asyncio.Queue()
        self.queued = 0
        self.room = asyncio.Event()
        self.room.set()
        self.last_due = 0.0
        self.link_free = 0.0
        self.dead = False

    async def read(self) -> None:
        try:
            while not self.dead:
                await self.room.wait()
                data = await self.reader.read(SEGMENT)
                if not data:
                    break
                await self.shaper.passable(self)
                if self.dead:
                    return
                self.queue.put_nowait((self._due(len(data)), data))
                self.queued += len(data)
                if self.queued >= self.shaper.profile.buffer_bytes:
                    self.room.clear()
        except (ConnectionError, OSError):
            pass
        if not self.dead:
            self.queue.put_nowait((self.last_due, None))

    def _due(self, size: int) -> float:
        p, now = self.shaper.profile, time.monotonic()
        kbps = p.down_kbps if self.down else p.up_kbps
        start = now
        if kbps:
            start = max(now, self.link_free)
            self.link_free = start + size * 8 / (kbps * 1000)
        due = self.link_free if kbps else start
        due += (p.latency_ms + self.shaper.rng.uniform(0, p.jitter_ms)) / 1000
        if p.loss and self.shaper.rng.random() < p.loss:
            due += max(0.2, 2 * (p.latency_ms + p.jitter_ms) / 1000)  # TCP's retransmission timeout, about two round trips
            self.shaper.lost += 1
        self.last_due = max(self.last_due, due)  # in order: never before the segment ahead
        return self.last_due

    async def write(self) -> None:
        try:
            while True:
                due, data = await self.queue.get()
                wait = due - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                await self.shaper.passable(self)
                if self.dead:
                    return
                if data is None:
                    self.writer.close()
                    return
                self.queued -= len(data)
                if self.queued < self.shaper.profile.buffer_bytes:
                    self.room.set()
                self.writer.write(data)
                await self.writer.drain()
                self.shaper.bytes[self.down] += len(data)
        except (ConnectionError, OSError):
            pass


class Shaper:
    def __init__(self, listen_port: int, target_port: int, profile: Profile | str = "clean", seed: int = 7):
        self.listen_port, self.target_port = listen_port, target_port
        self.profile = PROFILES[profile] if isinstance(profile, str) else profile
        self.rng = random.Random(seed)
        self.connections = 0
        self.lost = 0
        self.bytes = {True: 0, False: 0}
        self._out_until = 0.0
        self._back = asyncio.Event()
        self._back.set()
        self._pipes: list[_Pipe] = []
        self._server: asyncio.base_events.Server | None = None

    async def start(self) -> "Shaper":
        self._server = await asyncio.start_server(self._accept, "127.0.0.1", self.listen_port)
        return self

    async def stop(self) -> None:
        if self._server:
            self._server.close()
        for pipe in self._pipes:
            pipe.dead = True
            pipe.writer.close()

    def set_profile(self, profile: Profile | str, **changes) -> None:
        self.profile = replace(PROFILES[profile] if isinstance(profile, str) else profile, **changes)

    def outage(self, secs: float) -> None:
        """Nothing either way for `secs`; then the held bytes go on, a retransmission timeout later."""
        self._out_until = time.monotonic() + secs
        self._back.clear()
        asyncio.get_running_loop().call_later(secs + self.rng.uniform(0.3, min(2.0, 0.3 + secs / 3)), self._back.set)

    def switch(self) -> None:
        """The phone moved to another network: what is open goes silent for good; new connections work."""
        for pipe in self._pipes:
            pipe.dead = True
            pipe.room.set()
        self._pipes = []

    async def passable(self, pipe: _Pipe) -> None:
        if not self._back.is_set():
            await self._back.wait()

    async def _accept(self, client_r, client_w) -> None:
        self.connections += 1
        await self._back.wait()  # opened during an outage: the handshake gets no answer until it ends
        try:
            server_r, server_w = await asyncio.open_connection("127.0.0.1", self.target_port)
        except OSError:
            client_w.close()
            return
        up, down = _Pipe(self, client_r, server_w, down=False), _Pipe(self, server_r, client_w, down=True)
        self._pipes += [up, down]
        await asyncio.gather(up.read(), up.write(), down.read(), down.write())


async def _main(argv: list[str]) -> None:
    listen, target, profile = int(argv[0]), int(argv[1]), argv[2]
    shaper = await Shaper(listen, target, profile).start()
    start = time.monotonic()
    print(f"shaping 127.0.0.1:{listen} -> :{target} as {profile}: {shaper.profile}", flush=True)
    for step in sorted(argv[3:], key=lambda s: float(s.split(":", 1)[0])):
        at, what = step.split(":", 1)
        await asyncio.sleep(max(0.0, start + float(at) - time.monotonic()))
        if what.startswith("outage="):
            shaper.outage(float(what.split("=", 1)[1]))
        elif what == "switch":
            shaper.switch()
        elif what.startswith("profile="):
            shaper.set_profile(what.split("=", 1)[1])
        print(f"{time.monotonic() - start:6.1f} s  {what}", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(_main(sys.argv[1:]))
    except KeyboardInterrupt:
        pass
