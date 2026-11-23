"""Synthetic speech: Kokoro-82M (Apache-2.0, `mlx-community/Kokoro-82M-bf16` pinned in assets.py), rendered once per
clip into `.audio/` (ignored) as 48 kHz 16-bit PCM, the rate the fake page's microphone plays. `audio.lock` holds the
SHA-256 of every clip; a rebuild that differs is allowed and recorded as audio_matches_lock: false."""

import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
AUDIO = HERE / ".audio"
ROOT = HERE.parents[1]
RATE = 48000
VOICES = ("af_heart", "am_michael", "bf_emma", "bm_george")  # US female, US male, British female, British male


def clip_key(text: str, voice: str, speed: float) -> str:
    return hashlib.sha256(f"kokoro-82m-bf16|{voice}|{speed}|{text}".encode()).hexdigest()[:24]


def _kokoro():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    sys.path.insert(0, str(ROOT))
    import kokoro_mlx  # noqa: E402  (Pointe's own loader: the pinned snapshot, local files only)

    return kokoro_mlx


def render(text: str, voice: str, speed: float = 1.0) -> Path:
    path = AUDIO / f"{clip_key(text, voice, speed)}.pcm"
    if path.exists():
        return path
    k = _kokoro()
    parts = [np.asarray(r.audio, dtype=np.float32) for r in
             k._model().generate(text, voice=voice, lang_code=k.lang_code(voice), speed=speed, verbose=False)]
    audio = np.concatenate(parts)
    up = np.interp(np.arange(len(audio) * 2) / 2, np.arange(len(audio)), audio)  # 24 kHz to 48 kHz
    pcm = (np.clip(up, -1, 1) * 32767 * 0.9).astype(np.int16)
    AUDIO.mkdir(exist_ok=True)
    path.write_bytes(pcm.tobytes())
    return path


def load(path: Path) -> np.ndarray:
    return np.frombuffer(path.read_bytes(), dtype=np.int16)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(clips: dict[str, dict], lock_path: Path, write_lock: bool = False) -> dict:
    """clips: {clip_id: {text, voice, speed}}. Returns {clip_id: path} and whether every clip matches the lock."""
    paths = {cid: render(c["text"], c["voice"], c.get("speed", 1.0)) for cid, c in clips.items()}
    hashes = {cid: sha(p) for cid, p in paths.items()}
    lock = json.loads(lock_path.read_text()) if lock_path.exists() else {}
    if write_lock or not lock:
        lock_path.write_text(json.dumps(hashes, indent=0, sort_keys=True) + "\n")
        lock = hashes
    return {"paths": paths, "matches_lock": all(lock.get(c) == h for c, h in hashes.items())}


def to_16k(pcm48: np.ndarray) -> np.ndarray:
    """What the page sends the daemon: 48 kHz averaged down to 16 kHz (tests/e2e/rig.py does the same)."""
    n = len(pcm48) // 3 * 3
    return pcm48[:n].reshape(-1, 3).mean(axis=1).astype(np.int16)
