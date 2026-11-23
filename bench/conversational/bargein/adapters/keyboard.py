"""The typed reference on the same pty, launch line and permission mode: text plus scripted keypresses at the same
triggers as the spoken arms. Its answers are read as text from the terminal."""

from adapters.base import PtyArm


class Keyboard(PtyArm):
    name = "keyboard"
    capabilities = frozenset({"text_in", "approvals", "sessions", "interrupt"})
