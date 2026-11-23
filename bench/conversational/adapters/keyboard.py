"""keyboard-canonical and keyboard-transcript: text typed into the same pty, approve, deny and Escape as keypresses at
the same triggers. Canonical is the instruction as a person would type it (the reference ceiling); transcript is the
exact words the speech was rendered from (perfect ears)."""

from adapters.base import Base
from core.adapter import CAPABILITIES


class Keyboard(Base):
    kind = "typed"
    capabilities = frozenset({"text_in", "approvals", "sessions", "interrupt"})

    def __init__(self, variant: str = "canonical"):
        super().__init__()
        self.variant = variant
        self.name = f"keyboard-{variant}"
