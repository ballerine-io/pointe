""""Tell granary to—" with a pause is unfinished, also when the recognizer writes "Tell granary too."

From the conversation suite: a 1.6 s pause after "Tell granary to" was heard as "Tell granary too.", a whole sentence, so
the turn was taken after the normal settle and the voice asked "Tell granary what exactly?" over the rest of the
sentence. "to" heard as "too" or "two" right after "tell/ask <name>" is the same dangling "to".

uv run pytest -q tests/test_tell_to_pause.py
"""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

from guards import unfinished  # noqa: E402


@pytest.mark.parametrize("said", ["Tell granary too.", "Ask billing two", "tell the web one too", "Tell granary to."])
def test_tell_x_to_is_unfinished(said):
    assert unfinished(said)


@pytest.mark.parametrize("said", ["Tell granary about it too.", "Ask billing, too.", "I want that too."])
def test_a_real_too_is_not(said):
    assert not unfinished(said)
