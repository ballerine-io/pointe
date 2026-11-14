"""Whisper mode: quieter output, a raised microphone with a whisper voice-detector profile, short replies, and the same
approval rules as a normal voice. Offline.

uv run pytest -q tests/test_whisper.py
"""

import asyncio
import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import speaker  # noqa: E402
import whisper  # noqa: E402
from test_orchestrator import _consent_setup, _read_out_setup, client_for, d, verdicts  # noqa: E402,F401  (d is a fixture)


@pytest.fixture(autouse=True)
def _whisper_off_after():
    yield
    if "daemon" in sys.modules:
        sys.modules["daemon"].PREFS.update({"whisper": False, "voice_lock": "off", "microphone": "always"})


def _pcm(*samples) -> bytes:
    return np.array(samples, dtype=np.int16).tobytes()


def _ints(pcm: bytes) -> list[int]:
    return np.frombuffer(pcm, dtype=np.int16).tolist()


# ---------- the phrases ----------

@pytest.mark.parametrize("said", ["Whisper mode.", "whisper mode on", "OK, whisper mode", "Pointe, whisper mode",
                                  "turn on whisper mode", "Let's whisper.", "מצב לחישה", "מצב לחישה."])
def test_whisper_mode_phrases_turn_it_on(said):
    assert whisper.intent(said) is True


@pytest.mark.parametrize("said", ["Back to normal.", "normal mode", "stop whispering", "exit whisper mode",
                                  "Back to normal voice mode.", "normal voice", "back to normal mode",
                                  "whisper mode off", "חזרה לרגיל", "מצב רגיל"])
def test_back_to_normal_phrases_turn_it_off(said):
    assert whisper.intent(said) is False


@pytest.mark.parametrize("said", ["What is whisper mode?", "tell lantern to add a whisper mode flag",
                                  "the tests are back to normal now", "yes", "Normal.", "whisper the answer to billing", ""])
def test_other_sentences_are_not_a_mode_change(said):
    assert whisper.intent(said) is None


# ---------- the audio ----------

def test_input_gain_is_linear_for_a_whisper_and_never_clips():
    assert _ints(whisper.apply_gain(_pcm(100, -400, 2000), 2.5)) == [250, -1000, 5000]  # quiet: plain x2.5
    loud = _ints(whisper.apply_gain(_pcm(32767, -32768, 20000), 2.5))
    assert all(-32767 <= x <= 32767 for x in loud) and loud[0] > 30000 and loud[2] > 16384  # limited, not wrapped
    assert whisper.apply_gain(_pcm(5, 6), 1.0) == _pcm(5, 6)


def test_output_is_halved():
    assert _ints(whisper.scale(_pcm(1000, -1000, 32767), whisper.OUTPUT_GAIN)) == [500, -500, 16383]
    assert whisper.scale(_pcm(7), 1.0) == _pcm(7)


# ---------- the setting and the status ----------

def test_whisper_is_a_pref_both_clients_share_and_status_shows_it(d):
    c = client_for(d)
    assert c.get("/voice/prefs").json()["whisper"] is False
    assert c.get("/voice/status").json()["whisper"]["on"] is False
    assert c.post("/voice/prefs", json={"whisper": True}).json()["whisper"] is True
    s = c.get("/voice/status").json()["whisper"]
    assert s == {"on": True, "held": None, "output_gain": 0.5, "max_words": whisper.MAX_WORDS, "suggest_ptt": True,
                 "lock_note": None}
    assert c.post("/voice/prefs", json={"whisper": "yes"}).status_code == 400


def test_the_status_suggests_push_to_talk_only_when_it_is_off(d):
    d.PREFS.update({"whisper": True, "microphone": "ptt"})
    assert client_for(d).get("/voice/status").json()["whisper"]["suggest_ptt"] is False


def test_the_status_says_a_whisper_may_not_match_the_voiceprint(d):
    d.PREFS.update({"whisper": True, "voice_lock": "approvals"})
    assert "tap to approve" in client_for(d).get("/voice/status").json()["whisper"]["lock_note"]
    d.PREFS.update({"voice_lock": "commands"})
    assert "type" in client_for(d).get("/voice/status").json()["whisper"]["lock_note"]


# ---------- the call's audio ----------

def _processor(d, monkeypatch, cls, *args):
    proc = cls(*args)
    pushed = []

    async def push(frame, *a):
        pushed.append(frame)
    proc.push_frame = push
    monkeypatch.setattr(d.FrameProcessor, "process_frame", lambda self, f, dirn: asyncio.sleep(0))
    return proc, pushed


def _run(d, proc, frame, direction=None):
    asyncio.run(type(proc).process_frame(proc, frame, direction or d.FrameDirection.DOWNSTREAM))


def test_the_bot_is_half_as_loud_while_whispering_from_the_next_chunk(d, monkeypatch):
    out, pushed = _processor(d, monkeypatch, d.WhisperOut)
    chunk = lambda: d.OutputAudioRawFrame(audio=_pcm(1000, -2000), sample_rate=24000, num_channels=1)  # noqa: E731
    _run(d, out, chunk())
    d.PREFS.update({"whisper": True})
    _run(d, out, chunk())
    d.PREFS.update({"whisper": False})
    _run(d, out, chunk())
    assert [_ints(f.audio) for f in pushed] == [[1000, -2000], [500, -1000], [1000, -2000]]


def _vad_updates(d, pushed):
    from pipecat.frames.frames import VADParamsUpdateFrame
    return [f.params for f in pushed if isinstance(f, VADParamsUpdateFrame)]


def test_the_microphone_is_raised_and_the_voice_detector_takes_the_whisper_profile(d, monkeypatch):
    from pipecat.audio.vad.vad_analyzer import VADParams

    inp, pushed = _processor(d, monkeypatch, d.WhisperIn)
    mic = lambda: d.InputAudioRawFrame(audio=_pcm(100, -100), sample_rate=16000, num_channels=1)  # noqa: E731
    _run(d, inp, mic())
    assert _ints(pushed[-1].audio) == [100, -100] and _vad_updates(d, pushed) == []  # off: untouched
    d.PREFS.update({"whisper": True})
    _run(d, inp, mic())
    _run(d, inp, mic())
    assert _ints(pushed[-1].audio) == [250, -250]
    assert _vad_updates(d, pushed) == [VADParams(**whisper.VAD_WHISPER)]  # once, on the change
    d.PREFS.update({"whisper": False})
    _run(d, inp, mic())
    assert _ints(pushed[-1].audio) == [100, -100]
    assert _vad_updates(d, pushed)[-1] == VADParams()


def test_a_call_that_starts_in_whisper_mode_takes_the_profile_at_once(d, monkeypatch):
    from pipecat.audio.vad.vad_analyzer import VADParams

    d.PREFS.update({"whisper": True})
    inp, pushed = _processor(d, monkeypatch, d.WhisperIn)
    _run(d, inp, d.InputAudioRawFrame(audio=_pcm(100), sample_rate=16000, num_channels=1))
    assert _vad_updates(d, pushed) == [VADParams(**whisper.VAD_WHISPER)]


def test_a_meetings_room_audio_is_not_raised(d, monkeypatch):
    inp, pushed = _processor(d, monkeypatch, d.WhisperIn)
    d.PREFS.update({"whisper": True})
    monkeypatch.setattr(d, "_room_heard", lambda: True)
    _run(d, inp, d.InputAudioRawFrame(audio=_pcm(100), sample_rate=16000, num_channels=1))
    assert _ints(pushed[-1].audio) == [100]


# ---------- the brain ----------

def test_the_brain_is_told_to_keep_it_short_only_while_whispering(d):
    assert whisper.REPLY_RULE not in d._brain_context()
    d.PREFS.update({"whisper": True})
    assert whisper.REPLY_RULE in d._brain_context()


def test_the_brain_is_told_it_cannot_switch_the_mode_itself():
    """Live: a misheard "Normal." reached the brain, which answered "Normal mode is on." with nothing changed."""
    assert "back to normal" in whisper.REPLY_RULE and "cannot" in whisper.REPLY_RULE


# ---------- by voice ----------

def _ears(d, monkeypatch):
    ears = d.SonioxEars()
    reached, said = [], []

    async def push(frame, *a):
        reached.append(frame)

    async def say(text, *a, **k):
        said.append(text)
    ears.push_frame = push
    monkeypatch.setattr(d, "say", say)
    return ears, reached, said


def test_saying_whisper_mode_turns_it_on_in_code_and_back_to_normal_turns_it_off(d, monkeypatch):
    ears, reached, said = _ears(d, monkeypatch)
    asyncio.run(ears._take("whisper mode"))
    assert d.PREFS.get("whisper") is True and not reached  # the brain never got the words
    assert said and "whisper" in said[-1].lower()
    asyncio.run(ears._take("back to normal"))
    assert d.PREFS.get("whisper") is False and not reached


def test_while_thinking_out_loud_the_phrase_is_a_thought(d, monkeypatch):
    ears, reached, said = _ears(d, monkeypatch)
    d._start_dump("let me think out loud")
    try:
        asyncio.run(ears._take("whisper mode"))
    finally:
        d.state.dump = None
    assert d.PREFS.get("whisper") is False


# ---------- approvals: a whispered yes or no follows exactly the same rules ----------

ANSWERS = ["yes", "yes please", "go ahead", "no", "no, don't run it", "yes, and run the linter", "wait, what is it?",
           "okay, tell me more", "כן", "לא"]


def _outcome(d, monkeypatch, text, whispering, setup):
    d.PREFS.update({"whisper": whispering})
    active, posts, said = setup(d, monkeypatch)
    asyncio.run(d.on_user_utterance(text))
    return verdicts(posts), active.permission_id, len(said)


@pytest.mark.parametrize("text", ANSWERS)
def test_a_whispered_answer_to_a_read_out_request_is_judged_exactly_as_a_normal_one(d, monkeypatch, text):
    normal = _outcome(d, monkeypatch, text, False, _read_out_setup)
    whispered = _outcome(d, monkeypatch, text, True, _read_out_setup)
    assert whispered == normal


def _unread_setup(d, monkeypatch):
    active, posts = _consent_setup(d, monkeypatch)
    return active, posts, []


@pytest.mark.parametrize("text", ["yes", "no"])
def test_a_whispered_yes_before_the_request_was_read_out_is_judged_as_a_normal_one(d, monkeypatch, text):
    assert _outcome(d, monkeypatch, text, True, _unread_setup) == _outcome(d, monkeypatch, text, False, _unread_setup)


def test_whisper_mode_never_lowers_the_voice_lock(d, monkeypatch):
    d.PREFS.update({"voice_lock": "commands"})
    d.PREFS.update({"whisper": True})
    assert d.lock_level() == "commands"
    assert d.current_mode().approvals == "voice+tap"  # and it is no mode of its own: approvals are what they were


def test_a_whisper_that_does_not_match_the_voiceprint_does_not_approve(d, monkeypatch):
    """Fail closed: a whisper scores low against a voiceprint learned from the normal voice (bench: no unvoiced sentence
    reached T_HIGH). That weak score is never enough for a yes, whispering or not."""
    monkeypatch.setattr(d.VOICE, "confident", lambda v: v is not None and v.score is not None and v.score >= speaker.T_HIGH)
    outcomes = []
    for whispering in (False, True):
        d.PREFS.update({"voice_lock": "approvals", "whisper": whispering})
        active, posts, said = _read_out_setup(d, monkeypatch)
        d.state.last_speaker = speaker.Verdict(0.37, 2.0, "MacBook mic", time.time())
        asyncio.run(d.on_user_utterance("yes"))
        outcomes.append((verdicts(posts), active.permission_id))
    assert outcomes[0] == outcomes[1] == ([], "p1")


def test_the_daemon_defines_everything_before_it_starts():
    """bin/voice-daemon runs daemon.py as __main__: main() blocks, so code after the guard never runs (a live call once
    died on a NameError for WhisperIn). The guard must be the module's last statement."""
    import ast

    tree = ast.parse((Path(__file__).resolve().parents[1] / "daemon.py").read_text())
    last = tree.body[-1]
    assert isinstance(last, ast.If) and "__main__" in ast.unparse(last.test)


# ---------- with drive mode and a challenge ----------

def _drive_on(d):
    d.state.drive.enter("button")


def test_drive_mode_holds_whisper_mode_full_volume_normal_microphone_and_drives_rules(d, monkeypatch):
    """Drive wins: the user cannot look at a screen, and a half-volume voice in a car is a safety cost. The whisper
    setting stays as set and comes back when drive mode ends."""
    d.PREFS.update({"whisper": True})
    _drive_on(d)
    out, pushed = _processor(d, monkeypatch, d.WhisperOut)
    _run(d, out, d.OutputAudioRawFrame(audio=_pcm(1000), sample_rate=24000, num_channels=1))
    inp, raised = _processor(d, monkeypatch, d.WhisperIn)
    _run(d, inp, d.InputAudioRawFrame(audio=_pcm(100), sample_rate=16000, num_channels=1))
    assert _ints(pushed[-1].audio) == [1000] and _ints(raised[-1].audio) == [100] and _vad_updates(d, raised) == []
    ctx = d._brain_context()
    assert whisper.REPLY_RULE not in ctx and d.drives.RULES in ctx
    s = client_for(d).get("/voice/status").json()["whisper"]
    assert s["on"] is True and s["held"] == "drive" and s["output_gain"] == 1.0 and s["suggest_ptt"] is False
    d.state.drive.leave()
    _run(d, out, d.OutputAudioRawFrame(audio=_pcm(1000), sample_rate=24000, num_channels=1))
    assert _ints(pushed[-1].audio) == [500] and whisper.REPLY_RULE in d._brain_context()
    assert client_for(d).get("/voice/status").json()["whisper"]["held"] is None


def test_back_to_normal_while_driving_and_whispering_ends_drive_mode_first(d, monkeypatch):
    ears, reached, said = _ears(d, monkeypatch)
    monkeypatch.setattr(d, "set_drive", lambda on, how: _leave(d))
    d.PREFS.update({"whisper": True})
    _drive_on(d)
    asyncio.run(ears._take("back to normal"))
    assert not d.state.drive.on() and d.PREFS.get("whisper") is True and not reached
    asyncio.run(ears._take("back to normal"))
    assert d.PREFS.get("whisper") is False and not reached


async def _leave(d):
    d.state.drive.leave()


def test_back_to_normal_with_neither_mode_on_is_someone_elses_words(d, monkeypatch):
    ears, reached, said = _ears(d, monkeypatch)
    asyncio.run(ears._take("back to normal"))
    assert reached and not said and d.PREFS.get("whisper") is False


def test_a_challenge_and_whisper_mode_both_apply_and_whisper_widens_nothing(d, monkeypatch):
    import challenge
    import modes

    d.state.challenge = challenge.Challenge(plan="Ship the retry fix on Friday.", sessions=["lantern"], evidence=[])
    try:
        ears, reached, said = _ears(d, monkeypatch)
        asyncio.run(ears._take("whisper mode"))
        assert d.PREFS.get("whisper") is True and d.state.challenge is not None  # the challenge goes on
        assert d.current_mode() is modes.CHALLENGE and not d.current_mode().sends
        ctx = d._brain_context()
        assert whisper.REPLY_RULE in ctx and challenge.context_line(d.state.challenge) in ctx
    finally:
        d.state.challenge = None


def test_whisper_mode_asked_while_driving_waits_for_the_end_of_drive_mode(d, monkeypatch):
    ears, reached, said = _ears(d, monkeypatch)
    _drive_on(d)
    asyncio.run(ears._take("whisper mode"))
    assert d.PREFS.get("whisper") is True and "drive mode ends" in said[-1]
