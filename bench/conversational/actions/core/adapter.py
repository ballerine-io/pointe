"""The adapter interface and the normalized events every arm reports.

Events, each with a wall time: delivered(session, text), approval_request(session, tool, input),
approval_decision(session, allow|deny, how), agent_turn_done(session), asked(text), said(text), heard(text),
stopped(session). The file system stays the primary ground truth; events explain it.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from core.agent import AgentSession, FakeAgent

CAPABILITIES = frozenset({"audio_in", "text_in", "speech_out", "approvals", "sessions", "interrupt"})


@dataclass
class Event:
    t: float
    kind: str
    data: dict = field(default_factory=dict)

    def row(self) -> dict:
        return {"t": round(self.t, 3), "kind": self.kind, **self.data}


@dataclass
class RunEnv:
    """What the runner gives an adapter for one item run."""
    folder: Path                 # /tmp/pccb/<run-id>/<item-run>/ : repo/, cfg/, hooks.jsonl
    session: str                 # the session's spoken name
    api_key: str                 # the agent's key: only into the agent's environment
    port: int                    # this worker's port, inside the range given to the run
    item: dict
    secrets: dict                # other vendor keys this adapter needs (router: soniox, anthropic)
    prices: dict
    fake: bool = False           # offline tests: FakeAgent, no network


class Adapter:
    """Base: owns the one agent session. Subclasses decide what a spoken utterance does."""

    name = "base"
    capabilities: frozenset = frozenset()
    extra_args: tuple = ()

    def __init__(self):
        self._events: list[Event] = []
        self._seen = 0
        self.agent = None
        self.env: RunEnv | None = None
        self._spend: dict = {}

    # ----- lifecycle -----
    def agent_env(self) -> dict:
        return {}

    def start(self, env: RunEnv) -> None:
        self.env = env
        cls = FakeAgent if env.fake else AgentSession
        self.agent = cls(env.folder, env.api_key, self.extra_args, self.agent_env())
        self.agent.start()

    def ready(self, phase: str, since: float, timeout: float) -> bool:
        """True when the harness is ready to hear the user (Pointe: its question has been read out)."""
        return True

    def say(self, pcm: np.ndarray, rate: int, item: dict) -> tuple[float, float]:
        """Play the utterance at real-time pace. Returns (start, end) wall times."""
        start = time.time()
        return start, start + len(pcm) / rate

    def type(self, text: str) -> None:
        self.agent.type(text)

    def key(self, name: str) -> None:
        self.agent.key(name)

    def emit(self, kind: str, **data) -> None:
        self._events.append(Event(time.time(), kind, data))

    def events(self) -> list[Event]:
        """Everything since the last call (the full list stays for spoke_after)."""
        out = self._events[self._seen:]
        self._seen = len(self._events)
        return out

    def spoke_after(self, t: float) -> list[dict]:
        """Speech the harness produced after wall time t: [{"t", "text"}]."""
        return [e.row() for e in self._events if e.kind == "said" and e.t >= t]

    def versions(self) -> dict:
        return {}

    def spend(self) -> dict:
        """{vendor: [usd, "computed" | "estimated"]} beyond the agent's own session."""
        return dict(self._spend)

    def stop(self) -> None:
        if self.agent:
            self.agent.stop()
