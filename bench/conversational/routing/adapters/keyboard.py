"""keyboard-canonical: the request as a person would type it, typed into the named session's own pty. The reference
for how often the agent itself fails the one-line edit; it has no routing to do."""

from ..core.adapter import AgentArm


class KeyboardArm(AgentArm):
    name = "keyboard-canonical"
    kind = "typed"
    capabilities = frozenset({"text_in", "sessions"})
    wait_after_say = 30.0

    async def typed(self, text: str, sessions: list[str]) -> None:
        for name in sessions:
            self.type_into(name, text)
