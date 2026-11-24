"""Pointe's answer to the owner's question in a meeting is written under the room's open question, which is then done,
and the end notes see it answered. QA round 2: the feed kept "Open question" beside the spoken answer, and the end sheet
listed the retry limit as open."""

import asyncio
import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import meeting as m  # noqa: E402
from test_meeting_daemon import _meeting_ready, _start  # noqa: E402
from test_meeting_voice import _copy_answers  # noqa: E402
from test_orchestrator import add, d  # noqa: E402,F401


def _open_question(d, text):
    return d.NOTES.add("question", text, meeting=d.state.meeting.id)


def test_the_answer_closes_the_open_question_it_answers(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    billing = add(d, "b", "billing/main")
    _copy_answers(d, monkeypatch)
    _start(d, "participating")
    q = _open_question(d, "What is the current billing webhook retry limit?")
    other = _open_question(d, "Who owns the on-call runbook?")
    asyncio.run(d._ask_copy(billing, "What is billing's webhook retry limit?"))
    answer = next(n for n in d.NOTES.items if n.kind == "answer")
    assert answer.meta["question_id"] == q.id and answer.meeting == d.state.meeting.id
    assert d.NOTES.get(q.id).state == "done" and d.NOTES.get(other.id).state == "open"
    assert "[question, answered] What is the current billing webhook retry limit?" in m.end_prompt(d.state.meeting, d.NOTES)
    assert "[question] Who owns the on-call runbook?" in m.end_prompt(d.state.meeting, d.NOTES)


def test_an_answer_that_fits_no_open_question_leaves_them_open(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    billing = add(d, "b", "billing/main")
    _copy_answers(d, monkeypatch)
    _start(d, "listening")
    q = _open_question(d, "Who owns the on-call runbook?")
    asyncio.run(d._ask_copy(billing, "What is the retry limit?"))
    assert d.NOTES.get(q.id).state == "open"
    assert "question_id" not in next(n for n in d.NOTES.items if n.kind == "answer").meta


def test_a_meeting_started_by_voice_links_the_joined_sessions(d, monkeypatch):
    add(d, "b", "billing/main"), add(d, "c", "docs/main")
    assert d._meeting_sessions_heard("Pointe, start a meeting, just listen.") == ["billing/main", "docs/main"]
    assert d._meeting_sessions_heard("Start a meeting about billing.") == ["billing/main"]
