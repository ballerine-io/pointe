"""Audio is built, not stored: every utterance is rendered once into .audio/ (ignored) and its SHA-256 is kept in the
benchmark's audio.lock. A rebuild that differs is allowed and the run records audio_matches_lock: false."""

import hashlib
import json
import tomllib
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
AUDIO = HERE / ".audio"


def voices() -> list[str]:
    return [v["id"] for v in tomllib.loads((HERE / "voices.toml").read_text())["voice"]]


def render(clips: dict[str, tuple[str, str]], lock: Path) -> tuple[dict[str, np.ndarray], bool]:
    """clips: id -> (text, voice). Returns id -> int16 PCM at audio.RATE, and whether every clip matches the lock."""
    from . import audio

    AUDIO.mkdir(parents=True, exist_ok=True)
    out, shas = {}, {}
    for cid, (text, voice) in sorted(clips.items()):
        path = AUDIO / f"{hashlib.sha256(f'{voice}|{text}'.encode()).hexdigest()[:24]}.npy"
        if not path.exists():
            np.save(path, audio.kokoro(text, voice))
        out[cid] = np.load(path)
        shas[cid] = audio.sha(out[cid])
    old = json.loads(lock.read_text()) if lock.exists() else {}
    matches = all(old.get(k) == v for k, v in shas.items()) if old else True
    if not old:
        lock.write_text(json.dumps(shas, indent=1, sort_keys=True) + "\n")
    return out, matches
