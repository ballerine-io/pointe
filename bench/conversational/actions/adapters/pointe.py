"""Pointe as a stranger runs it: the plugin (`--plugin-dir`, the only change to the launch line), the session joined by
`/pointe:voice`, Pointe's default setup, and a call client speaking the page's WebSocket protocol (phone.py's).

Isolation: a fresh daemon per item run in the run's own /tmp state folder on the worker's port, its own uv environment,
and `POINTE_LINK_DIR` in /tmp so `bin/link-pointe` never rewrites the owner's `~/.local/bin/pointe`. Never port 7860 or
7443, never `~/.claude-voice`.

Capabilities, as the code at the pinned commit has them: audio in, speech out, approvals, sessions. There is no
interrupt for a Claude Code session (the brain's tools have no stop), so the stop items are run and scored as they come.
"""

import asyncio
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from core.adapter import Adapter

ROOT = Path(__file__).resolve().parents[4]
IN_RATE, OUT_RATE = 16000, 24000
FRAME = 320  # 20 ms at 16 kHz
ASKED = re.compile(r"speak: .*(?:Should it\?|[Ss]ay it again|wants to)")
LOG_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}) \| \w+ +\| [^-]+- (.*)$")
FORBIDDEN_PORTS = (7860, 7443)
# Unit prices behind the estimate (docs/benchmarks.md, "Cost arithmetic"; prices.json "pointe").
VENV = Path("/tmp/pccb/actions-pointe-venv")


def log_time(stamp: str) -> float:
    return time.mktime(time.strptime(stamp[:19], "%Y-%m-%d %H:%M:%S")) + float("0" + stamp[19:23])


class Call:
    """The page's call: mic frames out at real-time pace, the bot's audio in, with when it is audibly speaking."""

    def __init__(self, port: int, token: str):
        self.port, self.token = port, token
        self.queue: list[np.ndarray] = []
        self.play_until = 0.0
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.ws = None
        self.tasks = []

    def connect(self) -> None:
        self.thread.start()
        asyncio.run_coroutine_threadsafe(self._connect(), self.loop).result(30)

    async def _connect(self) -> None:
        from websockets.asyncio.client import connect

        self.ws = await connect(f"ws://127.0.0.1:{self.port}/voice/call", max_size=None,
                                additional_headers={"Authorization": f"Bearer {self.token}"})
        self.tasks = [asyncio.create_task(self._send()), asyncio.create_task(self._receive())]

    async def _send(self) -> None:
        start, n = time.time(), 0
        while True:
            wait = start + n * FRAME / IN_RATE - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
            chunk = self.queue.pop(0) if self.queue else np.zeros(FRAME, np.int16)
            try:
                await self.ws.send(chunk.tobytes())
            except Exception:
                return
            n += 1

    async def _receive(self) -> None:
        try:
            async for message in self.ws:
                if isinstance(message, str):
                    if json.loads(message).get("type") == "interrupt":
                        self.play_until = time.time()
                    continue
                pcm = np.frombuffer(message, dtype=np.int16)
                if len(pcm) and np.abs(pcm).mean() > 300:  # audible speech, played at real-time pace
                    self.play_until = max(self.play_until, time.time()) + len(pcm) / OUT_RATE
        except Exception:
            return

    def speaking(self) -> bool:
        return time.time() < self.play_until + 0.3

    def say(self, pcm: np.ndarray) -> tuple[float, float]:
        start = time.time()
        for i in range(0, len(pcm), FRAME):
            chunk = pcm[i:i + FRAME]
            self.queue.append(np.pad(chunk, (0, FRAME - len(chunk))))
        return start, start + len(pcm) / IN_RATE

    def close(self) -> None:
        async def _close():
            for t in self.tasks:
                t.cancel()
            if self.ws is not None:
                await self.ws.close()
        try:
            asyncio.run_coroutine_threadsafe(_close(), self.loop).result(10)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)


class PointeAdapter(Adapter):
    name = "pointe"
    capabilities = frozenset({"audio_in", "text_in", "speech_out", "approvals", "sessions"})
    extra_args = ("--plugin-dir", str(ROOT))

    def __init__(self):
        super().__init__()
        self.call = None
        self.state = None

    # ----- the daemon -----
    def _daemon_env(self) -> dict:
        drop = ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_CONFIG_DIR", "VIRTUAL_ENV")
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_") and k not in drop
               and not k.endswith("_API_KEY")}
        env.update(CLAUDE_VOICE_STATE=str(self.state), CLAUDE_VOICE_DAEMON_PORT=str(self.env.port),
                   CLAUDE_VOICE_NO_BROWSER="1", CLAUDE_VOICE_FRONT="brain",
                   POINTE_LINK_DIR=str(self.env.folder / "linkdir"), UV_PROJECT_ENVIRONMENT=str(VENV))
        return env

    def agent_env(self) -> dict:
        env = self._daemon_env()
        return {k: env[k] for k in ("CLAUDE_VOICE_STATE", "CLAUDE_VOICE_DAEMON_PORT", "CLAUDE_VOICE_NO_BROWSER",
                                    "CLAUDE_VOICE_FRONT", "POINTE_LINK_DIR", "UV_PROJECT_ENVIRONMENT")}

    def log(self) -> str:
        path = self.state / "daemon.log"
        return path.read_text(errors="replace") if path.exists() else ""

    def start(self, env) -> None:
        self.env = env
        assert env.port not in FORBIDDEN_PORTS, "the owner's ports are never used"
        self.state = env.folder / "pstate"
        assert os.path.realpath(self.state).startswith(("/tmp/", "/private/tmp/")), "state folder must be under /tmp"
        self.state.mkdir(parents=True, exist_ok=True)
        (env.folder / "linkdir").mkdir(exist_ok=True)
        (self.state / "setup-done").touch()  # skips the first-run setup flow; the setup itself is the default
        # A returning user: on a Mac's very first call Pointe answers the first words heard as its hello check, which
        # would eat the utterance under test (seen in the first smoke run).
        (self.state / "first-hello").touch()
        got = subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], env=self._daemon_env(),
                             capture_output=True, text=True, timeout=240)
        if got.returncode != 0:
            raise RuntimeError(f"daemon did not start: {got.stderr[-300:]}")
        super().start(env)
        before = len(re.findall(r"registered .*\(pid \d+", self.log()))
        self.agent.type(f"/pointe:voice --name {env.session}")
        deadline = time.time() + 120
        while time.time() < deadline and len(re.findall(r"registered .*\(pid \d+", self.log())) <= before:
            time.sleep(0.5)
        if len(re.findall(r"registered .*\(pid \d+", self.log())) <= before:
            raise TimeoutError("/pointe:voice did not register the session")
        deadline = time.time() + 90  # the join turn ends before the first request
        while time.time() < deadline and not any(h.get("hook_event_name") == "Stop" for h in self.agent.hooks()):
            time.sleep(0.5)
        self.call = Call(env.port, (self.state / "token").read_text().strip())
        self.call.connect()
        time.sleep(2)
        self._quiet(25)  # the greeting

    def _quiet(self, timeout: float, hold: float = 1.2) -> bool:
        deadline, quiet_since = time.time() + timeout, None
        while time.time() < deadline:
            if self.call.speaking():
                quiet_since = None
            else:
                quiet_since = quiet_since or time.time()
                if time.time() - quiet_since >= hold:
                    return True
            time.sleep(0.1)
        return False

    def ready(self, phase: str, since: float, timeout: float) -> bool:
        if phase == "pending":  # a person answers once the question has been read out
            deadline = time.time() + timeout
            while time.time() < deadline:
                if any(log_time(t) >= since - 1 for t, msg in self.lines() if ASKED.search(msg)):
                    break
                time.sleep(0.3)
            else:
                return False
            time.sleep(1.0)
            return self._quiet(max(1.0, deadline - time.time()))
        return self._quiet(timeout)

    def say(self, pcm, rate, item):
        assert rate == IN_RATE
        start, end = self.call.say(pcm)
        time.sleep(max(0.0, end - time.time()))
        return start, end

    # ----- what the log shows -----
    def lines(self) -> list[tuple[str, str]]:
        out = []
        for line in self.log().splitlines():
            m = LOG_LINE.match(line)
            if m:
                out.append((m.group(1), m.group(2)))
        return out

    def collect(self) -> None:
        """Normalized events from daemon.log: speech, what was heard, permission decisions. Called once at the end."""
        for stamp, msg in self.lines():
            t = log_time(stamp)
            if msg.startswith("speak: "):
                self._events.append(_event(t, "said", text=msg[7:].strip("'\"")[:200]))
            elif msg.startswith("user said: "):
                self._events.append(_event(t, "heard", text=msg[11:].strip("'\"")[:200]))
            elif m := re.match(r"permission \S+ -> (allow|deny)", msg):
                self._events.append(_event(t, "approval_decision", decision=m.group(1), how="voice"))
            elif msg.startswith("sent to") or msg.startswith("send:"):
                self._events.append(_event(t, "delivered", text=msg[:160]))

    def spoke_after(self, t: float) -> list[dict]:
        return [{"t": log_time(s), "text": m[7:120]} for s, m in self.lines() if m.startswith("speak: ") and log_time(s) >= t]

    def spend(self) -> dict:
        text = self.log()
        chars = sum(int(c) for c in re.findall(r"TTSService#\d+ usage characters: (\d+)", text))
        lines = self.lines()
        call_seconds = (log_time(lines[-1][0]) - log_time(next((s for s, m in lines if m.startswith("page connected")),
                                                              lines[-1][0]))) if lines else 0
        users = sum(1 for _, m in lines if m.startswith("user said: "))
        notes = sum(1 for _, m in lines if m.startswith("notes on "))
        p = self.env.prices["pointe"]
        return {"elevenlabs": [round(chars / 1000 * p["elevenlabs_per_1k_chars"], 6), "computed"],
                "soniox": [round(call_seconds * 2 / 3600 * p["soniox_per_stream_hour"], 6), "estimated"],
                "anthropic-brain": [round(users * p["brain_per_reply"], 6), "estimated"],
                "anthropic-reader": [round(notes * p["reader_per_report"], 6), "estimated"]}

    def versions(self) -> dict:
        setup = next((m for _, m in self.lines() if m.startswith("setup: ")), "")
        return {"pointe_setup": setup[7:200]}

    def stop(self) -> None:
        if self.call:
            self.call.close()
        if self.state is not None:
            self.collect()
        super().stop()
        if self.state is not None:
            subprocess.run([str(ROOT / "bin" / "voice-daemon"), "stop"], env=self._daemon_env(), capture_output=True,
                           timeout=60)
            for pid in subprocess.run(["lsof", "-t", "-nP", f"-iTCP:{self.env.port}", "-sTCP:LISTEN"],
                                      capture_output=True, text=True).stdout.split():
                try:
                    os.kill(int(pid), 9)
                except (ProcessLookupError, ValueError):
                    pass


def _event(t: float, kind: str, **data):
    from core.adapter import Event
    return Event(t, kind, data)
