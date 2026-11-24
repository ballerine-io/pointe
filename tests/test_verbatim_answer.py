"""A short answer from a session is said in Claude's own words, with no second model step to reword it.

From the conversation suite: the session's answer arrived about two seconds after the question, then waited for a
model step that only reworded it ("Tell the user its answer in one or two short sentences"), and twice that rewording
was refused (it named "the notes", it kept a file name) and cost another step, or the answer. A short plain answer is
now spoken as it came: code names said as words, markdown dropped. Anything longer, in another language than the user
spoke, or holding code, a link or a secret, still goes to the model.

uv run pytest -q tests/test_verbatim_answer.py
"""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import add, d  # noqa: E402,F401  (d is the daemon fixture)
from test_conversation_flow import call  # noqa: E402,F401  (the real injector on small clocks)


@pytest.mark.parametrize("final,said", [
    ("3 tests failed, all in `tests/test_refunds.py`, about rounding half-cent refunds.",
     "3 tests failed, all in test refunds, about rounding half-cent refunds."),
    ("**Priya** is reviewing the index change.", "Priya is reviewing the index change."),
    ("Plan: add an index on customer_id.", "Plan: add an index on customer id."),
    ("The nightly import took 47 minutes; `dedupe_rows` took 31 of them.",
     "The nightly import took 47 minutes; dedupe rows took 31 of them."),
])
def test_a_short_plain_answer_is_said_as_it_came(d, final, said):  # noqa: F811
    assert d._verbatim_answer(final, "How many tests failed?") == said


@pytest.mark.parametrize("final", [
    "```python\ndef refund(): ...\n```",
    "See https://example.com/build/123 for the log.",
    "| test | result |\n|---|---|\n| a | fail |",
    " ".join(["word"] * 60) + ".",
    "One. Two. Three. Four. Five.",
    "The key is sk-ant-abcdefghijklmnopqrstuvwxyz0123.",
])
def test_anything_else_goes_to_the_model(d, final):  # noqa: F811
    assert d._verbatim_answer(final, "How many tests failed?") is None


def test_an_english_answer_to_a_hebrew_question_goes_to_the_model_to_be_said_in_hebrew(d):  # noqa: F811
    assert d._verbatim_answer("3 tests failed.", "כמה טסטים נכשלו?") is None
    assert d._verbatim_answer("נכשלו 3 טסטים.", "כמה טסטים נכשלו?") == "נכשלו 3 טסטים."


def test_on_the_call_the_short_answer_is_said_by_the_daemon_without_a_model_step(call):  # noqa: F811
    import asyncio
    from types import SimpleNamespace

    from brain import Brain
    from test_conversation_flow import QUICK_ANSWER

    d = call.d  # noqa: F811
    spoken = []

    async def speak(text, request_id=None):
        spoken.append(text)

    async def run():
        injector = call.start()
        brain = Brain("fake:model", "instructions", [], lambda: "", speak)
        d.state.front = SimpleNamespace(brain=brain, _speak=speak)
        d._VERBATIM[QUICK_ANSWER] = "Three tests failed, all in the refund tests."
        await injector.inject(QUICK_ANSWER, True)
        await asyncio.sleep(0.2)
        assert spoken == ["Three tests failed, all in the refund tests."]
        assert call.asked == []  # no model step was asked for
        assert brain.messages[-1] == {"role": "assistant", "calls": [], "said": "Three tests failed, all in the refund tests."}

    asyncio.run(run())
