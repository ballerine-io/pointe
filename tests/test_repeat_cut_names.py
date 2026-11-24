"""A sentence is not cut as a repeat for sharing the session's name, or when it carries a number not said before.

From the conversation suite: "orchid-api says the version in the notes file is 2.4.1." was cut as a repeat of the
greeting ("orchid-api is connected and idle, and it says it's ready on the file you asked it to read"): five of its
seven content words were the session's name, "says" and "file". The user heard "That's what the notes say" without the
version they asked for.

uv run pytest -q tests/test_repeat_cut_names.py
"""

import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import brain  # noqa: E402

GREETING = "orchid-api/main is connected and idle, and it says it's ready on the file you asked it to read."


def test_a_new_number_is_never_a_repeat():
    said = "orchid-api/main says the version in the notes file is 2.4.1. That's what the notes say."
    assert brain.without_recent_repeats(said, [GREETING], "the API") == said


def test_the_sessions_name_does_not_make_a_repeat():
    said = "orchid-api/main says the release notes file is ready."
    kept = brain.without_recent_repeats(said, [GREETING], "", names={"orchid", "api", "main"})
    assert kept == said


def test_a_real_repeat_is_still_cut():
    said = "orchid-api/main is connected and idle and ready. Ask away."
    assert brain.without_recent_repeats(said, [GREETING], "", names={"orchid", "api", "main"}) == "Ask away."
