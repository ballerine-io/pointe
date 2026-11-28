"""Once the voice has said it does not know where a request goes, nothing is sent until the user names or confirms one.

From W4's fleet dialogue (8 sessions, 2026-11-28): "Tell the session working on the ticket migration to add a docstring
to the main function." The voice said "None of my sessions is clearly about a ticket migration. Is that the one, or a
different session?", then, in a turn of queued updates the user never spoke in, sent the request to orchid ("orchid is
the ticket migration session, so I sent the docstring request there"). Every check passed: the user had spoken since
the last send, and the message matched their words. Asking where a request goes now holds it for the user's answer.

uv run --locked --group test-tools pytest -q tests/test_ask_where_then_wait.py
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_orchestrator import add, d, open_gates, record_dispatch  # noqa: E402,F401  (d is a fixture)

ASKED = "Tell the session working on the lantern import to add a docstring to the main function."
MESSAGE = "Add a docstring to the main function."


@pytest.fixture
def fleet(d):  # noqa: F811
    for i, name in enumerate(("heron", "pelican-web", "fennel", "orchard")):
        add(d, f"s{i}", name)
    return d


def test_after_the_voice_asked_where_a_later_turn_does_not_send_it(fleet, monkeypatch):
    d = fleet
    sent = record_dispatch(d, monkeypatch)
    open_gates(d, monkeypatch, ASKED)
    d._bot_says("None of my sessions is clearly about a lantern import. Is that the one, or a different session?")
    d.state.brain_target = "orchard"  # a queued update's turn, with no words from the user, names a session
    result = asyncio.run(d._send_now(MESSAGE))
    assert sent == [] and "error" in result and "asked" in result["error"]


def test_the_users_answer_naming_a_session_sends_it(fleet, monkeypatch):
    d = fleet
    sent = record_dispatch(d, monkeypatch)
    open_gates(d, monkeypatch, ASKED)
    d._bot_says("Which one is it for: heron or orchard?")
    open_gates(d, monkeypatch, "Orchard.")
    d.state.brain_target = "orchard"
    asyncio.run(d._send_now(MESSAGE))
    assert [n for n, _ in sent] == ["orchard"]


def test_the_codes_own_which_session_refusal_holds_the_request_too(fleet, monkeypatch):
    d = fleet
    sent = record_dispatch(d, monkeypatch)
    open_gates(d, monkeypatch, "Tell it to add a docstring to the main function.")
    d.state.brain_target = None
    first = asyncio.run(d._send_now(MESSAGE))  # no session named, none active: the code asks which
    assert sent == [] and "error" in first
    d.state.brain_target = "orchard"  # the model guesses one in the same turn
    asyncio.run(d._send_now(MESSAGE))
    assert sent == []


@pytest.mark.parametrize("line", ["Sent to orchard.", "Orchard added the docstring. Want me to run the tests?",
                                  "Which file should it change?"])
def test_a_line_that_does_not_ask_where_holds_nothing(fleet, monkeypatch, line):
    d = fleet
    assert not d._asks_where(line)


@pytest.mark.parametrize("line", ["None of my sessions is clearly about a lantern import. Is that the one, or a different session?",
                                  "Which one: heron or orchard?", "Which session is it for?", "heron or orchard?",
                                  "I'm not sure which session that's for. Which one do you mean?"])
def test_a_line_that_asks_where_is_seen(fleet, line):
    assert fleet._asks_where(line)

