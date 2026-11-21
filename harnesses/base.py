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
#   port: the port the daemon listens on (a session it starts registers there)
HOST = SimpleNamespace(hold_permission=None, post_channel=None, state_dir=None, port=None)

# The bracketed line that tells the voice a session ended its turn. Producers write it with finished_tag(); the daemon
# reads it with FINISHED_MARK. One place, so a new label cannot silently stop reports.
FINISHED_MARK = "finished its turn]"


def finished_tag(label: str) -> str:
    return f"[{label} {FINISHED_MARK}"


class StartError(Exception):
    """A new session could not be started. Its text is fixed words for the user: said, and shown on the screens."""


_BYPASS = ("dangerously", "skip-permissions", "bypasspermissions", "danger-full-access", "dangerfullaccess")


def refuse_bypass(*parts) -> None:
    """Every command line and request a starter builds passes through here: nothing Pointe starts may skip its
    harness's permission prompts, whoever wrote the starter."""
    for part in parts:
        text = str(part).lower()
        if any(word in text for word in _BYPASS):
            raise StartError("Not started: Pointe never starts a session that skips its permission prompts.")


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
    starts = False  # Pointe can start a new session of it in a folder (docs/design/new-session.md)
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

    def can_start(self) -> str | None:
        """Why a new session of this harness cannot be started on this machine now (not installed), or None. Cheap: it
        runs for every look at the New session sheet."""
        return f"Pointe cannot start {self.agent} sessions"

    async def start(self, cwd: str, name: str, start_id: str) -> dict | None:
        """Start a new session in `cwd`, in the harness's default permission mode, never one that skips its prompts.
        Returns its /voice/register body, or None when the session registers itself (carrying `start_id`). Raises
        StartError with words for the user."""
        raise StartError(self.can_start() or "not supported")

    def open_hint(self, session: Session) -> str:
        """How the user opens a session Pointe started in their own terminal, or "" when it already is one."""
        return ""


class UnknownHarness(Harness):
    """A session registered by a harness this daemon does not know (a newer client). Listed, never driven."""

    attach = False

    def __init__(self, name: str) -> None:
        self.name, self.label = name, name

    def alive(self, session: Session) -> bool:
        return False  # dropped at the next check rather than kept as a session nothing can reach


Hold = Callable[["Session", str, dict, Callable[[], Awaitable[bool]] | None], Awaitable[str | None]]
