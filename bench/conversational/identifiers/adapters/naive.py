"""Keyword rules, ours (design 4.3). Speech to text with the same recognizer as llm-router, then rules: the first word
that names a session picks it, else the last one used; "yes", "approve", "go ahead" allow a pending prompt; "no",
"deny", "don't" deny one; "stop" or "cancel" send Escape; anything else is typed in as heard.
Expected to fail adversarial items by construction; never used in a headline delta."""

import re
import time

from adapters.base import AgentAdapter
from core import ears
from core.adapter import Event, SpendRow
from core.ledger import PRICES

YES = ("yes", "approve", "go ahead")
NO = ("no", "deny", "don't")
STOP = ("stop", "cancel")


def decide(transcript: str, sessions: list[str], pending: bool, last: str | None) -> tuple[str, str]:
    words = re.findall(r"[a-z']+", transcript.lower())
    session = next((w for w in words if w in sessions), last or sessions[-1])
    text = " ".join(words)
    if pending and any(re.search(rf"\b{re.escape(w)}\b", text) for w in YES):
        return "approve", session
    if pending and any(re.search(rf"\b{re.escape(w)}\b", text) for w in NO):
        return "deny", session
    if any(w in words for w in STOP) and len(words) <= 4:
        return "stop", session
    return "send", session


class Naive(AgentAdapter):
    name = "naive"
    capabilities = frozenset({"audio_in", "text_in", "approvals", "sessions", "interrupt"})

    def __init__(self):
        super().__init__()
        self.audio_seconds = 0.0
        self.last = None

    def say(self, pcm: bytes, rate: int) -> tuple[float, float]:
        start = time.time()
        heard = ears.transcribe(pcm, rate, self.env.secrets["soniox"])
        end = start + len(pcm) / (2 * rate)
        self.audio_seconds += heard["seconds"]
        self._events.append(Event("heard", time.time(), None, heard["text"]))
        action, session = decide(heard["text"], list(self.agents), False, self.last)
        self.last = session
        if action == "send" and heard["text"]:
            self.type(heard["text"], session)
        elif action == "stop":
            self.key("escape", session)
        return start, end

    def versions(self) -> dict:
        return {**super().versions(), "recognizer": f"soniox:{ears.MODEL}"}

    def spend(self) -> list[SpendRow]:
        usd = self.audio_seconds / 3600 * PRICES["soniox_rt_per_stream_hour"]
        return super().spend() + [SpendRow("soniox", usd, "computed", {"seconds": round(self.audio_seconds, 1)})]
