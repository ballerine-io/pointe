"""What the two reference voice arms share (naive and llm-router, both written by Pointe's team): the user's audio goes
through Soniox real-time, the recognizer of Pointe's default setup; the agent's permission prompts and the final
message of each of its turns (first 600 characters) are spoken through local Kokoro."""

import asyncio
import re
import threading
import time

import numpy as np

from adapters.base import Base
from core import asr
from core.adapter import CAPABILITIES, Event, SpendRow
from core.corpus import RATE, Kokoro
from core.ledger import PRICES

BOT_VOICE = "af_bella"  # not one of the four user voices


def speakable(text: str) -> str:
    text = re.sub(r"```.*?```", " (code) ", text or "", flags=re.S)
    text = re.sub(r"[`*#>|_]", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:600]


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

    def start(self, sessions, env):
        super().start(sessions, env)
        self.last_session = next(iter(self.agents))

    async def connect(self):
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
        """Synthesize and 'play' at real-time pace: the span runs from when the speaker is free until its length."""
        self.busy_until = time.time() + 30
        pcm = await asyncio.to_thread(Kokoro.say, text, BOT_VOICE, "en-us")
        start = max(time.time(), self._said_until)
        end = start + len(pcm) / RATE
        self._said_until = end
        self._spans.append((start, end, pcm))
        self._events.append(Event("said", start, None, text))
        self.busy_until = 0.0
        await asyncio.sleep(max(0.0, end - time.time()))

    def thinking(self) -> bool:
        return time.time() < self.busy_until

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
                         f"{self.heard_secs:.0f} s streamed")]

    def stop(self):
        if self._watch:
            self._watch.cancel()
        super().stop()
