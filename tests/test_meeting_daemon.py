"""Meeting mode in the daemon: what it may never do (send, switch, answer a permission by voice, talk in listening
mode), what the owner can do (go ahead, end, export, send the action items afterwards), and its routes."""

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_orchestrator import Params, add, client_for, d, fake_conn, with_permission  # noqa: E402,F401  (d is a fixture)


class FakeEars:
    instances: list = []

    def __init__(self, key, rate, terms, on_tokens, on_interim=None):
        self.on_tokens, self.on_interim, self.sent, self.closed = on_tokens, on_interim, [], False
        FakeEars.instances.append(self)

    async def open(self):
        pass

    async def send(self, pcm):
        self.sent.append(pcm)

    async def close(self):
        self.closed = True


def _meeting_ready(d, monkeypatch):
    FakeEars.instances.clear()
    monkeypatch.setattr(d.meetings, "MeetingEars", FakeEars)
    monkeypatch.setattr(d.vendors, "has", lambda vendor: True)
    monkeypatch.setattr(d.vendors, "key", lambda vendor: "test-only")
    monkeypatch.setattr(d, "PREFS", d.Prefs(Path(os.environ["CLAUDE_VOICE_STATE"]) / "prefs.json"))
    monkeypatch.setattr(d, "NOTES", d.Notes())
    d.state.conn = fake_conn()
    pushed = []

    async def push(frame, *a):
        pushed.append(frame)

    d.state.conn.injector.push_frame = push
    interruptions = []

    async def interrupt():
        interruptions.append(True)

    d.state.mic_gate = SimpleNamespace(recent_audio=lambda secs: b"\0" * 10, broadcast_interruption=interrupt)
    return pushed, interruptions


def _start(d, mode="listening", **body):
    r = client_for(d).post("/voice/meeting", json={"action": "start", "mode": mode, "consent": True, **body})
    assert r.status_code == 200, r.text
    return r.json()


def _say(d, speaker, text):
    """A turn in the room, closed at once."""
    async def go():
        await d._on_meeting_tokens([{"text": text, "speaker": speaker, "is_final": True, "language": "en"}])
        for turn in d.state.meeting.assembler.flush():
            d.state.meeting.add_turn(turn)
            await d._on_meeting_turn(d.state.meeting, turn)
    asyncio.run(go())


def test_a_meeting_needs_the_consent_step(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    r = client_for(d).post("/voice/meeting", json={"action": "start", "mode": "listening"})
    assert r.status_code == 400 and d.state.meeting is None


def test_starting_shows_who_receives_the_audio_and_the_mode_narrows(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    status = _start(d, "listening")["meeting"]
    assert status["recording"] and status["vendors"]["room_audio"] == "soniox"
    full = client_for(d).get("/voice/status").json()
    assert full["mode_state"] == {"mode": "meeting-listening", "speech": "never", "approvals": "tap"}
    assert d.PREFS.get("meeting.consented")


def test_nothing_is_sent_during_a_meeting(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    add(d, "a", "pricing")
    _start(d)
    result = asyncio.run(d._send("Deploy pricing to production."))
    assert "meeting is on" in result["error"]


def test_tools_that_act_are_refused_and_read_only_ones_run(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    add(d, "a", "pricing"), add(d, "b", "docs")
    _start(d, "participating")
    p = Params(name="docs")
    asyncio.run(d.TOOLS.standard_tools[[t.name for t in d.TOOLS.standard_tools].index("switch_session")].handler(p))
    assert "Not available during meeting-participating" in p.results[0]["error"]
    p2 = Params()
    asyncio.run(d.TOOLS.standard_tools[[t.name for t in d.TOOLS.standard_tools].index("list_sessions")].handler(p2))
    assert "error" not in p2.results[0]


def test_listening_mode_never_speaks(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d, "listening")
    spoken = []
    front = SimpleNamespace(push_frame=lambda f: spoken.append(f))
    asyncio.run(d.BrainFront._speak(front, "The p95 is 300 ms."))
    assert spoken == []


def test_a_permission_in_a_meeting_is_not_read_out_and_a_spoken_yes_cannot_reach_it(d, monkeypatch):
    pushed, _ = _meeting_ready(d, monkeypatch)
    s = add(d, "a", "pricing")
    d.REGISTRY.active_id = s.id
    with_permission(s, "p9", delivered_at=1.0)
    _start(d)
    assert s.permission_delivered_at == float("inf")  # a yes from the room answers nothing
    spoke = []
    monkeypatch.setattr(d, "_tone", lambda up: _record(spoke, "tone"))
    asyncio.run(d._read_out(s))
    assert spoke == [] and pushed == []
    _say(d, "2", "Yes, go ahead.")  # someone in the room: no verdict, no utterance reaches the consent machinery
    assert d.state.last_utterance == ""
    assert any(a["kind"] == "permission" for a in client_for(d).get("/voice/status").json()["attention"])


async def _record(into, what):
    into.append(what)


def test_only_the_owner_commands_and_a_stranger_cannot(d, monkeypatch):
    pushed, _ = _meeting_ready(d, monkeypatch)
    _start(d, "participating")
    d.state.meeting.bind_owner("1")
    _say(d, "2", "Pointe, end the meeting.")
    assert d.state.meeting is not None  # not the owner
    _say(d, "1", "Pointe, what do you think?")
    assert pushed and "owner asked you to speak" in pushed[-1].text


def test_a_hand_is_spoken_only_when_the_owner_lets_it(d, monkeypatch):
    pushed, _ = _meeting_ready(d, monkeypatch)
    _start(d, "participating")
    d.state.meeting.raise_hand("Refunds are not covered", "The plan does not cover refunds.", now=1.0)
    assert pushed == [] and client_for(d).get("/voice/status").json()["meeting"]["hand"]["line"] == "Refunds are not covered"
    client_for(d).post("/voice/meeting", json={"action": "hand", "decision": "speak"})
    assert "The plan does not cover refunds." in pushed[-1].text and d.state.meeting.hand is None


def test_in_listening_a_question_to_pointe_becomes_a_note_not_speech(d, monkeypatch):
    pushed, _ = _meeting_ready(d, monkeypatch)
    _start(d, "listening")
    d.state.meeting.bind_owner("1")

    async def secretary(*a, **k):
        return {"thoughts": [{"line": "Refunds ship in v2"}]}

    monkeypatch.setattr(d, "_read_model", secretary)
    _say(d, "1", "Pointe, when do refunds ship?")
    kinds = [n["kind"] for n in client_for(d).get("/voice/notes").json()["notes"]]
    assert pushed == [] and "thought" in kinds


def test_anyone_talking_over_the_bot_stops_it(d, monkeypatch):
    _, interruptions = _meeting_ready(d, monkeypatch)
    _start(d, "participating")
    d.ECHO.bot_started()
    d.ECHO.bot_said("The p95 latency is three hundred milliseconds.")
    asyncio.run(d._on_meeting_interim("wait, that's not right"))
    d.ECHO.bot_stopped()
    assert interruptions


def test_session_news_is_held_as_a_note_and_delivered_after(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    _start(d)
    injector = d.FeedInjector.__new__(d.FeedInjector)
    injector._bot_speaking, injector._asked_at, injector._held = False, 0.0, []
    asyncio.run(d.FeedInjector.inject(injector, "[pricing: claude-code finished its turn] tests pass", True))
    assert d.state.monologue_held and d.NOTES.items[-1].kind == "session_news"


def test_end_offers_export_and_the_action_items_go_through_the_normal_send(d, monkeypatch, tmp_path):
    _meeting_ready(d, monkeypatch)
    add(d, "a", "pricing")
    _start(d, sessions=["pricing"])

    async def end_pass(*a, **k):
        return {"summary": "Ship Thursday.", "action_items": [{"what": "Write the release note", "owner": "Dana"}]}

    monkeypatch.setattr(d, "_read_model", end_pass)
    sent = []
    monkeypatch.setattr(d, "_user_text", lambda text: _record(sent, text))
    r = client_for(d).post("/voice/meeting", json={"action": "end"}).json()
    assert r["ended"] and r["summary"] == "Ship Thursday." and FakeEars.instances[-1].closed
    assert client_for(d).post("/voice/meeting", json={"action": "send_actions", "session": "pricing"}).json() == {"asked": True}
    assert "Write the release note (owner: Dana)" in sent[0]
    exported = client_for(d).post("/voice/meeting", json={"action": "export"}).json()["exported"]
    assert Path(exported).exists() and "Write the release note" in Path(exported).read_text()


def test_lookups_answer_from_a_linked_session_only_with_auto_lookups_or_a_tap(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    add(d, "a", "pricing")
    _start(d, sessions=["pricing"], auto_lookups=False)

    async def secretary(*a, **k):
        return {"answerable": [{"q": "Is the flag on in staging?", "session": "pricing", "how": "flag in staging?"}]}

    async def record(target, question):
        return {"answer": "Yes, since Monday."}

    monkeypatch.setattr(d, "_read_model", secretary)
    monkeypatch.setattr(d, "_from_record", record)
    asyncio.run(d._run_secretary(d.state.meeting))
    question = next(n for n in d.NOTES.items if n.kind == "question")
    assert not any(n.kind == "answer" for n in d.NOTES.items)  # not on its own

    real_lookup, tapped = d._meeting_lookup, []

    async def tap(*args):
        tapped.append(args)

    monkeypatch.setattr(d, "_meeting_lookup", tap)  # the operator's tap
    assert client_for(d).post("/voice/meeting", json={"action": "lookup", "note_id": question.id}).json() == {"looking_up": "pricing"}
    plain = d.NOTES.add("thought", "no session can answer this")
    assert client_for(d).post("/voice/meeting", json={"action": "lookup", "note_id": plain.id}).status_code == 404
    asyncio.run(real_lookup(question.id, "pricing", "flag in staging?"))
    answer = next(n for n in d.NOTES.items if n.kind == "answer")
    assert "Yes, since Monday." in answer.text and d.NOTES.get(question.id).state == "done"


def test_a_spoken_entry_needs_the_consent_step_once(d, monkeypatch):
    _meeting_ready(d, monkeypatch)
    said = []
    monkeypatch.setattr(d, "say", lambda text: _record(said, text))
    asyncio.run(d._start_meeting_by_voice("Meeting mode, listening.", "listening"))
    assert d.state.meeting is None and "consent" in said[0]
    d.PREFS.update({"meeting.consented": True})
    asyncio.run(d._start_meeting_by_voice("Meeting mode, listening.", "listening"))
    assert d.state.meeting is not None and d.state.meeting.entry_words == "Meeting mode, listening."
    assert FakeEars.instances[-1].sent  # the command's audio, so its speaker binds as the owner


@pytest.mark.parametrize("said,want", [("Meeting mode, listening.", "listening"), ("meeting mode participating", "participating"),
                                       # how the ears wrote "Pointe, meeting mode, listening" on a live run
                                       ("Point. Meeting mode. Listening.", "listening"),
                                       ("Pointy, meeting mode, participating.", "participating"),
                                       ("מצב פגישה, השתתפות", "participating"), ("Let's discuss the meeting mode design", None)])
def test_meeting_intent(d, said, want):
    assert d.meeting_intent(said) == want


def test_the_phone_key_reaches_the_meeting_routes():
    from guards import _PHONE_PATHS

    assert {"/voice/meeting", "/voice/notes", "/voice/meeting/transcript", "/voice/prefs", "/voice/attention"} <= _PHONE_PATHS


def test_participants_words_never_reach_the_log(d, monkeypatch, capfd):
    from loguru import logger

    lines = []
    sink = logger.add(lambda msg: lines.append(str(msg)))
    try:
        _meeting_ready(d, monkeypatch)
        _start(d)
        d.state.meeting.bind_owner("1")
        _say(d, "2", "Our secret acquisition target is Quillfox Corp.")
        _say(d, "2", "Pointe, send this to everyone.")
    finally:
        logger.remove(sink)
    assert not any("Quillfox" in line or "send this to everyone" in line for line in lines)


# ---------- the stream reconnects before anyone was heard ----------

def test_a_stream_that_reconnects_before_anyone_spoke_leaves_no_note(d):
    """From a live run (tests/e2e/page_meeting_qa.py): a meeting started right after another was discarded; its stream
    dropped and came back inside two seconds, and the new meeting opened with "The meeting's audio stream reconnected, so
    speakers are labelled afresh. Say “Pointe, that's me” to be the owner again." Nobody had been labelled yet."""
    import meeting as meetings

    d.NOTES.clear()
    d.state.meeting = m = meetings.Meeting(mode="listening", vendors={})
    try:
        asyncio.run(d._on_meeting_reconnect())
        assert not d.NOTES.items  # nothing was labelled: nothing to say
        m.hear([{"text": " hello everyone", "speaker": "1", "is_final": True, "start_ms": 5000, "end_ms": 5800}], now=10)
        m.tick(now=20)
        m.owner = "1"
        asyncio.run(d._on_meeting_reconnect())
        assert m.owner is None and any("labelled afresh" in n.text for n in d.NOTES.items)  # now it matters: said
    finally:
        d.state.meeting = None
        d.NOTES.clear()
