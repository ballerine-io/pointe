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


@pytest.mark.parametrize("said,asks", [("What did hermes say?", True), ("what did the shop session answer", True),
                                       ("What did openclaw find?", True), ("מה הרמס אמר?", True),
                                       ("What did you say?", False), ("Tell billing what to say.", False)])
def test_what_a_session_said_is_asked_for_again_without_the_repeat_cut(said, asks):
    """On a live run with real agents, "What did hermes say?" got its answer cut as a repeat of the report a moment
    before, and the voice said nothing until a retry."""
    from guards import said_question

    assert said_question(said) is asks


def test_the_daemon_wires_both_into_the_brains_repeat_filter(monkeypatch):
    """The brain's repeat_asked is built in the daemon from both checks: a missing import there broke every brain turn.
    A waiting read-back lifts the filter too: the live proof logged "repeat cut" on a relay's read-back, whose opening
    quotes a reply already reported, though _speak then said it whole."""
    import os
    import tempfile

    os.environ.setdefault("CLAUDE_VOICE_STATE", tempfile.mkdtemp())
    import daemon

    assert daemon._repeat_filter_off("What did hermes say?") and daemon._repeat_filter_off("Say that again?")
    monkeypatch.setattr(daemon.state, "readback", None)
    assert not daemon._repeat_filter_off("Give hermes's answer to openclaw.")
    monkeypatch.setattr(daemon.state, "readback", "Send hermes's last reply to openclaw? It begins: Jupiter is large.")
    assert daemon._repeat_filter_off("Give hermes's answer to openclaw.")
    source = Path(daemon.__file__).read_text()
    assert "brain.repeat_asked = _repeat_filter_off" in source


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
