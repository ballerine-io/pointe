"""What every adapter shares: the agent sessions started with the one launch line, and events read from their hooks."""

import re
import time
from pathlib import Path

from core.adapter import AgentSession, Event, RunEnv, write_config


class Base:
    name = "base"
    kind = "typed"  # typed | spoken | null
    capabilities = frozenset()
    extra_args: tuple = ()

    def __init__(self):
        self.agents: dict = {}
        self.env: RunEnv | None = None
        self._seen: dict = {}
        self._events: list = []
        self._spans: list = []

    def agent_env(self, name: str) -> dict:
        return {}

    def start(self, sessions: dict, env: RunEnv) -> None:
        self.env = env
        for name, repo in sessions.items():
            cfg = env.slot / f".cfg-{name}"
            write_config(cfg, repo, [str(env.stage.parent), str(env.pointe / "bench" / "conversational")], allow=env.allow)
            agent = AgentSession(name, repo, cfg, env.api_key, self.extra_args, self.agent_env(name))
            self.agents[name] = agent
        for agent in self.agents.values():
            agent.start()

    def hook_events(self) -> list:
        out = []
        for name, agent in self.agents.items():
            ev = agent.hooks()
            for e in ev[self._seen.get(name, 0):]:
                kind = {"UserPromptSubmit": "delivered", "PermissionRequest": "approval_request",
                        "Stop": "agent_turn_done"}.get(e.get("hook_event_name"))
                if kind:
                    text = e.get("prompt") or str((e.get("tool_input") or {}).get("command") or "")
                    out.append(Event(kind, e["_t"], name, text[:400]))
            self._seen[name] = len(ev)
        return out

    def events(self) -> list:
        new = self.hook_events() + self._events
        self._events = []
        return new

    def speech(self) -> list:
        return list(self._spans)

    READOUT = re.compile(r"\bwants? to\b|\bמבקש\b|needs an approval|צריך אישור")

    def readout_since(self, t: float) -> float | None:
        """When the arm began to say a permission request's read-out, at or after `t`; None while it has not."""
        for e in self._said_events():
            if e[0] >= t and self.READOUT.search(e[1]):
                return e[0]
        return None

    def _said_events(self) -> list:
        """(time, text) of each line the arm said, as the arm itself records it."""
        return [(e.t, e.text or "") for e in getattr(self, "_events", []) if e.kind == "said"]

    def thinking(self) -> bool:
        return False

    def versions(self) -> dict:
        return {"adapter": self.name}

    def spend(self) -> list:
        return []

    def type(self, text: str, session: str | None = None) -> None:
        self.agents[session or next(iter(self.agents))].type(text)

    def key(self, name: str, session: str | None = None) -> None:
        self.agents[session or next(iter(self.agents))].key(name)

    async def say(self, pcm, rate: int) -> tuple[float, float]:
        now = time.time()
        return now, now

    def stop(self) -> None:
        for agent in self.agents.values():
            agent.stop()
