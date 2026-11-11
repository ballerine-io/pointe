"""Coding-agent harnesses the voice can drive. Each one implements the five things Pointe needs from a session:
join, watch, send, approvals, and side questions. See docs/harnesses.md."""

from .base import FINISHED_MARK, HOST, Harness, UnknownHarness, finished_tag

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


__all__ = ["FINISHED_MARK", "HOST", "Harness", "finished_tag", "get", "labels", "names", "register"]
