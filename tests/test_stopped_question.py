"""A question the user stopped is not answered after the stop.

From the first tester round (adv-09): "Give me a detailed rundown of every session, everything in their notes" was put
to billing; the user then said "Stop, stop. Tell billing to switch refund to Decimal", and 9 s after "Sent to billing"
the voice still read the notes rundown aloud, 15 s of what the user had cancelled. A question pending when the user
says stop is marked dropped: its short answer is not said, and the reader is told to leave it out of the report.

uv run pytest -q tests/test_stopped_question.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

import brief  # noqa: E402
from test_orchestrator import add, d, fake_conn  # noqa: E402,F401  (d is the daemon fixture)


def test_stop_drops_the_pending_question(d):  # noqa: F811
    s = add(d, "g", "granary")
    d.state.conn = fake_conn()
    d.state.unconfirmed["g"] = ["What does NOTES.md say, in full?"]
    d._drop_asked("Stop, stop. Tell granary to switch refunds to Decimal.")
    assert d.state.dropped["g"] == ["What does NOTES.md say, in full?"]
    assert d._quick_answer(s, f"[claude-code {d.FINISHED_MARK} {d.FINAL_MARK}NOTES says three tests fail.") is None


def test_an_order_or_no_stop_drops_nothing(d):  # noqa: F811
    add(d, "g", "granary")
    d.state.unconfirmed["g"] = ["Add a docstring to load_batches."]
    d._drop_asked("Stop, stop. Tell granary to switch refunds to Decimal.")
    assert not d.state.dropped.get("g")
    d.state.unconfirmed["g"] = ["What does NOTES.md say?"]
    d._drop_asked("And what about the tests?")
    assert not d.state.dropped.get("g")


def test_the_reader_is_told_to_leave_it_out():
    prompt = brief.report_prompt("granary", "NOTES says ... Switched to Decimal.", None, [], dropped=["What does NOTES say?"])
    assert "stopped" in prompt and "What does NOTES say?" in prompt
