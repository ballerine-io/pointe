"""How the voice sounded when it stopped: the probability that the turn is over, from the audio alone (intonation, a
trailing "and then…"), by the Smart Turn v3.2 model that ships inside the pinned pipecat wheel (BSD 2-Clause, 8.7 MB,
ONNX on the CPU). It runs on this Mac: no audio leaves it, nothing is downloaded. One signal of three that
turns.settle is given; today it is written on each turn's timing line and changes no wait (docs/design/turn-taking.md
§6). The model was not measured on Hebrew, so Hebrew words are not judged by it."""

import re
import threading
from collections import deque
from pathlib import Path

import no_telemetry  # noqa: F401  (before onnxruntime loads)
import numpy as np

RATE = 16000  # the call's microphone rate (phone.IN_RATE) and the model's
KEEP_SECS = 8  # the model reads the last 8 s of a turn
MODEL = "smart-turn-v3.2-cpu.onnx"
_HEBREW = re.compile(r"[֐-׿]")

_session = None
_lock = threading.Lock()


def model_path() -> Path:
    import pipecat.audio.turn.smart_turn as package

    return Path(package.__file__).parent / "data" / MODEL


def judged(text: str) -> bool:
    """Whether words in this language may be judged by their sound."""
    return not _HEBREW.search(text)


def _load():
    global _session
    with _lock:
        if _session is None:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            options.inter_op_num_threads = options.intra_op_num_threads = 1
            _session = ort.InferenceSession(str(model_path()), sess_options=options, providers=["CPUExecutionProvider"])
    return _session


def score(pcm: bytes) -> float | None:
    """The probability that the speaker has finished, from 16 kHz mono int16 audio of the turn so far (its last 8 s).
    None when there is nothing to judge or the model cannot run: the settle then goes by the other signals."""
    if not pcm:
        return None
    try:
        from pipecat.audio.turn.smart_turn._whisper_features import compute_whisper_log_mel_features

        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        keep = KEEP_SECS * RATE
        audio = audio[-keep:] if len(audio) >= keep else np.pad(audio, (keep - len(audio), 0))  # silence first, as trained
        features = np.expand_dims(compute_whisper_log_mel_features(audio, do_normalize=True), axis=0)
        with _lock:
            session = _session
        session = session or _load()
        return float(np.asarray(session.run(None, {"input_features": features})[0]).reshape(-1)[0])
    except Exception:  # a broken install must not take the call down: the text rules and Soniox still decide
        return None


PRE_SPEECH_SECS = 0.4  # kept from before the voice detector's start: it says "started" 0.2 s into the first word


class Heard:
    """The microphone audio of the turn being put together: the last KEEP_SECS of it, from just before its first word
    (begin). A turn that has the bot's own voice in it (speakers) is not judged: the model would hear the bot's
    sentence end, not the user's."""

    def __init__(self) -> None:
        self._frames: deque[bytes] = deque()
        self._bytes = 0
        self._bot = False

    def frame(self, pcm: bytes, bot_speaking: bool) -> None:
        self._bot = self._bot or bot_speaking
        self._frames.append(pcm)
        self._bytes += len(pcm)
        limit = KEEP_SECS * RATE * 2
        while self._bytes - len(self._frames[0]) >= limit:
            self._bytes -= len(self._frames.popleft())

    def begin(self, bot_speaking: bool = False) -> None:
        """A new turn's first word: what came before it (silence, the bot's last reply) is not part of the turn."""
        tail = b"".join(self._frames)[-int(PRE_SPEECH_SECS * RATE) * 2:]
        self._frames = deque([tail] if tail else [])
        self._bytes, self._bot = len(tail), bot_speaking

    def audio(self) -> bytes:
        return b"" if self._bot else b"".join(self._frames)[-KEEP_SECS * RATE * 2:]

    def clear(self) -> None:
        self._frames.clear()
        self._bytes, self._bot = 0, False
