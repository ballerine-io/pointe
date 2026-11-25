"""What Pointe says is shaped for the ear: the spoken-form rules that code can hold.

From the third tester's low-scored replies and the blind judge's notes: greetings that end by handing the conversation
back ("What should billing work on first?"), a session called "Billing slash main", and "keeping every caveat" turning a
one-word answer into three sentences.

uv run pytest -q tests/test_spoken_shape.py
"""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from brain import without_closer  # noqa: E402
from test_orchestrator import add, d  # noqa: E402,F401  (d is the daemon fixture)


@pytest.mark.parametrize("said,kept", [
    ("Billing is connected and idle. What should billing work on first?", "Billing is connected and idle."),
    ("Connected to billing and lantern. Neither needs you. What should I send first?", "Connected to billing and lantern. Neither needs you."),
    ("Lantern is connected and idle, and nothing needs you. What would you like it to do?", "Lantern is connected and idle, and nothing needs you."),
    ("All three are idle and none needs you. Which one do you want to start with?", "All three are idle and none needs you."),
    ("Connected. What should they do first?", "Connected."),
])
def test_a_reply_does_not_end_by_handing_the_conversation_back(said, kept):
    assert without_closer(said) == kept


@pytest.mark.parametrize("said", ["Which one, billing or lantern?", "Billing wants to run: pytest. Should it?",
                                  "Your sentence cut off after tell lantern to. What should I tell lantern?",
                                  "Should billing start the rounding fix?"])
def test_a_question_that_needs_an_answer_stays(said):
    assert without_closer(said) == said


def test_a_session_is_called_by_its_plain_name_however_the_model_wrote_it(d):  # noqa: F811
    add(d, "b", "billing/main"), add(d, "s", "search-reindex/dev")
    assert d._spoken_names("Billing/main is connected and idle.") == "billing is connected and idle."
    assert d._spoken_names("billing/main finished; Search-Reindex/dev is working.") == "billing finished; search reindex is working."
    assert d._spoken_names("The billing/mainline branch is old.") == "The billing/mainline branch is old."  # not the session


def test_the_instructions_say_how_to_sound_and_no_longer_ask_for_every_caveat(d):  # noqa: F811
    assert "You are heard, not read." in d.INSTRUCTIONS and "A greeting never ends in a question." in d.INSTRUCTIONS
    assert "contractions" in d.INSTRUCTIONS and "never with a \nslash" not in d.INSTRUCTIONS
