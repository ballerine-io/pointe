""""There's more if you want it" is not said: a cut reply ends where it was cut.

From the first tester round: the line ended five replies in one call, and the judge called it padding; it was then said
once an hour. The third tester still named it padding, and round 4's first sample heard it in 8 of 45 dialogues (each
call is a new daemon), once followed by the rest said unasked (orc-03). "Tell me more" works without the offer.

uv run pytest -q tests/test_more_once.py
"""

import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import conversation as cv  # noqa: E402
from brain import Brain  # noqa: E402


def _brain():
    async def speak(text):
        pass
    return Brain("gemini:x", "system", [], lambda: "[right now]", speak)


def test_the_offer_is_never_said():
    b = _brain()
    assert b.offer_more(f"The fix is in. {cv.MORE_EN}", now=100.0) == "The fix is in."
    assert b.offer_more(f"Checks pass. {cv.MORE_EN}", now=100.0 + 7200) == "Checks pass."


def test_hebrew_too():
    b = _brain()
    assert b.offer_more(f"התיקון נכנס. {cv.MORE_HE}", now=100.0) == "התיקון נכנס."
