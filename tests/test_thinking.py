"""The wait between the owner's last word and Pointe's reply (thinking.py, docs/features/thinking.md): a Thinking state
from the moment the turn is taken until the reply is heard or shown, and one soft sound when the wait is long.

The rules these pin: the state is true (it follows the work, and ends when nothing will be said); the sound never plays
when the reply is fast, never once the reply's words are on their way to the mouth, and never twice in a turn; it is a
plain audio frame, so no rule that times Pointe's speech takes it for speech. Offline: the clock is passed in."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import thinking  # noqa: E402
from test_orchestrator import add, client_for, d, fake_conn  # noqa: E402,F401  (d is a fixture)

T = 1000.0  # the turn is taken here


def _wait(last_word: float | None = T - 1.0) -> thinking.Wait:
    wait = thinking.Wait()
    wait.taken(T, last_word)
    wait.handled(T)
    return wait


# ---------- the state ----------

def test_thinking_starts_when_the_turn_is_taken_and_ends_at_the_first_sound():
    wait = thinking.Wait()
    assert not wait.thinking(T - 1, busy=False)  # nothing was said yet: Listening
    wait.taken(T, T - 1.0)
    assert wait.thinking(T + 0.01, busy=False)  # at once, before the model step has started
    assert wait.thinking(T + 2.0, busy=True)
    wait.handed(T + 2.1)
    assert wait.thinking(T + 2.3, busy=False)  # the words are with the mouth, no sound yet
    wait.sound(T + 2.5)
    assert not wait.thinking(T + 2.6, busy=False)


def test_a_turn_that_gets_no_reply_stops_thinking_after_a_moment():
    wait = _wait()
    assert wait.thinking(T + thinking.START_GRACE_SECS - 0.05, busy=False)
    assert not wait.thinking(T + thinking.START_GRACE_SECS + 0.05, busy=False)  # "mm-hm": nothing will be said


def test_while_the_daemon_itself_still_handles_the_words_it_is_thinking():
    wait = thinking.Wait()
    wait.taken(T, T - 1.0)
    assert wait.thinking(T + 3.0, busy=False)  # a yes being applied, a stop being sent: no model step yet
    wait.handled(T + 3.0)
    assert wait.thinking(T + 3.0 + thinking.START_GRACE_SECS - 0.05, busy=False)
    assert not wait.thinking(T + 3.0 + thinking.START_GRACE_SECS + 0.05, busy=False)


def test_news_said_after_the_turn_was_answered_is_not_thinking():
    wait = _wait()
    wait.handed(T + 1.0)
    wait.sound(T + 1.3)
    assert not wait.thinking(T + 3.0, busy=False)
    wait.close()  # the daemon closes a turn it sees answered (daemon._cue_watch)
    wait.handed(T + 30.0)  # a session's report on its way to the mouth
    assert not wait.thinking(T + 30.1, busy=False) and not wait.thinking(T + 30.1, busy=True)
    assert not wait.cue_due(T + 31.0, busy=True)


def test_after_a_one_sec_the_work_goes_on_and_so_does_thinking():
    wait = _wait()
    wait.handed(T + 4.5)
    wait.sound(T + 4.8)  # the filler
    assert wait.thinking(T + 6.0, busy=True)
    assert not wait.thinking(T + 6.0, busy=False)


def test_words_that_never_become_sound_do_not_hold_the_state():
    wait = _wait()
    wait.handed(T + 1.0)
    assert wait.thinking(T + 1.0 + thinking.HANDED_SECS - 0.1, busy=False)
    assert not wait.thinking(T + 1.0 + thinking.HANDED_SECS + 0.1, busy=False)  # the mouth is down: its own line says so


def test_a_step_that_never_ends_does_not_say_thinking_forever():
    wait = _wait()
    assert wait.thinking(T + thinking.MAX_SECS - 1, busy=True)
    assert not wait.thinking(T + thinking.MAX_SECS + 1, busy=True)


def test_the_call_ending_clears_it():
    wait = _wait()
    wait.clear()
    assert not wait.thinking(T + 0.1, busy=True)


# ---------- the sound: when ----------

def test_the_sound_is_due_once_the_wait_since_the_last_word_is_long():
    wait = _wait(last_word=T - 1.0)
    due = T - 1.0 + thinking.CUE_AFTER_LAST_WORD_SECS
    assert wait.cue_at() == pytest.approx(due)
    assert not wait.cue_due(due - 0.05, busy=True)
    assert wait.cue_due(due + 0.01, busy=True)


def test_a_fast_reply_never_gets_the_sound():
    wait = _wait(last_word=T - 0.3)
    wait.handed(T + 0.4)
    wait.sound(T + 0.7)  # heard 1.0 s after the last word
    for later in (T + 1.6, T + 3.0, T + 10.0):
        assert not wait.cue_due(later, busy=True), later  # not even while a tool of that turn still runs


def test_the_sound_never_plays_once_the_reply_is_on_its_way_to_the_mouth():
    wait = _wait(last_word=T - 1.0)
    wait.handed(T + 0.75)  # 50 ms before the sound was due
    assert not wait.cue_due(T + 0.81, busy=True)
    assert not wait.cue_due(T + 2.0, busy=True)


def test_the_sound_plays_once_in_a_turn():
    wait = _wait(last_word=T - 1.0)
    assert wait.cue_due(T + 1.0, busy=True)
    wait.cue_played(T + 1.0)
    assert not wait.cue_due(T + 1.5, busy=True) and not wait.cue_due(T + 9.0, busy=True)
    wait.taken(T + 20, T + 19)
    assert wait.cue_due(T + 21, busy=True)  # the next turn has its own


def test_typed_words_and_a_press_count_from_the_turn():
    wait = _wait(last_word=None)
    assert wait.cue_at() == pytest.approx(T + thinking.CUE_AFTER_TAKEN_SECS)
    assert not wait.cue_due(T + thinking.CUE_AFTER_TAKEN_SECS - 0.05, busy=True)
    assert wait.cue_due(T + thinking.CUE_AFTER_TAKEN_SECS + 0.05, busy=True)


def test_the_sound_never_comes_right_on_top_of_the_turn_being_taken():
    wait = _wait(last_word=T - 9.0)  # words held for a long settle, or released from a hold
    assert wait.cue_at() == pytest.approx(T + thinking.CUE_MIN_AFTER_TAKEN_SECS)


def test_no_sound_for_a_turn_nobody_is_working_on():
    wait = _wait(last_word=T - 1.0)
    assert not wait.cue_due(T + 2.0, busy=False)  # an "mm-hm": nothing is coming, so nothing is promised


def test_the_numbers_keep_their_promises():
    assert thinking.CUE_AFTER_TAKEN_SECS == 1.2
    assert thinking.CUE_AFTER_LAST_WORD_SECS + thinking.CUE_SECS <= 2.0  # no silence past 2 s without a sound
    assert thinking.CUE_AFTER_LAST_WORD_SECS < 4.0  # before the spoken "One sec." (brain.FILLER_AFTER_SECS)
    import brain
    assert thinking.CUE_AFTER_LAST_WORD_SECS + 1.0 < brain.FILLER_AFTER_SECS


# ---------- the sound: what ----------

def test_the_sound_is_short_quiet_and_has_no_click():
    pcm = np.frombuffer(thinking.cue_pcm(24000), dtype=np.int16)
    assert len(pcm) / 24000 == pytest.approx(thinking.CUE_SECS, abs=0.002) and thinking.CUE_SECS <= 0.15
    assert 0.03 * 32767 < np.abs(pcm).max() <= 0.12 * 32767  # audible, well under the chimes' 0.25
    assert abs(int(pcm[0])) < 40 and abs(int(pcm[-1])) < 40  # it fades in and out


# ---------- the daemon ----------

@pytest.fixture(autouse=True)
def _plain_call(d):
    yield
    d.state.mute = False
    d.PREFS.values.pop("thinking.cue", None)
    d.PREFS.values.pop("whisper", None)


def _brain(user_turns: int):
    return SimpleNamespace(_user_turns=user_turns, busy=bool(user_turns), interrupt=lambda: None)


def _on_a_call(d, user_turns: int = 1):
    d.state.conn = fake_conn()
    d.state.front = SimpleNamespace(brain=_brain(user_turns))


def test_status_says_thinking_from_the_turn_until_the_sound(d):
    _on_a_call(d)
    client = client_for(d)
    assert client.get("/voice/status").json()["phase"] is None
    asyncio.run(d.on_user_utterance("what is billing doing"))
    phase = client.get("/voice/status").json()["phase"]
    assert phase["name"] == "thinking" and phase["session"] is None
    d.ECHO.bot_started()
    assert client.get("/voice/status").json()["phase"] is None  # status.speaking says it
    d.state.wait.sound(d.time.time())
    d.ECHO.bot_stopped()
    d.state.front.brain._user_turns, d.state.front.brain.busy = 0, False
    assert client.get("/voice/status").json()["phase"] is None


def test_no_call_no_phase(d):
    asyncio.run(d.on_user_utterance("hello"))
    assert client_for(d).get("/voice/status").json()["phase"] is None


def test_a_meeting_and_a_mode_that_never_speaks_have_no_thinking(d, monkeypatch):
    _on_a_call(d)
    asyncio.run(d.on_user_utterance("what is billing doing"))
    client = client_for(d)
    assert client.get("/voice/status").json()["phase"]["name"] == "thinking"
    monkeypatch.setattr(d, "current_mode", lambda: SimpleNamespace(name="listening", speech="never", approvals="tap"))
    assert client.get("/voice/status").json()["phase"] is None


def test_a_line_shown_instead_of_spoken_ends_thinking(d):
    _on_a_call(d, user_turns=0)
    d.state.mute = True
    asyncio.run(d.on_user_utterance("what is billing doing"))

    async def run():
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.tests.utils import run_test
        await run_test(Pipeline([d.MuteOut()]), frames_to_send=[d.TTSSpeakFrame("Billing is idle.")])
    asyncio.run(run())
    status = client_for(d).get("/voice/status").json()
    assert status["phase"] is None and status["reading"]["writing"] is True


def test_every_line_for_the_mouth_is_marked_as_on_its_way(d):
    _on_a_call(d)
    asyncio.run(d.on_user_utterance("what is billing doing"))
    assert d.state.wait.handed_at == 0.0

    async def run():
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.tests.utils import run_test
        await run_test(Pipeline([d.MuteOut()]), frames_to_send=[d.TTSSpeakFrame("Billing is idle.")])
    asyncio.run(run())
    assert d.state.wait.handed_at >= d.state.wait.taken_at > 0


def test_the_first_sound_is_marked(d):
    _on_a_call(d)
    asyncio.run(d.on_user_utterance("what is billing doing"))

    async def run():
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.tests.utils import run_test
        await run_test(Pipeline([d.BotSpeechTap()]), frames_to_send=[d.BotStartedSpeakingFrame()])
    asyncio.run(run())
    assert d.state.wait.sound_at >= d.state.wait.taken_at


def test_the_setting_is_on_by_default_and_saved(d):
    client = client_for(d)
    assert client.get("/voice/prefs").json()["thinking.cue"] is True
    assert client.post("/voice/prefs", json={"thinking.cue": False}).json()["thinking.cue"] is False
    assert client.post("/voice/prefs", json={"thinking.cue": "loud"}).status_code == 400


@pytest.mark.parametrize("why", ["off", "muted", "whisper", "meeting", "silent mode", "no call", "speaking", "user talking"])
def test_where_the_sound_is_never_played(d, monkeypatch, why):
    _on_a_call(d)
    assert d._cue_allowed() is True
    if why == "off":
        d.PREFS.values["thinking.cue"] = False
    elif why == "muted":
        d.state.mute = True
    elif why == "whisper":
        d.PREFS.values["whisper"] = True
    elif why == "meeting":
        d.state.meeting = SimpleNamespace(status=lambda: {})
    elif why == "silent mode":
        monkeypatch.setattr(d, "current_mode", lambda: SimpleNamespace(speech="never"))
    elif why == "no call":
        d.state.conn = None
    elif why == "speaking":
        d.ECHO.bot_started()
    elif why == "user talking":
        monkeypatch.setattr(d, "_user_talking", lambda: True)
    assert d._cue_allowed() is False


def test_drive_mode_keeps_the_sound_though_muted(d):
    _on_a_call(d)
    d.state.mute = True
    d.state.drive.enter("voice")
    try:
        assert d._cue_allowed() is True  # on the road it is the only sign the words were heard
    finally:
        d.state.drive.leave()


class _Front:
    def __init__(self, user_turns: int = 1):
        self.brain = _brain(user_turns)
        self.pushed: list = []

    async def push_frame(self, frame, direction=None):
        self.pushed.append(frame)


def _fast_clock(d, monkeypatch):
    monkeypatch.setattr(d.thinking, "CUE_AFTER_TAKEN_SECS", 0.15)
    monkeypatch.setattr(d.thinking, "CUE_MIN_AFTER_TAKEN_SECS", 0.05)
    monkeypatch.setattr(d.thinking, "CUE_POLL_SECS", 0.01)


def test_a_slow_reply_gets_one_soft_sound_that_is_not_speech(d, monkeypatch):
    _fast_clock(d, monkeypatch)

    async def run():
        d.state.conn, d.state.front = fake_conn(), _Front()
        await d.on_user_utterance("what is billing doing", typed=True)
        await asyncio.sleep(0.5)
        return d.state.front.pushed
    pushed = asyncio.run(run())
    sounds = [f for f in pushed if isinstance(f, d.OutputAudioRawFrame)]
    assert len(sounds) == 1 and sounds[0].audio == thinking.cue_pcm(sounds[0].sample_rate)
    # Not a TTS frame: pipecat's output starts the bot's turn only on those, so the echo guard, the floor and the yes
    # window never see this sound as Pointe speaking.
    assert type(sounds[0]) is d.OutputAudioRawFrame
    assert d.state.wait.cued


def test_a_reply_that_arrives_first_gets_no_sound(d, monkeypatch):
    _fast_clock(d, monkeypatch)

    async def run():
        d.state.conn, d.state.front = fake_conn(), _Front()
        await d.on_user_utterance("what is billing doing", typed=True)
        await asyncio.sleep(0.05)
        d.state.wait.handed(d.time.time())  # the reply's words reach the mouth before the sound was due
        await asyncio.sleep(0.4)
        return d.state.front.pushed
    assert [f for f in asyncio.run(run()) if isinstance(f, d.OutputAudioRawFrame)] == []


def test_a_new_turn_drops_the_old_turns_sound(d, monkeypatch):
    _fast_clock(d, monkeypatch)
    monkeypatch.setattr(d.thinking, "CUE_AFTER_TAKEN_SECS", 0.3)

    async def run():
        d.state.conn, d.state.front = fake_conn(), _Front()
        await d.on_user_utterance("what is billing", typed=True)
        await asyncio.sleep(0.2)
        await d.on_user_utterance("what is billing doing right now", typed=True)
        await asyncio.sleep(0.2)
        early = list(d.state.front.pushed)  # 0.4 s after the first turn: its sound would have played by now
        await asyncio.sleep(0.3)
        return early, d.state.front.pushed
    early, pushed = asyncio.run(run())
    assert early == [] and len([f for f in pushed if isinstance(f, d.OutputAudioRawFrame)]) == 1


def test_the_calling_device_is_told_at_once(d):
    sent = []

    class Sock:
        async def send_text(self, text):
            sent.append(json.loads(text))

    async def run():
        d.state.conn, d.state.front = fake_conn(), _Front()
        d.state.call_socket = Sock()
        await d.on_user_utterance("what is billing doing", typed=True)
        await asyncio.sleep(0.05)
    asyncio.run(run())
    assert {"type": "phase", "name": "thinking", "session": None} in sent


# ---------- the words are the same everywhere ----------

def test_the_words_are_the_same_on_the_page_and_in_the_apps():
    root = Path(__file__).resolve().parents[1]
    page = (root / "pointe" / "ui_thinking.html").read_text()
    swift = (root / "apps" / "PointeKit" / "Sources" / "PointeUI" / "Thinking.swift").read_text()
    for key, words in thinking.COPY.items():
        page_words = words.replace("{session}", "${session}")
        swift_words = words.replace("{session}", "\\(session)")
        assert f"'{page_words}'" in page or f"`{page_words}`" in page, (key, words)
        assert f'"{swift_words}"' in swift, (key, words)
