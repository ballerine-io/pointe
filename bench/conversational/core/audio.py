"""Speech in and out, all local and pinned: Kokoro-82M (mlx-audio) renders every voice, Whisper large-v3-turbo
(mlx-whisper) scores every adapter's spoken output. Both models are the ones assets.py pins; nothing is downloaded here.

PCM is int16 mono. RATE is the suite's rate (16 kHz, what the recognizer and Soniox take); Kokoro renders 24 kHz.
"""

import hashlib
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import no_telemetry  # noqa: E402,F401  (mlx-audio's dependencies may load onnxruntime)

RATE = 16000
KOKORO_RATE = 24000
KOKORO = "mlx-community/Kokoro-82M-bf16"
WHISPER = "mlx-community/whisper-large-v3-turbo"
_tts = None
_asr_path = None


def resample(pcm: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return pcm
    n = int(len(pcm) * dst / src)
    return np.interp(np.linspace(0, len(pcm), n, endpoint=False), np.arange(len(pcm)), pcm.astype(np.float32))


def to_int16(x: np.ndarray) -> np.ndarray:
    if x.dtype == np.int16:
        return x
    return np.clip(np.asarray(x) * (32767 if np.abs(x).max(initial=0) <= 1.5 else 1), -32768, 32767).astype(np.int16)


def _model():
    global _tts
    if _tts is None:
        import assets
        from mlx_audio.tts.utils import load_model

        _tts = load_model(assets.snapshot(KOKORO, local_files_only=True), model_type="kokoro")
    return _tts


def kokoro(text: str, voice: str, rate: int = RATE) -> np.ndarray:
    """One utterance in one panel voice, int16 at `rate`."""
    parts = [np.asarray(r.audio, dtype=np.float32)
             for r in _model().generate(text, voice=voice, lang_code=voice[:1], speed=1.0, verbose=False)]
    audio = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
    return to_int16(resample(audio, KOKORO_RATE, rate) if rate != KOKORO_RATE else audio)


def warm() -> None:
    kokoro("Ready.", "af_heart")


def transcribe(pcm: np.ndarray, rate: int = RATE) -> str:
    """The one recognizer used to score spoken output, for every adapter: Whisper large-v3-turbo at its pinned commit,
    English, temperature 0."""
    global _asr_path
    import mlx_whisper

    if _asr_path is None:
        import assets

        _asr_path = str(assets.snapshot(WHISPER, local_files_only=True))
    x = resample(pcm.astype(np.float32), rate, 16000) / 32768.0
    if len(x) < 16000 // 4:
        return ""
    result = mlx_whisper.transcribe(x.astype(np.float32), path_or_hf_repo=_asr_path, language="en", temperature=0.0,
                                    condition_on_previous_text=False)
    return (result.get("text") or "").strip()


def voiced_end(pcm: np.ndarray, rate: int = RATE, floor: int = 500) -> float:
    """Seconds of trailing silence: the last word ends before the clip does."""
    loud = np.flatnonzero(np.abs(pcm.astype(np.int32)) > floor)
    return (len(pcm) - 1 - int(loud[-1])) / rate if len(loud) else 0.0


def spans(frames: list[tuple[float, np.ndarray]], since: float = 0.0, threshold: int = 400,
          gap: float = 0.7) -> list[tuple[float, float]]:
    """(start, end) receive times where the recorded output is audibly speaking; the same rule for every adapter.
    A frame's time is when it was received (start of the frame)."""
    out: list[list[float]] = []
    for t, pcm in frames:
        if t < since or not len(pcm) or np.abs(pcm.astype(np.int32)).mean() < threshold:
            continue
        end = t + len(pcm) / RATE
        if out and t - out[-1][1] <= gap:
            out[-1][1] = end
        else:
            out.append([t, end])
    return [(a, b) for a, b in out]


def cut(frames: list[tuple[float, np.ndarray]], start: float, end: float) -> np.ndarray:
    parts = [pcm for t, pcm in frames if start - 0.03 <= t <= end + 0.03]
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.int16)


def sha(pcm: np.ndarray) -> str:
    return hashlib.sha256(pcm.astype(np.int16).tobytes()).hexdigest()
