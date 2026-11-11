"""What every harness adapter provides, and what the daemon lends them."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Coroutine

if TYPE_CHECKING:
    from sessions import Feed, Session

# Set by the daemon at start, so adapters can use its flows without importing it:
#   hold_permission(session, tool_name, tool_input, gone, deadline) -> "allow" | "deny" | None (None: the harness's own
#     prompt answers)
#   post_channel(session, path, body) -> bool
#   state_dir: Path
HOST = SimpleNamespace(hold_permission=None, post_channel=None, state_dir=None)

# The bracketed line that tells the voice a session ended its turn. Producers write it with finished_tag(); the daemon
# reads it with FINISHED_MARK. One place, so a new label cannot silently stop reports.
FINISHED_MARK = "finished its turn]"


def finished_tag(label: str) -> str:
    return f"[{label} {FINISHED_MARK}"


class Harness:
    """One coding-agent harness. Subclasses override what they support; the defaults are safe no-ops."""

    name = "base"
    label = "agent"  # how the screens and the feed refer to it ("claude-code", "opencode"): short, no spaces
    agent = "the agent"  # what the voice calls the agent working in a session ("Claude" for Claude Code)

    # What this harness can do. Shown in /voice/status, so the brain and the screens never promise what it cannot.
    approvals = False  # its permission prompts can be answered by voice or a tap
    side_questions = False  # "by the way" questions go to a copy of the session (else the transcript reader answers)
    attach = True  # it joins a session the user already runs in their own terminal or app
    spawn = False  # it can only drive sessions Pointe starts itself
    joins_mid_turn = False  # joining runs inside one of its own turns (Claude Code's /pointe:voice): that turn is not news
    permission_deadline = 280.0  # how long the voice may hold one of its prompts before the harness's own prompt answers

    def capabilities(self) -> dict:
        return {"approvals": self.approvals, "side_questions": self.side_questions, "attach": self.attach,
                "spawn": self.spawn}

    def alive(self, session: Session) -> bool:
        """Still running. Called every few seconds from the event loop: it must not block."""
        return True

    async def probe(self, session: Session) -> None:
        """Refresh what alive() and title() rely on, with no call up (the daemon's liveness loop, every few seconds)."""

    def watch(self, session: Session, feed: Feed) -> list[Coroutine[Any, Any, None]]:
        """Coroutines that follow the session and call feed(session, text, respond) with its activity, the same
        bracketed lines Claude Code's transcript follower produces, so reports, notes and nudges work unchanged."""
        return []

    async def send(self, session: Session, text: str) -> bool:
        """Deliver the user's request into the running session. True when it arrived."""
        return False

    async def side_question(self, session: Session, question: str) -> str | None:
        """Answer a "by the way" question from a copy of the session, or None to use the transcript reader."""
        return None

    def transcript_path(self, session: Session) -> str:
        """Where the session's record is now (Claude Code moves it on /clear and /resume)."""
        return session.transcript

    def title(self, session: Session) -> str | None:
        """The name the harness itself shows for the session, if it has one."""
        return None

    def noise(self, text: str) -> str:
        """The user's own words in a typed turn, without what the harness injected. "" when it was all the harness's."""
        return text.strip()

    def join(self, argv: list[str]) -> dict:
        """The /voice/register body for a session of this harness, from the command line of `pointe join <harness>`."""
        raise SystemExit(f"{self.name}: join from inside the session instead")

    async def leave(self, session: Session) -> None:
        """Called after the session is taken off the voice: undo anything the harness set up for it."""


class UnknownHarness(Harness):
    """A session registered by a harness this daemon does not know (a newer client). Listed, never driven."""

    attach = False

    def __init__(self, name: str) -> None:
        self.name, self.label = name, name

    def alive(self, session: Session) -> bool:
        return False  # dropped at the next check rather than kept as a session nothing can reach


Hold = Callable[["Session", str, dict, Callable[[], Awaitable[bool]] | None], Awaitable[str | None]]
