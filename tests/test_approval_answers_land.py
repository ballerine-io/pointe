"""A yes and a no always land, each with a spoken result.

From the independent tester's second round: "No, don't run that." said before the request was read out got no reply and
the session kept waiting; a yes said before the read-out got "Okay." and then the request twice; and each answer's
acknowledgement was a model step that took two to three seconds. A no to a pending request is applied at once, a yes
before the read-out brings the read-out once and approves nothing, and the daemon says the result itself.

uv run pytest -q tests/test_approval_answers_land.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import _read_out_setup, d, verdicts  # noqa: E402,F401  (d is the daemon fixture)


def _unread(d, active):  # noqa: F811
    """The request is pending and on its card; the voice has not read it out yet."""
    active.permission_read_at, active.permission_delivered_at = 0.0, float("inf")
    d.ECHO.bot_started()
    d.ECHO.bot_stopped()
    d.ECHO.stopped_at = time.time() - 5
    d.state.user_started_at = time.time() - 1


def test_a_no_before_the_read_out_is_applied_and_said(d, monkeypatch):  # noqa: F811
    active, posts, said = _read_out_setup(d, monkeypatch)
    _unread(d, active)
    asyncio.run(d.on_user_utterance("No, don't run that."))
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "deny"}]
    assert said == ["Denied."]


def test_a_no_to_pointes_own_question_does_not_deny_an_unread_request(d, monkeypatch):  # noqa: F811
    active, posts, said = _read_out_setup(d, monkeypatch)
    _unread(d, active)
    monkeypatch.setattr(d, "PERMISSION_ANSWER_SECS", 120.0)  # the fixture's clock-free value would count the no as recent
    d.state.floor.said("Want me to ask billing first?", time.time())  # Pointe asked something of its own: the no answers that
    asyncio.run(d.on_user_utterance("No."))
    assert verdicts(posts) == []


def test_a_yes_before_the_read_out_reads_it_once_and_approves_nothing(d, monkeypatch):  # noqa: F811
    active, posts, said = _read_out_setup(d, monkeypatch)
    _unread(d, active)
    asyncio.run(d.on_user_utterance("Yes, go ahead."))
    assert verdicts(posts) == []
    assert len(said) == 1 and "rm -rf build" in said[0] and said[0].endswith("Should it?")
    assert "after I finish" not in said[0]  # nothing was being read: there was no end to wait for
    assert d.state.utterance_spent  # the brain does not answer the yes with an "Okay." of its own

    asyncio.run(d._read_out_when_quiet(active, "p1"))  # the read-out that waited for a gap: already said
    assert len(said) == 1

    d.ECHO.stopped_at = time.time() - 5
    d.state.user_started_at = time.time() - 1
    d.state.conn.injector.bot_started_at = time.time()
    asyncio.run(d.on_user_utterance("Yes."))
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "allow"}]
    assert said[-1] == "Approved."


def test_a_yes_over_another_line_before_the_read_out_is_not_told_to_wait_for_its_end(d, monkeypatch):  # noqa: F811
    active, posts, said = _read_out_setup(d, monkeypatch)
    active.permission_read_at, active.permission_delivered_at = 0.0, float("inf")
    d.ECHO.bot_started()  # "Sent to atlas." is still being said
    d.state.user_started_at = time.time() - 0.5
    asyncio.run(d.on_user_utterance("Yes."))
    assert verdicts(posts) == []
    assert len(said) == 1 and "rm -rf build" in said[0] and "after I finish" not in said[0]


def test_the_result_is_said_by_the_daemon_with_no_model_step(d, monkeypatch):  # noqa: F811
    active, posts, said = _read_out_setup(d, monkeypatch)
    asyncio.run(d._read_out(active))
    d.ECHO.bot_started()
    d.ECHO.bot_stopped()
    d.ECHO.stopped_at = time.time() - 5
    d.state.user_started_at = time.time() - 1
    d.state.conn.injector.bot_started_at = time.time()
    asyncio.run(d.on_user_utterance("yes"))
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "allow"}]
    assert said[-1] == "Approved."
    assert not [text for text, respond in d.state.conn.injector.fed if respond]  # nothing waits on the model


def test_the_result_is_said_in_hebrew_after_a_hebrew_answer(d, monkeypatch):  # noqa: F811
    active, posts, said = _read_out_setup(d, monkeypatch)
    _unread(d, active)
    asyncio.run(d.on_user_utterance("לא."))
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "deny"}]
    assert said == ["נדחה."]


def test_a_request_right_after_the_users_send_is_read_after_a_breath_not_the_quiet_gap(d, monkeypatch):  # noqa: F811
    """Measured: "Sent to billing." ended, the request was already there, and its read-out came five seconds later: the
    quiet gap that news waits for. The user is waiting for this one."""
    active, posts, said = _read_out_setup(d, monkeypatch)
    _unread(d, active)
    now = time.time()
    d.state.floor.bot_stopped_at = d.state.floor.said_at = now - 1.0  # "Sent to billing." ended a second ago
    d.state.floor.user_turn_at = now - 3.0
    d.state.user_started_at, d.state.user_stopped_at, d.state.user_heard_at = now - 4.0, now - 3.0, now - 3.0
    monkeypatch.setattr(d, "online", lambda s: True)
    monkeypatch.setattr(d.flow, "QUIET_GAP_SECS", 5.0)  # the fixture's floor has no waits: this test is about one

    active.last_delegation_at = now - 2.0  # the user's own send, two seconds ago
    asyncio.run(asyncio.wait_for(d._read_out_when_quiet(active, "p1"), 1.0))
    assert len(said) == 1 and said[0].endswith("Should it?")


def test_a_request_nobody_just_asked_for_still_waits_for_a_gap(d, monkeypatch):  # noqa: F811
    active, posts, said = _read_out_setup(d, monkeypatch)
    _unread(d, active)
    now = time.time()
    d.state.floor.bot_stopped_at = d.state.floor.said_at = now - 1.0
    d.state.floor.user_turn_at = now - 3.0
    d.state.user_started_at, d.state.user_stopped_at, d.state.user_heard_at = now - 4.0, now - 3.0, now - 3.0
    monkeypatch.setattr(d, "online", lambda s: True)
    monkeypatch.setattr(d.flow, "QUIET_GAP_SECS", 5.0)  # the fixture's floor has no waits: this test is about one
    active.last_delegation_at = now - 600

    async def run():
        try:
            await asyncio.wait_for(d._read_out_when_quiet(active, "p1"), 0.6)
        except asyncio.TimeoutError:
            pass

    asyncio.run(run())
    assert said == []
