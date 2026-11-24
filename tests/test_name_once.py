"""A line that starts with the session's name right after a line that ended on it drops the repeat.

From the conversation suite: "Sent to atlas." and then "Atlas. Nothing converted: the hero image isn't in the repo."
The report starts with its session's name so the user knows whose it is; when the line just before named it, that is
said twice in a row.

uv run pytest -q tests/test_name_once.py
"""

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import add, d  # noqa: E402,F401  (d is the daemon fixture)


def _say(d, text):  # noqa: F811
    pushed = []

    async def push(frame, direction=None):
        pushed.append(getattr(frame, "text", None))

    asyncio.run(d.BrainFront._speak(SimpleNamespace(push_frame=push), text))
    return pushed[-1]


def test_the_name_said_just_before_is_not_said_again(d):  # noqa: F811
    add(d, "a", "skyway/main")
    add(d, "b", "ledgerline/main")
    assert _say(d, "Sent to skyway.") == "Sent to skyway."
    assert _say(d, "skyway/main. Nothing converted: the hero image isn't in the repo.") == \
        "Nothing converted: the hero image isn't in the repo."


def test_another_sessions_name_or_a_later_line_keeps_it(d):  # noqa: F811
    add(d, "a", "skyway/main")
    add(d, "b", "ledgerline/main")
    _say(d, "Sent to skyway.")
    assert _say(d, "Ledgerline. All checks pass.") == "Ledgerline. All checks pass."
    d.state.bot_spoke.append((time.time() - 60, "Sent to skyway."))
    assert _say(d, "Skyway. Done.") == "Skyway. Done."


def test_a_hyphenated_name_said_either_way_is_one_name(d):  # noqa: F811
    """From the suite: "Sent to orchid-web." then "orchid web. Version bumped": the same name, written two ways."""
    add(d, "w", "orchid-web/main")
    add(d, "a", "orchid-api/main")
    _say(d, "Sent to orchid-web.")
    assert _say(d, "orchid-web/main. Version bumped to 0.9.1.") == "Version bumped to 0.9.1."
