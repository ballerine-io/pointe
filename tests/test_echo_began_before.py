"""Words the user began saying before the bot's voice began are not its echo.

Tester round 4's own full run, amb-02: "What version is the toll on?" got "Toll API or toll web?", and the user's "The
API.", begun about a second and a half before that question was heard, was dropped as its echo ("echo dropped: 'The
API.'"): "api" was in the bot's line and "the" was one stray word. The answer never came. An echo cannot start before the
sound it echoes.

uv run pytest -q tests/test_echo_began_before.py
"""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import echo  # noqa: E402
from echo import EchoGuard  # noqa: E402


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(echo.time, "time", lambda: now[0])
    return now


def _asking(clock) -> EchoGuard:
    g = EchoGuard()
    g.bot_said("Toll API or toll web?")
    clock[0] = 100.0
    g.bot_started()
    clock[0] = 100.8
    g.mirror_heard(" Toll API or", "")
    return g


def test_an_answer_begun_before_the_question_was_heard_is_the_users(clock):
    g = _asking(clock)
    assert g.user_part("The API.", spoken=(98.6, 99.7)) == "The API."


def test_the_same_words_begun_while_the_question_played_are_still_echo(clock):
    g = _asking(clock)
    assert g.user_part("The API.", spoken=(100.3, 100.9)) == ""
