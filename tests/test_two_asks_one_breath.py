"""An instruction and a question in one breath, joined by "and also", are two deliveries.

adv-03 in tester round 4 (2 of 2): "Tell atlas to add an alt text to the hero image, and also, how many tests failed in
billing?" sent atlas its task; the question to billing was refused as "the user has not asked for anything new", and the
user heard "I asked atlas to add the alt text. Want me to send it?".

uv run pytest -q tests/test_two_asks_one_breath.py
"""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import add, d  # noqa: E402,F401  (d is the daemon fixture)


@pytest.mark.parametrize("said", ["Tell harbor to add an alt text to the hero image, and also, how many tests failed in ledger?",
                                  "Tell harbor to add the alt text and also what's the reviewer on ledger?",
                                  "Ask harbor to rerun lint. Also, did ledger finish?",
                                  # as the recognizer wrote it in adv-03: no question mark
                                  "Tell Harbor to add an alt text to the hero image, and also how many tests failed in ledger."])
def test_a_task_and_a_question_in_one_breath_ask_for_two(d, said):  # noqa: F811
    add(d, "a", "harbor"), add(d, "b", "ledger")
    assert d._asked_of_several(said)


@pytest.mark.parametrize("said", ["Tell harbor to add an alt text to the hero image.", "Also, add the alt text.",
                                  "Tell harbor to also fix the logo."])
def test_one_request_is_still_one(d, said):  # noqa: F811
    add(d, "a", "harbor"), add(d, "b", "ledger")
    assert not d._asked_of_several(said)
