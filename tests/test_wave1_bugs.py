"""Defects an independent bug hunt proved at 0defe50, each as the scenario that showed it. Ordered as fixed."""

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ptt  # noqa: E402
import meeting as meetings  # noqa: E402
from test_orchestrator import add, d, fake_conn, with_permission  # noqa: E402,F401  (d is a fixture)
from test_meeting_daemon import _meeting_ready, _start  # noqa: E402
from test_speaker import OTHER_HZ, OWNER_HZ, tone  # noqa: E402
from test_voice_lock import v  # noqa: E402,F401  (fixture: an enrolled voice lock on a fake model)

T0 = 1000.0


# ---------- 1. voice lock at Commands / Everything: a no from another voice still denies ----------

def _real_ears(d, monkeypatch):
    """SonioxEars with its real _take, so a final transcript reaches on_user_utterance."""
    from test_voice_lock import FrameDirection, InputAudioRawFrame, TranscriptionFrame, VADUserStartedSpeakingFrame, \
        VADUserStoppedSpeakingFrame
    ears = d.SonioxEars()

    async def noop(*_a, **_k):
        pass

    monkeypatch.setattr(ears, "broadcast_interruption", noop)
    monkeypatch.setattr(ears, "push_frame", noop)
    monkeypatch.setattr(ears, "create_task", lambda coro, name=None: asyncio.get_running_loop().create_task(coro))
    monkeypatch.setattr(d.FrameProcessor, "process_frame", lambda self, f, dirn: asyncio.sleep(0))

    async def utter(hz: float, text: str, secs: float = 2.0) -> None:
        down = FrameDirection.DOWNSTREAM
        await d.SonioxEars.process_frame(ears, VADUserStartedSpeakingFrame(), down)
        pcm = tone(hz, secs)
        for i in range(0, len(pcm), 640):
            await d.SonioxEars.process_frame(ears, InputAudioRawFrame(audio=pcm[i:i + 640], sample_rate=16000, num_channels=1), down)
        await d.SonioxEars.process_frame(ears, VADUserStoppedSpeakingFrame(), down)
        await d.SonioxEars.process_frame(ears, TranscriptionFrame(text=text, user_id="u", timestamp="t"), down)
    return utter


@pytest.mark.parametrize("lvl", ["commands", "everything"])
def test_a_no_from_another_voice_still_denies_at_commands_and_everything(d, v, monkeypatch, lvl):
    """Rule: a "no" from any voice counts (speaker.py: 'A "no" counts from anyone'). At Commands and Everything the
    intake gate drops the stranger's words before on_user_utterance sees them, so the pending tool call stays pending."""
    from test_orchestrator import _consent_setup, verdicts
    d.PREFS.update({"voice_lock": lvl})
    active, posts = _consent_setup(d, monkeypatch)
    utter = _real_ears(d, monkeypatch)

    async def resume_cut(since):
        pass

    d.state.conn.injector.resume_cut = resume_cut
    asyncio.run(utter(OTHER_HZ, "no, don't"))
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "deny"}], (verdicts(posts), active.permission_id)


def test_the_owners_no_and_a_strangers_no_at_approvals_deny_through_the_same_path(d, v, monkeypatch):
    from test_orchestrator import _consent_setup, verdicts
    d.PREFS.update({"voice_lock": "commands"})
    active, posts = _consent_setup(d, monkeypatch)
    utter = _real_ears(d, monkeypatch)

    async def resume_cut(since):
        pass

    d.state.conn.injector.resume_cut = resume_cut
    asyncio.run(utter(OWNER_HZ, "no, don't"))
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "deny"}]
    d.PREFS.update({"voice_lock": "approvals"})
    with_permission(active, "p2", delivered_at=1.0)
    asyncio.run(utter(OTHER_HZ, "no, don't"))
    assert verdicts(posts)[-1] == {"request_id": "p2", "behavior": "deny"}


# ---------- 2. push to talk: a press does not survive a microphone setting change ----------

def test_a_press_closes_when_the_microphone_leaves_push_to_talk():
    """Rule: in push to talk, room audio never reaches the conversation unless pressed. A press is open; the setting goes
    to "always" and back to "ptt". The clients forget their press on a mode change, so a press left open would pass
    audio with no thumb on it for up to 90 s. Only the switch-back tail (the sentence under way) may pass."""
    p = ptt.Ptt()
    assert p.press(T0)
    assert p.audio(640, "ptt", T0 + 0.1)
    assert p.tick("always", T0 + 1.0) == ["closed"], "the setting changed under the press: it ends"
    assert p.closed_why == "the microphone setting changed"
    assert p.audio(640, "always", T0 + 1.1)
    p.tick("ptt", T0 + 2.0)
    assert not p.open
    after_the_tail = T0 + 2.0 + ptt.TAIL_SECS + ptt.LINK_SLACK_SECS + 0.1
    assert not p.audio(640, "ptt", after_the_tail), "no press is held, so no audio may pass"


def test_the_daemon_closes_a_press_when_the_microphone_setting_leaves_push_to_talk(d, monkeypatch):
    """The same, through the daemon's prefs and gate: the setting changes with no release message."""
    monkeypatch.setattr(d, "PREFS", d.Prefs(Path(d.STATE_DIR) / "prefs-ptt.json"))
    d.PREFS.update({"microphone": "ptt"})
    d.state.ptt.reset()
    d.state.ptt.press(T0)
    assert d.state.ptt.audio(640, d.PREFS.get("microphone"), T0 + 0.5)
    d.PREFS.update({"microphone": "always"})
    assert d.state.ptt.audio(640, d.PREFS.get("microphone"), T0 + 1)
    d.PREFS.update({"microphone": "ptt"})
    d.state.ptt.tick(d.PREFS.get("microphone"), T0 + 2)
    assert not d.state.ptt.passes("ptt", T0 + 3)


# ---------- 3. a session's permission request (its exact command) is not put to the brain during a meeting ----------

def test_a_permission_request_during_a_meeting_is_not_told_to_the_brain(d, monkeypatch):
    """_ask_permission feeds the request text with respond=False, which inject() does not hold during a meeting; in
    participating the brain can then say the command into the room when the owner asks it anything."""
    pushed, _ = _meeting_ready(d, monkeypatch)
    monkeypatch.setattr(d, "FRONT", "brain")
    s = add(d, "s1", "pricing")
    d.REGISTRY.active_id = s.id
    _start(d, "participating")
    d.state.front = SimpleNamespace(brain=SimpleNamespace(busy=False), _speak=None)
    asyncio.run(d._put_permission(s, "p9", "Bash", "delete the build folder", '{"command": "rm -rf build"}'))
    told = [t for t, respond in d.state.conn.injector.fed if "rm -rf build" in t]
    assert not told, told


# ---------- 4. meeting, participating: a late reply to an earlier ask does not spend the new ask's window ----------

def test_a_late_reply_to_an_earlier_ask_is_not_spoken_in_the_new_asks_window(d, monkeypatch):
    """_meeting_speak opens one window per ask; BrainFront._speak closes it on the first speak, whichever ask that speech
    answers. A new "[the owner asked ...]" frame did not interrupt the brain's running turn (BrainFront interrupts only on
    text that does not start with "["), so the earlier answer, in the earlier language, went to the room and the answer
    to the new ask was held as "nobody asked"."""
    _meeting_ready(d, monkeypatch)
    _start(d, "participating")
    spoken, steps = [], []
    front, late = SimpleNamespace(), {}

    async def push_frame(frame, *a):
        spoken.append(frame.text)

    async def step(choice, instructions, messages, decls):
        steps.append(choice)
        if len(steps) == 1:  # the earlier ask: its answer is still being written when the new ask comes
            await late["gate"].wait()
        text = "I think closing the meeting now is fine." if len(steps) == 1 else "ההשקה ביום חמישי נראית מסוכנת בלי בדיקות."
        return d.vendors.Step(calls=[{"id": f"c{len(steps)}", "name": "speak", "args": {"text": text}}])

    monkeypatch.setattr(d.vendors, "step", step)
    front.push_frame = push_frame
    front.brain = d.make_brain(lambda text, rid=None: d.BrainFront._speak(front, text, rid))
    d.state.front = front

    async def go():
        late["gate"] = asyncio.Event()
        earlier = "[the owner asked you to speak in the meeting] should we close the meeting now?"
        await d._meeting_speak(earlier)
        first = asyncio.create_task(front.brain.turn(earlier))
        await asyncio.sleep(0.05)
        now = "[the owner asked you to speak in the meeting] מה דעתך על ההשקה?"
        await d._meeting_speak(now)
        late["gate"].set()  # the earlier answer arrives after the new ask
        await first
        await front.brain.turn(now)  # the frame _meeting_speak pushed starts this turn in the pipeline
    asyncio.run(go())
    assert spoken == ["ההשקה ביום חמישי נראית מסוכנת בלי בדיקות."], spoken


def test_a_failed_translation_is_not_spoken_into_a_meeting(d, monkeypatch):
    """_translate returned the English reply when the checker failed, silently: in a meeting the room then heard an
    English answer to a Hebrew question. Outside a meeting the reply still comes, as it was."""
    _meeting_ready(d, monkeypatch)

    async def down(*_a, **_k):
        raise RuntimeError("checker down")

    monkeypatch.setattr(d.vendors, "text", down)
    d.state.last_utterance = "מה דעתך על ההשקה?"
    assert asyncio.run(d._translate("The launch looks risky.")) == "The launch looks risky."
    _start(d, "participating")
    assert asyncio.run(d._translate("The launch looks risky.")) == ""


# ---------- 5. meeting: an unlabelled speaker ("?") is nobody, not the owner ----------

def test_an_unlabelled_speaker_is_nobody_not_the_owner():
    m = meetings.Meeting(mode="listening", vendors={})
    m.bind_owner("?")
    assert m.owner is None, "a speaker Soniox could not label must not become the owner"


def test_entry_words_from_an_unlabelled_speaker_do_not_bind_the_owner():
    m = meetings.Meeting(mode="listening", vendors={}, entry_words="meeting mode listening")
    now = m.since + 1
    m.hear([{"is_final": True, "text": " meeting mode listening", "speaker": None}], now)
    m.tick(now + 5)
    assert m.owner != "?"
    # otherwise a later unlabelled turn is the owner's: "Pointe, end the meeting" from anyone would end it
    m.hear([{"is_final": True, "text": " Pointe, end the meeting", "speaker": None}], now + 10)
    closed = m.tick(now + 15)
    assert closed and closed[0].who != "You"


def test_that_was_me_on_an_unlabelled_turn_is_refused(d, monkeypatch):
    from test_orchestrator import client_for
    _meeting_ready(d, monkeypatch)
    _start(d, "listening")
    m = d.state.meeting
    m.hear([{"is_final": True, "text": " the numbers are in", "speaker": None}], m.since + 1)
    turn = m.tick(m.since + 5)[0]
    r = client_for(d).post("/voice/meeting", json={"action": "owner", "turn_id": turn.id})
    assert r.status_code == 409 and m.owner is None, r.text


def test_that_s_me_from_an_unlabelled_speaker_is_refused_out_loud(d, monkeypatch):
    """Refusing "?" must not be silent: after a reconnect the owner's short claim can come back unlabelled, and the owner
    otherwise never learns why the seat stayed empty."""
    _meeting_ready(d, monkeypatch)
    _start(d, "participating")
    m = d.state.meeting
    for t in m.hear([{"is_final": True, "text": " Pointe, that's me.", "speaker": None}], m.since + 1) + m.tick(m.since + 5):
        asyncio.run(d._on_meeting_turn(m, t))
    assert m.owner is None
    assert any("say it again" in n.text.lower() for n in d.NOTES.items), [n.text for n in d.NOTES.items]


# ---------- 6. meeting: a Hebrew "tell me what you think" is a think command ----------

@pytest.mark.parametrize("said, kind", [("תגיד מה דעתך", "think"), ("tell us what you think", "think"),
                                        ("תגיד מה מחכה", "waiting"), ("go ahead and look that up", "lookup"),
                                        ("תגיד", "go_ahead"), ("go ahead", "go_ahead"), ("tell us", "go_ahead")])
def test_tell_us_what_you_think_is_a_think_command(said, kind):
    """_THINK lists "תגיד מה דעתך", but _GO_AHEAD ("^תגיד") was checked first, so it never matched."""
    assert meetings.command(said)[0] == kind


def test_hebrew_tell_me_what_you_think_in_participating_gets_an_answer(d, monkeypatch):
    pushed, _ = _meeting_ready(d, monkeypatch)
    _start(d, "participating")
    m = d.state.meeting
    m.owner = "1"
    asyncio.run(d._meeting_command("תגיד מה דעתך"))
    assert pushed, "the owner asked for an opinion and nothing was put to the brain (meeting_hand found no hand)"


# ---------- 7. meeting: "anything waiting?" asked in Hebrew is answered in Hebrew ----------

def test_waiting_asked_in_hebrew_is_answered_in_hebrew(d, monkeypatch):
    """_meeting_command("waiting") speaks a fixed English line and leaves state.last_utterance as it was, so the brain is
    told to speak the language of the words said before the meeting."""
    pushed, _ = _meeting_ready(d, monkeypatch)
    add(d, "s1", "pricing")
    d.state.last_utterance = "meeting mode participating"  # the spoken entry, in English
    _start(d, "participating")
    d.state.meeting.owner = "1"
    asyncio.run(d._meeting_command("מה מחכה"))
    assert pushed and "waiting" in pushed[-1].text.lower()
    assert "speak Hebrew" in d._brain_context(), d._brain_context().splitlines()[0]
    assert d._language_problem("Nothing is waiting on you.") is not None, "an English answer to a Hebrew ask is not corrected either"


# ---------- 8. meeting + voice lock: the entry command binds by the voiceprint, not the label ----------

def test_with_a_voiceprint_the_entry_words_in_another_voice_do_not_bind_the_owner(d, v, monkeypatch):
    """As built: "with a voiceprint and the lock on, a meeting turn in the owner's voice binds the owner label ...
    one source of truth: the voiceprint when there is one". Meeting.add_turn binds the entry speaker before any voice
    check, and _on_meeting_turn returns early for the entry turn, so another voice saying "meeting mode" is the owner."""
    d.PREFS.update({"voice_lock": "approvals"})
    m = meetings.Meeting(mode="listening", vendors={}, entry_words="meeting mode listening")
    d.state.meeting = m
    d.state.meeting_ears = SimpleNamespace(audio_between=lambda a, b: tone(OTHER_HZ, 2.0))
    now = m.since + 1
    turns = m.hear([{"is_final": True, "text": " meeting mode listening", "speaker": "2", "start_ms": 0, "end_ms": 2000}], now)
    turns += m.tick(now + 5)
    for t in turns:
        asyncio.run(d._on_meeting_turn(m, t))
    assert m.owner is None, f"bound {m.owner!r} from the entry words in a voice the voiceprint does not match"


def test_with_a_voiceprint_the_entry_words_in_the_owners_voice_bind_the_owner(d, v, monkeypatch):
    d.PREFS.update({"voice_lock": "approvals"})
    m = meetings.Meeting(mode="listening", vendors={}, entry_words="meeting mode listening")
    d.state.meeting = m
    d.state.meeting_ears = SimpleNamespace(audio_between=lambda a, b: tone(OWNER_HZ, 2.0))
    now = m.since + 1
    turns = m.hear([{"is_final": True, "text": " meeting mode listening", "speaker": "2", "start_ms": 0, "end_ms": 2000}], now)
    turns += m.tick(now + 5)
    for t in turns:
        asyncio.run(d._on_meeting_turn(m, t))
    assert m.owner == "2"


# ---------- 9. meeting + voice lock + reconnect: a strong voiceprint re-binds the owner on the label the echo took ----------

def _echo_then_claim(d, monkeypatch, hz):
    """After a reconnect the bot's echo closes first on the new stream, labelled "1:1"; then someone says "Pointe, that's
    me" under the same label (diarisation settles late), in a voice of the given pitch."""
    if d.VOICE.profiles.items:
        d.PREFS.update({"voice_lock": "approvals"})
    m = meetings.Meeting(mode="participating", vendors={})
    m.owner = "1"
    d.state.meeting = m
    m.stream_restarted()
    assert m.owner is None
    monkeypatch.setattr(d.ECHO, "speaking", True)  # ECHO.live
    monkeypatch.setattr(d.ECHO, "user_part", lambda text: "")
    now = time.time()
    echo = m.hear([{"is_final": True, "text": " the launch looks fine to me", "speaker": "1", "start_ms": 0, "end_ms": 1500}], now)
    echo += m.tick(now + 5)
    for t in echo:
        asyncio.run(d._on_meeting_turn(m, t))
    assert m.bot == "1:1"
    monkeypatch.setattr(d.ECHO, "user_part", lambda text: text)
    d.state.meeting_ears = SimpleNamespace(audio_between=lambda a, b: tone(hz, 2.0))
    claim = m.hear([{"is_final": True, "text": " Pointe, that's me.", "speaker": "1", "start_ms": 4000, "end_ms": 6000}], now + 10)
    claim += m.tick(now + 15)
    for t in claim:
        asyncio.run(d._on_meeting_turn(m, t))
    return m


def test_after_a_reconnect_the_voiceprint_rebinds_the_owner_even_on_the_label_the_echo_took(d, v, monkeypatch):
    """bind_owner refused the label the bot's echo took, although the voiceprint said it was the owner."""
    m = _echo_then_claim(d, monkeypatch, OWNER_HZ)
    assert m.owner == "1:1" and m.bot is None, "the voiceprint matched the owner, yet the seat stays empty"


def test_after_a_reconnect_another_voice_on_the_echos_label_does_not_take_the_seat(d, v, monkeypatch):
    m = _echo_then_claim(d, monkeypatch, OTHER_HZ)
    assert m.owner is None and m.bot == "1:1"


def test_without_a_voiceprint_that_s_me_on_the_label_the_echo_took_binds_the_owner(d, monkeypatch):
    """The same reconnect with the lock off (no voiceprint: labels decide). The claim passed the echo check, so its label
    is a person's; bind_owner refused it silently because the echo had taken it first (e2e meeting.py, flaky re-bind)."""
    monkeypatch.setattr(d, "PREFS", d.Prefs(Path(d.STATE_DIR) / "prefs-nolock.json"))
    m = _echo_then_claim(d, monkeypatch, OTHER_HZ)
    assert m.owner == "1:1" and m.bot is None


# ---------- 10. logs during a meeting: "repeat cut" is withheld ----------

def test_repeat_cut_log_line_is_withheld_during_a_meeting(d):
    d.state.meeting = SimpleNamespace(ending=False)
    record = {"message": "repeat cut: 'Dana said the pricing page goes live Thursday' -> 'Dana said the pricing page'",
              "name": "brain", "level": SimpleNamespace(no=20)}
    d._meeting_redact(record)
    assert "pricing" not in record["message"], record["message"]


# ---------- 11. a transcript correction with an id that is not a number is a 400, not a 500 ----------

def test_a_correction_with_an_id_that_is_not_a_number_is_refused_cleanly(d):
    from test_orchestrator import client_for
    r = client_for(d).post("/voice/correct", json={"id": "abc", "text": "deploy the docs"})
    assert r.status_code == 400, (r.status_code, r.text)


# ---------- 12. a new call starts with no verdicts or ignored speech from the last one ----------

def test_a_new_call_shows_nothing_ignored_or_judged_from_the_last_call(d, v, monkeypatch):
    """The page says "Nothing ignored on this call", but the list (with a stranger's words, at Commands), the count and
    the last verdict carried over from the last call."""
    async def no_worker(_session):
        pass

    monkeypatch.setattr(d, "_add_worker", no_worker)
    voice = d.VOICE
    voice.ignore(d.speaker.Verdict(0.1, 1.5, at=1.0), "a stranger's words")
    voice.last = d.speaker.Verdict(0.1, 1.5, at=1.0)
    asyncio.run(d._on_connect(fake_conn()))
    status = voice.status("commands")
    assert status["ignored"] == {"count": 0, "last_at": None, "recent": []}, status["ignored"]
    assert status["speaker"] is None


# ---------- 13. "Pointe, that's me" after the owner's own words is scored on the whole turn ----------

def _owner_claims_after(d, monkeypatch, before: list[tuple[str, int, int]]):
    """The seat is held by label "2"; the owner (label "1") speaks, then says "Pointe, that's me" (0.8 s, under the
    voiceprint's 1 s strong-match minimum). Audio is the owner's voice, as long as the span asked for."""
    d.PREFS.update({"voice_lock": "approvals"})
    m = meetings.Meeting(mode="listening", vendors={})
    m.owner = "2"
    d.state.meeting = m
    d.state.meeting_ears = SimpleNamespace(audio_between=lambda a, b: tone(OWNER_HZ, (b - a) / 1000))
    now = m.since + 1
    for text, start, end in before + [(" Pointe, that's me.", 2300, 3100)]:
        for t in m.hear([{"is_final": True, "text": text, "speaker": "1", "start_ms": start, "end_ms": end}], now):
            asyncio.run(d._on_meeting_turn(m, t))
        for t in m.tick(now + 2):
            asyncio.run(d._on_meeting_turn(m, t))
        now += 2.5
    return m


def test_that_s_me_right_after_the_owners_own_words_is_scored_on_the_whole_turn(d, v, monkeypatch):
    m = _owner_claims_after(d, monkeypatch, [(" We should ship on Thursday.", 0, 2000)])
    assert m.turns[-1].merged
    assert m.owner == "1", "the turn holds 2.8 s of the owner's voice, yet only the 0.8 s claim was scored"


def test_a_lone_short_that_s_me_still_needs_a_strong_match(d, v, monkeypatch):
    """Not loosened: 0.8 s alone is under the strong-match minimum, so the seat does not move on it."""
    m = _owner_claims_after(d, monkeypatch, [])
    assert m.owner == "2"


# ---------- 14. status says the bot is speaking to the room while its answer plays ----------

def test_meeting_status_says_speaking_while_the_bot_talks_to_the_room(d, monkeypatch):
    """Meeting.speaking was never set, so status["meeting"]["speaking"] stayed false while a participating answer played
    (the page's "speaking to the room", the app's "Speaking to the room")."""
    from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame
    from pipecat.processors.frame_processor import FrameDirection
    _meeting_ready(d, monkeypatch)
    _start(d, "participating")
    ears = d.SonioxEars()

    async def noop(*_a, **_k):
        pass

    monkeypatch.setattr(ears, "push_frame", noop)
    monkeypatch.setattr(d.FrameProcessor, "process_frame", lambda self, f, dirn: asyncio.sleep(0))
    monkeypatch.setattr(d, "_journal_bot_turn", lambda: None)
    up = FrameDirection.UPSTREAM
    asyncio.run(d.SonioxEars.process_frame(ears, BotStartedSpeakingFrame(), up))
    assert d.state.meeting.status()["speaking"] is True
    asyncio.run(d.SonioxEars.process_frame(ears, BotStoppedSpeakingFrame(), up))
    assert d.state.meeting.status()["speaking"] is False


# ---------- 15. during a meeting no room words and no owner question reach the log, in any line ----------

def _log_during(d, run) -> list[str]:
    """Every log message as the sinks get it (the daemon's meeting patcher applied) while `run` runs."""
    from loguru import logger
    lines = []
    logger.configure(patcher=d._meeting_redact)
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="DEBUG")
    try:
        asyncio.run(run())
    finally:
        logger.remove(sink)
        logger.configure(patcher=lambda r: None)
    return lines


def _echoing_reader(d, monkeypatch):
    """A reading model that repeats the owner's words it was given into the report, as a model may."""
    async def read(_system, prompt, _thinking=None):
        asked = prompt.split("The owner's recent words on this call, last one latest:\n", 1)[-1].split("\n\n", 1)[0] \
            if "The owner's recent words" in prompt else ""
        return {"say": "", "line": "", "speak": True, "waiting": True, "need": asked, "unblock": asked}

    monkeypatch.setattr(d, "_read_model", read)


def _session_finishes(d, s):
    from brief import FINAL_MARK
    s.idle_since = time.time()
    return d.feed(s, f"[{s.name} finished its turn] {FINAL_MARK}The export is written.", True)


def test_the_owners_meeting_question_does_not_reach_the_log_through_a_session_report(d, monkeypatch):
    """The owner's question in a meeting became state.last_utterance, which the report prompt passes as "the owner's
    recent words"; the report then went to the log ("is waiting on the user: ...", "feed: ...")."""
    _meeting_ready(d, monkeypatch)
    _echoing_reader(d, monkeypatch)
    s = add(d, "s1", "pricing")
    d.REGISTRY.active_id = s.id
    _start(d, "participating")
    d.state.meeting.owner = "1"

    async def run():
        await d._meeting_command("should we raise the Lisbon price to twelve euros?")
        await _session_finishes(d, s)
    leaked = [line for line in _log_during(d, run) if "Lisbon" in line]
    assert not leaked, leaked


def test_room_words_a_raised_hand_took_as_the_language_do_not_reach_the_log(d, monkeypatch):
    """meeting_hand("speak") set state.last_utterance to the room's latest turn (for its language): the same path then
    carried a participant's words into the log."""
    _meeting_ready(d, monkeypatch)
    _echoing_reader(d, monkeypatch)
    s = add(d, "s1", "pricing")
    d.REGISTRY.active_id = s.id
    _start(d, "participating")
    m = d.state.meeting
    m.hear([{"is_final": True, "text": " Dana thinks the Lisbon launch slips to May.", "speaker": "2"}], m.since + 1)
    m.tick(m.since + 5)
    m.hand = d.meetings.Hand("A risk.", "The launch date is at risk.", time.time())

    async def run():
        await d.meeting_hand("speak")
        await _session_finishes(d, s)
    leaked = [line for line in _log_during(d, run) if "Lisbon" in line]
    assert not leaked, leaked


def test_any_log_line_quoting_the_room_or_the_owners_question_is_withheld_in_a_meeting(d, monkeypatch):
    """A backstop for lines nobody listed: run 7 of the meeting e2e logged `barge-in: "<the bot's words>"` mid-meeting."""
    _meeting_ready(d, monkeypatch)
    _start(d, "participating")
    m = d.state.meeting
    m.hear([{"is_final": True, "text": " Dana thinks the Lisbon launch slips to May.", "speaker": "2"}], m.since + 1)
    m.tick(m.since + 5)
    d.state.last_utterance = "should we raise the price to twelve euros"
    for line in ("barge-in: 'the Lisbon launch slips to May, she said'",
                 "send_to_claude_code refused: 'x' (user said 'should we raise the price to twelve euros')",
                 "something new: we raise the price to twelve"):
        record = {"name": "__main__", "level": SimpleNamespace(no=20), "message": line}
        d._meeting_redact(record)
        assert "Lisbon" not in record["message"] and "twelve" not in record["message"], record["message"]
    record = {"name": "__main__", "level": SimpleNamespace(no=20), "message": "meeting command: ask"}
    d._meeting_redact(record)
    assert record["message"] == "meeting command: ask"


# ---------- 16. the bot's own voice in the meeting stream is the bot, however late its turn closes ----------

def _bot_said_then_room_turn(d, monkeypatch, bot_text, heard, label, secs_after_stop=9.0):
    """The bot said `bot_text` into the meeting and stopped; its echo closes as a meeting turn `secs_after_stop` later (the
    e2e measured 8-11 s: Soniox finalises late, a turn closes on 1.2 s of quiet, the loop ticks every 2 s)."""
    monkeypatch.setattr(d, "ECHO", d.EchoGuard())  # its own: the module's guard outlives the test
    _meeting_ready(d, monkeypatch)
    _start(d, "participating")
    m = d.state.meeting
    m.owner = "1"
    m.hear([{"is_final": True, "text": " Who owns the pricing page?", "speaker": "2"}], m.since + 1)
    for t in m.tick(m.since + 5):
        asyncio.run(d._on_meeting_turn(m, t))
    d.state.meeting_may_speak_until = time.time() + 10

    async def push_frame(frame, *a):
        pass

    asyncio.run(d.BrainFront._speak(SimpleNamespace(push_frame=push_frame), bot_text))
    d.ECHO.bot_started()
    d.ECHO.bot_stopped()
    monkeypatch.setattr(d.ECHO, "stopped_at", time.time() - secs_after_stop)
    turns = m.hear([{"is_final": True, "text": " " + heard, "speaker": label}], m.since + 20)
    turns += m.tick(m.since + 30)
    for t in turns:
        asyncio.run(d._on_meeting_turn(m, t))
    return m, turns


def test_the_bots_late_echo_on_a_new_label_is_not_a_fourth_person(d, monkeypatch):
    m, turns = _bot_said_then_room_turn(d, monkeypatch, "Before we agree, if we skip the payment tests the refunds break.",
                                        "Before we agree, if we skip the payment tests", "4")
    assert turns[0].who == "Pointe"
    assert "4" not in [s["label"] for s in m.speakers()], m.speakers()


def test_the_bots_late_echo_on_a_participants_label_is_the_bot_and_the_participant_stays(d, monkeypatch):
    """Seen in the e2e: the bot's "I can't judge that yet." came back under Dana's label, 8 s after it stopped."""
    m, turns = _bot_said_then_room_turn(d, monkeypatch, "I can't judge that yet without the numbers.", "I can't judge that yet.", "2")
    assert turns[0].who == "Pointe"
    assert m.bot != "2" and "2" in [s["label"] for s in m.speakers()], (m.bot, m.speakers())


def test_a_participant_echoing_nothing_the_bot_said_is_still_a_participant(d, monkeypatch):
    m, turns = _bot_said_then_room_turn(d, monkeypatch, "I can't judge that yet without the numbers.",
                                        "Let's ship it on Thursday anyway.", "3")
    assert turns[0].who != "Pointe" and "3" in [s["label"] for s in m.speakers()]


def test_an_addressed_turn_in_the_bots_words_is_the_owners_command(d, monkeypatch):
    async def no_model(*_a, **_k):
        return {}

    monkeypatch.setattr(d, "_read_model", no_model)  # the end-of-meeting pass
    m, turns = _bot_said_then_room_turn(d, monkeypatch, "Say Pointe, end the meeting, when you are done.",
                                        "Pointe, end the meeting.", "1")
    assert d.state.meeting is None, "the owner's end command was taken for the bot's echo"


# ---------- 17. a stale transcript from the conversation's ears does not cut the bot off in a meeting ----------

def test_a_stale_conversation_transcript_does_not_cut_the_bot_off_in_a_meeting(d, monkeypatch):
    """Seen in the meeting e2e: every 25-35 s `barge-in: "Connected to pricing. I'm still catching up on it."` (the call's
    greeting echo, left unfinalised when the meeting took the microphone) came back as an interim while the bot spoke to
    the room, and cut it off."""
    from pipecat.frames.frames import InterimTranscriptionFrame, TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection
    monkeypatch.setattr(d, "ECHO", d.EchoGuard())  # its own: the module's guard outlives the test
    _meeting_ready(d, monkeypatch)
    _start(d, "participating")
    ears = d.SonioxEars()
    cuts, heard = [], []

    async def cut():
        cuts.append(True)

    async def noop(*_a, **_k):
        pass

    async def took(text):
        heard.append(text)

    monkeypatch.setattr(ears, "broadcast_interruption", cut)
    monkeypatch.setattr(ears, "push_frame", noop)
    monkeypatch.setattr(ears, "_take", took)
    monkeypatch.setattr(d.FrameProcessor, "process_frame", lambda self, f, dirn: asyncio.sleep(0))
    d.ECHO.bot_started()
    d.ECHO.bot_said("The refunds flow still uses the old prices.")
    down = FrameDirection.DOWNSTREAM
    stale = "Connected to pricing. I'm still catching up on it."
    asyncio.run(d.SonioxEars.process_frame(ears, InterimTranscriptionFrame(text=stale, user_id="u", timestamp="t"), down))
    asyncio.run(d.SonioxEars.process_frame(ears, TranscriptionFrame(text=stale, user_id="u", timestamp="t"), down))
    d.ECHO.bot_stopped()
    assert not cuts and not heard, (cuts, heard)


def test_the_conversations_ears_are_finalised_when_a_meeting_takes_the_microphone(d, monkeypatch):
    """So the words cut off by the meeting finish inside it (where they are dropped), not stuck until after it."""
    sent = []

    async def send(message):
        sent.append(message)

    gate = d.PttGate(SimpleNamespace(_websocket=SimpleNamespace(send=send)))
    asyncio.run(gate.tick(T0))
    d.state.meeting = SimpleNamespace(ending=False)
    asyncio.run(gate.tick(T0 + 0.1))
    asyncio.run(gate.tick(T0 + 0.2))
    assert sent == ['{"type": "finalize"}'], sent


# ---------- 18. an addressed sentence split across two closes is handled once, as a whole ----------

def _owner_says(d, monkeypatch, parts, mode="participating"):
    """The owner (label "1") says `parts` in one breath; the room's quiet between finals closes the turn after each part
    (Soniox finalises in bursts), as in the e2e: "Point, end" then "the meeting."."""
    async def no_model(*_a, **_k):
        return {}

    monkeypatch.setattr(d, "_read_model", no_model)  # the end-of-meeting pass
    monkeypatch.setattr(d, "HOLD_ADDRESSED_SECS", 0.2)
    pushed, _ = _meeting_ready(d, monkeypatch)
    _start(d, mode)
    m = d.state.meeting
    m.owner = "1"

    async def go():
        at, ms = m.since + 1, 0
        for i, part in enumerate(parts):
            turns = m.hear([{"is_final": True, "text": " " + part, "speaker": "1", "start_ms": ms, "end_ms": ms + 600}], at)
            turns += m.tick(at + 2 * d.meetings.SILENCE_CLOSES_SECS)
            for t in turns:
                await d._on_meeting_turn(m, t)
            at, ms = at + 2, ms + 700  # 0.1 s of audio between the parts: one speaker, one turn
            await asyncio.sleep(0.05)  # less than the hold: the next part arrives in time
        await asyncio.sleep(0.4)  # past the hold
    asyncio.run(go())
    return m, [f.text for f in pushed]


def test_pointe_end_the_meeting_split_across_two_closes_ends_it(d, monkeypatch):
    _owner_says(d, monkeypatch, ["Point, end", "the meeting."])
    assert d.state.meeting is None, "the end command was taken as a question about 'end'"


def test_a_question_split_across_two_closes_is_asked_once_whole(d, monkeypatch):
    m, pushed = _owner_says(d, monkeypatch, ["Pointe, what do you think", "about the launch date?"])
    asks = [p for p in pushed if "[the owner said:]" in p]
    assert len(asks) == 1 and asks[0].rstrip().endswith("what do you think about the launch date?"), asks


def test_a_question_without_closing_punctuation_is_still_answered_once(d, monkeypatch):
    m, pushed = _owner_says(d, monkeypatch, ["Pointe, what do you think about the launch date"])
    asks = [p for p in pushed if "[the owner said:]" in p]
    assert len(asks) == 1, asks


def test_a_punctuated_question_is_answered_at_once(d, monkeypatch):
    m, pushed = _owner_says(d, monkeypatch, ["Pointe, what do you think about the launch date?"])
    asks = [p for p in pushed if "[the owner said:]" in p]
    assert len(asks) == 1, asks


# ---------- 19. the secretary's hand decision is in the log, without its words ----------

@pytest.mark.parametrize("mode, hand, outcome", [
    ("participating", {"raise": True, "line": "Refunds are untested."}, "raised"),
    ("listening", {"raise": True, "line": "Refunds are untested."}, "written instead (listening)"),
    ("participating", {"raise": False, "line": ""}, "not asked for")])
def test_the_secretarys_hand_decision_is_logged_without_its_words(mode, hand, outcome):
    from loguru import logger
    from notes import Notes
    lines = []
    sink = logger.add(lambda msg: lines.append(msg.record["message"]), level="INFO")
    try:
        meetings.apply_secretary(meetings.Meeting(mode=mode, vendors={}), Notes(), {"hand": hand})
    finally:
        logger.remove(sink)
    assert f"meeting: secretary pass, hand {outcome}" in lines and not any("Refunds" in x for x in lines), lines
