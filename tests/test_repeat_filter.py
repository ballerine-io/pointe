"""Feature interactions: the repeat filter after the fix ("an answer to a status question is not cut").

The exemption keys on the user's LAST words, not on the turn that answers them. Feed-driven turns (bracketed session
news, nudges, warnings) never replace `asked`, so once the user has asked a status question every later daemon-driven
turn is exempt from the repeat filter until the user speaks again. The filter's own reason to exist ("warned three
times that an answer had not arrived") is exactly that kind of turn. Single-machine regression."""

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from brain import without_recent_repeats  # noqa: E402
from test_orchestrator import _brain, _say, _scripted  # noqa: E402

WARNING = "Alpha's answer has not arrived yet."


def test_a_repeated_warning_is_still_cut_when_the_users_last_words_were_a_status_question():
    """The warning was said a moment ago; the status question did not ask about alpha's answer. Before that fix the
    first sentence was cut (no overlap with the asked words); now the whole thing is exempt."""
    said = f"{WARNING} Nothing else changed."
    assert without_recent_repeats(said, [WARNING], "what's going on everywhere?") == "Nothing else changed."


@pytest.mark.parametrize("asked", ["turn on meeting mode", "focus on me", "what is left to do on the auth bug"])
def test_status_intent_substrings_switch_the_repeat_filter_off_for_unrelated_words(asked):
    """guards.status_intent matches substrings ("on me" is in "turn on meeting mode"); every such utterance now also
    disables the repeat filter for the turns that follow."""
    said = f"{WARNING} Nothing else changed."
    assert without_recent_repeats(said, [WARNING], asked) == "Nothing else changed."


def test_feed_driven_turns_after_a_status_question_are_still_deduplicated(monkeypatch):
    """Brain-level: the user asks a status question, gets the answer, then alpha's news arrives twice in bracketed
    feeds. The second report repeats the first sentence; it must be cut as before (the user's words have not changed,
    and they did not ask about alpha's answer)."""
    b, spoken = _brain([])
    b.may_stay_silent = lambda: False
    _scripted(monkeypatch, [_say("On devbox, shop is idle. Alpha is working."),
                            _say(WARNING),
                            _say(f"{WARNING} It is still on the retry loop.")])
    asyncio.run(b.turn("what's going on everywhere?"))
    asyncio.run(b.turn("[alpha has not reported in 2 minutes]"))
    asyncio.run(b.turn("[alpha has not reported in 4 minutes]"))
    assert spoken[-1] == "It is still on the retry loop.", spoken
