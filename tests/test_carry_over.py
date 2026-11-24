"""The answer the user was waiting for survives a dropped call: said after the call comes back.

From the conversation suite (the reconnect dialogue): the phone's link dropped for a moment while billing answered
the user's question. The call's queue was emptied when it ended ("not said into the next one") and an answer arriving
with no call was kept for the notes only, so the user, back two seconds later, never heard it. Answers to their own
question, queued or arriving in the gap, are now carried into a call that comes back within CARRY_SECS.

uv run pytest -q tests/test_carry_over.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_conversation_flow import QUICK_ANSWER, REPORT_DOCS, call  # noqa: E402,F401
from test_orchestrator import add, d  # noqa: E402,F401  (d is the daemon fixture)


def test_a_queued_answer_is_carried_into_the_next_call(call):  # noqa: F811
    d = call.d  # noqa: F811

    async def run():
        first = call.start()
        d.state.floor.user_started(time.time())  # the user talks, so both wait in the queue
        await first.inject(QUICK_ANSWER, True)
        await first.inject(REPORT_DOCS, True)
        first.call_over()
        d.state.conn = None
        second = call.start()
        await d._carry_over(second)
        await asyncio.sleep(0.3)
        assert [text for _, text in call.asked] == [QUICK_ANSWER]  # the answer; the other news stays for the notes

    asyncio.run(run())


def test_an_answer_that_arrives_with_no_call_is_carried(d, monkeypatch):  # noqa: F811
    s = add(d, "b", "billing")
    d.REGISTRY.active_id = "b"
    d.state.conn = None
    d.state.unconfirmed["b"] = ["How many tests failed?"]

    async def digest(session, text):
        return {}

    monkeypatch.setattr(d, "_digest_turn", digest)
    asyncio.run(d.feed(s, f"[claude-code {d.FINISHED_MARK} {d.FINAL_MARK}Three tests failed.", True))
    assert d.state.carried and "Three tests failed." in d.state.carried[-1][1]


def test_an_old_carry_is_dropped(call):  # noqa: F811
    d = call.d  # noqa: F811

    async def run():
        d.state.carried = [(time.time() - d.CARRY_SECS - 1, QUICK_ANSWER)]
        second = call.start()
        await d._carry_over(second)
        await asyncio.sleep(0.2)
        assert call.asked == [] and d.state.carried == []

    asyncio.run(run())
