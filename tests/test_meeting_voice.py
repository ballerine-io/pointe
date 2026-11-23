"""Meeting mode by voice alone, the way a demo runs it: "Pointe, join in" switches to participating (and "just listen"
back), a question that names a session is looked up in a read-only copy of it and answered aloud in participating,
and after the end "send the action items to billing" is read back and sent only on the owner's yes.

uv run --locked pytest -q tests/test_meeting_voice.py
"""

import asyncio
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import meeting as m  # noqa: E402
from test_meeting_daemon import FakeEars, _meeting_ready, _say, _start  # noqa: E402
from test_orchestrator import add, client_for, d  # noqa: E402,F401  (d is a fixture)


# ---------- switching mode by voice ----------

@pytest.mark.parametrize("said,mode", [
    ("Pointe, join in.", "participating"), ("Pointe, participate.", "participating"),
    ("Pointe, you can participate now.", "participating"), ("Pointe, please join in", "participating"),
    ("Pointe, switch to participating mode.", "participating"), ("Pointe, start participating.", "participating"),
    ("Pointe, join the conversation.", "participating"), ("Pointe, participating mode.", "participating"),
    ("Pointe, just listen.", "listening"), ("Pointe, go back to listening.", "listening"),
    ("Pointe, listening mode.", "listening"), ("Pointe, stop participating.", "listening"),
    ("Pointe, switch to listening mode please.", "listening"), ("Pointe, only listen for now.", "listening"),
    ("פוינט, תשתתף", "participating"), ("פוינט, מצב השתתפות", "participating"),
    ("פוינט, רק תקשיב", "listening"), ("פוינט, מצב הקשבה", "listening"),
])
def test_the_owner_switches_the_meeting_mode_by_voice(said, mode):
    assert m.command(m.addressed(said)) == ("mode", {"mode": mode})


@pytest.mark.parametrize("said", [
    "Pointe, should you join in?", "Pointe, can Dana participate in the review?", "Pointe, what do you think?",
    "Pointe, who is listening to the customers?", "Pointe, jump in.", "Pointe, are you listening?"])
def test_a_question_about_joining_or_listening_is_not_a_switch(said):
    assert m.command(m.addressed(said))[0] != "mode"


def test_join_in_switches_a_listening_meeting_to_participating_and_back(d, monkeypatch):
    pushed, _ = _meeting_ready(d, monkeypatch)
    _start(d, "listening")
    d.state.meeting.bind_owner("1")
    _say(d, "1", "Pointe, join in.")
    status = client_for(d).get("/voice/status").json()
    assert status["meeting"]["mode"] == "participating" and status["mode_state"]["mode"] == "meeting-participating"
    assert not any("You asked" in n.text for n in d.NOTES.items)  # a switch, not a question written down
    d.state.meeting.raise_hand("Refunds are not covered", "The plan does not cover refunds.", now=1.0)
    _say(d, "1", " Pointe, just listen.")  # Soniox's tokens carry their leading space
    assert d.state.meeting.mode == "listening" and d.state.meeting.hand is None  # as the route: listening has no hand


def test_another_speaker_cannot_switch_the_mode(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d, "listening")
    d.state.meeting.bind_owner("1")
    _say(d, "2", "Pointe, join in.")
    assert d.state.meeting.mode == "listening"


def test_meeting_mode_participating_said_mid_meeting_switches_it(d, monkeypatch):
    """The words that start a meeting, said again later by the owner, ask for that mode: not the entry replayed."""
    _meeting_ready(d, monkeypatch)
    _start(d, "listening")
    d.state.meeting.bind_owner("1")
    d.state.meeting.since -= 120
    _say(d, "1", "Pointe, meeting mode, participating.")
    assert d.state.meeting.mode == "participating"


def test_a_typed_join_in_switches_too(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d, "listening")
    client_for(d).post("/voice/meeting", json={"action": "ask", "text": "join in"})
    assert d.state.meeting.mode == "participating"


# ---------- a question about a session, answered from a read-only copy of it ----------

def _copy_answers(d, monkeypatch, answer="The retry limit is 5 attempts, with backoff capped at 10 minutes."):
    asked = []

    async def side_question(target, question):
        asked.append((target.name, question))
        return answer

    adapter = SimpleNamespace(side_questions=True, side_question=side_question)
    monkeypatch.setattr(d, "COPY_SESSIONS", True)
    monkeypatch.setattr(d.harnesses, "of", lambda s: adapter)
    monkeypatch.setattr(d, "_capabilities", lambda s: {"side_questions": True})
    return asked


async def _drain():
    for _ in range(20):
        await asyncio.sleep(0)


def _say_and_settle(d, speaker, text):
    async def go():
        await d._on_meeting_tokens([{"text": text, "speaker": speaker, "is_final": True, "language": "en"}])
        for turn in d.state.meeting.assembler.flush():
            d.state.meeting.add_turn(turn)
            await d._on_meeting_turn(d.state.meeting, turn)
        await _drain()
    asyncio.run(go())


def test_participating_a_question_naming_a_session_is_looked_up_and_answered_aloud(d, monkeypatch):
    pushed, _ = _meeting_ready(d, monkeypatch)
    add(d, "b", "billing/main"), add(d, "o", "docs/main")
    sent = []

    async def dispatch(*a, **k):
        sent.append(a)
        return True

    monkeypatch.setattr(d, "_dispatch", dispatch)
    asked = _copy_answers(d, monkeypatch)
    _start(d, "participating")  # started by voice: no session linked, and the owner may still ask any of them
    d.state.meeting.bind_owner("1")
    _say_and_settle(d, "1", "Pointe, what does billing's session say about the retry limit?")
    assert asked and asked[0][0] == "billing/main" and "retry limit" in asked[0][1]
    assert sent == []  # read-only: the live session gets nothing
    spoken = [f.text for f in pushed]
    assert spoken and "5 attempts" in spoken[-1] and "at most two sentences" in spoken[-1]
    assert d.state.meeting_may_speak_until > 0  # the answer has the room's one-reply window
    assert any(n.kind == "answer" and "5 attempts" in n.text for n in d.NOTES.items)


def test_listening_the_same_question_is_answered_in_the_notes_and_never_aloud(d, monkeypatch):
    pushed, _ = _meeting_ready(d, monkeypatch)
    add(d, "b", "billing/main")
    asked = _copy_answers(d, monkeypatch)
    _start(d, "listening")
    d.state.meeting.bind_owner("1")
    _say_and_settle(d, "1", "Pointe, what does billing's session say about the retry limit?")
    assert asked and pushed == []
    assert any(n.kind == "answer" and n.text.startswith("billing/main: ") for n in d.NOTES.items)


def test_a_question_from_another_speaker_looks_nothing_up(d, monkeypatch):
    pushed, _ = _meeting_ready(d, monkeypatch)
    add(d, "b", "billing/main")
    asked = _copy_answers(d, monkeypatch)
    _start(d, "participating")
    d.state.meeting.bind_owner("1")
    _say_and_settle(d, "2", "Pointe, what does billing's session say about the retry limit?")
    assert asked == [] and pushed == []


# ---------- after the end: the action items, sent by voice on a yes ----------

def _ended_meeting(d, monkeypatch, items=None):
    _meeting_ready(d, monkeypatch)
    add(d, "b", "billing/main"), add(d, "o", "docs/main")
    _start(d, "participating")

    async def end_pass(*a, **k):
        return {"summary": "Retries fail at night.", "action_items": items or [
            {"what": "Raise the retry limit to eight attempts", "owner": "Sam", "due": "Friday"},
            {"what": "Update the on-call runbook", "owner": "Dana"}]}

    monkeypatch.setattr(d, "_read_model", end_pass)
    assert client_for(d).post("/voice/meeting", json={"action": "end"}).json()["ended"]
    said, asked = [], []

    async def speak(text, *a):
        said.append(text)

    async def deliver(session, text):
        asked.append(f"{session.name}|{text}")
        return True

    async def brain(text):
        raise AssertionError("the confirmed action items go as read back, never rewritten by the model")

    d.state.front = SimpleNamespace(_speak=speak)
    monkeypatch.setattr(d, "FRONT", "brain")
    monkeypatch.setattr(d, "deliver", deliver)
    monkeypatch.setattr(d, "_user_text", brain)
    return said, asked


@pytest.mark.parametrize("said,session", [
    ("Send the action items to billing.", "billing"), ("send the meeting's action items to billing please", "billing"),
    ("Pointe, send those action items over to docs.", "docs"), ("Forward the action items to billing", "billing"),
    ("תשלח את המשימות מהפגישה לbilling", "billing")])
def test_send_the_action_items_words(said, session):
    assert m.send_actions_intent(said) == session


@pytest.mark.parametrize("said", ["Tell billing to send the action items to the customer.", "What were the action items?",
                                  "Send the release note to billing."])
def test_other_words_are_not_a_send_of_the_action_items(said):
    assert m.send_actions_intent(said) is None


def test_send_the_action_items_is_read_back_and_sent_on_the_yes(d, monkeypatch):
    said, asked = _ended_meeting(d, monkeypatch)
    assert asyncio.run(d._meeting_actions_words("Send the action items to billing.")) is True
    assert asked == []  # nothing yet: the read-back first
    assert said and "billing" in said[-1] and "Raise the retry limit to eight attempts" in said[-1] and said[-1].endswith("?")
    pending = client_for(d).get("/voice/status").json()["meeting"]
    assert pending["send_pending"]["session"] == "billing/main" and pending["send_pending"]["line"] == said[-1]
    assert pending["sent_to"] is None
    assert asyncio.run(d._meeting_actions_words("Yes.")) is True
    # From a live run: sent through the model, the items were rewritten ("(currently 5)") and the send check refused
    # the rewrite as "not what the user asked", after the owner had heard them and said yes. They go as read back.
    assert len(asked) == 1 and asked[0].startswith("billing/main|Action items from a meeting, sent by the user")
    assert "- Raise the retry limit to eight attempts (owner: Sam) (due: Friday)" in asked[0]
    assert "- Update the on-call runbook (owner: Dana)" in asked[0]
    assert "sent" in d.state.conn.injector.fed[-1][0]  # the voice says where they went
    status = client_for(d).get("/voice/status").json()["meeting"]
    assert status.get("send_pending") is None and status["sent_to"] == "billing/main"  # the end sheet shows where they went


def test_a_no_or_other_words_send_nothing(d, monkeypatch):
    said, asked = _ended_meeting(d, monkeypatch)
    asyncio.run(d._meeting_actions_words("Send the action items to billing."))
    assert asyncio.run(d._meeting_actions_words("No, wait.")) is True and asked == []
    asyncio.run(d._meeting_actions_words("Send the action items to billing."))
    assert asyncio.run(d._meeting_actions_words("What's the weather like?")) is False and asked == []
    assert asyncio.run(d._meeting_actions_words("Yes.")) is False and asked == []  # the read-back was dropped


def test_the_read_back_heard_back_is_not_a_yes(d, monkeypatch):
    said, asked = _ended_meeting(d, monkeypatch)
    asyncio.run(d._meeting_actions_words("Send the action items to billing."))
    d.state.heard_own_words = True
    asyncio.run(d._meeting_actions_words("Yes."))
    assert asked == []


def test_an_unknown_session_or_no_meeting_is_said_and_sends_nothing(d, monkeypatch):
    said, asked = _ended_meeting(d, monkeypatch)
    assert asyncio.run(d._meeting_actions_words("Send the action items to lantern.")) is True
    assert asked == [] and "lantern" in d.state.conn.injector.fed[-1][0]
    d.state.last_meeting = None
    assert asyncio.run(d._meeting_actions_words("Send the action items to billing.")) is True
    assert asked == []


def test_while_the_meeting_is_on_the_words_are_not_taken_here(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    add(d, "b", "billing/main")
    _start(d, "participating")
    assert asyncio.run(d._meeting_actions_words("Send the action items to billing.")) is False
    assert FakeEars.instances


def test_a_copy_the_brain_asked_in_participating_is_answered_aloud_too(d, monkeypatch):
    """The brain may still call ask_about_session for the owner's question: in participating its answer reaches the room,
    in its own one-reply window, instead of only a note after "I'm asking billing"."""
    pushed, _ = _meeting_ready(d, monkeypatch)
    billing = add(d, "b", "billing/main")
    _copy_answers(d, monkeypatch)
    _start(d, "participating")
    asyncio.run(d._ask_copy(billing, "What is the retry limit?"))
    assert any(n.kind == "answer" and "5 attempts" in n.text for n in d.NOTES.items)
    assert pushed and "5 attempts" in pushed[-1].text and d.state.meeting_may_speak_until > 0


def test_in_listening_a_copy_the_brain_asked_stays_a_note(d, monkeypatch):
    pushed, _ = _meeting_ready(d, monkeypatch)
    billing = add(d, "b", "billing/main")
    _copy_answers(d, monkeypatch)
    _start(d, "listening")
    asyncio.run(d._ask_copy(billing, "What is the retry limit?"))
    assert pushed == [] and any(n.kind == "answer" for n in d.NOTES.items)


def test_a_tap_on_send_shows_where_they_went_and_drops_a_spoken_read_back(d, monkeypatch):
    said, asked = _ended_meeting(d, monkeypatch)
    asyncio.run(d._meeting_actions_words("Send the action items to billing."))
    assert client_for(d).post("/voice/meeting", json={"action": "send_actions", "session": "docs/main"}).json() == {"asked": True}
    status = client_for(d).get("/voice/status").json()["meeting"]
    assert status["sent_to"] == "docs/main" and status["send_pending"] is None
    assert asyncio.run(d._meeting_actions_words("Yes.")) is False  # that yes no longer sends to billing


def test_the_entry_command_is_replayed_even_when_the_stream_opens_slowly(d, monkeypatch):
    """From a live run on a slow link: the meeting stream took ten seconds to open, the last 5 s replayed then were
    room noise, not "Pointe, meeting mode, listening", so the owner was never bound and "Pointe, join in" was ignored as
    a stranger's. The command's audio is taken when the command is heard."""
    _meeting_ready(d, monkeypatch)
    ring = {"audio": b"the entry command"}
    d.state.mic_gate.recent_audio = lambda secs: ring["audio"]

    async def slow_open(self):
        await asyncio.sleep(0.3)
        ring["audio"] = b"whatever came after"  # the room went on while the stream connected

    monkeypatch.setattr(FakeEars, "open", slow_open)
    d.PREFS.update({"meeting.consented": True})
    asyncio.run(d._start_meeting_by_voice("Pointe, meeting mode, listening.", "listening"))
    assert FakeEars.instances[-1].sent == [b"the entry command", b"whatever came after"]  # the command first, nothing lost


@pytest.mark.parametrize("secs", [5, 2.94871875, 0.00009375])  # the last two are odd byte counts
def test_recent_audio_is_whole_samples(d, secs):
    """From a live run: 2.948 s of room audio came out as an odd number of bytes, Soniox refused it ("must be a multiple
    of 2") and closed the meeting stream, which relabelled every speaker and lost the owner."""
    gate = d.MicGate()
    gate.ring.append(b"\x01\x02" * 100_000)
    assert len(gate.recent_audio(secs)) % 2 == 0


def test_a_yes_with_a_condition_sends_no_action_items(d, monkeypatch):
    """Mythos review AV-3: "yes, but not the runbook one" would send both items read back."""
    said, asked = _ended_meeting(d, monkeypatch)
    asyncio.run(d._meeting_actions_words("Send the action items to billing."))
    asyncio.run(d._meeting_actions_words("Yes, but only the first one."))
    assert asked == []


def test_a_yes_after_the_bot_said_something_else_sends_no_action_items(d, monkeypatch):
    said, asked = _ended_meeting(d, monkeypatch)
    asyncio.run(d._meeting_actions_words("Send the action items to billing."))
    d._bot_says("Billing is idle. Want me to check docs too?")  # the bot answered something else meanwhile
    asyncio.run(d._meeting_actions_words("Yes."))
    assert asked == []


FOUR = [{"what": "Raise the retry limit to eight attempts", "owner": "Sam", "due": "Friday"},
        {"what": "Update the on-call runbook", "owner": "Dana"},
        {"what": "Share the incident notes", "due": "Monday"},
        {"what": "Force-push the release branch and delete the old tags", "owner": "Lee", "due": "today"}]


def test_every_action_item_sent_was_read_back_with_its_owner_and_due(d, monkeypatch):
    """Mythos review AV-1. The read-back said three items "and 1 more", and the yes sent all four, the fourth unheard;
    an owner and a due date went in the text and were never said. Only what was read back is sent."""
    said, asked = _ended_meeting(d, monkeypatch, FOUR)
    asyncio.run(d._meeting_actions_words("Send the action items to billing."))
    line = said[-1]
    asyncio.run(d._meeting_actions_words("Yes."))
    assert len(asked) == 1, asked
    items = [x for x in asked[0].split("\n") if x.startswith("- ")]
    assert len(items) == 4, asked[0]
    for item in items:
        for part in [item[2:].split(" (")[0]] + re.findall(r"\((?:owner|due): ([^)]*)\)", item):
            assert part in line, (part, line)


def test_more_action_items_than_can_be_read_out_go_from_the_end_sheet(d, monkeypatch):
    many = [{"what": f"Task number {i}", "owner": "Sam"} for i in range(1, 8)]
    said, asked = _ended_meeting(d, monkeypatch, many)
    assert asyncio.run(d._meeting_actions_words("Send the action items to billing.")) is True
    assert d.state.pending_actions is None and asked == []
    assert "end sheet" in d.state.conn.injector.fed[-1][0]
    assert asyncio.run(d._meeting_actions_words("Yes.")) is False and asked == []
def test_a_meeting_started_by_voice_links_the_joined_sessions(d, monkeypatch):
    """From a live run: "Meeting mode, join in." linked no session, so "Pointe, look that up" always answered "Nothing to
    look up yet". The page and the apps let the user tick sessions; by voice, every joined one is linked."""
    _meeting_ready(d, monkeypatch)
    add(d, "s1", "pricing")
    add(d, "s2", "billing/main")
    d.PREFS.update({"meeting.consented": True})
    asyncio.run(d._start_meeting_by_voice("Pointe, meeting mode, join in.", "participating"))
    assert sorted(d.state.meeting.sessions) == ["billing/main", "pricing"]


def test_a_meeting_started_by_voice_that_names_a_session_links_that_one(d):
    add(d, "s1", "pricing")
    add(d, "s2", "billing/main")
    assert d._meeting_sessions_heard("Pointe, meeting mode with billing, join in.") == ["billing/main"]


def test_meeting_mode_by_voice_before_consent_says_the_fixed_line(d, monkeypatch):
    """From a live run: "Meeting mode, join in." before the consent step got "pricing is joined and idle... What would
    you like it to do?" from the model."""
    said = []

    async def say_exactly(line, tag):
        said.append(line)

    monkeypatch.setattr(d, "_say_exactly", say_exactly)
    d.PREFS.update({"meeting.consented": False})
    asyncio.run(d._start_meeting_by_voice("Meeting mode, join in.", "participating"))
    assert said == [d.MEETING_CONSENT_FIRST] and d.state.meeting is None
