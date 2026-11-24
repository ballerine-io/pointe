"""Two answers the user waits for, from one session, are both said: the second does not replace the first.

From the conversation suite (heb-04, round 4): "Who is the reviewer on granary?" then, before the answer was said,
"ומה התוכנית לשפר את המהירות?". Both answers came back; the first waited in the queue while the user spoke, and the
second, keyed to the same session, replaced it: the user never heard who the reviewer is. Replacing an older report is
for progress ("3 of 7 checks", then "all green"); two answers to two questions are two things to say.

uv run pytest -q tests/test_two_answers_queued.py
"""

import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import conversation  # noqa: E402

FIRST = "[granary: claude-code finished its turn] It answered the question you sent it. Tell the user: the reviewer is Dana."
SECOND = "[granary: claude-code finished its turn] It answered the question you sent it. Tell the user: add an index."
PROGRESS_1 = "[granary: claude-code finished its turn] Tell the user this: 3 of 7 checks done."
PROGRESS_2 = "[granary: claude-code finished its turn] Tell the user this: all checks green."


def test_two_awaited_answers_are_both_kept():
    u = conversation.Updates()
    u.add(FIRST, key="granary")
    u.add(SECOND, key="granary")
    assert u.take_awaited() == [FIRST, SECOND]


def test_a_newer_report_still_replaces_an_older_one():
    u = conversation.Updates()
    u.add(PROGRESS_1, key="granary")
    u.add(PROGRESS_2, key="granary")
    assert u.take() == [PROGRESS_2]
