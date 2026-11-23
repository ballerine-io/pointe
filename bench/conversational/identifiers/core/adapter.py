"""The adapter interface and the normalized events (design section 4.2).

Every arm is one Adapter. The runner never looks inside one: it starts it on named repositories, plays audio or types
text into it, reads its events, and stops it. The file system stays the primary ground truth; events explain it.
"""

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

CAPABILITIES = frozenset({"audio_in", "text_in", "speech_out", "approvals", "sessions", "interrupt"})


@dataclass
class Event:
    kind: str  # delivered | approval_request | approval_decision | agent_turn_done | asked | said | heard | stopped | note
    at: float = field(default_factory=time.time)
    session: str | None = None
    text: str = ""
    extra: dict = field(default_factory=dict)

    def row(self) -> dict:
        return asdict(self)


@dataclass
class SpendRow:
    vendor: str  # anthropic-agent | anthropic-router | soniox | pointe-voice
    usd: float
    how: str  # metered | computed
    detail: dict = field(default_factory=dict)


@dataclass
class RunEnv:
    """What the runner gives an adapter for one item run."""

    item_dir: Path  # /tmp/pccb/<run-id>/<item>/ : holds repo/, config/ and the adapter's own state
    model: str
    permission_mode: str
    deny_read: list[str]  # folders no arm may read (the bench's own folder, the staging folder)
    port: int  # this worker's port, in the range the runner was given
    secrets: dict[str, str]  # vendor keys, handed only to the child processes that need them
    pointe_root: Path | None = None  # the Pointe checkout under test (pointe arms only)
    allow: list[str] | None = None  # the settings file's allow rules, the same in every arm
    seed: int = 0


class Adapter(Protocol):
    name: str
    capabilities: frozenset[str]

    def start(self, sessions: dict[str, Path], env: RunEnv) -> None: ...
    def say(self, pcm: bytes, rate: int) -> tuple[float, float]: ...
    def type(self, text: str, session: str | None = None) -> None: ...
    def key(self, name: str, session: str | None = None) -> None: ...
    def events(self) -> list[Event]: ...
    def speech(self) -> list[tuple[float, float, bytes]]: ...
    def versions(self) -> dict[str, str]: ...
    def spend(self) -> list[SpendRow]: ...
    def stop(self) -> None: ...


class Unsupported(Exception):
    """An item needs a capability the adapter lacks: the run is `unsupported`, shown as coverage, never a failure."""
