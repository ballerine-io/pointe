"""The typed reference on the same pty (design 4.3): text plus scripted keypresses. Used by two arms:
`keyboard-canonical` (the instruction as a person types it) and `keyboard-transcript` (the exact words the speech was
rendered from: perfect ears). No speech output: the final answer is read as text from the transcript."""

from adapters.base import AgentAdapter


class Keyboard(AgentAdapter):
    name = "keyboard"
    capabilities = frozenset({"text_in", "approvals", "sessions", "interrupt"})
