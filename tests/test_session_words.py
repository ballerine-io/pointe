"""A word the session itself used in the answer being relayed is not a backstage word.

From the conversation suite: a session answered "3 tests failed, per NOTES.md", and the voice's "three failed, per the
notes" was refused for naming its own notes, which cost a model step while the user waited and, on that run, the
answer itself: the user had moved on. The rule keeps Pointe's own machinery out of speech; the user's project may have
a notes file, a feed or a transcript of its own.

uv run pytest -q tests/test_session_words.py
"""

import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

from brain import Brain  # noqa: E402

ANSWER = ("[billing: claude-code finished its turn] It answered the question you sent it. Tell the user its answer in "
          "English, in one or two short sentences:\n3 tests failed, per NOTES.md, all in the refund tests.")


def _brain():
    async def speak(text):
        pass

    return Brain("gemini:x", "system", [], lambda: "[right now]", speak)


def test_the_sessions_own_word_may_be_said_when_relaying_its_answer():
    b = _brain()
    b.append(ANSWER)
    b._trigger = ANSWER
    assert b.speech_problem("Three failed, per the notes, all in the refund tests.", True) is None


def test_pointes_own_notes_are_still_not_named():
    b = _brain()
    b.append("How many tests failed?")
    b._trigger = "How many tests failed?"
    assert b.speech_problem("In my notes, three failed.", True) is not None
    b.append(ANSWER)
    b._trigger = ANSWER
    assert b.speech_problem("In my notes, three failed.", True) is not None  # "my notes" is never the session's
