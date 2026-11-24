""""There's more if you want it" is said once in a while, not after every cut reply.

From the first tester round: the line ended five replies in one call, and the judge called it padding: the user learns
in one hearing that a short answer has more behind it. After it is said, cut replies end without it for MORE_ONCE_SECS.

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


def test_the_offer_is_said_once_then_left_out():
    b = _brain()
    first = b.offer_more(f"The fix is in. {cv.MORE_EN}", now=100.0)
    second = b.offer_more(f"Checks pass. {cv.MORE_EN}", now=160.0)
    third = b.offer_more(f"Lint is red. {cv.MORE_EN}", now=100.0 + b.MORE_ONCE_SECS + 1)
    assert first.endswith(cv.MORE_EN) and second == "Checks pass." and third.endswith(cv.MORE_EN)


def test_hebrew_too():
    b = _brain()
    b.offer_more(f"התיקון נכנס. {cv.MORE_HE}", now=100.0)
    assert b.offer_more(f"הבדיקות עוברות. {cv.MORE_HE}", now=110.0) == "הבדיקות עוברות."
