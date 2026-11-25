"""Three signals for the end of a turn (docs/design/turn-taking.md §6): the text rules, Soniox's own endpoint, and
how the voice sounded at the stop (turnsound.py). A candidate rule waits less when they agree; measured, it cut in on
too many pauses, so no level uses it: the signals are judged and logged on every turn, and the wait is as before.
Offline: no audio leaves, no model of a vendor's is called."""

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "pointe"), str(ROOT / "tests")]

import turns  # noqa: E402
import turnsound  # noqa: E402

NORMAL = turns.CANDIDATE  # the rule that was tried
SURE, OPEN = 0.95, 0.05  # a voice that sounds finished, and one that trails off


def test_a_clear_end_waits_a_third_of_a_second_and_a_doubtful_one_a_whole_second():
    said = "Run the tests in the billing package."
    assert turns.settle(said, False, NORMAL, endpoint=True, sound=SURE) == NORMAL.agreed == 0.3
    assert turns.settle(said, False, NORMAL, endpoint=False, sound=SURE) == NORMAL.likely == 0.6
    assert turns.settle(said, False, NORMAL, endpoint=True, sound=None) == NORMAL.likely
    assert turns.settle(said, False, NORMAL, endpoint=True, sound=0.5) == NORMAL.likely  # the sound is not sure
    assert turns.settle(said, False, NORMAL, endpoint=False, sound=None) == NORMAL.complete == 1.0
    assert turns.settle(said, False, NORMAL) == NORMAL.complete  # no signal given: as before


def test_no_level_a_user_can_choose_waits_less_for_the_signals():
    """bench/turn_bench.py: the candidate took a whole-reading first part in its pause 94% of the time, against 15%."""
    said = "Run the tests in the billing package."
    for name, level in turns.LEVELS.items():
        for endpoint in (True, False):
            for sound in (None, SURE, OPEN, 0.5):
                assert turns.settle(said, False, name, endpoint=endpoint, sound=sound) == level.complete
        assert turns.finalize_after(name, sound=SURE) == turns.finalize_after(name)


@pytest.mark.parametrize("said", ["Open the parser and then", "So basically,", "I want to look at", "Um", "It fails when",
                                  "תבדוק בבקשה את", "ואז"])
def test_words_that_trail_off_wait_the_long_time_whatever_the_voice_and_soniox_say(said):
    assert turns.settle(said, False, NORMAL, endpoint=True, sound=SURE) == NORMAL.unfinished == 3.0


def test_a_voice_that_trails_off_keeps_the_whole_wait_even_when_the_words_read_whole():
    said = "Let's look at the parser."
    assert turns.settle(said, False, NORMAL, endpoint=True, sound=OPEN) == NORMAL.complete
    assert turns.settle(said, False, NORMAL, endpoint=False, sound=OPEN) == NORMAL.complete


def test_a_sentence_said_in_parts_is_never_taken_fast():
    """A first part was held: this speaker pauses inside sentences, so the next pause may be one too."""
    assert turns.settle("and see why it fails.", True, NORMAL, endpoint=True, sound=SURE) == NORMAL.complete


def test_answers_holds_and_stops_still_act_at_once():
    assert turns.settle("yes", False, NORMAL, endpoint=False, sound=OPEN) == 0.0
    assert turns.settle("stop", False, NORMAL, endpoint=False, sound=OPEN) == 0.0
    assert turns.settle("hold on", False, NORMAL, endpoint=False, sound=OPEN) == 0.0


def test_a_level_built_without_the_new_times_falls_back_to_its_whole_sentence_time():
    level = turns.Patience(complete=0.7, unfinished=2.0, maximum=8.0)
    assert level.agreed == level.likely == 0.7


def test_the_candidate_asks_soniox_for_its_words_sooner_when_the_voice_sounds_finished():
    """So the final transcript is in when the short wait ends: asked `likely` less Soniox's 0.3 s after the sound."""
    assert turns.finalize_after("normal") == pytest.approx(0.7)
    assert turns.finalize_after(NORMAL, sound=SURE) == pytest.approx(0.3)
    assert turns.finalize_after(NORMAL, sound=OPEN) == pytest.approx(0.7)
    assert turns.finalize_after(NORMAL, sound=None) == pytest.approx(0.7)
    now = 100.0
    assert not turns.finalize_due(True, False, now - 0.4, 0.0, now, "normal", sound=SURE)
    assert not turns.finalize_due(True, False, now - 0.4, 0.0, now, NORMAL)
    assert turns.finalize_due(True, False, now - 0.4, 0.0, now, NORMAL, sound=SURE)
    assert not turns.finalize_due(True, True, now - 0.4, 0.0, now, NORMAL, sound=SURE)  # never while they talk


def test_hebrew_is_not_judged_by_its_sound():
    """The model's languages do not include Hebrew: its words get the text rules and Soniox only."""
    assert turnsound.judged("Run the tests in billing.")
    assert not turnsound.judged("תריץ את הבדיקות של שירות התשלומים.")
    assert not turnsound.judged("תעשה rebase על dev.")


def test_the_sound_model_is_the_one_inside_the_pinned_pipecat_wheel_and_scores_between_zero_and_one():
    path = turnsound.model_path()
    assert path.name == "smart-turn-v3.2-cpu.onnx" and "pipecat" in path.parts and path.stat().st_size > 1_000_000
    rate = turnsound.RATE
    t = np.arange(rate * 2) / rate
    tone = (np.sin(2 * np.pi * 220 * t) * 8000).astype(np.int16)
    score = turnsound.score(tone.tobytes())
    assert score is not None and 0.0 <= score <= 1.0
    assert turnsound.score(b"") is None  # nothing was heard: nothing to judge


def test_the_last_eight_seconds_of_the_turn_are_kept_and_no_more():
    heard = turnsound.Heard()
    second = np.zeros(turnsound.RATE, np.int16).tobytes()
    for _ in range(12):
        heard.frame(second, bot_speaking=False)
    assert len(heard.audio()) == turnsound.KEEP_SECS * turnsound.RATE * 2
    heard.clear()
    assert heard.audio() == b""


def test_a_turn_with_the_bot_s_own_voice_in_it_is_not_judged_by_its_sound():
    """On speakers the microphone hears the bot: the model would judge the bot's sentence, not the user's."""
    heard = turnsound.Heard()
    second = np.zeros(turnsound.RATE, np.int16).tobytes()
    heard.frame(second, bot_speaking=False)
    heard.frame(second, bot_speaking=True)  # the user talks over the voice
    assert heard.audio() == b""


def test_a_new_turn_starts_just_before_its_first_word_and_forgets_the_reply_before_it():
    heard = turnsound.Heard()
    second = np.zeros(turnsound.RATE, np.int16).tobytes()
    heard.frame(second, bot_speaking=True)  # the bot's reply, then quiet
    heard.frame(second, bot_speaking=False)
    heard.begin()  # the voice detector hears the user
    heard.frame(second, bot_speaking=False)
    assert len(heard.audio()) == int((1 + turnsound.PRE_SPEECH_SECS) * turnsound.RATE) * 2
    heard.begin(bot_speaking=True)  # a turn begun over the voice
    assert heard.audio() == b""


# ---------- on the call ----------

from test_orchestrator import client_for, d  # noqa: E402,F401  (d is the daemon fixture)
from test_turn_taking import _ears  # noqa: E402


def test_on_the_call_the_three_signals_set_the_wait_and_the_timing_line_keeps_them(d, monkeypatch):
    import asyncio
    import time

    async def run():
        ears = _ears(d, monkeypatch)
        monkeypatch.setitem(d.turns.LEVELS, "normal", NORMAL)  # the candidate, to see the signals reach the rule
        monkeypatch.setattr(d, "_soniox_ears", lambda: True)
        now = time.time()
        d.state.user_started_at, d.state.finalize_asked_at, d.state.turn_sound = now - 3, 0.0, 0.93
        assert ears._settle("Run the tests in the billing package.", False) == 0.3
        assert d.state.turn_signals == {"wait": 300, "endpoint": True, "sound": 0.93}
        d.state.finalize_asked_at = now - 0.2  # the final came because Pointe asked for it: Soniox had not ended it
        assert ears._settle("Run the tests in the billing package.", False) == 0.6
        d.state.turn_sound = None
        assert ears._settle("Run the tests in the billing package.", False) == 1.0
        d.state.turn_sound, d.state.finalize_asked_at = 0.93, 0.0
        assert ears._settle("תריץ את הבדיקות של שירות התשלומים.", False) == 0.6  # Hebrew: the words and Soniox only
        assert "sound" not in d.state.turn_signals
        assert ears._settle("Open the parser and then", False) == 3.0
        monkeypatch.setattr(d, "_soniox_ears", lambda: False)  # other ears cut on silence: their final is no opinion
        assert ears._settle("Run the tests in the billing package.", False) == 0.6

    asyncio.run(run())


def test_the_voice_is_judged_at_each_stop_and_forgotten_when_it_comes_back(d, monkeypatch):
    import asyncio

    from pipecat.frames.frames import InputAudioRawFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
    from pipecat.processors.frame_processor import FrameDirection

    judged = []

    def score(pcm):
        judged.append(len(pcm))
        return 0.91

    async def run():
        ears = _ears(d, monkeypatch)
        monkeypatch.setattr(d.turnsound, "score", score)
        down = FrameDirection.DOWNSTREAM
        second = np.zeros(16000, np.int16).tobytes()
        await d.SonioxEars.process_frame(ears, InputAudioRawFrame(audio=second, sample_rate=16000, num_channels=1), down)
        await d.SonioxEars.process_frame(ears, VADUserStartedSpeakingFrame(), down)
        await d.SonioxEars.process_frame(ears, InputAudioRawFrame(audio=second, sample_rate=16000, num_channels=1), down)
        await d.SonioxEars.process_frame(ears, VADUserStoppedSpeakingFrame(), down)
        await asyncio.sleep(0.2)
        assert d.state.turn_sound == 0.91
        assert judged == [int((1 + d.turnsound.PRE_SPEECH_SECS) * 16000) * 2]  # the turn, not the quiet before it
        await d.SonioxEars.process_frame(ears, VADUserStartedSpeakingFrame(), down)
        assert d.state.turn_sound is None
        monkeypatch.setitem(d.PREFS.values, "turns.patience", "patient")  # Patient does not use it: not computed
        await d.SonioxEars.process_frame(ears, VADUserStoppedSpeakingFrame(), down)
        await asyncio.sleep(0.1)
        assert d.state.turn_sound is None and len(judged) == 1

    asyncio.run(run())


def test_soniox_is_asked_sooner_only_for_a_voice_that_sounded_finished_and_the_ask_is_remembered():
    source = (ROOT / "pointe" / "daemon.py").read_text()
    assert "sound=state.turn_sound if turnsound.judged(" in source
    assert "self._asked = state.finalize_asked_at = now" in source
