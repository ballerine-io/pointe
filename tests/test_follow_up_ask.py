"""A follow-up question about what a session just answered goes to it as said, with no model step.

From the conversation suite (lat-01): "How many tests failed in billing?" was answered by billing; "And what's blocked
because of it?" then waited 1.3 s for a model step and 0.7 s for the relevance check before "Asking billing.", 3.5 s
in all. Its "it" is billing's last answer, which billing has: a question that opens with "and" or "what about", right
after a session's answer was said, goes to that session as said. One that names another session, or asks the voice's
own opinion, or comes long after, is the model's.

uv run pytest -q tests/test_follow_up_ask.py
"""

import sys
import time
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import add, d  # noqa: E402,F401  (d is the daemon fixture)


@pytest.fixture
def heard_billing(d):  # noqa: F811
    b = add(d, "b", "billing")
    add(d, "g", "granary")
    d.state.thread = ("b", time.time() - 5)
    d.state.answered_by = ("b", time.time() - 3)
    return b


@pytest.mark.parametrize("said,message", [
    ("And what's blocked because of it?", "What's blocked because of it?"),
    ("What about the staging deploy?", "What about the staging deploy?"),
    ("And who reviews it?", "Who reviews it?"),
])
def test_a_follow_up_goes_to_the_session_that_answered(d, heard_billing, said, message):  # noqa: F811
    assert d._fast_send(said) == (heard_billing, message)


@pytest.mark.parametrize("said", [
    "And what about granary?",           # another session
    "And do you think it's worth it?",   # the voice's own view
    "And then what?",                    # too little to send
    "What's blocked because of it?",     # no "and": could be about anything said
])
def test_anything_else_is_the_models(d, heard_billing, said):  # noqa: F811
    assert d._fast_send(said) is None


def test_long_after_the_answer_it_is_the_models(d, heard_billing):  # noqa: F811
    d.state.answered_by = ("b", time.time() - 120)
    assert d._fast_send("And what's blocked because of it?") is None


def test_the_follow_up_needs_no_relevance_check(d, heard_billing, monkeypatch):  # noqa: F811
    import asyncio
    asked = []

    async def text(choice, prompt, max_tokens=16):
        asked.append(prompt)
        return "no"
    monkeypatch.setattr(d.vendors, "text", text)
    assert asyncio.run(d._is_current_request("What's blocked because of it?", "And what's blocked because of it?", [])) is True
    assert asked == []
