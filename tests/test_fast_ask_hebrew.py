"""A Hebrew question about one named session, or a Hebrew follow-up to its answer, goes to it as said.

From the first tester round (heb-01): "כמה טסטים נכשלו ב-billing?" was answered 11 s later with "I don't know whether
tests failed in billing; I asked Claude how many tests there are", while the English form of the same question goes
to billing at once (fast ask). heb-04: "ומה התוכנית לשפר את המהירות?" right after the session's answer went through the
model. Both now go as said, as their English forms do.

uv run pytest -q tests/test_fast_ask_hebrew.py
"""

import sys
import time
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import add, d  # noqa: E402,F401  (d is the daemon fixture)


@pytest.mark.parametrize("said,message", [
    ("כמה טסטים נכשלו ב-billing?", "כמה טסטים נכשלו?"),
    ("מי הסוקר של השינוי ב-billing?", "מי הסוקר של השינוי?"),
    ("מה השלב האיטי אצל billing?", "מה השלב האיטי?"),
])
def test_a_hebrew_question_about_a_named_session_goes_as_said(d, said, message):  # noqa: F811
    b = add(d, "b", "billing")
    add(d, "g", "granary")
    assert d._fast_send(said) == (b, message)


@pytest.mark.parametrize("said", ["מה אתה חושב על billing?", "מה קורה ב-billing?", "כמה טסטים נכשלו?"])
def test_an_opinion_a_status_question_or_no_session_is_the_models(d, said):  # noqa: F811
    add(d, "b", "billing")
    add(d, "g", "granary")
    assert d._fast_send(said) is None


def test_a_hebrew_follow_up_goes_to_the_session_that_answered(d):  # noqa: F811
    g = add(d, "g", "granary")
    add(d, "b", "billing")
    d.state.answered_by = ("g", time.time() - 3)
    assert d._fast_send("ומה התוכנית לשפר את המהירות?") == (g, "מה התוכנית לשפר את המהירות?")
    assert d._fast_send("ומה לגבי billing?") is None


@pytest.mark.parametrize("message,utterance", [
    ("כמה טסטים נכשלו?", "כמה טסטים נכשלו ב-billing?"),
    ("מה התוכנית לשפר את המהירות?", "ומה התוכנית לשפר את המהירות?"),
])
def test_they_need_no_relevance_check(d, monkeypatch, message, utterance):  # noqa: F811
    import asyncio
    add(d, "b", "billing")
    asked = []

    async def text(choice, prompt, max_tokens=16):
        asked.append(prompt)
        return "no"
    monkeypatch.setattr(d.vendors, "text", text)
    assert asyncio.run(d._is_current_request(message, utterance, [])) is True
    assert asked == []
