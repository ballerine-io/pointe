"""The adapter interface every arm implements, and the normalized events it reports.

One clock for the whole suite: `now()`, the runner's monotonic clock. Every time in an event, a speech span or a row is
on it, so an audio frame's send time and a recorded frame's receive time can be subtracted directly.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

now = time.monotonic

CAPABILITIES = frozenset({"audio_in", "text_in", "speech_out", "approvals", "sessions", "interrupt"})


@dataclass
class Event:
    t: float
    kind: str  # delivered | approval_request | approval_decision | agent_turn_done | asked | said | stopped | heard | action
    session: str | None = None
    text: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class SpendRow:
    vendor: str
    usd: float
    how: str  # metered | computed
    detail: str = ""


@dataclass
class RunEnv:
    """What the runner hands an adapter for one item run."""

    root: Path  # /tmp/pccb/<run-id>/<item>-<arm>-<k>: everything this run writes
    port_base: int
    setup: str | None = None  # --pointe-setup
    mode: str = "acceptEdits"  # one permission mode per benchmark, the same in every arm
    allow: list = field(default_factory=list)  # the agent's settings file: identical in every arm
    deny: list = field(default_factory=list)
    voice: str = "af_heart"  # the item's panel voice; reference arms speak in their own fixed voice
    log: list = field(default_factory=list)  # raw lines for events.jsonl, scrubbed before they are written


class Adapter(Protocol):
    name: str
    capabilities: frozenset[str]

    def start(self, sessions: dict[str, Path], env: RunEnv) -> None: ...
    def setup_type(self, text: str) -> float: ...  # runner-side setup turn, identical in every arm; not under test
    def say(self, pcm: bytes, rate: int) -> tuple[float, float]: ...  # real-time pace; (start, end) on now()
    def type(self, text: str, session: str | None = None) -> float: ...
    def key(self, name: str, session: str | None = None) -> float: ...
    def events(self) -> list[Event]: ...
    def speech(self) -> list[tuple[float, float, bytes]]: ...  # (start, end, pcm16 at 16 kHz) of the arm's spoken output
    def versions(self) -> dict[str, str]: ...
    def spend(self) -> list[SpendRow]: ...
    def stop(self) -> None: ...
