"""Addressed speech (pointe/addressed.py, docs/features/addressed-speech.md): the microphone setting between Always on
and Push to talk, "Only when I say Pointe". A spoken turn is acted on only when its words address Pointe or a session
by name; anything else is side talk (a phone call, a colleague at the desk) and is dropped before it is remembered,
sent or taken for an answer to a request. Offline: no model, no network, no audio. The recorded clips are measured by
bench/addressed_bench.py; its committed result is checked here.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
import addressed  # noqa: E402
from test_orchestrator import _consent_setup, client_for, d, verdicts  # noqa: E402,F401  (d is the daemon fixture)
from test_turn_taking import _ears  # noqa: E402

SESSIONS = ["billing/main", "docs", "river-lantern", "harbor"]


# ---------- the rule ----------

@pytest.mark.parametrize("said, rest", [
    ("Pointe, what's billing doing?", "what's billing doing?"),
    ("Pointe what's billing doing", "what's billing doing"),
    ("Hey Pointe, tell docs to update the changelog.", "tell docs to update the changelog."),
    ("Okay, Pointe. Status.", "Status."),
    ("So, Pointe, is the build green?", "is the build green?"),
    ("pointe yes", "yes"),
    ("Pointe, yes.", "yes."),
    ("Yes, Pointe.", "Yes."),
    ("What's billing doing, Pointe?", "What's billing doing?"),
    ("Approve it, Pointe", "Approve it"),
    ("Point, what's billing doing?", "what's billing doing?"),  # the recognizer's commonest spelling of the name
    ("Hey point, what is docs doing", "what is docs doing"),
    ("Hey Pointe what is docs doing", "what is docs doing"),
    ("Pointy, stop.", "stop."),
    ("Pointe.", ""),
    ("Hey, Pointe?", ""),
    ("Point what's billing doing.", "what's billing doing."),  # a recognizer with no comma after the name
    ("Point yes.", "yes."),
    ("So point what changed since this morning?", "what changed since this morning?"),
    ("Hay point is the build green.", "is the build green."),
    ("Yes point.", "Yes."),
    ("No Pointe.", "No."),  # the name as it is spelled: "no point" in a lower case stays a phrase
    ("Give me the status point.", "Give me the status."),
    ("Approve it pointer.", "Approve it."),
    ("What's billing doing point?", "What's billing doing?"),
    ("פוינט, מה הסטטוס?", "מה הסטטוס?"),
    ("היי פוינט מה קורה עם billing", "מה קורה עם billing"),
])
def test_words_that_address_pointe_are_taken_with_the_name_off(said, rest):
    got = addressed.address(said, SESSIONS)
    assert got is not None and got.who == "pointe", said
    assert got.rest == rest


@pytest.mark.parametrize("said, who", [
    ("Billing, run the tests again.", "billing/main"),
    ("billing main, are you done?", "billing/main"),
    ("Docs: update the changelog", "docs"),
    ("Tell docs to update the changelog.", "docs"),
    ("Ask river lantern whether the retry budget is five.", "river-lantern"),
    ("Okay, tell billing to open the pull request.", "billing/main"),
    ("Switch to harbor.", "harbor"),
    ("Hey harbor, what's the status?", "harbor"),
    ("Billing run the tests again.", "billing/main"),  # no comma, and an order
    ("Billing are you done with the retry fix?", "billing/main"),
    ("Dogs, what did you change?", "docs"),  # one letter off, where a name is called
    ("Harbour, open a pull request.", "harbor"),  # another spelling of the name
    ("Tell Harbour to rebase on Maine.", "harbor"),
    ("Switch the harbour.", "harbor"),
])
def test_words_that_address_a_session_by_name_are_taken_whole(said, who):
    got = addressed.address(said, SESSIONS)
    assert got is not None and got.who == who, said
    assert got.rest == said  # the name is what routes it


@pytest.mark.parametrize("said", [
    "Yes.", "No.", "Okay.", "Yeah, go ahead.", "Stop.",
    "Shall we hear from marketing first?",
    "Well, we need to think about how it's going to look different.",
    "The point is we're marketing to guys as much as to women.",
    "Point taken.", "Point of order, the battery is in the back.", "That's a good point.", "My point, exactly.",
    "I'll point it out to them on Thursday.", "At this point, yes.", "Point is, it works.", "Pointe is a ballet word.",
    "I sent the docs to the client yesterday.", "The billing department called again.",
    "Can you send me the docs?", "We should tell billing about the refund.", "I'll ask the docs team tomorrow.",
    "What's the status of the harbor project, John?",
    "So I told docs it was fine.",
    "What's the point?", "That's the whole point.", "I see your point.", "You've made your point.", "There's no point.",
    "It's beside the point.", "We'll get to that at some point.", "That's not the point.", "He has a point.",
    "Point one, the battery. Point two, the case.", "Point me to the right folder.", "Point number three is the price.",
    "We need one more data point.", "That's a fair point.", "It's the boiling point.", "Docs were out of date again.", "Dogs are not allowed in here.",
    "Harbor is the name of the town.",
    "Tell Doug to call me back.", "Ask him, he knows.", "Tell the bank I'll be late.",
    "", "   ", "Mm-hmm.",
])
def test_side_talk_addresses_nobody(said):
    assert addressed.address(said, SESSIONS) is None, said


def test_a_session_whose_name_is_an_everyday_word_needs_the_comma_or_the_verb():
    assert addressed.address("Docs are in the shared drive.", SESSIONS) is None
    assert addressed.address("Billing was wrong last month.", SESSIONS) is None
    assert addressed.address("Docs, are you done?", SESSIONS).who == "docs"


def test_the_setting_is_between_always_on_and_push_to_talk():
    import prefs

    assert prefs.SCHEMA["microphone"] == ("always", ("always", "addressed", "ptt"))
    assert addressed.MODE == "addressed" and addressed.COPY["setting"] == "Only when I say Pointe"


# ---------- the daemon ----------

def _call(d, monkeypatch, mode="addressed"):
    """A call's ears in the given microphone setting; returns (final, taken): say a final transcript, and the turns taken."""
    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection

    monkeypatch.setattr(d.PREFS, "values", {**d.PREFS.values, "microphone": mode})
    taken: list[str] = []
    ears = _ears(d, monkeypatch)

    async def utterance(text, typed=False):
        taken.append(text)
    monkeypatch.setattr(d, "on_user_utterance", utterance)

    async def push(frame, direction=None):
        pass
    monkeypatch.setattr(ears, "push_frame", push)
    monkeypatch.setattr(ears, "broadcast_interruption", lambda: asyncio.sleep(0))

    async def final(text):
        d.state.user_stopped_at = time.time()
        await d.SonioxEars.process_frame(ears, TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.05)
    return final, taken


def test_side_talk_is_not_a_turn_and_addressed_words_are(d, monkeypatch):
    from test_orchestrator import add

    add(d, "a", "billing/main")
    add(d, "b", "docs")

    async def run():
        final, taken = _call(d, monkeypatch)
        await final("Shall we hear from marketing first?")
        await final("I sent the docs to the client yesterday.")
        assert taken == [] and d.state.last_utterance != "I sent the docs to the client yesterday."
        await final("Pointe, what's billing doing?")
        assert taken == ["what's billing doing?"]
        await final("Tell docs to update the changelog.")
        assert taken[-1] == "Tell docs to update the changelog."
        return taken
    assert len(asyncio.run(run())) == 2
    assert not any("marketing" in line.get("text", "") for line in client_for(d).get("/voice/status").json()["talk"])


def test_always_on_takes_everything_as_before(d, monkeypatch):
    async def run():
        final, taken = _call(d, monkeypatch, mode="always")
        await final("Shall we hear from marketing first?")
        return taken
    assert asyncio.run(run()) == ["Shall we hear from marketing first?"]


def test_the_name_alone_opens_a_short_window_for_the_next_words(d, monkeypatch):
    async def run():
        final, taken = _call(d, monkeypatch)
        await final("Pointe.")
        assert taken == []
        await final("What's the status?")
        assert taken == ["What's the status?"]
        await final("And we need to think about the battery.")  # the window was that one turn
        assert taken == ["What's the status?"]
        await final("Pointe?")
        d.state.addressed_until = time.time() - 1  # the window ran out
        await final("Never mind, I'll call them back.")
        return taken
    assert asyncio.run(run()) == ["What's the status?"]


@pytest.mark.parametrize("said, answered", [("Yes.", False), ("Go ahead.", False), ("No.", False), ("Pointe, yes.", True), ("Yes, Pointe.", True)])
def test_a_yes_from_side_talk_approves_nothing(d, monkeypatch, said, answered):
    active, posts = _consent_setup(d, monkeypatch)

    async def run():
        monkeypatch.setattr(d.PREFS, "values", {**d.PREFS.values, "microphone": "addressed"})
        heard: list[str] = []

        async def answer(text, deny_only=False):
            heard.append(text)
        monkeypatch.setattr(d, "_answer_permission", answer)
        resumed: list[float] = []

        async def resume_cut(since):
            resumed.append(since)
        d.state.conn.injector.resume_cut = resume_cut  # the real injector's: a voice cut by side talk goes on
        from pipecat.frames.frames import TranscriptionFrame
        from pipecat.processors.frame_processor import FrameDirection

        ears = _ears(d, monkeypatch)
        monkeypatch.setattr(ears, "push_frame", lambda frame, direction=None: asyncio.sleep(0))
        monkeypatch.setattr(ears, "broadcast_interruption", lambda: asyncio.sleep(0))
        d.state.user_stopped_at = time.time()
        await d.SonioxEars.process_frame(ears, TranscriptionFrame(text=said, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.05)
        return heard
    heard = asyncio.run(run())
    assert bool(heard) == answered, heard
    if answered:
        assert d.permission_answer(heard[-1]) == "allow"


def test_the_journal_gets_the_length_of_side_talk_never_its_words(d, monkeypatch):
    lines: list[str] = []
    sink = d.logger.add(lambda m: lines.append(m.record["message"]), level="INFO")

    async def run():
        final, _ = _call(d, monkeypatch)
        await final("My salary is forty two thousand and the card number is four five three two.")
    try:
        asyncio.run(run())
    finally:
        d.logger.remove(sink)
    assert any(line.startswith("not addressed:") for line in lines)
    assert not any("salary" in line or "forty" in line for line in lines), lines


def test_a_brain_dump_a_hold_and_a_challenge_hear_everything_once_started(d, monkeypatch):
    async def run():
        final, taken = _call(d, monkeypatch)
        d.state.hold = d.turns.Hold(since=time.time(), said=[], last_at=time.time())
        await final("So the checkout keeps timing out.")
        said = list(d.state.hold.said)
        d.state.hold = None
        return said
    assert asyncio.run(run()) == ["So the checkout keeps timing out."]


def test_status_says_the_mode_and_the_setting_saves(d, monkeypatch):
    monkeypatch.setattr(d.PREFS, "values", dict(d.PREFS.values))
    c = client_for(d)
    assert c.post("/voice/prefs", json={"microphone": "addressed"}).status_code == 200
    s = c.get("/voice/status").json()
    assert s["ptt"]["mode"] == "addressed" and s["ptt"]["open"] is False
    assert c.post("/voice/prefs", json={"microphone": "sometimes"}).status_code in (400, 422)


def test_the_recognizer_is_told_the_name_only_in_this_mode(d, monkeypatch):
    monkeypatch.setattr(d.PREFS, "values", {**d.PREFS.values, "microphone": "addressed"})
    assert "Pointe" in d._recognition_terms({})
    monkeypatch.setattr(d.PREFS, "values", {**d.PREFS.values, "microphone": "always"})
    assert "Pointe" not in d._recognition_terms({})


# ---------- the measured acceptance ----------

# An addressed clip the rule did not take, by ears: each one a name the recognizer wrote as another word. Listed so
# that a new miss fails, and so that the gap is on the page and not hidden: 50 of 50 on Pointe's default ears, 48 of 50
# on the local ones.
KNOWN_MISSES = {
    "soniox": {},
    "whisper": {"addressed.30.ff_siwis": "'No, Pointe.' was heard as 'No point.', which is also a phrase",
                "addressed.36.hm_omega": "docs was heard as darks"},
}


@pytest.mark.parametrize("ears, file", [("soniox", "addressed_heard.soniox.jsonl"), ("whisper", "addressed_heard.whisper.jsonl")])
def test_on_the_recorded_clips_side_talk_is_acted_on_zero_times(ears, file):
    """bench/addressed_bench.py: 50 clips of people talking in a meeting (AMI Meeting Corpus, CC BY 4.0) and 50 lines
    said to Pointe or a session, heard by a recognizer Pointe ships and judged by addressed.address. The committed
    transcripts are judged again here, so a change to the rule that breaks this fails without the audio."""
    rows = [json.loads(line) for line in (ROOT / "bench" / file).read_text().splitlines()]
    side = [r for r in rows if r["kind"] == "side"]
    aimed = [r for r in rows if r["kind"] == "addressed"]
    assert len(side) == 50 and len(aimed) == 50 and {r["ears"] for r in rows} == {ears}
    assert all(r["heard"].strip() for r in rows), "every clip was heard as some words"
    assert all(r["source"].startswith("AMI Meeting Corpus, CC BY 4.0") for r in side), "the corpus is named on every row from it"
    assert [r["clip"] for r in side if addressed.address(r["heard"], r["sessions"]) is not None] == [], "side talk acted on"
    missed = [r["clip"] for r in aimed if addressed.address(r["heard"], r["sessions"]) is None]
    assert missed == sorted(KNOWN_MISSES[ears]), f"addressed clips not taken on {ears}"
    assert len(aimed) - len(missed) == {"soniox": 50, "whisper": 48}[ears]
