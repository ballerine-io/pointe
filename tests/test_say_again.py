""""Sorry, say that again?" gets the last answer again, not a new one with the repeated part cut.

From the conversation suite: "How big is the hero image?" got "The hero image is 2.3 megabytes"; "Sorry, say that
again?" got "Claude hasn't checked the actual file on disk. Wanted to check?" The repeat filter cut the sentence the
user asked to hear again. Words that ask for a repeat lift it, as a status question does.

uv run pytest -q tests/test_say_again.py
"""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

from guards import repeat_intent  # noqa: E402


@pytest.mark.parametrize("said", ["Sorry, say that again?", "Can you repeat that?", "What did you say?", "Come again?",
                                  "Sorry?", "Pardon?", "תחזור על זה", "מה אמרת?", "שוב?"])
def test_these_ask_for_a_repeat(said):
    assert repeat_intent(said)


@pytest.mark.parametrize("said", ["Tell billing to run it again.", "Say hello to granary.", "What did billing say?"])
def test_these_do_not(said):
    assert not repeat_intent(said)


def test_the_brain_lets_the_repeated_sentence_through(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import brain

    spoken = []

    async def speak(text):
        spoken.append(text)

    replies = ["The hero image is 2.3 megabytes.", "The hero image is 2.3 megabytes."]

    async def step(choice, instructions, messages, decls, heard=None):
        return SimpleNamespace(calls=[{"id": "s", "name": "speak", "args": {"text": replies.pop(0)}}], said="", raw=None,
                               vendor="fake", usage={})

    monkeypatch.setattr(brain.vendors, "step", step)
    b = brain.Brain("fake:model", "s", [], lambda: "[right now] hero image 2.3 megabytes", speak)
    b.may_stay_silent = lambda: False
    b.repeat_asked = repeat_intent
    asyncio.run(b.turn("How big is the hero image?"))
    asyncio.run(b.turn("Sorry, say that again?"))
    assert spoken == ["The hero image is 2.3 megabytes.", "The hero image is 2.3 megabytes."]
