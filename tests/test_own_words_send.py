"""A send that is the user's own words, word for word, needs no model to say it was asked for.

From the conversation suite: every send waited about 0.9 s for the relevance check (a fast model asked whether the
instruction carries the user's latest words), also when the instruction was those words: "How many tests failed in
billing?" sent as "How many tests failed in billing?". When the instruction is a run of the user's latest words as
they said them (beside "tell billing to"), it is asked for by construction; anything else (a word added, a negation
dropped, a hold in force, an unfinished sentence, a repeat) still goes to the model.

uv run pytest -q tests/test_own_words_send.py
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import add, d  # noqa: E402,F401  (d is the daemon fixture)


@pytest.fixture
def checker(d, monkeypatch):  # noqa: F811
    asked = []

    async def text(choice, prompt, max_tokens=16):
        asked.append(prompt)
        return "no"

    monkeypatch.setattr(d.vendors, "text", text)
    add(d, "b", "billing")
    return asked


@pytest.mark.parametrize("message,utterance", [
    ("How many tests failed in billing?", "How many tests failed in billing?"),
    ("Add a docstring to refund.", "Tell billing to add a docstring to refund."),
    ("add a docstring to refund", "Ask billing to add a docstring to refund, please."),
    # The fast ask drops where the question goes: "in billing" names the session, it is not part of the question.
    ("How many tests failed?", "How many tests failed in billing?"),
    ("What's the reviewer?", "What's the reviewer on billing, please?"),
])
def test_the_users_own_words_go_without_the_model(d, checker, message, utterance):  # noqa: F811
    assert asyncio.run(d._is_current_request(message, utterance, [])) is True
    assert checker == []


@pytest.mark.parametrize("message,utterance,earlier,talk", [
    ("Delete the database.", "Don't delete the database.", [], []),
    ("Add a docstring to refund and run the tests.", "Tell billing to add a docstring to refund.", [], []),
    ("Add a docstring to refund.", "Tell billing to add a docstring to refund.", ["Add a docstring to refund."], []),
    ("Deploy it.", "Deploy it.", [], [("user", "Hold off on deploying until I say so.")]),
    ("Tell billing to", "Tell billing to", [], []),
    ("How many tests failed?", "How many tests failed in production?", [], []),
])
def test_anything_else_still_asks_the_model(d, checker, message, utterance, earlier, talk):  # noqa: F811
    asyncio.run(d._is_current_request(message, utterance, earlier, talk))
    assert len(checker) == 1


def test_a_slow_check_is_hedged_with_the_second_checker(d, monkeypatch):  # noqa: F811
    """The second checker used to start only after the first's whole timeout (5 s): now beside it, after a moment."""
    import time

    calls = []

    async def text(choice, prompt, max_tokens=16):
        calls.append(choice)
        if len(calls) == 1:
            await asyncio.sleep(5)
        return "yes"

    monkeypatch.setattr(d.vendors, "text", text)
    monkeypatch.setattr(d, "CHECK_HEDGE_SECS", 0.1)
    add(d, "b", "billing")
    t0 = time.time()
    assert asyncio.run(d._is_current_request("Run the whole suite.", "run the tests", [])) is True
    assert time.time() - t0 < 1.0 and len(calls) == 2


def test_the_users_words_with_one_word_from_the_conversation_put_back_go_without_the_model(d, checker):  # noqa: F811
    """t3-02 in tester round 4 (2 of 2): "Going back to the import, who reviews that change?" was sent as "Going back to
    the nightly import: who reviews that change?" and the check said no, twice; the user heard "I didn't send your import
    question". One word put back from a phrase already said ("the nightly import took 47 minutes") is still their words."""
    talk = [("user", "How long did the nightly import take in lantern?"),
            ("assistant", "The nightly import took 47 minutes.")]
    message, said = "Going back to the nightly import: who reviews that change?", "Going back to the import, who reviews that change?"
    assert asyncio.run(d._is_current_request(message, said, [], talk)) is True
    assert checker == []


@pytest.mark.parametrize("message", ["Going back to the import: who deletes that change?",
                                     "Going back to the import: who reviews that big change?",
                                     "Going back to the import: who never reviews that change?"])
def test_a_word_put_in_that_nobody_said_there_still_asks_the_model(d, checker, message):  # noqa: F811
    talk = [("assistant", "The nightly import took 47 minutes. The old change is merged. Nobody deletes reviews.")]
    asyncio.run(d._is_current_request(message, "Going back to the import, who reviews that change?", [], talk))
    assert len(checker) == 1
