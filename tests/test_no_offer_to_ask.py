"""Asked a question only a session can answer, the voice asks the session; it does not offer to.

From the conversation suite: "Who's reviewing the granary change?" got "Do you want me to ask the granary session who is
reviewing the change?", and "What's its biggest file?" got "Do you want me to ask atlas for its biggest file?". The
user had asked: the offer is a needless confirmation, and the answer waits a whole extra exchange. A reply that offers
to ask or check with a session, to words that were a question, with nothing sent, is sent back to the model.

uv run pytest -q tests/test_no_offer_to_ask.py
"""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

from brain import Brain  # noqa: E402


def _brain(asked: str) -> Brain:
    async def speak(text):
        pass

    b = Brain("gemini:x", "system", [], lambda: "[right now]", speak)
    b.may_stay_silent = lambda: False  # the user said something that wants a reply
    b.append(asked)
    b._trigger = asked
    return b


@pytest.mark.parametrize("said", [
    "Do you want me to ask granary who is reviewing the change?",
    "Want me to check with granary?",
    "Should I ask granary for the reviewer?",
])
def test_an_offer_to_ask_a_question_the_user_already_asked_is_sent_back(said):
    assert "ask" in (_brain("Who's reviewing the granary change?").speech_problem(said, False) or "").lower()


def test_once_sent_or_when_the_user_did_not_ask_an_offer_is_fine():
    assert _brain("Who's reviewing the granary change?").speech_problem("Asking granary.", True) is None
    assert _brain("Granary is slow again.").speech_problem("Want me to ask granary why?", False) is None
    assert _brain("What do you think about the plan?").speech_problem(
        "I think it's sound. Want me to ask granary to start?", False) is None  # an offer to act, not to relay a question


@pytest.mark.parametrize("said", [
    "Granary joined Pointe and is idle. It read the notes file, but I don't know what's in it.",
    "I'm not sure what granary is working on.",
])
def test_not_knowing_what_a_named_session_knows_means_asking_it(said):
    """From the first tester round: "Just tell me about granary" got "It read the notes file, but I don't know what's
    in it." The session knows: the voice asks it instead of saying it does not know."""
    b = _brain("Just tell me about granary.")
    b.session_words = lambda: {"granary", "main"}
    assert "ask" in (b.speech_problem(said, False) or "").lower()


def test_not_knowing_about_something_no_session_holds_is_fine():
    b = _brain("What will the weather be tomorrow?")
    b.session_words = lambda: {"granary", "main"}
    assert b.speech_problem("I don't know the forecast.", False) is None


@pytest.mark.parametrize("asked,said", [
    ("Give me a detailed rundown of every session.",
     "All three joined and read the NOTES file. I don't have what the NOTES file says, nor where each one stands."),
    ("What's everyone doing?", "I haven't got the details of what each session is on."),
])
def test_not_having_what_the_sessions_hold_about_all_of_them_means_asking(asked, said):
    """From the first tester round (adv-09): "a detailed rundown of every session" got "I don't have what the NOTES
    file says": the sessions had it, and one question to each would have."""
    b = _brain(asked)
    b.session_words = lambda: {"granary", "orchid", "main"}
    assert "ask" in (b.speech_problem(said, False) or "").lower()
