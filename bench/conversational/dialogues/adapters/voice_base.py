"""The plain router's ears and mouth (written by Pointe's team): the user's audio goes through Soniox real-time, the
recognizer of Pointe's default setup; the agent's permission prompts and the final message of each of its turns (first
600 characters) are spoken through the same ElevenLabs voice as Pointe's default setup. (The published benchmarks used
local Kokoro; on this shared, heavily loaded machine Kokoro took 10-20 s a line, which would have measured the CPU.)"""

import asyncio
import re
import threading
import time

import numpy as np

from adapters.base import Base
from core import asr
from core.adapter import CAPABILITIES, Event, SpendRow
from core.corpus import RATE, ROOT
from core.ledger import PRICES

BOT_VOICE = "af_bella"  # not one of the four user voices


def speakable(text: str) -> str:
    text = re.sub(r"```.*?```", " (code) ", text or "", flags=re.S)
    text = re.sub(r"[`*#>|_]", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:600]


def elevenlabs(text: str) -> tuple[float, np.ndarray]:
    """(time the first audio byte arrived, 24 kHz PCM) from ElevenLabs' streaming endpoint. The key goes only into this
    request's header."""
    import json as _json
    import sys
    import urllib.request
    from core.corpus import _key
    sys.path.insert(0, str(ROOT))
    import vendors
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{vendors.DEFAULT_ELEVENLABS_VOICE}/stream?output_format=pcm_24000",
        data=_json.dumps({"text": text, "model_id": "eleven_v4_turbo"}).encode(),
        headers={"xi-api-key": _key("ELEVENLABS_API_KEY", "elevenlabs-api-key"), "Content-Type": "application/json"})
    first, parts = None, []
    with urllib.request.urlopen(req, timeout=30) as r:
        while chunk := r.read(4800):
            first = first or time.time()
            parts.append(chunk)
    raw = b"".join(parts)
    return first or time.time(), np.frombuffer(raw[:len(raw) // 2 * 2], dtype=np.int16).copy()


class VoiceBase(Base):
    kind = "spoken"
    capabilities = frozenset(CAPABILITIES)

    def __init__(self, soniox_model: str):
        super().__init__()
        self.soniox_model = soniox_model
        self.heard_secs = 0.0
        self.busy_until = 0.0
        self._handled_stops: dict = {}
        self._handled_perms: set = set()
        self._speak_lock = threading.Lock()
        self._said_until = 0.0
        self.last_session: str | None = None
        self._watch: asyncio.Task | None = None
        self.heard: list = []
        self.tts_chars = 0
        self._said_log: list = []

    def _said_events(self) -> list:
        return list(self._said_log)

    def start(self, sessions, env):
        super().start(sessions, env)
        self.last_session = next(iter(self.agents))

    async def connect(self):
        for name, agent in self.agents.items():  # the setup turn's reply is not the user's business
            self._handled_stops[name] = agent.stops()
        self._watch = asyncio.create_task(self._watcher())

    async def _watcher(self):
        """Speak each permission prompt once, and each turn's final message."""
        while True:
            await asyncio.sleep(0.5)
            for name, agent in self.agents.items():
                ap = agent.pending_approval()
                if ap and ap["_t"] not in self._handled_perms:
                    self._handled_perms.add(ap["_t"])
                    cmd = (ap.get("tool_input") or {}).get("command") or ap.get("tool_name", "a tool")
                    self._events.append(Event("approval_request", time.time(), name, str(cmd)[:300]))
                    await self.speak(f"{name} wants to run: {speakable(str(cmd))[:200]}. Should it?")
                stops = agent.stops()
                if stops > self._handled_stops.get(name, 0):
                    self._handled_stops[name] = stops
                    await asyncio.sleep(0.5)
                    text = speakable(agent.last_text())
                    if text:
                        await self.speak(text)

    async def speak(self, text: str) -> None:
        """Speak through the same mouth as Pointe's default setup (ElevenLabs eleven_v4_turbo, HTTP streaming, the same
        voice), played at real-time pace from the first audio byte. One voice at a time: a line waits for the last."""
        self.busy_until = time.time() + 30
        first, pcm = await asyncio.to_thread(elevenlabs, text)
        self.tts_chars += len(text)
        start = max(first, self._said_until)
        end = start + len(pcm) / RATE
        self._said_until = end
        self._spans.append((start, end, pcm))
        self._events.append(Event("said", start, None, text))
        self._said_log.append((start, text))
        self.busy_until = 0.0
        await asyncio.sleep(max(0.0, end - time.time()))

    def thinking(self) -> bool:
        return time.time() < self.busy_until or time.time() < self._said_until

    async def say(self, pcm, rate):
        start = time.time()
        self.busy_until = start + 60
        try:
            text, secs = await asr.soniox(np.asarray(pcm), rate, self.env.keys["soniox"], self.soniox_model)
        finally:
            self.busy_until = time.time() + 30
        self.heard_secs += secs
        end = start + len(pcm) / rate
        self.heard.append(text)
        try:
            await self.handle(text)
        finally:
            self.busy_until = 0.0
        return start, end

    async def handle(self, text: str) -> None:
        raise NotImplementedError

    def pending(self):
        for name, agent in self.agents.items():
            ap = agent.pending_approval()
            if ap:
                return name, ap
        return None, None

    def spend(self):
        return [SpendRow("soniox", self.heard_secs / 3600 * PRICES["soniox_stream_hour"], "computed",
                         f"{self.heard_secs:.0f} s streamed"),
                SpendRow("elevenlabs", self.tts_chars / 1000 * PRICES["elevenlabs_per_1k_chars"], "computed",
                         f"{self.tts_chars} characters spoken")]

    def stop(self):
        if self._watch:
            self._watch.cancel()
        super().stop()
