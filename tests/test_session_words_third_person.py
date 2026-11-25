"""A session's words said as they came are said about the session, and to the user.

Tester round 5: "the session's first person is read aloud as if it were the voice: 'I haven't deleted anything', 'I
bumped the version'", and "the user is called 'he' or 'the owner': 'Say if he wanted minor or major'". Said as they came
(no model step, for speed), the session's "I" becomes its name at the start of a sentence and "it" inside one, and "the
owner" or "the user" becomes "you".

uv run pytest -q tests/test_session_words_third_person.py
"""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import d  # noqa: E402,F401  (d is the daemon fixture)


@pytest.mark.parametrize("line,said", [
    ("I added a docstring to dedupe rows in load. I did not change any logic and I did not run tests.",
     "Lantern added a docstring to dedupe rows in load. Lantern did not change any logic and it did not run tests."),
    ("I haven't rerun the tests, so that count may be out of date.",
     "Lantern hasn't rerun the tests, so that count may be out of date."),
    ("I'm not sure which file you mean.", "Lantern is not sure which file you mean."),
    ("I bumped the version to 0.9.1. Say so if the owner wanted minor or major.",
     "Lantern bumped the version to 0.9.1. Say so if you wanted minor or major."),
    ("I recommend an index on customer id, and I need your go-ahead.",
     "Lantern recommends an index on customer id, and it needs your go-ahead."),
    ("I've kept my notes as they were.", "Lantern has kept its notes as they were."),
    ("Three tests failed, all in refunds.", "Three tests failed, all in refunds."),
    ("The user wants the docstring short.", "You want the docstring short."),
    ("Items in the queue: 4. It's idle.", "Items in the queue: 4. It's idle."),
])
def test_a_sessions_words_are_said_about_it(d, line, said):  # noqa: F811
    assert d._about_the_session(line, "lantern") == said


def test_hebrew_is_left_as_it_came(d):  # noqa: F811
    assert d._about_the_session("הוספתי docstring.", "lantern") == "הוספתי docstring."
