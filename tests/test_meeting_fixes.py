"""The 18 defects a code review found in meeting mode, each as the scenario that showed it. Ordered as fixed."""

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from test_meeting_daemon import FakeEars, _meeting_ready, _start  # noqa: F401
from test_orchestrator import add, client_for, d, fake_conn  # noqa: F401  (d is a fixture)

import meeting as meetings


def _feed(d, speaker, text, at):
    """One speaker's words at a given moment, in audio time; then the room goes quiet so the turn closes. Unlike _say
    it keeps the speaker, so a second fragment of the same speaker exercises the merge path."""
    m = d.state.meeting

    async def go():
        tok = {"text": " " + text, "speaker": speaker, "is_final": True, "language": "en",
               "start_ms": int(at * 1000), "end_ms": int(at * 1000) + 600}
        for turn in m.hear([tok], now=at):
            await d._on_meeting_turn(m, turn)
        for turn in m.tick(now=at + 2 * meetings.SILENCE_CLOSES_SECS + 1):
            await d._on_meeting_turn(m, turn)
    asyncio.run(go())


def _commands(d, monkeypatch):
    seen = []

    async def record(words, typed=False):
        seen.append(words)
    monkeypatch.setattr(d, "_meeting_command", record)
    return seen


# 1. the same-speaker merge

def test_an_owner_command_after_their_own_talk_is_heard(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d)
    m = d.state.meeting
    m.owner = "1"
    seen = _commands(d, monkeypatch)
    _feed(d, "1", "let's talk pricing", 100.0)
    _feed(d, "1", "Pointe, end the meeting", 102.0)  # 2 s later, nobody in between
    assert seen == ["end the meeting"]


def test_talking_on_after_a_command_does_not_fire_it_again(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d)
    m = d.state.meeting
    m.owner = "1"
    seen = _commands(d, monkeypatch)
    _feed(d, "1", "Pointe, what do you think", 100.0)
    _feed(d, "1", "about the rollout plan for next week", 101.5)
    _feed(d, "1", "and the pricing page too", 103.0)
    assert seen == ["what do you think"]


def test_a_long_single_speaker_counts_each_new_fragment_once():
    m = meetings.Meeting(mode="listening", vendors={})
    for i in range(6):
        for t in m.hear([{"text": f" part {i} of a long talk", "speaker": "1", "is_final": True,
                          "start_ms": 100_000 + i * 2000, "end_ms": 100_000 + i * 2000 + 600}], now=100 + i * 2):
            pass
        m.tick(now=100 + i * 2 + 3)
    assert m.turns_since_secretary <= 6
    assert m.speech_since_secretary < 30  # the merged turn's whole length is not re-added each time


def test_a_command_after_a_sentence_in_the_same_breath_is_heard(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d)
    d.state.meeting.owner = "1"
    seen = _commands(d, monkeypatch)
    _feed(d, "1", "Good, I think we covered the launch plan. Pointe, end the meeting.", 100.0)
    assert [w.rstrip(".") for w in seen] == ["end the meeting"]


def test_two_addressed_sentences_in_one_turn_are_both_heard():
    assert meetings.addressed_all("Pointe, that's me. Fine. Pointe, end the meeting.") == ["that's me. Fine.", "end the meeting."]
    assert meetings.addressed_all("I told Pointe to wait. Then we left.") == []
    assert meetings.addressed_all("Pointe, what do you think?") == ["what do you think?"]


def test_a_question_finalised_in_bursts_is_asked_once(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d)
    d.state.meeting.owner = "1"
    seen = _commands(d, monkeypatch)
    m = d.state.meeting

    async def go():
        for text, at, ms in ((" Pointe, should we close the meeting now", 100.0, 100_000), (",", 102.0, 100_600),
                             ("?", 104.0, 101_200)):  # Soniox's late bursts: punctuation alone, glued to the word before
            for turn in m.hear([{"text": text, "speaker": "1", "is_final": True, "start_ms": ms, "end_ms": ms + 500}], now=at):
                await d._on_meeting_turn(m, turn)
            for turn in m.tick(now=at + 1.5):
                await d._on_meeting_turn(m, turn)
    asyncio.run(go())
    assert len(seen) == 1 and seen[0].startswith("should we close the meeting")


def test_talk_then_a_command_with_no_punctuation_between_is_heard(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d)
    d.state.meeting.owner = "1"
    seen = _commands(d, monkeypatch)
    _feed(d, "1", "let's talk pricing", 100.0)
    _feed(d, "1", "Pointe end the meeting", 102.0)  # Soniox wrote no full stop between them
    assert seen == ["end the meeting"]


# 3. notes leak across meetings

def test_a_new_meeting_starts_with_no_notes_from_the_last(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d)
    d.NOTES.add("decision", "Meeting A decided to ship on Monday")
    d.NOTES.add("action", "Dana: write the migration")
    asyncio.run(d.end_meeting())
    client_for(d).post("/voice/meeting", json={"action": "discard"})
    _start(d)
    texts = [n["text"] for n in client_for(d).get("/voice/notes?since=0").json()["notes"]]
    assert not any("Meeting A" in t or "Dana: write" in t for t in texts)
    assert "Meeting A" not in meetings.secretary_prompt(d.state.meeting, d.NOTES, {})


def test_discard_forgets_the_ended_meetings_notes(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d)
    d.NOTES.add("thought", "Something said in the meeting")
    asyncio.run(d.end_meeting())
    client_for(d).post("/voice/meeting", json={"action": "discard"})
    assert not any(n.text == "Something said in the meeting" for n in d.NOTES.items)


# 5. held speech released into the room

def test_news_held_before_the_meeting_is_not_spoken_in_it(d, monkeypatch):
    pushed, _ = _meeting_ready(d, monkeypatch)
    inj = d.FeedInjector()
    inj.push_frame = d.state.conn.injector.push_frame
    d.state.conn.injector = inj
    inj._held = ["[billing finished its turn] the retry fix is in"]
    _start(d, mode="participating")
    asyncio.run(inj._respond("[billing finished its turn] the retry fix is in"))
    assert not any("retry fix" in getattr(f, "text", "") for f in pushed)
    assert any("retry fix" in text for text, _ in d.state.monologue_held)


def test_in_participating_only_what_the_owner_asked_for_is_spoken(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d, mode="participating")
    front = d.BrainFront.__new__(d.BrainFront)
    spoken = []

    async def push(frame, *a):
        spoken.append(frame)
    front.push_frame = push
    asyncio.run(front._speak("Connected to 3 sessions, billing waits on you."))
    assert spoken == []  # nobody asked: not said to the room
    d.state.meeting_may_speak_until = time.time() + 30
    asyncio.run(front._speak("The retry loop is the likelier cause."))
    assert len(spoken) == 1


# 6. the spoken entry command answered as a question

def test_the_entry_command_is_not_taken_as_a_question(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    d.PREFS.update({"meeting.consented": True})
    seen = _commands(d, monkeypatch)
    asyncio.run(d.start_meeting("participating", entry_words="Pointe, meeting mode, participating"))
    _feed(d, "1", "Pointe, meeting mode, participating", 100.0)
    assert d.state.meeting.owner == "1" and seen == []


def test_talk_right_after_the_entry_command_does_not_replay_it_as_a_question(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    d.PREFS.update({"meeting.consented": True})
    seen = _commands(d, monkeypatch)
    asyncio.run(d.start_meeting("participating", entry_words="Pointe, meeting mode, participating"))
    _feed(d, "1", "Pointe, meeting mode, participating", 100.0)
    _feed(d, "1", "so, about the pricing launch", 101.5)
    assert seen == []


# 9. "end" inside a question

@pytest.mark.parametrize("said", ["do you think we should close the meeting now?",
                                  "before we finish the meeting, what's open?", "close the meeting? not yet, Dana has one more",
                                  "stop the meeting from running over, what is left"])
def test_a_question_mentioning_the_meeting_end_does_not_end_it(said):
    assert meetings.command(said)[0] != "end"


@pytest.mark.parametrize("said", ["end the meeting", "end meeting mode", "please close the meeting", "stop the meeting now",
                                  "סיים את הפגישה", "end the meeting. Thanks everyone."])
def test_a_plain_end_command_still_ends(said):
    assert meetings.command(said)[0] == "end"


# 2. Soniox reconnect

def test_after_the_stream_reconnects_old_labels_and_the_owner_no_longer_apply():
    m = meetings.Meeting(mode="listening", vendors={})
    m.hear([{"text": " hello", "speaker": "1", "is_final": True, "start_ms": 5000, "end_ms": 5500}], now=10)
    m.tick(now=20)
    m.owner, m.bot = "1", "3"
    m.stream_restarted()
    assert m.owner is None and m.bot is None
    turns = m.hear([{"text": " Pointe, end the meeting", "speaker": "1", "is_final": True, "start_ms": 100, "end_ms": 600}],
                   now=30) + m.tick(now=40)
    assert turns and turns[-1].speaker != "1"  # a new stream's "1" is a different label


def test_an_unreachable_stream_is_not_redialled_on_every_frame(monkeypatch):
    attempts = []

    class Down(meetings.MeetingEars):
        async def open(self):
            attempts.append(time.time())
            raise OSError("unreachable")

    async def go():
        ears = Down("k", 16000, [], None)
        started = time.time()
        for _ in range(100):  # two seconds of 20 ms frames
            await ears.send(b"\0" * 640)
        took = time.time() - started
        await asyncio.sleep(0.2)
        await ears.close()
        return took
    took = asyncio.run(go())
    assert len(attempts) <= 2 and took < 0.5  # never stalls the call's audio path


def test_a_dropped_stream_redials_and_tells_the_daemon(monkeypatch):
    class Sock:
        def __init__(self):
            self.sent = []

        async def send(self, data):
            self.sent.append(data)

        async def close(self):
            pass

    socks, told = [], []

    class Up(meetings.MeetingEars):
        async def open(self):
            self._ws = Sock()
            socks.append(self._ws)
            self.connected = self._opened = True

    async def go():
        ears = Up("k", 16000, [], None)

        async def on_reconnect():
            told.append(True)
        ears.on_reconnect = on_reconnect
        await ears.open()
        await ears.send(b"a")
        await asyncio.sleep(0.05)
        await ears.reconnect()
        await ears.send(b"b")
        await asyncio.sleep(0.05)
        await ears.close()
    asyncio.run(go())
    assert len(socks) == 2 and told == [True] and socks[1].sent == [b"b"]


def test_the_owner_can_ask_for_a_new_audio_stream(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d)
    asked = []

    async def reconnect():
        asked.append(True)
    d.state.meeting_ears.reconnect = reconnect
    r = client_for(d).post("/voice/meeting", json={"action": "reconnect"})
    assert r.status_code == 200 and asked == [True]


# 4. end is guarded and does not wait behind lookups

def test_ending_twice_runs_one_end_pass(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d)
    calls = []

    async def slow_read(system, prompt, effort="low"):
        calls.append(1)
        await asyncio.sleep(0.2)
        return {"summary": "done"}
    monkeypatch.setattr(d, "_read_model", slow_read)

    async def go():
        return await asyncio.gather(d.end_meeting(), d.end_meeting())
    first, second = asyncio.run(go())
    assert len(calls) == 1 and (first.get("error") or second.get("error"))
    assert sum(1 for n in d.NOTES.items if n.kind == "summary") == 1


def test_the_end_pass_does_not_wait_for_busy_lookups(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d)

    async def read(system, prompt, effort="low"):
        return {"summary": "done"}
    monkeypatch.setattr(d, "_read_model", read)

    async def go():
        blockers = [asyncio.create_task(d.JOBS.run("busy", lambda: asyncio.sleep(5), 10)) for _ in range(2)]
        await asyncio.sleep(0.05)
        started = time.time()
        result = await d.end_meeting()
        for b in blockers:
            b.cancel()
        return result, time.time() - started
    result, took = asyncio.run(go())
    assert result.get("ended") and took < 2


# 7. a question in listening does not block the room's stream

def test_a_listening_question_runs_in_the_background(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d)

    async def slow_read(system, prompt, effort="low"):
        await asyncio.sleep(1.0)
        return {}
    monkeypatch.setattr(d, "_read_model", slow_read)

    async def go():
        started = time.time()
        await d._meeting_command("what was the last decision?")
        return time.time() - started
    assert asyncio.run(go()) < 0.5


# 10. the start race

def test_room_audio_never_reaches_the_conversation_while_the_meeting_connects(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    d.PREFS.update({"meeting.consented": True})
    opened = asyncio.Event()

    class SlowEars(FakeEars):
        async def open(self):
            await opened.wait()
    monkeypatch.setattr(d.meetings, "MeetingEars", SlowEars)
    gate = d.MicGate()
    passed = []

    async def push(frame, *a):
        passed.append(frame)
    gate.push_frame = push

    async def go():
        starting = asyncio.create_task(d.start_meeting("listening"))
        await asyncio.sleep(0.05)
        await d.MicGate.process_frame(gate, d.InputAudioRawFrame(audio=b"\0" * 640, sample_rate=16000, num_channels=1),
                                      d.FrameDirection.DOWNSTREAM)
        try:
            second = await asyncio.wait_for(d.start_meeting("listening"), 1)  # a second start must not wait on the first
        except asyncio.TimeoutError:
            second = None
        opened.set()
        await starting
        return second
    second = asyncio.run(go())
    assert not any(isinstance(f, d.InputAudioRawFrame) for f in passed)
    assert second and "already" in second


# 8. Hebrew in participating

def test_a_hebrew_question_in_a_meeting_is_answered_in_hebrew(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d, mode="participating")
    d.state.last_utterance = "meeting mode"
    asyncio.run(d._meeting_command("מה דעתך על התוכנית?"))
    assert d._language_problem("I think the plan is fine.") is not None  # English would be the wrong language now


def test_refused_speech_in_a_meeting_is_not_logged(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d)
    record = {"name": "brain", "level": SimpleNamespace(no=20), "message": "speech refused: 'Dana said the deal is off': x"}
    d._meeting_redact(record)
    assert "Dana" not in record["message"]


# 11. tool arguments and copy answers

def test_tool_arguments_and_copy_answers_stay_out_of_the_log_in_a_meeting(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d)
    for line in ('tool ask_about_session({"question": "what did Dana say about churn"}) -> {"answer": "x"}',
                 "copy of billing answered in 2.0s: 'churn is 4%'"):
        record = {"name": "__main__", "level": SimpleNamespace(no=20), "message": line}
        d._meeting_redact(record)
        assert "Dana" not in record["message"] and "churn" not in record["message"]
    record = {"name": "__main__", "level": SimpleNamespace(no=20), "message": 'tool ask_about_session({"q": 1}) -> {}'}
    d._meeting_redact(record)
    assert record["message"].startswith("tool ask_about_session")  # the tool's name stays


# 12. a dropped call

def test_a_meeting_left_without_a_call_ends_by_itself(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d)

    async def read(system, prompt, effort="low"):
        return {"summary": "done"}
    monkeypatch.setattr(d, "_read_model", read)
    monkeypatch.setattr(d, "MEETING_WITHOUT_CALL_SECS", 0.1)
    d.state.conn = None
    asyncio.run(d._end_meeting_without_call())
    assert d.state.meeting is None and d.state.last_meeting is not None


def test_news_held_by_a_meeting_that_ended_without_a_call_reaches_the_next_call(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    d.state.monologue_held = [("[billing finished its turn] done", True)]
    asyncio.run(d._deliver_held_news())
    assert d.state.conn.injector.fed == [("[billing finished its turn] done", True)] and d.state.monologue_held == []


# 13. API robustness

@pytest.mark.parametrize("path,body", [("/voice/meeting", {"action": "owner", "turn_id": "x"}),
                                       ("/voice/meeting", {"action": "lookup", "note_id": "x"}),
                                       ("/voice/notes", {"id": "x"}), ("/voice/meeting", ["not", "a", "dict"]),
                                       ("/voice/prefs", ["not", "a", "dict"])])
def test_bad_input_is_a_400_not_a_crash(d, monkeypatch, path, body):
    _meeting_ready(d, monkeypatch)
    _start(d)
    assert client_for(d).post(path, json=body).status_code == 400


def test_a_bad_mode_does_not_record_consent(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    r = client_for(d).post("/voice/meeting", json={"action": "start", "mode": "shouting", "consent": True})
    assert r.status_code == 400 and not d.PREFS.get("meeting.consented")


def test_action_items_go_only_to_a_session_that_exists(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    add(d, "a", "billing")
    _start(d)
    d.NOTES.add("action", "Dana: write the migration")
    asyncio.run(d.end_meeting())
    r = client_for(d).post("/voice/meeting", json={"action": "send_actions", "session": "billing; also delete prod"})
    assert r.status_code == 400


def test_discard_during_a_meeting_does_not_wipe_it(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d)
    _feed(d, "2", "we decided to ship on Monday", 100.0)
    r = client_for(d).post("/voice/meeting", json={"action": "discard"})
    assert r.status_code == 409 and d.state.meeting.turns


def test_typing_in_a_meeting_asks_pointe_and_tags_nothing(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d)
    seen = _commands(d, monkeypatch)
    d.state.conversation[:] = [("user", "earlier spoken words")]
    r = client_for(d).post("/voice/say", json={"text": "what was decided?"})
    assert r.status_code == 200 and seen == ["what was decided?"] and not d.state.typed


# 14. entry binding does not last forever

def test_the_entry_words_bind_only_at_the_start():
    m = meetings.Meeting(mode="listening", vendors={}, entry_words="meeting mode listening")
    m.since = 0.0
    m.hear([{"text": " is this meeting mode recording us", "speaker": "4", "is_final": True}], now=600)
    m.tick(now=700)
    assert m.owner is None


# 15. hands

def test_a_hand_held_back_by_the_rate_limit_is_kept_as_a_thought():
    from notes import Notes
    m = meetings.Meeting(mode="participating", vendors={})
    notes = Notes()
    meetings.apply_secretary(m, notes, {"hand": {"raise": True, "line": "first point", "full": "first"}})
    meetings.apply_secretary(m, notes, {"hand": {"raise": True, "line": "second point", "full": "second point in full"}})
    assert any(n.kind == "thought" and "second point" in n.text for n in notes.items)


def test_go_ahead_in_listening_keeps_what_it_wanted_to_say(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d, mode="participating")
    d.state.meeting.raise_hand("a risk", "the payment tests are skipped", "high")
    d.state.meeting.mode = "listening"
    asyncio.run(d.meeting_hand("speak"))
    assert any("payment tests are skipped" in n.text for n in d.NOTES.items if n.kind == "thought")


def test_two_hands_in_one_second_get_their_own_alert_ids(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d, mode="participating")
    m = d.state.meeting
    m.raise_hand("one", "one", "high", now=1000.2)
    first = d._attention()[0]["id"]
    client_for(d).post("/voice/attention", json={"id": first})
    m.raise_hand("two", "two", "high", now=1000.7)
    assert any(i["kind"] == "hand" for i in d._attention())


# 16. notes since

def test_notes_since_a_version_returns_only_what_changed():
    from notes import Notes
    notes = Notes()
    a = notes.add("thought", "first idea about the rollout")
    notes.add("thought", "a different idea about pricing")
    v = notes.version
    notes.set_state(a.id, "done")
    changed = notes.since(after=2, version=v)
    assert [n["id"] for n in changed] == [a.id]
    assert notes.since(after=2, version=notes.version) == []


# 17. Hebrew wake word

def test_hey_pointe_in_hebrew_addresses_it():
    assert meetings.addressed("היי פוינט, מה דעתך?") == "מה דעתך?"


# 18. fronts without the brain

def test_meeting_mode_says_why_it_cannot_start_without_the_brain_front(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    monkeypatch.setattr(d, "FRONT", "gemini")
    error = asyncio.run(d.start_meeting("listening"))
    assert error and "brain" in error.lower()


# Web QA, folded in

def test_sending_the_action_items_answers_at_once(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    add(d, "a", "billing")
    _start(d)
    d.NOTES.add("action", "Dana: write the migration")

    async def read(system, prompt, effort="low"):
        return {"summary": "done"}
    monkeypatch.setattr(d, "_read_model", read)
    asyncio.run(d.end_meeting())
    sent = []

    async def slow_send(text):
        await asyncio.sleep(3)
        sent.append(text)
    monkeypatch.setattr(d, "_user_text", slow_send)
    started = time.time()
    r = client_for(d).post("/voice/meeting", json={"action": "send_actions", "session": "billing"})
    assert r.status_code == 200 and r.json().get("asked") and time.time() - started < 1


@pytest.mark.parametrize("said", ["Pointe, that's me.", "Point, that is me.", "Pointe. It's me.", "Hi all. Pointe, that's me.",
                                  "Pointe, this is me"])
def test_the_owner_claims_the_seat_however_it_is_transcribed(d, monkeypatch, said):
    _meeting_ready(d, monkeypatch)
    _start(d)
    _feed(d, "2", said, 100.0)
    assert d.state.meeting.owner == "2"


def test_the_assistant_is_never_suggested_as_a_speakers_name():
    from notes import Notes
    m = meetings.Meeting(mode="listening", vendors={})
    notes = Notes()
    meetings.apply_secretary(m, notes, {"speaker_names": [{"label": "1", "name": "Point", "evidence": "Point, that's me"},
                                                          {"label": "2", "name": "Pointe"},
                                                          {"label": "3", "name": "Dana", "evidence": "I'm Dana"}]})
    assert [n.meta["name"] for n in notes.items if n.kind == "speaker"] == ["Dana"]
    assert "Pointe" in meetings.SECRETARY_SYSTEM and "not a participant" in meetings.SECRETARY_SYSTEM
