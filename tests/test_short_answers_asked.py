"""A short question relayed to a session asks for a short answer: it will be read aloud.

From the conversation suite: "How long did the nightly import take?" came back as three sentences with caveats ("that
comes from the notes file, not a fresh run"), longer than a spoken answer needs, and too long to be said as it came.
A short question now tells the session the answer is read aloud and should be one or two short sentences; a request
for work, or a question that asks for detail, is relayed as before.

uv run pytest -q tests/test_short_answers_asked.py
"""

import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

from sessions import voice_message  # noqa: E402


def test_a_short_question_asks_for_a_short_answer():
    out = voice_message("How long did the nightly import take?")
    assert "read aloud" in out and out.endswith("] How long did the nightly import take?")


def test_work_and_detail_are_relayed_as_before():
    assert "read aloud" not in voice_message("Add a docstring to refund.")
    assert "read aloud" not in voice_message("Explain in detail why the refund tests fail?")


def test_the_short_answer_asked_for_is_said_as_a_person_says_it():
    """Tester round 4's first sample: answers said as they came were "According to NOTES, the last test run had 3
    failures… I haven't rerun the tests, so that count may be out of date." and "Tuesday. NOTES records it: 'Last deploy:
    Tuesday.'" The session is asked for the answer alone: not where it read it, and a caveat only when it changes the
    answer."""
    out = voice_message("How many tests failed?")
    assert "the answer first" in out and "not where you read it" in out and "a caveat only if it changes the answer" in out
