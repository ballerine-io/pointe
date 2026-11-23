"""Reply limits that fit the question. QA round 2: "What's the difference between a mutex and a semaphore?" was cut at 30
words and lost the semaphore (3 of 3); appositive commas ("Israel Standard Time, UTC+2, ...") and "on Monday, March 3,
at noon" counted as lists, so a 2-fact answer was sent back and came about 8 s late."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import conversation as cv  # noqa: E402

ANSWER = ("A mutex lets one thread at a time hold a lock and only its owner can release it. A semaphore keeps a count, so up "
          "to that many threads may enter at once, and any thread may signal it.")


@pytest.mark.parametrize("asked", ["What's the difference between a mutex and a semaphore?", "Mutex vs semaphore?",
                                   "How does a mutex compare to a semaphore?", "מה ההבדל בין mutex ל-semaphore?"])
def test_a_comparison_keeps_both_halves(asked):
    limit = cv.limit_for(asked, asked)
    assert limit == cv.COMPARE
    assert cv.length_problem(ANSWER, limit) is None and cv.trim(ANSWER, limit) == ANSWER


def test_a_plain_question_keeps_the_short_limit():
    assert cv.limit_for("What is a mutex?", "What is a mutex?") == cv.REPLY


@pytest.mark.parametrize("said", ["Tel Aviv is in Israel Standard Time, UTC+2, and Israel Daylight Time, UTC+3, in summer.",
                                  "The meeting is on Monday, March 3, at noon, in room 4."])
def test_phrases_set_off_by_commas_are_not_a_list(said):
    assert cv.list_items(said) <= 3 and cv.retry_problem(said, cv.REPLY) is None


def test_a_real_list_is_still_a_list():
    assert cv.list_items("Billing, docs, shop and admin are waiting.") == 4
