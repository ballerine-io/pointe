"""What every arm shares: the one agent launch (core/agent.py) in the item's repo, and its spend."""

from pathlib import Path

from core import agent as agent_mod
from core.adapter import Event, RunEnv, SpendRow, now


class PtyArm:
    name = "base"
    capabilities = frozenset({"text_in", "interrupt"})
    extra_args: tuple[str, ...] = ()

    def __init__(self):
        self.agent: agent_mod.AgentPty | None = None
        self.env: RunEnv | None = None
        self._events: list[Event] = []
        self._extra_spend: list[SpendRow] = []

    def env_extra(self, env: RunEnv) -> dict:
        return {}

    def start(self, sessions: dict[str, Path], env: RunEnv) -> None:
        (name, repo), = sessions.items()  # bargein: one session per item
        self.session, self.env = name, env
        self.agent = agent_mod.AgentPty(repo, env.root / "cfg", env.mode, env.allow, env.deny,
                                        extra_args=self.extra_args, env_extra=self.env_extra(env))
        self.agent.start()
        if "acceptedits" not in self.agent.flat() and "accept edits" not in self.agent.screen.lower():
            raise RuntimeError("the session does not show the benchmark's permission mode")

    def setup_type(self, text: str) -> float:
        return self.agent.type(text)

    def say(self, pcm, rate):
        raise NotImplementedError(f"{self.name} takes no audio")

    def type(self, text: str, session: str | None = None) -> float:
        at = self.agent.type(text)
        self._events.append(Event(at, "delivered", self.session, text, {"how": "typed"}))
        return at

    def key(self, name: str, session: str | None = None) -> float:
        at = self.agent.key(name)
        self._events.append(Event(at, "action", self.session, name, {"how": "key"}))
        return at

    def events(self) -> list[Event]:
        out, self._events = self._events, []
        return out

    def speech(self):
        return []

    def versions(self) -> dict[str, str]:
        return {"agent_model": agent_mod.MODEL, "claude_code": agent_mod.claude_version()}

    def spend(self) -> list[SpendRow]:
        usd, tokens = self.agent.usage_usd() if self.agent else (0.0, {})
        rows = [SpendRow("anthropic:agent", round(usd, 6), "computed", f"session usage {tokens}")]
        return rows + self._extra_spend

    def idle_since(self, t: float) -> float | None:
        return self.agent.turn_done_at(t) if self.agent else None

    def stop(self) -> None:
        if self.agent:
            self.agent.stop()
        if self.env:
            agent_mod.sweep(self.env.root)
