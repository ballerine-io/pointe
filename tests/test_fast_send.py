""""Tell billing to add a docstring to refund" is sent by the daemon itself, without waiting for a model step.

From the conversation suite: a plain "tell <session> to ..." waited for the model to read it (about 1.5 s) and then
for the relevance check, before "Sent to billing." When the words are a plain request to one named session, with
nothing in them that points back ("it", "that", "again") or needs the conversation, they are the brief: sent as said,
through every guard a send passes, and the model is told afterwards. Anything else goes to the model as before.

uv run pytest -q tests/test_fast_send.py
"""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import add, d  # noqa: E402,F401  (d is the daemon fixture)


def _two(d):  # noqa: F811
    add(d, "b", "ledgerline")
    add(d, "s", "skyway")
    d.REGISTRY.mode = "orchestrator"


@pytest.mark.parametrize("said,session,message", [
    ("Tell ledgerline to add a docstring to refund.", "ledgerline", "Add a docstring to refund."),
    ("Ask skyway to convert the hero image to WebP", "skyway", "Convert the hero image to WebP."),
    ("Ask ledgerline how many tests failed.", "ledgerline", "How many tests failed?"),
    ("Please tell skyway to add alt text to the hero image.", "skyway", "Add alt text to the hero image."),
    ("Ask skyway to add a docstring to dedupe rows explaining that it keeps the first copy of each row.", "skyway",
     "Add a docstring to dedupe rows explaining that it keeps the first copy of each row."),  # "it" inside the request
])
def test_a_plain_request_to_one_named_session_is_parsed(d, said, session, message):  # noqa: F811
    _two(d)
    got = d._fast_send(said)
    assert got is not None and got[0].name == session and got[1] == message


@pytest.mark.parametrize("said", [
    "Tell ledgerline to fix it.",                          # points back
    "Tell ledgerline to run that one more time.",          # points back
    "Tell ledgerline to do the same thing again.",         # needs the conversation
    "Tell ledgerline to add a docstring and tell skyway to add tests.",  # two sessions
    "Tell everyone to pull main.",                         # a broadcast
    "Tell ledgerline to",                                  # unfinished
    "Tell the orchid one to bump the version.",            # no session named
    "What do you think, should I tell ledgerline to rebase?",  # not a request
    "Tell ledgerline to delete the production database credentials.",  # the production warning is the model's
])
def test_anything_else_goes_to_the_model(d, said):  # noqa: F811
    _two(d)
    assert d._fast_send(said) is None


def _front(d):  # noqa: F811
    from types import SimpleNamespace

    from brain import Brain

    spoken, started = [], []

    async def speak(text, request_id=None):
        spoken.append(text)

    brain = Brain("fake:model", "s", [], lambda: "", speak)
    return SimpleNamespace(brain=brain, _speak=speak, _start=started.append), spoken, started


def test_the_send_goes_through_the_guards_and_is_acknowledged_without_the_model(d, monkeypatch):  # noqa: F811
    import asyncio

    from test_orchestrator import open_gates, record_dispatch

    _two(d)
    sent = record_dispatch(d, monkeypatch)
    said = "Tell ledgerline to add a docstring to refund."
    open_gates(d, monkeypatch, said)
    front, spoken, started = _front(d)
    session, message = d._fast_send(said)
    assert asyncio.run(d._send_fast(front, said, session, message)) is True
    assert sent == [("ledgerline", message)] and spoken == ["Sent to ledgerline."] and started == []
    assert front.brain.messages[-1] == {"role": "assistant", "calls": [], "said": "Sent to ledgerline."}


def test_a_refused_send_goes_to_the_model_with_the_users_words(d, monkeypatch):  # noqa: F811
    import asyncio

    from test_orchestrator import open_gates, record_dispatch

    _two(d)
    sent = record_dispatch(d, monkeypatch)
    said = "Tell ledgerline to add a docstring to refund."
    open_gates(d, monkeypatch, said)
    d.state.holding = True  # the user said to hold sends: the guard refuses it
    front, spoken, started = _front(d)
    session, message = d._fast_send(said)
    assert asyncio.run(d._send_fast(front, said, session, message)) is False
    assert sent == [] and spoken == []


@pytest.mark.parametrize("said,session,message", [
    ("How many tests failed in ledgerline?", "ledgerline", "How many tests failed?"),
    ("What's the Lighthouse score on skyway right now?", "skyway", "What's the Lighthouse score right now?"),
    ("How long did the nightly import take in skyway?", "skyway", "How long did the nightly import take?"),
])
def test_a_question_about_one_named_session_is_asked_as_said(d, said, session, message):  # noqa: F811
    _two(d)
    got = d._fast_send(said)
    assert got is not None and got[0].name == session and got[1] == message


@pytest.mark.parametrize("said", ["What's going on in ledgerline?", "What's the status of skyway?",
                                  "What do you think of the plan in ledgerline?", "How is it going on skyway?"])
def test_status_and_opinion_questions_go_to_the_model(d, said):  # noqa: F811
    _two(d)
    assert d._fast_send(said) is None


def test_a_hebrew_request_to_one_named_session_is_sent_as_said(d):  # noqa: F811
    _two(d)
    got = d._fast_send("תגיד ל-skyway להוסיף docstring לפונקציה dedupe_rows.")
    assert got is not None and got[0].name == "skyway" and got[1] == "להוסיף docstring לפונקציה dedupe_rows."
    assert d._fast_send("תגיד ל-skyway לתקן את זה.") is None  # "את זה" points back
