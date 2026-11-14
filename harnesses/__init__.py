"""Coding-agent harnesses the voice can drive. Each one implements the five things Pointe needs from a session:
join, watch, send, approvals, and side questions. See docs/harnesses.md."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from .base import FINISHED_MARK, HOST, Harness, UnknownHarness, finished_tag

if TYPE_CHECKING:
    from sessions import Session

_HARNESSES: dict[str, Harness] = {}


def register(harness: Harness) -> Harness:
    _HARNESSES[harness.name] = harness
    return harness


def get(name: str | None) -> Harness:
    """The harness a session runs in. One this daemon does not know is not driven as Claude Code: it gets a stand-in
    that reports nothing and drops the session (a newer client, or a typo, must not be typed into the wrong agent)."""
    if not _HARNESSES:
        _load()
    name = name or "claude-code"
    return _HARNESSES.get(name) or UnknownHarness(name)


# Set by the hub's node link (harnesses/remote.py): wraps the inner adapter of a session on another machine.
_REMOTE: Callable[[Session, Harness], Harness] | None = None


def set_remote(wrap: Callable[[Session, Harness], Harness] | None) -> None:
    global _REMOTE
    _REMOTE = wrap


def of(session: Session) -> Harness:
    """The adapter that drives this session. Every per-session adapter call goes through here, never get(): a session
    on another machine (`machine` set) is driven over the node link, with its harness's adapter inside, or, with no
    link wired, by a stand-in that drives nothing, so it is never typed into this machine's agent."""
    inner = get(session.harness)
    if not session.machine:
        return inner
    return _REMOTE(session, inner) if _REMOTE else UnknownHarness(inner.name)


def labels() -> list[str]:
    """How each known harness names its agent in the feed ("claude-code", "opencode")."""
    if not _HARNESSES:
        _load()
    return [h.label for h in _HARNESSES.values()]


def names() -> list[str]:
    if not _HARNESSES:
        _load()
    return list(_HARNESSES)


def _load() -> None:
    from .claude_code import ClaudeCode
    from .codex import Codex
    from .opencode import OpenCode

    register(ClaudeCode())
    register(OpenCode())
    register(Codex())


__all__ = ["FINISHED_MARK", "HOST", "Harness", "finished_tag", "get", "labels", "names", "of", "register", "set_remote"]
