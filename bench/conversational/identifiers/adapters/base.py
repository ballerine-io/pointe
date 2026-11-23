"""What the agent-backed arms share: one AgentPty per named session, events from the pty and the Stop hook, the
agent's spend computed from its transcript usage and prices.json."""

import time
from pathlib import Path

from core.adapter import Event, RunEnv, SpendRow
from core.agent import AgentPty, claude_version


class AgentAdapter:
    name = "agent"
    capabilities = frozenset({"text_in"})
    plugin = False

    def __init__(self):
        self.agents: dict[str, AgentPty] = {}
        self._events: list[Event] = []
        self._stops: dict[str, int] = {}
        self.env: RunEnv | None = None

    def agent_args(self, env: RunEnv) -> tuple:
        return ()

    def agent_env(self, env: RunEnv) -> dict:
        return {}

    def start(self, sessions: dict[str, Path], env: RunEnv) -> None:
        self.env = env
        for name, repo in sessions.items():
            a = AgentPty(repo, env.item_dir / f"config-{name}", env.model, env.permission_mode, env.deny_read,
                         env.secrets["anthropic"], self.agent_args(env), self.agent_env(env), env.allow)
            self.agents[name] = a
            a.start()
            self._stops[name] = a.stop_count()

    def _session(self, session: str | None) -> str:
        return session or next(iter(self.agents))

    def type(self, text: str, session: str | None = None) -> None:
        s = self._session(session)
        at = self.agents[s].type(text)
        self._events.append(Event("delivered", at, s, text))

    def key(self, name: str, session: str | None = None) -> None:
        self.agents[self._session(session)].key(name)

    def say(self, pcm: bytes, rate: int) -> tuple[float, float]:
        raise NotImplementedError

    def poll(self) -> None:
        for name, a in self.agents.items():
            n = a.stop_count()
            if n > self._stops[name]:
                self._stops[name] = n
                self._events.append(Event("agent_turn_done", time.time(), name, a.last_text()[-600:]))

    def events(self) -> list[Event]:
        self.poll()
        out, self._events = self._events, []
        return out

    def speech(self) -> list:
        return []

    def last_text(self, session: str | None = None) -> str:
        return self.agents[self._session(session)].last_text()

    def versions(self) -> dict:
        return {"adapter": self.name, "claude_code": claude_version(), "agent_model": self.env.model if self.env else ""}

    def spend(self) -> list[SpendRow]:
        rows = []
        for name, a in self.agents.items():
            rows.append(SpendRow("anthropic-agent", a.usd(), "computed", {"session": name, "usage": a.usage()}))
        return rows

    def transcripts(self) -> list[Path]:
        return [t for a in self.agents.values() for t in a.transcripts()]

    def prompts_denied(self) -> int:
        return sum(a.prompts_denied for a in self.agents.values())

    def init_info(self) -> dict:
        return next((a.init_info() for a in self.agents.values()), {})

    def stop(self) -> None:
        for a in self.agents.values():
            a.stop()
