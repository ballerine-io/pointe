"""Meeting mode's parts on their own: speaker turns, owner binding, addressed commands, the secretary's notes and hand,
the end-of-meeting record, the export; and the foundations it stands on (modes, notes, jobs, prefs)."""

import asyncio
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
import meeting as m  # noqa: E402
import modes  # noqa: E402
from jobs import JobRunner  # noqa: E402
from notes import Notes, mostly_same  # noqa: E402
from prefs import Prefs  # noqa: E402


def tok(text, speaker, final=True, lang="en"):
    return {"text": text, "speaker": speaker, "is_final": final, "language": lang}


# ---------- turns ----------

def test_a_speaker_change_closes_a_turn_and_a_pause_closes_the_last():
    turns = m.Turns()
    assert turns.feed([tok("Hello ", "1"), tok("everyone.", "1")], now=0.0) == []
    closed = turns.feed([tok(" Hi there.", "2")], now=0.5)
    assert [(t.speaker, t.text) for t in closed] == [("1", "Hello everyone.")]
    assert turns.tick(now=1.0) == []  # still within the pause
    assert [(t.speaker, t.text) for t in turns.tick(now=3.0)] == [("2", "Hi there.")]


def test_a_tiny_label_flip_inside_one_speakers_talk_is_folded_back():
    turns = m.Turns()
    turns.feed([tok("We should ship the pricing change ", "1")], now=0.0)
    turns.feed([tok("on ", "3")], now=0.3)  # Soniox briefly calls it someone else
    turns.feed([tok("Thursday after the review.", "1")], now=0.6)
    turns.flush()
    assert [(t.speaker, t.text) for t in turns.closed] == [("1", "We should ship the pricing change on Thursday after the review.")]


def test_provisional_and_marker_tokens_are_ignored():
    turns = m.Turns()
    turns.feed([tok("maybe", "1", final=False), tok("<end>", "1"), tok("Yes.", "1")], now=0.0)
    assert [t.text for t in turns.flush()] == ["Yes."]


# ---------- owner, commands ----------

def test_the_speaker_of_the_entry_command_becomes_the_owner():
    meeting = m.Meeting(mode="listening", vendors={}, entry_words="Meeting mode, listening.")
    meeting.hear([tok("Meeting mode, listening.", "2")], now=0.0)
    meeting.hear([tok("So, the agenda.", "1")], now=0.5)
    meeting.tick(now=5.0)
    assert meeting.owner == "2" and [t.who for t in meeting.turns] == ["You", "Speaker 1"]


def test_naming_a_speaker_relabels_their_turns():
    meeting = m.Meeting(mode="listening", vendors={})
    meeting.hear([tok("I'm Dana, I run billing.", "3")], now=0.0)
    meeting.tick(now=5.0)
    meeting.name_speaker("3", "Dana")
    assert meeting.turns[0].who == "Dana" and meeting.speakers()[0]["name"] == "Dana"


@pytest.mark.parametrize("said,kind", [
    ("Pointe, what do you think?", "think"), ("pointe go ahead", "go_ahead"), ("Pointe, look that up", "lookup"),
    ("Pointe, that's me", "me"), ("Pointe, speaker two is Dana", "name"), ("Pointe, end the meeting", "end"),
    ("Pointe, anything waiting?", "waiting"), ("Pointe, the agenda is pricing, then hiring", "agenda"),
    ("פוינט, מה אתה חושב?", "think"), ("פוינט, סיים את הפגישה", "end"), ("Pointe, how many users signed up?", "ask")])
def test_addressed_commands(said, kind):
    words = m.addressed(said)
    assert words is not None and m.command(words)[0] == kind


def test_a_sentence_that_only_mentions_pointe_is_not_addressed():
    assert m.addressed("We could use point estimates here") is None or m.addressed("We could use point estimates here") == ""
    assert m.addressed("Let's talk about the pointe deployment") is None
    assert m.command("speaker two is Dana")[1] == {"label": "2", "name": "Dana"}


# ---------- the secretary ----------

def _reply(**over):
    base = {"summary_delta": "", "thoughts": [], "open_questions": [], "answerable": [], "decisions": [],
            "action_items": [], "speaker_names": [], "hand": {"raise": False}}
    return {**base, **over}


def test_secretary_notes_are_typed_deduplicated_and_lookups_only_for_linked_sessions():
    meeting = m.Meeting(mode="listening", vendors={}, sessions=["pricing"])
    notes = Notes()
    lookups = m.apply_secretary(meeting, notes, _reply(
        thoughts=[{"line": "Nobody owns the rollback plan", "why": "risk"}],
        open_questions=[{"q": "What is the p95 latency of checkout?", "asked_by": "Speaker 2"}],
        answerable=[{"q": "Is the pricing flag on in staging?", "session": "pricing", "how": "is the flag on in staging"},
                    {"q": "What does HR think?", "session": "hr"}],
        action_items=[{"what": "Dana writes the migration note", "owner": "Dana", "due": "Friday"}],
        speaker_names=[{"label": "2", "name": "Dana", "evidence": "I'm Dana"}]))
    assert [n.kind for n in notes.items] == ["thought", "question", "action", "speaker", "question"]
    assert lookups == [{"note_id": notes.items[-1].id, "session": "pricing", "question": "is the flag on in staging"}]
    assert meeting.names == {}  # a suggested name is never applied without the owner
    m.apply_secretary(meeting, notes, _reply(thoughts=[{"line": "nobody owns the rollback plan yet"}]))
    assert len([n for n in notes.items if n.kind == "thought"]) == 1  # the same thought, updated in place


def test_listening_never_raises_a_hand_it_writes_the_thought():
    meeting, notes = m.Meeting(mode="listening", vendors={}), Notes()
    m.apply_secretary(meeting, notes, _reply(hand={"raise": True, "line": "The test plan misses refunds",
                                                   "full": "The test plan does not cover refunds."}))
    assert meeting.hand is None and notes.items[-1].kind == "thought"


def test_participating_raises_one_hand_at_a_time_unless_urgent():
    meeting, notes = m.Meeting(mode="participating", vendors={}), Notes()
    assert meeting.raise_hand("one", "one", now=100.0)
    assert not meeting.raise_hand("two", "two", now=150.0)  # within two minutes
    assert meeting.raise_hand("urgent", "urgent", urgency="high", now=160.0)
    assert meeting.hand.line == "urgent"


def test_the_end_record_and_export_keep_no_transcript_unless_asked(tmp_path):
    meeting, notes = m.Meeting(mode="listening", vendors={}, brief="Pricing rollout"), Notes()
    meeting.hear([tok("We ship Thursday.", "1")], now=0.0)
    meeting.tick(now=5.0)
    m.apply_end(meeting, notes, {"summary": "Ship Thursday.", "decisions": ["Ship Thursday"],
                                 "action_items": [{"what": "Write the release note", "owner": "Dana", "due": ""}]})
    path = m.export(meeting, notes, tmp_path, with_transcript=False)
    text = path.read_text()
    assert "Ship Thursday." in text and "Write the release note (owner: Dana)" in text and "We ship Thursday." not in text
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert "We ship Thursday." in m.export(meeting, notes, tmp_path, with_transcript=True).read_text()


def test_the_window_leaves_out_the_bots_own_voice():
    meeting = m.Meeting(mode="participating", vendors={})
    meeting.bot = "4"
    meeting.hear([tok("The p95 is 300 ms.", "4")], now=0.0)
    meeting.hear([tok("Thanks.", "1")], now=0.5)
    meeting.tick(now=5.0)
    assert "300 ms" not in meeting.window() and "Thanks." in meeting.window()
    assert all(s["label"] != "4" for s in meeting.speakers())


def test_the_secretary_runs_on_cadence_not_per_sentence():
    meeting = m.Meeting(mode="listening", vendors={})
    for i in range(8):
        meeting.hear([tok(f"line {i}.", str(i % 2 + 1))], now=float(i))
    meeting.tick(now=9.0)
    assert meeting.due(now=9.0)  # eight turns closed
    meeting.mark_read()
    assert not meeting.due(now=9.0)


def test_a_pause_in_the_room_lets_the_secretary_read_what_is_new():
    meeting = m.Meeting(mode="listening", vendors={})
    meeting.hear([tok("We skip the payment tests.", "1")], now=100.0)
    meeting.tick(now=102.0)
    assert not meeting.due(now=105.0)
    assert meeting.due(now=115.0)


def test_a_word_finalised_in_two_bursts_stays_one_word():
    turns = m.Turns()
    turns.feed([tok("Po", "1")], now=0.0)
    turns.tick(now=2.0)  # Soniox's finals arrived late: the turn closed mid-word
    turns.feed([tok("int, that's me.", "1")], now=2.5)
    assert [t.text for t in turns.flush()] == ["Point, that's me."]
    assert m.addressed(turns.closed[0].text) == "that's me."


def test_the_pause_that_closes_a_turn_is_measured_in_the_audio_when_soniox_gives_times():
    turns = m.Turns()
    turns.feed([{**tok("Ship it", "1"), "start_ms": 0, "end_ms": 600}], now=0.0)
    turns.feed([{**tok(" on Thursday.", "1"), "start_ms": 700, "end_ms": 1500}], now=3.0)  # arrived late, spoken at once
    assert len(turns.closed) == 0 and turns.flush()[0].text == "Ship it on Thursday."


# ---------- foundations ----------

def test_every_mode_only_narrows_plain_conversation():
    assert all(modes.narrows(mode) for mode in modes.ALL)
    wider = modes.Mode("wider", approvals="voice+tap", tools=None, holds_news=False, reads_out=True, speech="free")
    assert modes.narrows(wider)  # equal is allowed
    assert not modes.narrows(modes.CONVERSATION, base=modes.MEETING_LISTENING)  # conversation is wider than a meeting
    assert not modes.MEETING_LISTENING.allows_tool("send_to_claude_code") and modes.MEETING_LISTENING.allows_tool("speak")


def test_notes_since_returns_new_and_changed_notes():
    notes = Notes()
    a = notes.add("thought", "first")
    notes.add("question", "second?")
    assert [n["id"] for n in notes.since(1)] == [2]
    notes.set_state(a.id, "dismissed")
    assert {n["id"] for n in notes.since(2)} == {1}
    with pytest.raises(ValueError):
        notes.add("shout", "x")
    assert mostly_same("Nobody owns the rollback plan", "nobody owns the rollback plan yet")


def test_prefs_accept_only_known_settings_and_stay_private(tmp_path):
    prefs = Prefs(tmp_path / "prefs.json")
    assert prefs.get("meeting.default_mode") == "listening"
    prefs.update({"meeting.default_mode": "participating", "meeting.auto_lookups": True})
    assert Prefs(tmp_path / "prefs.json").get("meeting.default_mode") == "participating"
    assert stat.S_IMODE(os.stat(tmp_path / "prefs.json").st_mode) == 0o600
    for bad in ({"meeting.default_mode": "shouting"}, {"evil": 1}, {"meeting.auto_lookups": "yes"}):
        with pytest.raises(ValueError):
            prefs.update(bad)


def test_a_job_that_runs_out_of_time_returns_nothing():
    runner = JobRunner(concurrency=1)

    async def slow():
        await asyncio.sleep(1)

    async def quick():
        return 42

    assert asyncio.run(runner.run("slow", slow, timeout=0.05)) is None
    assert asyncio.run(runner.run("quick", quick, timeout=1)) == 42
    assert runner.stats() == {"running": 0, "done": 1, "failed": 1}
