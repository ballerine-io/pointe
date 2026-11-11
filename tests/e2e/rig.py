"""End-to-end rig: a real Claude Code session, the voice daemon, and a fake browser.

The fake browser speaks synthesized utterances over WebRTC, exactly where a mic
would, and records what the voice model says back. Nothing in the daemon or
channel is mocked.
"""

import asyncio
import fcntl
import io
import json
import os
import pty
import re
import select
import struct
import subprocess
import termios
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "tests" / "e2e" / ".cache"

STATE = Path(os.environ.get("CLAUDE_VOICE_STATE", Path.home() / ".claude-voice"))
LOG = STATE / "daemon.log"
DAEMON = f"http://127.0.0.1:{os.environ.get('CLAUDE_VOICE_DAEMON_PORT', '7860')}"
RATE = 48000
FRAME = 960  # 20 ms
USER_VOICE = "EXAVITQu4vr4xnSDxMaL"  # differs from both front-model voices
GUEST_VOICES = ("JBFqnCBsd6RMkjVDRZzb", "N2lVS1w4EtoT3dr4eOWO")  # other people in a meeting: distinct from the user and the bot
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[()][A-Z0-9]")


def keychain(item: str) -> str:
    return subprocess.run(
        ["security", "find-generic-password", "-s", item, "-w"], capture_output=True, text=True, check=True
    ).stdout.strip()


# ---------- synthetic user speech ----------

async def synth(text: str, voice: str = USER_VOICE) -> np.ndarray:
    """ElevenLabs speech for the fake user (or a meeting guest), 48 kHz int16, cached by text and voice."""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = text if voice == USER_VOICE else f"{voice}:{text}"
    path = CACHE / f"{abs(hash(key)) % 10**12}.pcm"
    for attempt in range(4):
        if path.exists():
            break
        try:
            await _synth_once(text, path, voice)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            await asyncio.sleep(2 * (attempt + 1))
    return np.frombuffer(path.read_bytes(), dtype=np.int16)


async def _synth_once(text: str, path: Path, voice: str = USER_VOICE) -> None:
    if True:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=pcm_48000",
                headers={"xi-api-key": keychain("elevenlabs-api-key")},
                json={"text": text, "model_id": "eleven_v4_turbo"},
            ) as r:
                r.raise_for_status()
                path.write_bytes(await r.read())


class UserMic:
    """Audio track that plays queued utterances and silence otherwise."""

    kind = "audio"

    def __init__(self):
        self._queue: list[np.ndarray] = []
        self._current: np.ndarray | None = None
        self._pos = 0
        self._pts = 0
        self._start: float | None = None
        self.spoke_until = 0.0  # wall time the last utterance ends
        self.echo_gain = 0.0  # > 0: the speaker leaks back into this mic, as on laptop speakers
        self._echo = np.zeros(0, dtype=np.int16)

    def hear(self, pcm: np.ndarray) -> None:
        if self.echo_gain:
            self._echo = np.concatenate([self._echo, pcm])

    def say(self, pcm: np.ndarray) -> tuple[float, float]:
        """Queue speech; returns its expected (start, end) wall times."""
        start = max(time.time(), self.spoke_until)
        self.spoke_until = start + len(pcm) / RATE
        self._queue.append(pcm)
        return start, self.spoke_until

    async def recv(self) -> np.ndarray:
        if self._start is None:
            self._start = time.time()
        wait = self._start + self._pts / RATE - time.time()
        if wait > 0:
            await asyncio.sleep(wait)
        if self._current is None and self._queue:
            self._current, self._pos = self._queue.pop(0), 0
        if self._current is not None:
            chunk = self._current[self._pos : self._pos + FRAME]
            self._pos += FRAME
            if self._pos >= len(self._current):
                self._current = None
            chunk = np.pad(chunk, (0, FRAME - len(chunk)))
        else:
            chunk = np.zeros(FRAME, dtype=np.int16)
        if self.echo_gain and len(self._echo) >= FRAME:
            leak, self._echo = self._echo[:FRAME], self._echo[FRAME:]
            chunk = np.clip(chunk.astype(np.int32) + (leak * self.echo_gain).astype(np.int32),
                            -32768, 32767).astype(np.int16)
        self._pts += FRAME
        return chunk


@dataclass
class Speaker:
    """Records the voice model's audio with wall-clock timestamps."""

    chunks: list[tuple[float, np.ndarray]] = field(default_factory=list)
    mic: "UserMic | None" = None

    def speech_spans(self, since: float = 0, threshold: int = 400, gap: float = 0.7) -> list[tuple[float, float]]:
        """(start, end) wall times where the bot was audibly speaking."""
        spans: list[list[float]] = []
        for t, pcm in self.chunks:
            if t < since or not len(pcm) or np.abs(pcm).mean() < threshold:
                continue
            if spans and t - spans[-1][1] <= gap:
                spans[-1][1] = t
            else:
                spans.append([t, t])
        return [(a, b) for a, b in spans]

    def audio(self, start: float, end: float) -> np.ndarray:
        parts = [pcm for t, pcm in self.chunks if start - 0.05 <= t <= end + 0.05]
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.int16)


async def transcribe(pcm: np.ndarray) -> str:
    """What the bot said, via Gemini audio understanding."""
    if len(pcm) < RATE // 4:
        return ""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=(os.environ.get("GOOGLE_API_KEY") or keychain("gemini-api-key")))
    for attempt in range(4):
        try:
            return await _transcribe_once(client, buf.getvalue())
        except Exception:
            await asyncio.sleep(2 * (attempt + 1))
    return ""


async def _transcribe_once(client, wav: bytes) -> str:
    from google.genai import types

    resp = await client.aio.models.generate_content(
        model="gemini-3.5-flash",
        contents=[
            types.Part.from_bytes(data=wav, mime_type="audio/wav"),
            "Transcribe the speech in this audio.",
        ],
        config=types.GenerateContentConfig(
            temperature=0,
            system_instruction="You are a speech-to-text engine. Output only the exact spoken words, in the "
            "language spoken. No commentary, labels, quotes or corrections. Output nothing if there is no speech.",
        ),
    )
    return (resp.text or "").strip()


class Browser:
    """Fake browser tab: the page's WebSocket call to the daemon (phone.py's protocol), mic in, speaker out."""

    IN_RATE, OUT_RATE = 16000, 24000

    def __init__(self, echo_gain: float = 0.0):
        self.mic = UserMic()
        self.mic.echo_gain = echo_gain
        self.speaker = Speaker(mic=self.mic)
        self._socket = None
        self._tasks: list[asyncio.Task] = []
        self.interrupts = 0

    async def connect(self) -> None:
        from websockets.asyncio.client import connect

        url = DAEMON.replace("http", "ws", 1) + "/voice/call"
        self._socket = await connect(url, max_size=None, additional_headers={
            "Authorization": f"Bearer {(STATE / 'token').read_text().strip()}"})
        self._playback = np.zeros(0, dtype=np.int16)
        self._tasks = [asyncio.create_task(self._send()), asyncio.create_task(self._receive()), asyncio.create_task(self._play())]

    async def _send(self) -> None:
        while True:
            pcm = (await self.mic.recv()).reshape(-1, RATE // self.IN_RATE).mean(axis=1)  # 48 to 16 kHz, averaged against aliasing
            try:
                await self._socket.send(pcm.astype(np.int16).tobytes())
            except Exception:
                return

    async def _receive(self) -> None:
        try:
            async for message in self._socket:
                if isinstance(message, str):
                    if json.loads(message).get("type") == "interrupt":
                        self.interrupts += 1
                        self._playback = np.zeros(0, dtype=np.int16)
                    continue
                pcm = np.frombuffer(message, dtype=np.int16)
                up = np.interp(np.linspace(0, len(pcm), len(pcm) * RATE // self.OUT_RATE, endpoint=False),
                               np.arange(len(pcm)), pcm).astype(np.int16)
                self._playback = np.concatenate([self._playback, up])
        except Exception:
            return

    async def _play(self) -> None:
        """Plays at real-time pace, as a speaker does; an "interrupt" empties what is still queued, as the page must."""
        start, played = time.time(), 0
        while True:
            wait = start + played / RATE - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
            chunk, self._playback = self._playback[:FRAME], self._playback[FRAME:]
            chunk = np.pad(chunk, (0, FRAME - len(chunk)))
            self.speaker.chunks.append((time.time(), chunk))
            self.mic.hear(chunk) if chunk.any() else None
            played += FRAME

    async def say(self, text: str, voice: str = USER_VOICE) -> tuple[float, float]:
        return self.mic.say(await synth(text, voice))

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._socket is not None:
            await self._socket.close()



# ---------- the Claude Code session ----------

class ClaudeSession:
    """bin/claude-voice in a pty, auto-accepting the startup dialogs."""

    def __init__(self, cwd: Path, *claude_args: str, front: str = "brain"):
        self.cwd, self.args, self.front = cwd, claude_args, front
        self.screen = ""
        self._stop = False

    def start(self, timeout: float = 90) -> None:
        # Run from inside Claude Code, a child session inherits markers that stop it writing a transcript: it would be no
        # real session, and the voice would never hear from it.
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_") and k not in ("CLAUDECODE", "CLAUDE_PID")}
        env.update(CLAUDE_VOICE_NO_BROWSER="1", CLAUDE_VOICE_FRONT=self.front)
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(self.cwd)
            os.execvpe(str(ROOT / "bin" / "claude-voice"), ["claude-voice", *self.args], env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 200, 0, 0))
        threading.Thread(target=self._pump, daemon=True).start()
        deadline = time.time() + timeout
        while time.time() < deadline:
            # The daemon's record, not the status line: Claude Code's wording there changes between releases.
            if "channels(experimental)" in self.flat() or (LOG.exists() and re.search(r"registered .*\(pid \d+, channel[,)]", LOG.read_text(errors="ignore"))):
                return
            time.sleep(0.5)
        raise TimeoutError(f"Claude Code did not register the channel:\n{self.flat()[-800:]}")

    def flat(self) -> str:
        return re.sub(r"\s+", "", self.screen).lower()

    def _pump(self) -> None:
        handled: set[str] = set()
        while not self._stop:
            r, _, _ = select.select([self.fd], [], [], 0.3)
            if r:
                try:
                    self.screen += ANSI.sub("", os.read(self.fd, 65536).decode("utf-8", "replace"))
                    self.screen = self.screen[-200_000:]
                except OSError:
                    return
            flat = self.flat()[-8000:]
            if "trustthisfolder" in flat and "trust" not in handled:
                handled.add("trust"), time.sleep(0.4), os.write(self.fd, b"\x1b[B"), time.sleep(0.2), os.write(self.fd, b"\r")
            if "localdevelopment" in flat and "dev" not in handled:
                handled.add("dev"), time.sleep(0.4), os.write(self.fd, b"\r")

    def stop(self) -> None:
        self._stop = True
        for _ in range(2):
            try:
                os.write(self.fd, b"\x03")
            except OSError:
                break
            time.sleep(0.4)
        try:  # as a closed terminal tab would: the pty goes away and the whole group gets the signal, Claude Code included
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.killpg(self.pid, 9)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            os.kill(self.pid, 9)
            for _ in range(50):  # reap it, as a shell would, without waiting forever on a process that ignores us
                if os.waitpid(self.pid, os.WNOHANG) != (0, 0):
                    break
                time.sleep(0.1)
            # an unreaped zombie still looks alive
        except (ProcessLookupError, ChildProcessError):
            pass
        # Only this session's processes: a shared daemon (and the user's own voice) keeps running.


def stop_daemon() -> None:
    subprocess.run([str(ROOT / "bin" / "voice-daemon"), "stop"], env=dict(os.environ), capture_output=True, timeout=60)


def fresh_state() -> None:
    """A clean, test-only daemon state. Refuses the real one, which may be serving the user."""
    assert STATE != Path.home() / ".claude-voice", "set CLAUDE_VOICE_STATE for tests"
    stop_daemon()
    STATE.mkdir(parents=True, exist_ok=True)
    LOG.unlink(missing_ok=True)
    (STATE / "sessions.json").unlink(missing_ok=True)  # a mode or session from the last run must not carry over


def log_lines(pattern: str) -> list[str]:
    return [l for l in LOG.read_text().splitlines() if re.search(pattern, l)] if LOG.exists() else []
