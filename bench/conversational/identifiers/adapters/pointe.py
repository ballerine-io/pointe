"""Pointe, the system under test (design 4.3), on an isolated daemon, in its default setup.

Per item run: a fresh state folder under the item folder (CLAUDE_VOICE_STATE), the worker's own ports
(CLAUDE_VOICE_DAEMON_PORT, CLAUDE_VOICE_TLS_PORT) and POINTE_LINK_DIR inside the item folder, so the owner's daemon
(7860, 7443), ~/.claude-voice and ~/.local/bin/pointe are never touched. The daemon reads its own keys from the
Keychain, as it does for a user. The agent is the same launch line as every arm plus `--plugin-dir <Pointe>`, and
joins with /pointe:voice, the way people run it (tests/e2e/hook_session.py). Audio goes in where a browser's mic would,
over the page's call socket (phone.py's protocol, as tests/e2e/rig.Browser speaks it); the bot's audio is recorded.

`pointe-text` is the same, with the words sent through POST /voice/say instead of audio: it separates recognition
from the brain.

The state folder starts with Pointe's `first-hello` marker, as on a Mac past its first call: otherwise the first
words of every run would be taken as the first hello and answered with a fixed line, not acted on.

Spend is computed from daemon.log (Pointe has no per-call bill): brain steps at the logged token counts with an
assumed 300 output tokens each, the spoken characters at the mouth's list price, two Soniox streams (ears and the echo
guard's mirror) for the call's length, and an assumed 2,000 tokens in and 60 out of the gate per send and 4,000 in and
150 out of the reader per finished turn.
"""

import asyncio
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np

from adapters.base import AgentAdapter
from core.adapter import Event, SpendRow
from core.agent import clean_env
from core.ledger import PRICES, tokens_usd

FRAME = 320  # 20 ms at 16 kHz
OUT_RATE = 24000
LOG_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d[.,]?\d*)")


class Call:
    """The page's call: 16 kHz PCM up at real-time pace (silence between utterances), 24 kHz PCM down, recorded."""

    def __init__(self, url: str, token: str):
        self.url, self.token = url, token
        self.queue: list[bytes] = []
        self.spoke_until = 0.0
        self.received: list[tuple[float, bytes]] = []
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.ws = None
        self.opened = 0.0
        self.error = ""

    def open(self) -> None:
        self.thread.start()
        asyncio.run_coroutine_threadsafe(self._open(), self.loop).result(30)
        self.opened = time.time()

    async def _open(self) -> None:
        from websockets.asyncio.client import connect

        self.ws = await connect(self.url, max_size=None, additional_headers={"Authorization": f"Bearer {self.token}"})
        self.loop.create_task(self._send())
        self.loop.create_task(self._receive())

    async def _send(self) -> None:
        start, sent = time.time(), 0
        current, pos = None, 0
        while True:
            wait = start + sent * FRAME / 16000 - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
            if current is None and self.queue:
                current, pos = self.queue.pop(0), 0
            if current is not None:
                chunk = current[pos:pos + FRAME * 2]
                pos += FRAME * 2
                if pos >= len(current):
                    current = None
                chunk = chunk + bytes(FRAME * 2 - len(chunk))
            else:
                chunk = bytes(FRAME * 2)
            try:
                await self.ws.send(chunk)
            except Exception as e:  # noqa: BLE001  the socket closed: the call is over
                self.error = type(e).__name__
                return
            sent += 1

    async def _receive(self) -> None:
        try:
            async for message in self.ws:
                if isinstance(message, bytes):
                    self.received.append((time.time(), message))
        except Exception:  # noqa: BLE001
            return

    def say(self, pcm: bytes) -> tuple[float, float]:
        start = max(time.time(), self.spoke_until)
        self.spoke_until = start + len(pcm) / 32000
        self.queue.append(pcm)
        return start, self.spoke_until

    def last_audio(self, threshold: int = 300) -> float:
        """Wall time of the last bot audio chunk that was not silence."""
        for t, b in reversed(self.received):
            if np.abs(np.frombuffer(b, dtype="<i2")).mean() >= threshold:
                return t
        return 0.0

    def close(self) -> None:
        async def _close():
            if self.ws is not None:
                await self.ws.close()
            for task in [t for t in asyncio.all_tasks(self.loop) if t is not asyncio.current_task()]:
                task.cancel()
        try:
            asyncio.run_coroutine_threadsafe(_close(), self.loop).result(10)
        except Exception:  # noqa: BLE001
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)


class Pointe(AgentAdapter):
    name = "pointe"
    capabilities = frozenset({"audio_in", "text_in", "speech_out", "approvals", "sessions", "interrupt"})
    text_only = False

    def __init__(self):
        super().__init__()
        self.state = self.port = self.tls = None
        self.call: Call | None = None
        self._log_pos = 0
        self.call_seconds = 0.0
        self.daemon_ok = False

    # ---------- the isolated daemon ----------

    def daemon_env(self) -> dict:
        env = clean_env()
        env.update(CLAUDE_VOICE_STATE=str(self.state), CLAUDE_VOICE_DAEMON_PORT=str(self.port),
                   CLAUDE_VOICE_TLS_PORT=str(self.tls), POINTE_LINK_DIR=str(self.state.parent / "link"),
                   CLAUDE_VOICE_NO_BROWSER="1", CLAUDE_VOICE_FRONT="brain")
        return env

    def agent_args(self, env) -> tuple:
        return ("--plugin-dir", str(env.pointe_root))

    def agent_env(self, env) -> dict:
        d = self.daemon_env()
        return {k: d[k] for k in ("CLAUDE_VOICE_STATE", "CLAUDE_VOICE_DAEMON_PORT", "CLAUDE_VOICE_TLS_PORT",
                                  "POINTE_LINK_DIR", "CLAUDE_VOICE_NO_BROWSER", "CLAUDE_VOICE_FRONT")}

    def _daemon(self, verb: str) -> subprocess.CompletedProcess:
        return subprocess.run([str(self.env.pointe_root / "bin" / "voice-daemon"), verb], env=self.daemon_env(),
                              capture_output=True, text=True, timeout=240)

    def log(self) -> str:
        p = self.state / "daemon.log"
        return p.read_text(errors="ignore") if p.exists() else ""

    def _http(self, path: str, body: dict | None = None) -> dict:
        token = (self.state / "token").read_text().strip()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     method="POST" if body is not None else "GET",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")

    def start(self, sessions: dict[str, Path], env) -> None:
        self.env = env
        assert env.port not in (7860, 7443) and 1024 < env.port < 65000 - 100, "never the owner's ports"
        self.port, self.tls = env.port, env.port + 50
        self.state = env.item_dir / "pointe-state"
        assert str(self.state).startswith(("/tmp/", "/private/tmp/")), "Pointe's state must be under /tmp"
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "first-hello").touch()  # a Mac past its first call: no "say hello so I know I can hear you"
        got = self._daemon("ensure")
        if got.returncode != 0:
            raise RuntimeError(f"the isolated daemon did not start: {got.stderr[-300:]}")
        self.daemon_ok = True
        super().start(sessions, env)
        for name, agent in self.agents.items():
            before = len(re.findall(r"registered .*\(pid \d+", self.log()))
            stops = agent.stop_count()
            agent.type("/pointe:voice")
            deadline = time.time() + 120
            while time.time() < deadline and len(re.findall(r"registered .*\(pid \d+", self.log())) <= before:
                time.sleep(0.5)
            if len(re.findall(r"registered .*\(pid \d+", self.log())) <= before:
                raise RuntimeError("/pointe:voice did not register the session")
            agent.wait_stops(stops, 90)  # the join turn ends before the first request
            self._stops[name] = agent.stop_count()
        token = (self.state / "token").read_text().strip()
        self.call = Call(f"ws://127.0.0.1:{self.port}/voice/call", token)
        self.call.open()
        self._quiet(min_wait=4, quiet=2.5, timeout=25)
        self._log_pos = len(self.log())

    def _quiet(self, min_wait: float, quiet: float, timeout: float) -> None:
        """Wait out the greeting: the bot has said nothing for `quiet` seconds."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            last = max(self.call.last_audio(), self.call.opened)
            if time.time() - t0 >= min_wait and time.time() - last >= quiet:
                return
            time.sleep(0.25)

    # ---------- input ----------

    def say(self, pcm: bytes, rate: int) -> tuple[float, float]:
        assert rate == 16000
        return self.call.say(pcm)

    def say_text(self, text: str) -> float:
        self._http("/voice/say", {"text": text})
        return time.time()

    def type(self, text: str, session: str | None = None) -> None:
        raise NotImplementedError("the Pointe arms take speech, or text through the call (pointe-text)")

    # ---------- events from the daemon's own log ----------

    def poll(self) -> None:
        text = self.log()
        new, self._log_pos = text[self._log_pos:], len(text)
        for line in new.splitlines():
            m = re.search(r" - -> ([^:]+): (['\"])(.*)\2 \(routing: ([^)]*)\)$", line)
            if m:
                self._events.append(Event("delivered", time.time(), m.group(1), m.group(3), {"routing": m.group(4)}))
                continue
            m = re.search(r" - speak: (['\"])(.*)\1$", line)
            if m:
                self._events.append(Event("said", time.time(), None, m.group(2)))
                continue
            m = re.search(r" - user said: (['\"])(.*)\1$", line)
            if m:
                self._events.append(Event("heard", time.time(), None, m.group(2)))
                continue
            m = re.search(r" - permission (request|.*verdict).*$", line)
            if m:
                self._events.append(Event("note", time.time(), None, line[-200:]))
        super().poll()

    def speech(self) -> list:
        return [(t, t + len(b) / (2 * OUT_RATE), b) for t, b in self.call.received] if self.call else []

    # ---------- versions, spend, stop ----------

    def versions(self) -> dict:
        v = {**super().versions(), "pointe_root_commit": (self.env.pointe_root / "COMMIT").read_text().strip()}
        roles = re.findall(r"(brain|reader|checker|ears|mouth)[:=] ?([\w.:\-]+)", self.log()[:20000])
        if roles:
            v["roles_logged"] = ",".join(sorted({f"{a}={b}" for a, b in roles}))[:300]
        return v

    def spend(self) -> list[SpendRow]:
        log = self.log()
        steps = [(int(c), int(k or 0)) for c, k in
                 re.findall(r"brain step: \d+ ms, (\d+) tokens in(?:, (\d+) of them cached)?", log)]
        brain = {"input": sum(c - k for c, k in steps), "cache_read": sum(k for _, k in steps), "cache_write": 0,
                 "output": 300 * len(steps)}
        spoken = sum(len(m) for m in re.findall(r" - speak: (?:'|\")(.*)(?:'|\")$", log, re.M))
        sends = len(re.findall(r" - -> [^:]+: ", log))
        reports = len(re.findall(r"finished its turn", log))
        gate = {"input": 2000 * sends, "cache_read": 0, "cache_write": 0, "output": 60 * sends}
        reader = {"input": 4000 * reports, "cache_read": 0, "cache_write": 0, "output": 150 * reports}
        usd = (tokens_usd("claude-sonnet-5-5", brain) + tokens_usd("gemini-3.5-flash-lite", gate)
               + tokens_usd("claude-sonnet-5-5", reader) + spoken / 1000 * PRICES["elevenlabs_per_1000_chars"]
               + 2 * self.call_seconds / 3600 * PRICES["soniox_rt_per_stream_hour"])
        detail = {"brain_steps": len(steps), "brain_tokens_in": sum(c for c, _ in steps), "spoken_chars": spoken,
                  "sends": sends, "reports": reports, "call_seconds": round(self.call_seconds, 1)}
        return super().spend() + [SpendRow("pointe-voice", usd, "computed", detail)]

    def stop(self) -> None:
        if self.call:
            self.call_seconds = time.time() - self.call.opened
            self.call.close()
        super().stop()
        if self.daemon_ok:
            self._daemon("stop")
        pid_file = self.state / "daemon.pid" if self.state else None
        if pid_file and pid_file.exists():
            try:
                os.kill(int(pid_file.read_text().strip()), 9)
            except (ValueError, ProcessLookupError, PermissionError):
                pass


class PointeText(Pointe):
    name = "pointe-text"
    capabilities = frozenset({"text_in", "speech_out", "approvals", "sessions", "interrupt"})
    text_only = True

    def type(self, text: str, session: str | None = None) -> None:
        self.say_text(text)
