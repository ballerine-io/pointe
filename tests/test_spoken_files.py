"""A file name in a reply is said as words, in code, instead of sending the whole reply back to the model.

From the conversation suite: 5 of the first 12 dialogues had a reply refused for a file name ("update hero.js",
"per NOTES.md"), each costing a model step while the user waited. The rule stays (no paths or code read aloud); the
fix is said in code: "the hero file", "the NOTES file". Product names that look like files (Node.js) are left alone.

uv run pytest -q tests/test_spoken_files.py
"""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import brain  # noqa: E402


@pytest.mark.parametrize("said,spoken", [
    ("I asked atlas to update hero.js to point at it.", "I asked atlas to update the hero file to point at it."),
    ("Three failed, per NOTES.md.", "Three failed, per the NOTES file."),
    ("All in `tests/test_refunds.py`.", "All in the test refunds file."),
    ("It's in `dedupe_rows`.", "It's in dedupe rows."),
    ("We use Node.js 22 there.", "We use Node.js 22 there."),
    ("Version 2.4.1 is out.", "Version 2.4.1 is out."),
])
def test_file_names_are_said_as_words(said, spoken):
    assert brain.spoken_code(said) == spoken


def test_a_reply_with_a_file_name_is_spoken_without_a_second_step():
    import asyncio
    from types import SimpleNamespace

    spoken, steps = [], []

    async def speak(text):
        spoken.append(text)

    async def step(choice, instructions, messages, decls, heard=None):
        steps.append(1)
        return SimpleNamespace(calls=[{"id": "s1", "name": "speak", "args": {"text": "Atlas will update hero.js next."}}],
                               said="", raw=None, vendor="fake", usage={})

    brain.vendors.step, old = step, brain.vendors.step
    try:
        b = brain.Brain("fake:model", "s", [], lambda: "[right now] atlas hero", speak)
        b.may_stay_silent = lambda: False
        asyncio.run(b.turn("What's next on atlas?"))
    finally:
        brain.vendors.step = old
    assert spoken == ["Atlas will update the hero file next."] and len(steps) == 1


def test_a_session_name_and_the_projects_notes_file_are_left_to_their_own_rules():
    assert brain.spoken_code("I asked atlas/main to do it.") == "I asked atlas/main to do it."
    b = brain.Brain("gemini:x", "s", [], lambda: "[right now]", None)
    b.may_stay_silent = lambda: False
    b.append("How many failed?")
    assert b.speech_problem(brain.spoken_code("Three failed, per NOTES.md."), True) is None
    assert b.speech_problem("In my notes, three failed.", True) is not None


@pytest.mark.parametrize("said,spoken", [
    ("Add an index on customer_id.", "Add an index on customer id."),
    ("The slow step is dedupe_rows, 31 minutes.", "The slow step is dedupe rows, 31 minutes."),
    ("Set MAX_RETRIES to 3.", "Set MAX RETRIES to 3."),
])
def test_a_snake_case_name_is_said_as_words(said, spoken):
    """From the suite: "add an index on customer_id" was read "customer underscore ID"."""
    assert brain.spoken_code(said) == spoken
