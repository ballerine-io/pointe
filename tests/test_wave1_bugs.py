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
from test_orchestrator import add, d, with_permission  # noqa: E402,F401  (d is a fixture)
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
    claim = m.hear([{"is_final": True, "text": " Pointe, that's me", "speaker": "1", "start_ms": 4000, "end_ms": 6000}], now + 10)
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
