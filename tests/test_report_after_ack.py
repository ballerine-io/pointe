"""A session's report that arrives after the user said "okay" is still said in full.

From the first tester round: "Okay." (acc-04) and "Mm-hm" (brv-02) were followed by the session's report, and the
report was refused as "They only acknowledged. Speak empty text, or a few words at most.": the rule for a reply to an
acknowledgment was applied to the report that came after it, and the user never heard what the session did.

uv run pytest -q tests/test_report_after_ack.py
"""

import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

from brain import Brain  # noqa: E402

REPORT = "[ledgerline finished its turn] Say this:\nBatch size is now 2000 in load batches, untested and uncommitted."


def _brain():
    async def speak(text):
        pass

    b = Brain("gemini:x", "system", [], lambda: "[right now]", speak)
    b.may_stay_silent = lambda: True  # the user's last words were "Okay."
    b.append("Okay.")
    return b


def test_a_report_after_an_acknowledgment_is_said():
    b = _brain()
    b.append(REPORT)
    b._trigger = REPORT
    said = "Ledgerline set the batch size to 2000 in load batches; it is untested and not committed yet."
    assert b.speech_problem(said, False) is None


def test_a_long_reply_to_the_acknowledgment_itself_is_still_refused():
    b = _brain()
    b._trigger = "Okay."
    assert "acknowledged" in b.speech_problem("Great, I will keep that in mind and let you know how it goes later today.", False)


def test_an_empty_reply_to_a_report_is_sent_back():
    b = _brain()
    b.append(REPORT)
    b._trigger = REPORT
    assert b.speech_problem("", False) is not None
