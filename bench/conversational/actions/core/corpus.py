"""Synthetic user speech: Kokoro-82M (Apache-2.0) through mlx-audio, the copy pinned in Pointe's assets.py. $0, no key.

Audio is built, not stored: `render()` writes 16 kHz mono int16 WAVs into `.audio/` (ignored) and `audio.lock` holds
the SHA-256 of every clip. A rebuild that differs is allowed; the run records `audio_matches_lock: false`.

A cut-off word is the clip truncated in code at a seeded point inside the first word, with a 10 ms fade. It is
labelled "truncated clip" everywhere it is shown.
"""

import hashlib
import json
import random
import sys
import threading
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
AUDIO = HERE / ".audio"
LOCK = HERE / "audio.lock"
RATE = 16000
KOKORO_RATE = 24000
MODEL = "mlx-community/Kokoro-82M-bf16"
_lock = threading.Lock()
_model = None


def _kokoro():
    global _model
    if _model is None:
        sys.path[0:0] = [str(HERE.parents[2] / "pointe"), str(HERE.parents[2])]
        import assets  # Pointe's pins: the model is read at its pinned commit
        from mlx_audio.tts.utils import load_model

        _model = load_model(assets.snapshot(MODEL, local_files_only=True), model_type="kokoro")
    return _model


def to_rate(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return x
    n = int(len(x) * dst / src)
    return np.interp(np.linspace(0, len(x), n, endpoint=False), np.arange(len(x)), x)


def synth(text: str, voice: str) -> np.ndarray:
    """16 kHz int16 speech. One Kokoro call at a time: MLX models are not shared across threads."""
    with _lock:
        model = _kokoro()
        parts = [np.asarray(r.audio, dtype=np.float32)
                 for r in model.generate(text, voice=voice, lang_code=voice[0], speed=1.0, verbose=False)]
    audio = to_rate(np.concatenate(parts) if parts else np.zeros(1, np.float32), KOKORO_RATE, RATE)
    return (np.clip(audio, -1, 1) * 32767).astype(np.int16)


def _speech_span(pcm: np.ndarray) -> tuple[int, int]:
    loud = np.nonzero(np.abs(pcm.astype(np.int32)) > 600)[0]
    return (int(loud[0]), int(loud[-1])) if len(loud) else (0, len(pcm))


def truncate(pcm: np.ndarray, seed: str, first_word: np.ndarray) -> tuple[np.ndarray, float]:
    """Cut inside the first word: at a seeded 30% to 50% of that word's own length (the word rendered alone in the
    same voice), then a 10 ms linear fade. A cut by fixed seconds left short words whole ("Yes" is about 0.3 s)."""
    onset = _speech_span(pcm)[0]
    a, b = _speech_span(first_word)
    keep = random.Random(seed).uniform(0.30, 0.50) * (b - a) / RATE
    end = min(len(pcm), onset + int(keep * RATE))
    out = pcm[:end].astype(np.float32)
    fade = min(len(out), int(0.010 * RATE))
    out[len(out) - fade:] *= np.linspace(1, 0, fade)
    return out.astype(np.int16), keep


def path_of(item_id: str) -> Path:
    return AUDIO / f"actions-{item_id}.wav"


def write_wav(path: Path, pcm: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
        w.writeframes(pcm.tobytes())


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def render(items: list[dict], write_lock: bool = False) -> dict:
    """Render every clip that is missing. Returns {"clips": n, "matches_lock": bool, "truncated": {id: seconds}}."""
    lock = json.loads(LOCK.read_text()) if LOCK.exists() else {}
    hashes, cuts = {}, {}
    for item in items:
        path = path_of(item["id"])
        if not path.exists():
            pcm = synth(item["text"], item["voice"])
            if item.get("truncate"):
                word = item["text"].split()[0].strip(",.!?")
                pcm, cuts[item["id"]] = truncate(pcm, item["id"], synth(word, item["voice"]))
            write_wav(path, pcm)
        hashes[f"actions/{item['id']}"] = sha(path)
    matches = all(lock.get(k) == v for k, v in hashes.items()) and bool(lock)
    if write_lock:
        lock.update(hashes)
        LOCK.write_text(json.dumps(dict(sorted(lock.items())), indent=1) + "\n")
        matches = True
    return {"clips": len(hashes), "matches_lock": matches, "truncated": cuts}


def load(item_id: str) -> np.ndarray:
    return read_wav(path_of(item_id))
