"""A one- or two-word sentence is taken at once only when it can be an answer (or a stop), not always.

From the first tester round (adv-07, adv-09): "Okay." opened a longer sentence, was taken at once as a whole turn, and
the rest ("In English now. What's the next step on billing?") arrived as separate turns that the voice answered over.
Zero settle exists for a yes or a no to a waiting question, approval or read-back, and for "stop"; with nothing
waiting, a short sentence settles like any other.

uv run pytest -q tests/test_short_answer_settle.py
"""

import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import turns  # noqa: E402


def test_a_short_sentence_with_nothing_waiting_settles_as_ever():
    assert turns.settle("Okay.", False, "normal", answering=False) == turns.LEVELS["normal"].complete


def test_a_short_answer_to_a_waiting_question_goes_at_once():
    assert turns.settle("Yes.", False, "normal", answering=True) == 0.0


def test_stop_goes_at_once_whatever_waits():
    assert turns.settle("Stop.", False, "normal", answering=False) == 0.0
    assert turns.settle("Wait.", False, "normal", answering=False) == 0.0
