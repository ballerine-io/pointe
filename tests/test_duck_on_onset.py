"""The voice steps back the moment a voice comes over it, and is decided on after: a cut or full volume again.

The independent review (item 5): the voice stopped 1.3 s after a recorded "stop" at the median, against 0.4 s, because
the cut waits for words (BARGE_CONFIRM_SECS, then up to BARGE_WORDS_SECS) so that "mm-hm" does not stop it. Now the
voice is ducked at the voice's onset, before any words, and the words decide: a backchannel or a cough brings it back
to full volume, real words cut it as before. A client that says it can duck (the "duck" capability in its hello) is
told at once and lowers its own playback; for any other the daemon scales the audio it sends.

uv run pytest -q tests/test_duck_on_onset.py
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import d  # noqa: E402,F401  (d is the daemon fixture)
from test_turn_taking import _ears  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class FakeLink:
    def __init__(self, duckable: bool):
        self.duckable = duckable
        self.texts: list[dict] = []

    async def send_text(self, text: str) -> None:
        self.texts.append(json.loads(text))


def _call(d, monkeypatch, duckable: bool):  # noqa: F811
    import phone

    link, serializer = FakeLink(duckable), phone.PhoneSerializer()
    monkeypatch.setattr(d.state, "call_socket", link)
    monkeypatch.setattr(d.state, "call_client", serializer)
    return link, serializer


def _over_the_voice(d, monkeypatch, heard: str, voiced_for: float, duckable: bool = True):  # noqa: F811
    from pipecat.frames.frames import VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
    from pipecat.processors.frame_processor import FrameDirection

    link, serializer = _call(d, monkeypatch, duckable)
    cuts, at_onset = [], {}

    async def run():
        ears = _ears(d, monkeypatch)

        async def cut():
            cuts.append(time.time())
        monkeypatch.setattr(ears, "broadcast_interruption", cut)
        monkeypatch.setattr(d.ECHO, "speaking", True, raising=False)
        monkeypatch.setattr(d.LEVEL, "loud", lambda: True)
        monkeypatch.setattr(d, "BARGE_CONFIRM_SECS", 0.1)
        await ears.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0)  # the duck is sent at once, off the frame's path
        at_onset["texts"], at_onset["gain"] = list(link.texts), serializer.gain
        d.state.hearing = (time.time(), heard)
        await asyncio.sleep(voiced_for)
        if voiced_for < 0.1:
            await ears.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.25)

    asyncio.run(run())
    return cuts, at_onset, link, serializer


def test_a_voice_over_the_bot_ducks_it_at_once_before_any_words(d, monkeypatch):  # noqa: F811
    cuts, at_onset, link, serializer = _over_the_voice(d, monkeypatch, "Mm-hm", 0.15)
    assert at_onset["texts"] == [{"type": "duck", "gain": d.DUCK_GAIN}]
    assert at_onset["gain"] == 1.0  # a client that ducks itself: the audio is not scaled twice


def test_a_backchannel_brings_the_voice_back_to_full_volume_and_does_not_cut_it(d, monkeypatch):  # noqa: F811
    cuts, _, link, serializer = _over_the_voice(d, monkeypatch, "Mm-hm", 0.15)
    assert cuts == []
    assert link.texts == [{"type": "duck", "gain": d.DUCK_GAIN}, {"type": "duck", "gain": 1.0}]
    assert serializer.gain == 1.0


def test_a_cough_with_no_words_brings_the_voice_back(d, monkeypatch):  # noqa: F811
    cuts, _, link, _ = _over_the_voice(d, monkeypatch, "", 0.05)
    assert cuts == [] and link.texts[-1] == {"type": "duck", "gain": 1.0}


def test_real_words_cut_the_voice_and_the_next_line_is_at_full_volume(d, monkeypatch):  # noqa: F811
    cuts, _, link, serializer = _over_the_voice(d, monkeypatch, "Wait, just tell me about", 0.15)
    assert len(cuts) == 1
    assert link.texts[-1] == {"type": "duck", "gain": 1.0} and serializer.gain == 1.0


def test_an_older_client_gets_quieter_audio_from_the_daemon_instead(d, monkeypatch):  # noqa: F811
    _, at_onset, link, serializer = _over_the_voice(d, monkeypatch, "Mm-hm", 0.15, duckable=False)
    assert at_onset["texts"] == [] and at_onset["gain"] == d.DUCK_GAIN
    assert link.texts == [] and serializer.gain == 1.0  # and full volume again after the backchannel


def test_the_voice_is_never_left_ducked(d, monkeypatch):  # noqa: F811
    """Whatever happens to the decision (a task cancelled with the call, an error), the duck ends by itself."""
    link, serializer = _call(d, monkeypatch, duckable=False)
    monkeypatch.setattr(d, "DUCK_MAX_SECS", 0.05)

    async def run():
        await d._duck_voice(True)
        assert serializer.gain == d.DUCK_GAIN
        await asyncio.sleep(0.15)

    asyncio.run(run())
    assert serializer.gain == 1.0


def test_the_bot_stopping_ends_the_duck(d, monkeypatch):  # noqa: F811
    from pipecat.frames.frames import BotStoppedSpeakingFrame
    from pipecat.processors.frame_processor import FrameDirection

    link, serializer = _call(d, monkeypatch, duckable=True)

    async def run():
        ears = _ears(d, monkeypatch)
        await d._duck_voice(True)
        await ears.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await asyncio.sleep(0)

    asyncio.run(run())
    assert link.texts[-1] == {"type": "duck", "gain": 1.0}


def test_no_duck_when_the_voice_is_not_above_the_echo(d, monkeypatch):  # noqa: F811
    """The bot's own echo trips the voice detector on loud speakers: that must not make the voice dip."""
    from pipecat.frames.frames import VADUserStartedSpeakingFrame
    from pipecat.processors.frame_processor import FrameDirection

    link, _ = _call(d, monkeypatch, duckable=True)

    async def run():
        ears = _ears(d, monkeypatch)
        monkeypatch.setattr(d.ECHO, "speaking", True, raising=False)
        monkeypatch.setattr(d.LEVEL, "loud", lambda: False)
        await ears.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0)

    asyncio.run(run())
    assert link.texts == []


def test_the_serializer_scales_the_bots_audio_by_its_gain():
    import phone
    from pipecat.frames.frames import OutputAudioRawFrame

    serializer = phone.PhoneSerializer()
    pcm = (np.ones(480, dtype=np.int16) * 10000).tobytes()
    frame = OutputAudioRawFrame(pcm, phone.OUT_RATE, 1)
    assert asyncio.run(serializer.serialize(frame)) == pcm
    serializer.gain = 0.3
    out = np.frombuffer(asyncio.run(serializer.serialize(frame)), dtype=np.int16)
    assert int(out[0]) == 3000


def test_a_client_that_ducks_itself_says_so_in_its_hello():
    import calllink

    link = calllink.CallLink.__new__(calllink.CallLink)
    for caps, duckable in ((["ptt", "resume", "duck"], True), (["ptt", "resume"], False)):
        link.serializer = __import__("phone").PhoneSerializer()
        link.token, link.grace, link._text, link._wake = "t", 0, [], asyncio.Event()
        link._audio, link._audio_bytes = [], 0
        link._hello(json.dumps({"type": "hello", "protocol": 5, "capabilities": caps}))
        assert link.duckable is duckable


def test_the_page_ducks_its_own_playback_and_says_it_can():
    page = (ROOT / "pointe" / "ui.html").read_text()
    assert "capabilities: ['ptt', 'resume', 'duck']" in page
    assert "m.type === 'duck'" in page and "call.duck.gain.setTargetAtTime" in page


def test_the_apps_duck_their_own_playback_and_say_they_can():
    wire = (ROOT / "apps" / "PointeKit" / "Sources" / "PointeKit" / "Wire.swift").read_text()
    call = (ROOT / "apps" / "PointeKit" / "Sources" / "PointeUI" / "CallWire.swift").read_text()
    assert '"duck"' in wire and 'case "duck":' in wire
    assert "case .duck(let gain):" in call and "playout.duck(gain)" in call
