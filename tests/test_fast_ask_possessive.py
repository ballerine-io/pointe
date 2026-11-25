""""What's the plan for lantern's slow import?" goes to lantern as said, as "... in lantern?" does.

net-01 in r8 and r9 (2 of 2): the question went through the model, which relayed it as "The owner asks: what's the plan
for the lantern slow import? Please tell them the goal, current state…"; the session led with the goal, and the plan
itself was cut from what was said. Asked as the user asked it, the answer is the plan.

uv run pytest -q tests/test_fast_ask_possessive.py
"""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import add, d  # noqa: E402,F401  (d is the daemon fixture)


@pytest.mark.parametrize("said,message", [
    ("What's the plan for lantern's slow import?", "What's the plan for the slow import?"),
    ("Who is lantern's reviewer?", "Who is the reviewer?"),
    ("How long did lantern's nightly import take?", "How long did the nightly import take?"),
])
def test_a_question_about_a_sessions_thing_goes_to_it_as_said(d, said, message):  # noqa: F811
    s = add(d, "l", "lantern")
    add(d, "b", "billing")
    assert d._fast_send(said) == (s, message)


@pytest.mark.parametrize("said", ["What's lantern's status?", "What do you think of lantern's plan?",
                                  "What's the plan for the slow import?", "Is it lantern's or billing's job?",
                                  "What's the plan for granary's import?"])
def test_a_status_question_an_opinion_or_no_session_named_is_the_models(d, said):  # noqa: F811
    add(d, "l", "lantern")
    add(d, "b", "billing")
    assert d._fast_send(said) is None


@pytest.mark.parametrize("said,message", [
    # orc-03, 3 of 11 runs: relayed as "... Please answer with the goal, current state and next step", the session led
    # with the goal and the two-sentence cut dropped the plan.
    ("Meanwhile, what's the plan for speeding up lantern?", "What's the plan for speeding up lantern?"),
    ("What's the plan for speeding up lantern?", "What's the plan for speeding up lantern?"),
    ("So, what's wrong with lantern?", "What's wrong with lantern?"),
    ("Meanwhile, how many tests failed in lantern?", "How many tests failed?"),
])
def test_a_question_that_ends_on_a_sessions_name_goes_to_it_as_said(d, said, message):  # noqa: F811
    s = add(d, "l", "lantern")
    add(d, "b", "billing")
    assert d._fast_send(said) == (s, message)


@pytest.mark.parametrize("said", ["Meanwhile, what's going on with lantern?", "What do you know about lantern?",
                                  "What's the plan for moving billing into lantern?", "Meanwhile, how is it going?",
                                  "What's the plan for speeding up granary?", "What's the latest update on the state of lantern?"])
def test_a_status_question_an_opinion_or_two_sessions_at_the_end_are_the_models(d, said):  # noqa: F811
    add(d, "l", "lantern")
    add(d, "b", "billing")
    assert d._fast_send(said) is None
