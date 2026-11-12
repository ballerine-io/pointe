"""Whisper mode: the owner whispers in an open office; Pointe answers briefly and quietly, and typing is one tap away.

A daemon pref ("whisper"), not one of modes.py's exclusive modes: it sits beside brainstorm, push to talk and the voice
lock, like the microphone setting does. It changes only how the call sounds and how long the replies are:

- the bot's audio is scaled down in the daemon before it leaves (both clients, every protocol version);
- the microphone audio is raised (x2.5, soft limiter) and the voice detector gets a whisper profile (lower volume and
  confidence floors, a longer stop), so a whisper starts a turn and times a yes;
- the brain is told to keep to one short sentence.

It never changes what voice may do. A whispered yes goes through exactly the same approval check as a spoken one, and
the voice lock is not lowered: a whisper that does not match the voiceprint counts as "not the owner" (fail closed).
"""

import re
from collections.abc import Callable

import numpy as np
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import Frame, InputAudioRawFrame, OutputAudioRawFrame, VADParamsUpdateFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

OUTPUT_GAIN = 0.5  # the bot at half amplitude (-6 dB): less disturbance, less echo
INPUT_GAIN = 2.5  # before the voice detector, through a soft limiter; see bench/results/whisper.md
VAD_WHISPER = {"confidence": 0.5, "min_volume": 0.35, "start_secs": 0.2, "stop_secs": 0.4}
MAX_WORDS = 20  # the reply rule's length

REPLY_RULE = ("[whisper mode is on: the user is whispering in a shared room and can read the screen. Answer in one short "
              f"sentence, at most {MAX_WORDS} words; for anything longer, say it is on the screen. Approvals and sends "
              "follow the usual rules. You cannot turn whisper mode on or off: the user says \"whisper mode\" or \"back to "
              "normal\", or taps the button; never say the mode changed.]")

_ON = re.compile(r"^\W*(?:(?:ok(?:ay)?|so|hey|pointe)\W+)?(?:whisper(?:ing)? mode(?: on)?|(?:turn on |start )?whisper(?:ing)? "
                 r"mode|let'?s whisper|i(?:'ll| will)? whisper)\W*$|^\W*(?:מצב לחישה|מצב שקט|לחישה)\W*$", re.I)
_OFF = re.compile(r"^\W*(?:(?:ok(?:ay)?|so|hey|pointe)\W+)?(?:back to normal(?: voice)?(?: mode)?|normal (?:voice|mode)(?: mode)?|"
                  r"(?:stop|end|exit|leave) whisper(?:ing)?(?: mode)?|whisper(?:ing)? mode off)\W*$|"
                  r"^\W*(?:חזרה לרגיל|מצב רגיל|בטל(?: את)? מצב לחישה|צא ממצב לחישה)\W*$", re.I)


def intent(text: str) -> bool | None:
    """A whole short utterance that turns whisper mode on (True) or off (False); None for anything else."""
    text = text.strip()
    if _ON.match(text):
        return True
    if _OFF.match(text):
        return False
    return None


def apply_gain(pcm: bytes, gain: float) -> bytes:
    """16-bit PCM times gain, through a soft limiter: unchanged below half scale, never past full scale."""
    if gain == 1.0 or not pcm:
        return pcm
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) * (gain / 32768.0)
    knee = 0.5
    over = np.abs(x) > knee
    x[over] = np.sign(x[over]) * (knee + (1 - knee) * np.tanh((np.abs(x[over]) - knee) / (1 - knee)))
    return np.clip(np.rint(x * 32768.0), -32767, 32767).astype(np.int16).tobytes()


def scale(pcm: bytes, gain: float) -> bytes:
    """The bot's output, quieter: a plain scale (gain < 1 cannot clip)."""
    if gain >= 1.0 or not pcm:
        return pcm
    return (np.frombuffer(pcm, dtype=np.int16).astype(np.float32) * gain).astype(np.int16).tobytes()


def status(on: bool, lock: str, microphone: str, held: str | None = None) -> dict:
    """What both clients show. `on` is the setting; `held` names a mode that suspends it ("drive"), and then nothing of
    whisper mode applies. `lock_note`: the voice lock stays as set, and a whisper may not match the voiceprint."""
    live = on and not held
    return {"on": on, "held": held if on else None, "output_gain": OUTPUT_GAIN if live else 1.0,
            "max_words": MAX_WORDS if live else None, "suggest_ptt": live and microphone != "ptt",
            "lock_note": LOCK_NOTES.get(lock) if live else None}


LOCK_NOTES = {
    "approvals": "Your voiceprint was learned from your normal voice. A whispered yes may not match it: then tap to approve.",
    "commands": "Your voiceprint was learned from your normal voice. Whispered words may not match it and may be kept "
                "out: type, or speak normally.",
    "everything": "Your voiceprint was learned from your normal voice. Whispered words may not match it and may be kept "
                  "out: type, or speak normally.",
}


class In(FrameProcessor):
    """Before the voice detector: raises the microphone while `raised()` holds, and tells the detector which profile to
    use whenever that changes (pipecat's own VADParamsUpdateFrame, so it applies in order with the audio)."""

    def __init__(self, raised: Callable[[], bool]):
        super().__init__()
        self._raised = raised
        self._profile: bool | None = None  # the profile last sent; None until the first audio

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame) and direction == FrameDirection.DOWNSTREAM:
            on = bool(self._raised())
            if on != self._profile and (self._profile is not None or on):
                await self.push_frame(VADParamsUpdateFrame(params=VADParams(**VAD_WHISPER) if on else VADParams()))
            self._profile = on
            if on:
                frame = InputAudioRawFrame(audio=apply_gain(frame.audio, INPUT_GAIN), sample_rate=frame.sample_rate,
                                           num_channels=frame.num_channels)
        await self.push_frame(frame, direction)


class Out(FrameProcessor):
    """Last before the transport: the bot's audio at OUTPUT_GAIN while `quiet()` holds, from the next chunk on."""

    def __init__(self, quiet: Callable[[], bool]):
        super().__init__()
        self._quiet = quiet

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, OutputAudioRawFrame) and self._quiet():
            frame.audio = scale(frame.audio, OUTPUT_GAIN)
        await self.push_frame(frame, direction)
