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

import pytest

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


def test_a_yes_that_cut_the_read_out_hears_the_request_again_even_before_the_cut_is_noted(d, monkeypatch):  # noqa: F811
    """Measured (apr-08): the yes that cut the read-out reached the approval check before the interruption reached the
    front, so the read-out still counted as heard to its end and the user got the short line with no request in it."""
    active, posts, said = _read_out_setup(d, monkeypatch)
    asyncio.run(d._read_out(active))  # the read-out is being said: the window's clock is set, nothing has cut it yet
    d.ECHO.bot_started()
    d.state.user_started_at = time.time() - 0.3
    asyncio.run(d.on_user_utterance("Yes."))
    assert verdicts(posts) == []
    assert len(said) == 2 and said[1].startswith("I need the yes after I finish.") and "rm -rf build" in said[1]


def test_a_line_said_in_the_instant_of_a_cut_waits_for_the_cut_to_pass(d, monkeypatch):  # noqa: F811
    from test_no_silent_turn import _call
    front, spoken, asked, say = _call(d, monkeypatch, [])
    monkeypatch.setattr(d, "SPEAK_AFTER_CUT_SECS", 0.2)

    async def run():
        d.state.voice_cut_at = time.time()
        t0 = time.time()
        await front._speak("I need the yes after I finish. Say it again.", d.KEEP_WINDOW)
        return time.time() - t0

    waited = asyncio.run(run())
    assert spoken == ["I need the yes after I finish. Say it again."] and waited >= 0.18


def _heard_out(d, active):  # noqa: F811
    """The read-out was said and ended three seconds ago; nobody has spoken since."""
    asyncio.run(d._read_out(active))
    d.ECHO.bot_started()
    d.ECHO.bot_stopped()
    d.ECHO.stopped_at = time.time() - 3
    d.state.conn.injector.bot_started_at = time.time() - 6
    active.permission_delivered_at = time.time() - 7


def test_a_sound_with_no_words_after_the_read_out_is_asked_about_once(d, monkeypatch):  # noqa: F811
    """Measured with recorded people: one "yes" in twelve got no words from the recognizer, and nothing happened."""
    active, posts, said = _read_out_setup(d, monkeypatch)
    monkeypatch.setattr(d, "UNHEARD_ANSWER_SECS", 0.1)
    _heard_out(d, active)
    said.clear()
    now = time.time()
    d.state.user_started_at, d.state.user_stopped_at = now - 0.5, now  # half a second of voice, and no transcript
    assert d._unheard_answer_possible()
    asyncio.run(d._ask_unheard_answer(d.state.user_started_at, d.state.user_stopped_at))
    assert said == ["I didn't catch that. Yes or no?"] and verdicts(posts) == []

    d.state.user_started_at, d.state.user_stopped_at = time.time() - 0.5, time.time()  # a second sound: not asked again
    assert not d._unheard_answer_possible()

    d.ECHO.stopped_at = time.time() - 5  # the line kept the window: the yes after it still answers the request
    d.state.user_started_at = time.time() - 1
    asyncio.run(d.on_user_utterance("Yes."))
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "allow"}]


def test_a_sound_that_did_get_words_is_not_asked_about(d, monkeypatch):  # noqa: F811
    active, posts, said = _read_out_setup(d, monkeypatch)
    monkeypatch.setattr(d, "UNHEARD_ANSWER_SECS", 0.1)
    _heard_out(d, active)
    said.clear()
    now = time.time()
    d.state.user_started_at, d.state.user_stopped_at = now - 0.5, now

    async def run():
        task = asyncio.ensure_future(d._ask_unheard_answer(d.state.user_started_at, d.state.user_stopped_at))
        await asyncio.sleep(0.02)
        d.state.last_utterance, d.state.last_user_speech_at = "What does it run?", time.time()  # words came
        await task

    asyncio.run(run())
    assert said == []


def test_no_request_waiting_means_a_sound_is_just_a_sound(d, monkeypatch):  # noqa: F811
    active, posts, said = _read_out_setup(d, monkeypatch)
    active.permission_id = None
    now = time.time()
    d.state.user_started_at, d.state.user_stopped_at = now - 0.5, now
    assert not d._unheard_answer_possible()


def test_read_it_brings_the_request_again_and_the_yes_after_it_counts(d, monkeypatch):  # noqa: F811
    active, posts, said = _read_out_setup(d, monkeypatch)
    _heard_out(d, active)
    d._note_bot_speech("Bluebell is still waiting for your yes or no.")  # something else was said since: the window closed
    said.clear()
    d.state.user_started_at = time.time() - 1
    asyncio.run(d.on_user_utterance("Read it."))
    assert len(said) == 1 and "rm -rf build" in said[0] and verdicts(posts) == []
    d.ECHO.stopped_at = time.time() - 5
    d.state.user_started_at = time.time() - 1
    d.state.conn.injector.bot_started_at = time.time()
    asyncio.run(d.on_user_utterance("Yes."))
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "allow"}]


def test_mm_hm_after_should_it_is_asked_for_a_yes_or_a_no_once(d, monkeypatch):  # noqa: F811
    """Measured (brv-02): "Mm-hm." right after "Should it?" met silence, then the whole request again 39 s later. It is
    not a word that may approve; Pointe asks, once, and the yes after that counts. Tester round 4's judge called "I need a
    yes or a no." a needless confirmation of a clear "Mm-hm": the question is now asked as a person asks it."""
    active, posts, said = _read_out_setup(d, monkeypatch)
    _heard_out(d, active)
    said.clear()
    d.state.user_started_at = time.time() - 1
    asyncio.run(d.on_user_utterance("Mm-hm."))
    assert said == ["Is that a yes?"] and verdicts(posts) == [] and d.state.utterance_spent

    d.ECHO.stopped_at = time.time() - 5
    d.state.user_started_at = time.time() - 1
    asyncio.run(d.on_user_utterance("Mm-hm."))  # a second one: not asked twice
    assert said == ["Is that a yes?"]


def test_the_yes_after_is_that_a_yes_approves(d, monkeypatch):  # noqa: F811
    active, posts, said = _read_out_setup(d, monkeypatch)
    _heard_out(d, active)
    said.clear()
    d.state.user_started_at = time.time() - 1
    asyncio.run(d.on_user_utterance("Mm-hm."))
    assert said == ["Is that a yes?"]
    d.ECHO.stopped_at = time.time() - 5
    d.state.user_started_at = time.time() - 1
    d.state.utterance_spent = False
    asyncio.run(d.on_user_utterance("Yes."))
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "allow"}]


@pytest.mark.parametrize("yes,tail", [("כן.", "תריץ."), ("Yes.", "Go ahead."), ("Yeah.", "Run it.")])
def test_the_rest_of_a_yes_said_as_its_own_turn_is_part_of_it(d, monkeypatch, yes, tail):  # noqa: F811
    """Tester round 4's first sample, heb-03: "כן, תריץ." came as two turns. "כן" approved; "תריץ" two seconds later went
    to the model, which said for nine seconds that the tests were already with billing and an approval was pending."""
    active, posts, said = _read_out_setup(d, monkeypatch)
    _heard_out(d, active)
    said.clear()
    d.state.user_started_at = time.time() - 1
    asyncio.run(d.on_user_utterance(yes))
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "allow"}]
    d.state.utterance_spent = False
    asyncio.run(d.on_user_utterance(tail))
    assert d.state.utterance_spent and verdicts(posts) == [{"request_id": "p1", "behavior": "allow"}]


def test_a_new_request_after_a_yes_is_not_taken_for_its_tail(d, monkeypatch):  # noqa: F811
    active, posts, said = _read_out_setup(d, monkeypatch)
    _heard_out(d, active)
    d.state.user_started_at = time.time() - 1
    asyncio.run(d.on_user_utterance("Yes."))
    d.state.utterance_spent = False
    asyncio.run(d.on_user_utterance("Run the lint too."))
    assert not d.state.utterance_spent


@pytest.mark.parametrize("words", ["Sorry, read it again.", "Can you read it again?", "Read that again, please.",
                                   "Repeat the command.", "Could you repeat it?", "תקריא שוב", "Read it."])
def test_read_it_again_in_its_common_forms_brings_the_read_out(words):
    """Tester round 4's o4-03 (2 of 2): "Sorry, read it again." went to the model, which said the request in its own
    words; a yes after that could not approve, and the request was read once more. These are the daemon's to answer."""
    import daemon
    assert daemon._read_it_intent(words)


@pytest.mark.parametrize("words", ["Read the readme to billing.", "Tell billing to read it again from disk.", "Yes."])
def test_other_words_are_not_read_it(words):
    import daemon
    assert not daemon._read_it_intent(words)
