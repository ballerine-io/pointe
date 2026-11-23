"""The floor (design 4.3): starts the sessions and does nothing."""

import time

from adapters.base import AgentAdapter
from core.adapter import CAPABILITIES


class Null(AgentAdapter):
    name = "null"
    capabilities = CAPABILITIES  # all, as no-ops

    def say(self, pcm: bytes, rate: int) -> tuple[float, float]:
        now = time.time()
        return now, now + len(pcm) / (2 * rate)

    def type(self, text: str, session: str | None = None) -> None:
        pass

    def key(self, name: str, session: str | None = None) -> None:
        pass
