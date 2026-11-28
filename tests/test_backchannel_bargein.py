"""A backchannel over the voice ("mm-hm") does not cut it off; words that want the floor still do, at once.

From the conversation suite: "What's the status of each session?", then "mm-hm" while the answer played, and the voice
stopped 0.4 s in ("barge-in: voice well above the echo"), then treated "MMHM?" as a question and said the status again.
LiveKit's defaults ignore speech under 0.5 s and tell backchannels from interruptions; here a loud voice cuts only once
it has lasted BARGE_CONFIRM_SECS more and its words so far are not only a backchannel. A stop word, or two words of
something else, still cut at once (echo.is_barge_in), and a final backchannel never cuts or asks for a reply.

uv run pytest -q tests/test_backchannel_bargein.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from guards import ack_only  # noqa: E402
from test_orchestrator import d  # noqa: E402,F401  (d is the daemon fixture)
from test_turn_taking import _ears  # noqa: E402


def _loud_start(d, monkeypatch, heard: str, voiced_for: float):  # noqa: F811
    from pipecat.frames.frames import VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
    from pipecat.processors.frame_processor import FrameDirection

    cuts = []

    async def run():
        ears = _ears(d, monkeypatch)

        async def cut():
            cuts.append(time.time())
        monkeypatch.setattr(ears, "broadcast_interruption", cut)
        monkeypatch.setattr(d.ECHO, "speaking", True, raising=False)
        monkeypatch.setattr(d.LEVEL, "loud", lambda: True)
        monkeypatch.setattr(d, "BARGE_CONFIRM_SECS", 0.1)
        started = time.time()
        await ears.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        assert cuts == []  # not on the first sound
        d.state.hearing = (time.time(), heard)
        await asyncio.sleep(voiced_for)
        if voiced_for < 0.1:
            await ears.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.2)
        return started

    started = asyncio.run(run())
    return cuts, started


def test_a_backchannel_over_the_voice_does_not_cut_it(d, monkeypatch):  # noqa: F811
    cuts, _ = _loud_start(d, monkeypatch, "Mm-hm", 0.15)
    assert cuts == []


def test_a_voice_that_goes_on_with_words_cuts_it_soon(d, monkeypatch):  # noqa: F811
    cuts, started = _loud_start(d, monkeypatch, "Wait, just tell me about", 0.15)
    assert len(cuts) == 1 and cuts[0] - started < 0.3


def test_a_final_backchannel_is_an_acknowledgment_even_heard_as_a_question():
    assert ack_only("MMHM?") and ack_only("Uh-huh?")
    assert not ack_only("Okay?")  # "okay?" may ask


def test_a_backchannel_whose_words_come_late_still_does_not_cut(d, monkeypatch):  # noqa: F811
    """From the suite's second round: at the confirm time the recognizer had no live words yet for "mm-hm", and a voice
    with no words cut the bot. Without words the cut waits up to BARGE_WORDS_SECS more for them."""
    from pipecat.frames.frames import VADUserStartedSpeakingFrame
    from pipecat.processors.frame_processor import FrameDirection

    cuts = []

    async def run():
        ears = _ears(d, monkeypatch)

        async def cut():
            cuts.append(time.time())
        monkeypatch.setattr(ears, "broadcast_interruption", cut)
        monkeypatch.setattr(d.ECHO, "speaking", True, raising=False)
        monkeypatch.setattr(d.LEVEL, "loud", lambda: True)
        monkeypatch.setattr(d, "BARGE_CONFIRM_SECS", 0.05)
        monkeypatch.setattr(d, "BARGE_WORDS_SECS", 0.3)
        d.state.hearing = (0.0, "")
        await ears.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.12)
        d.state.hearing = (time.time(), "Mm-hm")  # the words arrive after the confirm time
        await asyncio.sleep(0.4)

    asyncio.run(run())
    assert cuts == []


def test_a_wordless_short_sound_over_the_voice_does_not_cut_it(d, monkeypatch):  # noqa: F811
    """From the third probe: "mm-hm" got no live words at all before its final, and 0.6 s of voice cut the bot. A voice
    with no words cuts only once it has lasted BARGE_WORDS_SECS; a real interruption has words long before that."""
    from pipecat.frames.frames import VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
    from pipecat.processors.frame_processor import FrameDirection

    cuts = []

    async def run():
        ears = _ears(d, monkeypatch)

        async def cut():
            cuts.append(time.time())
        monkeypatch.setattr(ears, "broadcast_interruption", cut)
        monkeypatch.setattr(d.ECHO, "speaking", True, raising=False)
        monkeypatch.setattr(d.LEVEL, "loud", lambda: True)
        monkeypatch.setattr(d, "BARGE_CONFIRM_SECS", 0.05)
        monkeypatch.setattr(d, "BARGE_WORDS_SECS", 0.4)
        d.state.hearing = (0.0, "")
        await ears.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.25)  # about 0.9 s of "mm-hm" in real time, scaled
        await ears.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.4)

    asyncio.run(run())
    assert cuts == []


def test_a_wordless_voice_must_outlast_a_backchannel_before_it_cuts(d):  # noqa: F811
    """The third probe's "mm-hm" was voiced for 0.94 s with no live words; the wordless cut came at 0.6 s."""
    assert d.BARGE_CONFIRM_SECS + d.BARGE_WORDS_SECS >= 1.0


# From the synthetic barge-in set (bench/conversational/dialogues/bargein.toml, 2026-11-28): a doubled listener sound or
# one heard half way still cut the voice in 5 of 30 backchannels: "Yeah, yeah." and "Okay, okay" as live words are two
# words in a row (echo.is_barge_in), "Mm-h" is "mm" and "h", and "Yes, yes." read as a final was not a backchannel.

def _interim_over_the_voice(d, monkeypatch, text: str) -> list:  # noqa: F811
    from pipecat.frames.frames import InterimTranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection

    cuts = []

    async def run():
        ears = _ears(d, monkeypatch)

        async def cut():
            cuts.append(text)
        monkeypatch.setattr(ears, "broadcast_interruption", cut)
        monkeypatch.setattr(d.ECHO, "speaking", True, raising=False)
        await ears.process_frame(InterimTranscriptionFrame(text, "u", "t"), FrameDirection.DOWNSTREAM)

    asyncio.run(run())
    return cuts


import pytest  # noqa: E402


@pytest.mark.parametrize("text", ["Yeah, yeah", "Okay, ok", "Yes, yes", "Mm-h", "Mm-hm, mm-hm", "Uh-huh, yeah"])
def test_a_doubled_or_half_heard_listener_sound_over_the_voice_does_not_cut_it(d, monkeypatch, text):  # noqa: F811
    assert _interim_over_the_voice(d, monkeypatch, text) == []


@pytest.mark.parametrize("text", ["Okay, stop", "No, no", "Yeah, but wait", "Yes, tell billing"])
def test_listener_words_with_anything_else_still_cut_at_once(d, monkeypatch, text):  # noqa: F811
    assert _interim_over_the_voice(d, monkeypatch, text) == [text]


def test_listener_sounds_are_only_listener_sounds():
    from guards import listener_sounds

    assert all(listener_sounds(t) for t in ("Yeah, yeah.", "Yes, yes.", "Mm-h", "Okay, okay.", "mhm", "Right, right."))
    assert not any(listener_sounds(t) for t in ("Okay, stop.", "No, no.", "Yes, do it.", "Yeah, yeah, yeah, yeah, yeah.",
                                                  "", "Stop."))
