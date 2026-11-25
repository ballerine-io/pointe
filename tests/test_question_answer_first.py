"""News waits while the answer to the user's newest question is on its way.

orc-03 in tester round 4 (2 of 4) and r9: "Meanwhile, what's the plan for speeding up quarry?" got "Asking quarry.", then
billing's report of the comment it had just added, and only then quarry's answer. The question the user just asked comes
first; other news waits for it (at most QUESTION_FIRST_SECS).

uv run pytest -q tests/test_question_answer_first.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_orchestrator import d  # noqa: E402,F401  (d is a fixture)
from test_switch_stops_speech import call, report, the_floor_frees  # noqa: E402,F401  (call is a fixture)


def _question_out(c, ago: float) -> None:
    c.d.REGISTRY.mode = "orchestrator"
    c.beta.last_delegation_at = time.time() - ago
    c.d.state.unconfirmed = {c.beta.id: ["What's the plan for speeding up the import?"]}


def test_another_sessions_report_waits_for_the_answer_just_asked_for(call):  # noqa: F811
    async def run():
        _question_out(call, ago=3)
        call.inj._bot_speaking = True
        await call.inj.inject(report(call.d, "alpha", "The parser refactor is done."), True)
        await the_floor_frees(call)
    asyncio.run(run())
    assert not any("parser" in t for t in call.inj.asked_to_speak())


def test_after_a_while_it_is_said_anyway(call):  # noqa: F811
    async def run():
        _question_out(call, ago=call.d.QUESTION_FIRST_SECS + 1)
        call.inj._bot_speaking = True
        await call.inj.inject(report(call.d, "alpha", "The parser refactor is done."), True)
        await the_floor_frees(call)
    asyncio.run(run())
    assert any("parser" in t for t in call.inj.asked_to_speak())


def test_the_asked_sessions_own_report_is_not_held_behind_its_question(call):  # noqa: F811
    async def run():
        _question_out(call, ago=3)
        call.inj._bot_speaking = True
        await call.inj.inject(report(call.d, "beta", "The plan is an index on customer id."), True)
        await the_floor_frees(call)
    asyncio.run(run())
    assert any("index on customer id" in t for t in call.inj.asked_to_speak())
