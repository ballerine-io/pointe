"""A plain send is acknowledged in two or three words at once, without a second model step.

From the conversation suite: "How many tests failed in billing?" cost two model steps before any sound: one to send
the question, a second to say "I asked billing how many tests failed. I don't have the number yet.", 14 words that
the session's answer then had to wait behind. When the send went through and its result asks nothing more of the voice,
the daemon says "Asking billing." itself. Anything else (a refusal, a line the result asks to be said, a second
question in the user's words) still goes back to the model.

uv run pytest -q tests/test_quick_ack.py
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import add, d  # noqa: E402,F401  (d is the daemon fixture)

SENT = {"sent_to": ["billing/main"], "routing": "brain", "note": "Sent is not done: say you asked Claude, not that it happened."}
LONG_ACK = "I asked billing how many tests failed. I don't have the number yet."


def _brain(monkeypatch, result, message, ack):
    import brain as brain_module

    spoken, steps = [], []

    async def speak(text, request_id=None):
        spoken.append(text)

    async def step(choice, instructions, messages, decls):
        steps.append(len(messages))
        if len(steps) == 1:
            return SimpleNamespace(calls=[{"id": "s1", "name": "send_to_claude_code", "args": {"message": message}}],
                                   said="", raw=None, vendor="fake", usage={})
        return SimpleNamespace(calls=[{"id": "s2", "name": "speak", "args": {"text": LONG_ACK}}], said="", raw=None,
                               vendor="fake", usage={})

    async def handler(params):
        await params.result_callback(result)

    tool = SimpleNamespace(name="send_to_claude_code", description="send", properties={}, required=[], handler=handler)
    monkeypatch.setattr(brain_module.vendors, "step", step)
    b = brain_module.Brain("fake:model", "instructions", [tool], lambda: "[right now] billing", speak)
    b.may_stay_silent = lambda: False
    b.quick_ack = ack
    return b, spoken, steps


def test_a_sent_question_is_acknowledged_at_once_without_a_second_step(monkeypatch, d):  # noqa: F811
    b, spoken, steps = _brain(monkeypatch, SENT, "How many tests failed in billing?", d._quick_ack)
    asyncio.run(b.turn("How many tests failed in billing?"))
    assert spoken == ["Asking billing."] and len(steps) == 1
    tool_msgs = [m for m in b.messages if m["role"] == "tool"]
    assert tool_msgs and b.messages[-1] == {"role": "assistant", "calls": [], "said": "Asking billing."}


def test_a_sent_instruction_says_sent(d):  # noqa: F811
    assert d._quick_ack({"message": "Add a docstring to refund()."}, SENT, "Tell billing to add a docstring to refund.") \
        == "Sent to billing."


def test_hebrew_in_hebrew_out(d):  # noqa: F811
    assert d._quick_ack({"message": "How many tests failed?"}, SENT, "כמה טסטים נכשלו ב-billing?") == "שאלתי את billing."
    assert d._quick_ack({"message": "Add a docstring."}, SENT, "תגיד ל-billing להוסיף docstring") == "שלחתי ל-billing."


@pytest.mark.parametrize("result", [
    {**SENT, "say": "Tell the user it went to billing."},
    {"error": "Not sent: the user has not spoken."},
    {**SENT, "failed": ["docs"]},
    {**SENT, "offline": ["docs"]},
    {**SENT, "then": "Ask which branch."},
])
def test_anything_the_result_asks_the_voice_to_say_goes_back_to_the_model(monkeypatch, d, result):  # noqa: F811
    assert d._quick_ack({"message": "How many tests failed?"}, result, "How many tests failed in billing?") is None
    b, spoken, steps = _brain(monkeypatch, result, "How many tests failed?", d._quick_ack)
    asyncio.run(b.turn("How many tests failed in billing?"))
    assert len(steps) >= 2 and "Asking billing." not in spoken  # the model writes it (a refused send's claim is sent back)


def test_a_second_question_in_the_users_words_goes_back_to_the_model(d):  # noqa: F811
    asked = "Tell billing to add a docstring to refund. And what's a semaphore?"
    assert d._quick_ack({"message": "Add a docstring to refund()."}, SENT, asked) is None


def test_the_brain_without_a_quick_ack_still_takes_the_model_step(monkeypatch):
    b, spoken, steps = _brain(monkeypatch, SENT, "How many tests failed?", lambda *_a: None)
    asyncio.run(b.turn("How many tests failed in billing?"))
    assert len(steps) == 2 and spoken == [LONG_ACK]


def test_a_question_passed_on_inside_a_brief_is_still_a_question(d):  # noqa: F811
    """From the suite: the brain sent "The owner asks: how long did the import take? Answer from your notes." and the
    acknowledgement fell back to the model, because the message did not end on the question mark."""
    message = "The owner asks: how long did the nightly import take? Answer from your notes or whatever you know."
    assert d._quick_ack({"message": message}, SENT, "How long did the nightly import take?") == "Asking billing."


def test_a_question_put_to_a_read_only_copy_is_acknowledged_the_same_way(d):  # noqa: F811
    """From the suite: ask_about_session's "tell the user you are asking, the answer comes in about ten seconds" became
    "I'm asking granary, since the answer is in the notes file. It should come back in about ten seconds." after a
    model step."""
    result = {"asking": "billing/main", "say": "Tell the user in a few words that you are asking billing/main, and that "
                                               "the answer comes in about ten seconds."}
    assert d._quick_ack({"question": "Who reviews it?"}, result, "Who reviews the billing change?") == "Asking billing."


def test_the_ack_says_a_hyphenated_session_as_words(d):  # noqa: F811
    """r9, amb-02: "Asking toll dash API." The quick acknowledgement used the session's name as written."""
    add(d, "t", "toll-api/main")
    result = {"sent_to": ["toll-api/main"], "routing": "brain"}
    assert d._quick_ack({"message": "What version is it on?"}, result, "What version is the toll api on?") == "Asking toll api."
