"""pointe: the system under test, on an isolated daemon. Its own CLAUDE_VOICE_STATE under /tmp, its own daemon and TLS
ports from the worker's range, POINTE_LINK_DIR under /tmp so the installed `pointe` command is never rewritten, and the
default setup (no setup chosen: each role takes the first vendor in Pointe's order whose key exists; the daemon reads its
own keys from the Keychain). Sessions are plain Claude Code sessions started with the shared launch line plus
`--plugin-dir <pointe checkout>`, joined with /pointe:voice as a person does (tests/e2e/hook_session.py JoinedSession).
Audio goes in over the page's WebSocket call exactly where a microphone would (tests/e2e/rig.py Browser, no Chrome);
the bot's audio is recorded with wall-clock times. daemon.log and /voice/status are mapped to events."""

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import numpy as np

from adapters.base import Base
from core.adapter import CAPABILITIES, Event, SpendRow, clean_env
from core.ledger import PRICES, token_cost

RATE = 48000
FRAME = 960  # 20 ms
FORBIDDEN_PORTS = {7860, 7443}


class Call:
    """The page's call: mic in at 16 kHz, speaker out at 24 kHz, as tests/e2e/rig.py Browser speaks it."""

    IN_RATE, OUT_RATE = 16000, 24000

    def __init__(self, url: str, token: str):
        self.url, self.token = url, token
        self.queue: list = []
        self.current = None
        self.pos = 0
        self.spoke_until = 0.0
        self.chunks: list = []  # (wall time, 48 kHz int16 frame) the bot played
        self.playback = np.zeros(0, dtype=np.int16)
        self.tasks: list = []
        self.socket = None
        self.interrupts = 0

    async def connect(self):
        from websockets.asyncio.client import connect
        self.socket = await connect(self.url, max_size=None, additional_headers={"Authorization": f"Bearer {self.token}"})
        self.tasks = [asyncio.create_task(self._send()), asyncio.create_task(self._receive()),
                      asyncio.create_task(self._play())]

    def say(self, pcm48: np.ndarray) -> tuple[float, float]:
        start = max(time.time(), self.spoke_until)
        self.spoke_until = start + len(pcm48) / RATE
        self.queue.append(pcm48)
        return start, self.spoke_until

    async def _send(self):
        t0, sent = time.time(), 0
        while True:
            wait = t0 + sent / RATE - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
            if self.current is None and self.queue:
                self.current, self.pos = self.queue.pop(0), 0
            if self.current is not None:
                chunk = self.current[self.pos:self.pos + FRAME]
                self.pos += FRAME
                if self.pos >= len(self.current):
                    self.current = None
                chunk = np.pad(chunk, (0, FRAME - len(chunk)))
            else:
                chunk = np.zeros(FRAME, dtype=np.int16)
            sent += FRAME
            pcm = chunk.reshape(-1, RATE // self.IN_RATE).mean(axis=1).astype(np.int16)
            try:
                await self.socket.send(pcm.tobytes())
            except Exception:
                return

    async def _receive(self):
        try:
            async for message in self.socket:
                if isinstance(message, str):
                    if json.loads(message).get("type") == "interrupt":
                        self.interrupts += 1
                        self.playback = np.zeros(0, dtype=np.int16)
                    continue
                pcm = np.frombuffer(message, dtype=np.int16)
                up = np.interp(np.linspace(0, len(pcm), len(pcm) * RATE // self.OUT_RATE, endpoint=False),
                               np.arange(len(pcm)), pcm).astype(np.int16)
                self.playback = np.concatenate([self.playback, up])
        except Exception:
            return

    async def _play(self):
        start, played = time.time(), 0
        while True:
            wait = start + played / RATE - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
            chunk, self.playback = self.playback[:FRAME], self.playback[FRAME:]
            if len(chunk):
                chunk = np.pad(chunk, (0, FRAME - len(chunk)))
                self.chunks.append((time.time(), chunk))
            played += FRAME

    def spans(self, threshold: int = 400, gap: float = 0.7) -> list:
        spans = []
        for t, pcm in self.chunks:
            if np.abs(pcm).mean() < threshold:
                continue
            if spans and t - spans[-1][1] <= gap:
                spans[-1][1] = t
            else:
                spans.append([t, t])
        out = []
        for a, b in spans:
            pcm = np.concatenate([p for t, p in self.chunks if a - 0.05 <= t <= b + 0.05])
            out.append((a, b + FRAME / RATE, pcm))
        return out

    async def close(self):
        for t in self.tasks:
            t.cancel()
        if self.socket is not None:
            try:
                await self.socket.close()
            except Exception:
                pass


class Pointe(Base):
    name = "pointe"
    kind = "spoken"
    capabilities = frozenset(CAPABILITIES)

    def __init__(self, worker_port: int):
        super().__init__()
        assert worker_port not in FORBIDDEN_PORTS and worker_port + 1 not in FORBIDDEN_PORTS
        self.port, self.tls = worker_port, worker_port + 1
        self.call: Call | None = None
        self._log_pos = 0
        self.log_lines: list = []
        self.state: Path | None = None
        self.started_at = 0.0
        self.names: dict = {}  # repo name -> the name Pointe gave the session ("tariff/main")

    @property
    def extra_args(self):
        return ("--plugin-dir", str(self.env.pointe))

    def denv(self) -> dict:
        assert self.state and str(self.state).startswith(("/tmp/", "/private/tmp/")), "state must be under /tmp"
        assert self.state != Path.home() / ".claude-voice"
        return {"CLAUDE_VOICE_STATE": str(self.state), "CLAUDE_VOICE_DAEMON_PORT": str(self.port),
                "CLAUDE_VOICE_TLS_PORT": str(self.tls), "POINTE_LINK_DIR": str(self.state / "linkbin"),
                "CLAUDE_VOICE_FRONT": "brain", "CLAUDE_VOICE_NO_BROWSER": "1"}

    def agent_env(self, name):
        return self.denv()

    def daemon(self, *args) -> subprocess.CompletedProcess:
        env = clean_env()
        env.update(self.denv())
        env["PATH"] = f"/tmp/pccb-pointe/guard-bin:{env.get('PATH', '/usr/bin:/bin')}"  # core.runner.guard_bin
        return subprocess.run([str(self.env.pointe / "bin" / "voice-daemon"), *args], env=env, capture_output=True,
                              text=True, timeout=600)

    def fresh_state(self) -> None:
        """rig.fresh_state(): a clean, test-only daemon state, never the real one."""
        assert self.state != Path.home() / ".claude-voice", "set CLAUDE_VOICE_STATE for tests"
        self.daemon("stop")
        shutil.rmtree(self.state, ignore_errors=True)
        self.state.mkdir(parents=True)
        (self.state / "setup-done").touch()  # Pointe has been set up on this machine: /pointe:voice joins, no setup
        (self.state / "first-hello").touch()  # and has answered someone before: no first-call onboarding greeting

    def status(self) -> dict:
        token = (self.state / "token").read_text().strip()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/voice/status", headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.load(r)
        except Exception:
            return {}

    def lines(self) -> list:
        path = self.state / "daemon.log"
        if path.exists():
            with open(path, errors="replace") as f:
                f.seek(self._log_pos)
                data = f.read()
                self._log_pos = f.tell()
            self.log_lines += data.splitlines()
        return self.log_lines

    def start(self, sessions, env):
        self.env = env
        self.state = Path(f"/tmp/pccb-pointe/{env.run_id}-{self.port}")
        self.fresh_state()
        got = self.daemon("ensure")
        if got.returncode != 0:
            raise RuntimeError(f"pointe daemon did not start: {got.stderr[-300:]}")
        self.started_at = time.time()
        super().start(sessions, env)  # starts every agent session with --plugin-dir
        for name, agent in self.agents.items():
            before = len([l for l in self.lines() if re.search(r"registered .*\(pid \d+", l)])
            agent.type("/pointe:voice")
            deadline = time.time() + 120
            while time.time() < deadline:
                regs = [l for l in self.lines() if re.search(r"registered .*\(pid \d+", l)]
                if len(regs) > before:
                    m = re.search(r"registered (\S+) \(pid", regs[-1])
                    self.names[name] = m.group(1) if m else name
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError(f"/pointe:voice did not register {name}")
            for _ in range(60):  # the join turn finishes before the first request
                if not agent.busy():
                    break
                time.sleep(1)
            time.sleep(2)
        token = (self.state / "token").read_text().strip()
        self.call = Call(f"ws://127.0.0.1:{self.port}/voice/call", token)

    async def connect(self):
        await self.call.connect()
        t0 = time.time()
        while time.time() - t0 < 25:  # the greeting
            await asyncio.sleep(0.5)
            spans = self.call.spans()
            if spans and time.time() - spans[-1][1] > 2.0:
                break

    async def say(self, pcm, rate):
        pcm = np.asarray(pcm)
        if rate != RATE:
            pcm = np.interp(np.linspace(0, len(pcm), int(len(pcm) * RATE / rate), endpoint=False),
                            np.arange(len(pcm)), pcm).astype(np.int16)
        start, end = self.call.say(pcm)
        await asyncio.sleep(max(0.0, end - time.time()))
        return start, end

    def speech(self):
        return self.call.spans() if self.call else []

    def thinking(self) -> bool:
        """The voice is mid-step: a brain step or a send logged in the last 2.5 seconds."""
        lines = self.lines()[-5:]
        if not lines:
            return False
        try:
            t = time.mktime(time.strptime(lines[-1][:19], "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            return False
        return time.time() - t < 2.5

    def events(self):
        out = self.hook_events()
        for line in self.lines()[getattr(self, "_mapped", 0):]:
            try:
                t = time.mktime(time.strptime(line[:19], "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                t = time.time()
            if m := re.search(r" - -> (\S+): (.*)", line):
                out.append(Event("delivered", t, m.group(1), m.group(2)[:400]))
            elif "[permission request]" in line or "permission request]" in line:
                out.append(Event("approval_request", t, None, line[-300:]))
            elif m := re.search(r"permission (\S+)/\S+ -> (\w+) \((.*)\)", line):
                out.append(Event("approval_decision", t, m.group(1), m.group(2), {"how": m.group(3)}))
            elif m := re.search(r"speak: (.*)", line):
                out.append(Event("said", t, None, m.group(1)[:400]))
            elif "finished its turn" in line:
                out.append(Event("agent_turn_done", t, None, line[-200:]))
        self._mapped = len(self.lines())
        return out

    def versions(self):
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.env.pointe, capture_output=True, text=True).stdout.strip()
        setup = {}
        for line in self.log_lines:
            if m := re.search(r"setup: Setup\((.*?)(?:, notes=|\))", line):
                setup = dict(re.findall(r"(\w+)='([^']*)'", m.group(1)))
                break
        return {"adapter": self.name, "pointe_commit": commit, "setup": "default (no setup chosen)", "roles": setup}

    def spend(self):
        """Computed from daemon.log: brain steps at their logged token counts, an output allowance per step, the reader
        and checker at a fixed price per call, the mouth by characters spoken, and two Soniox streams for the call."""
        lines = self.log_lines
        brain = 0.0
        steps = 0
        for line in lines:
            if m := re.search(r"brain step: \d+ ms, (\d+) tokens in(?:, (\d+) of them cached)?", line):
                total, cached = int(m.group(1)), int(m.group(2) or 0)
                steps += 1
                brain += token_cost("claude-sonnet-5-5", {"cache_read_input_tokens": cached,
                                                          "cache_creation_input_tokens": max(0, total - cached),
                                                          "output_tokens": PRICES["pointe_brain_output_tokens_per_step"]})
        chars = sum(len(m.group(1)) for line in lines if (m := re.search(r"speak: '(.*)'", line)))
        reports = sum(1 for line in lines if re.search(r"notes on .* updated|brain:read:", line))
        checks = sum(1 for line in lines if re.search(r" - -> \S+: |permission \S+ -> ", line))
        secs = max(0.0, time.time() - self.started_at)
        return [SpendRow("anthropic", brain, "computed", f"{steps} brain steps from daemon.log"),
                SpendRow("anthropic", reports * PRICES["pointe_reader_report"], "computed", f"{reports} reader reports"),
                SpendRow("gemini", checks * PRICES["pointe_checker_call"], "computed", f"{checks} checker lines"),
                SpendRow("elevenlabs", chars / 1000 * PRICES["elevenlabs_per_1k_chars"], "computed", f"{chars} chars"),
                SpendRow("soniox", 2 * secs / 3600 * PRICES["soniox_stream_hour"], "computed", f"2 streams x {secs:.0f} s")]

    def stop(self):
        if self.call:
            try:
                asyncio.get_event_loop().create_task(self.call.close())
            except RuntimeError:
                pass
        super().stop()
        try:
            self.daemon("stop")
        except Exception:
            pass
