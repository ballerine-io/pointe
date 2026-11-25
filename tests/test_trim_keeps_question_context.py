"""A closing question cut away from the sentence it depends on is not said alone.

Tester round 4's first sample (acc-01, rec-02): "Billing edited the refunds code and its test file, twice in the tests.
Should it?" The reply was cut from 30 words to 15: the closing question was kept, the sentence that said what "it"
should do was dropped. A short question that leans on the sentence before it goes with that sentence or not at all.

uv run pytest -q tests/test_trim_keeps_question_context.py
"""

import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import conversation as cv  # noqa: E402


def test_a_short_question_whose_sentence_was_cut_is_not_said_alone():
    said = ("Billing renamed calc total to compute invoice total and updated the test. It now wants to run a grep and "
            "the refund tests to check nothing else uses the old name. Should it?")
    out = cv.trim(said, cv.REPLY)
    assert not out.rstrip().endswith("Should it?")
    assert out.startswith("Billing renamed calc total")


def test_a_question_that_stands_on_its_own_is_still_kept():
    said = ("Billing renamed calc total to compute invoice total and updated the test. It edited two files and ran "
            "nothing yet. Do you want billing to run the refund tests now?")
    assert cv.trim(said, cv.REPLY).endswith("Do you want billing to run the refund tests now?")



def test_a_short_offer_that_names_its_object_is_kept():
    said = ("A queue lets work wait until a worker is free. It smooths bursts and survives a crash of the worker. It also "
            "decouples the two services. Want an example?")
    assert cv.trim(said, cv.REPLY).endswith("Want an example?")
