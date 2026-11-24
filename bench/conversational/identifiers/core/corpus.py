"""The synthetic speech corpus (design 4.5): Kokoro-82M v1.0 voices, noise made in code, an audio.lock of hashes.

Audio is built, not stored: `run.py corpus` renders into bench/conversational/identifiers/.audio/ (ignored by git). Every clip is
16 kHz mono int16 PCM, the bytes every audio adapter receives. A rebuild that differs from audio.lock is allowed and
the run records audio_matches_lock: false.

Needs the `local` extra (kokoro-onnx), already pinned in assets.py: `uv run --locked --extra local ...`.
"""

import hashlib
import json
import random
import sys
import tomllib
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
AUDIO = HERE / ".audio"
VOICES = tomllib.loads((HERE / "voices.toml").read_text())["voice"]
RATE = 16000
KOKORO_RATE = 24000
FILLER = (
    "The quarterly review moved to the small room on the second floor, next to the printer.",
    "Has anyone seen the blue folder with the venue contracts from last spring?",
    "I think the train was late again, so the morning standup started without half of us.",
    "We could order lunch from the place on the corner if the meeting runs long today.",
    "The heating in this building never works on Mondays, so bring a jumper next week.",
    "She said the new chairs arrive on Thursday, but they said that about the desks too.",
)


def _kokoro():
    sys.path[0:0] = [str(HERE.parents[2] / "pointe"), str(HERE.parents[2])]
    import no_telemetry  # noqa: F401  (before kokoro-onnx loads onnxruntime)
    import assets
    from kokoro_onnx import Kokoro

    model, voices = assets.ensure_kokoro()
    return Kokoro(str(model), str(voices))


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    """Windowed-sinc low-pass at the new Nyquist, then linear interpolation: no aliasing from 24 to 16 kHz."""
    if src == dst:
        return x.astype(np.float32)
    cutoff = 0.5 * min(src, dst) / src * 0.95
    n = np.arange(-64, 65)
    taps = 2 * cutoff * np.sinc(2 * cutoff * n) * np.hamming(len(n))
    y = np.convolve(x.astype(np.float32), taps / taps.sum(), mode="same")
    t = np.arange(0, len(y) * dst // src) * src / dst
    return np.interp(t, np.arange(len(y)), y).astype(np.float32)


def render(kokoro, text: str, voice: dict) -> np.ndarray:
    samples, rate = kokoro.create(text, voice=voice["id"], speed=1.0, lang=voice["lang"])
    return resample(np.asarray(samples, dtype=np.float32), rate, RATE)


def babble(kokoro, speaker: str, length: int, seed: int) -> np.ndarray:
    """The three other panel voices reading filler text at once, each from a seeded offset (design 4.5)."""
    rng = random.Random(seed)
    mix = np.zeros(length, dtype=np.float32)
    for v in [v for v in VOICES if v["id"] != speaker]:
        text = " ".join(rng.sample(FILLER, 3))
        x = render(kokoro, text, v)
        x = np.tile(x, int(np.ceil((length + RATE) / len(x))))
        start = rng.randrange(0, RATE)
        mix += x[start:start + length] / (np.sqrt(np.mean(x ** 2)) + 1e-9)
    return mix


def mix_snr(speech: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    ps = np.mean(speech[np.abs(speech) > 1e-4] ** 2)
    pn = np.mean(noise ** 2) + 1e-12
    return speech + noise * np.sqrt(ps / (pn * 10 ** (snr_db / 10)))


def to_pcm(x: np.ndarray) -> bytes:
    peak = np.max(np.abs(x)) or 1.0
    scale = 0.9 / peak if peak > 0.9 else 1.0  # louder babble would clip: the whole clip is scaled, the SNR stays
    return (np.clip(x * scale, -1, 1) * 32767).astype("<i2").tobytes()


def build(clips: list[dict], bench: str) -> dict:
    """clips: {name, text, voice, noise_db (None for clean), seed}. Writes .audio/<bench>/<name>.pcm and
    <bench>/audio.lock; returns {name: sha256}."""
    out = AUDIO / bench
    out.mkdir(parents=True, exist_ok=True)
    kokoro = _kokoro()
    voices = {v["id"]: v for v in VOICES}
    hashes = {}
    for c in clips:
        speech = render(kokoro, c["text"], voices[c["voice"]])
        if c.get("noise_db") is not None:
            speech = mix_snr(speech, babble(kokoro, c["voice"], len(speech), c["seed"]), c["noise_db"])
        pcm = to_pcm(speech)
        (out / f"{c['name']}.pcm").write_bytes(pcm)
        hashes[c["name"]] = hashlib.sha256(pcm).hexdigest()
        print(f"  {c['name']}: {len(pcm) / 2 / RATE:.1f} s", flush=True)
    return hashes


def load(bench: str, name: str) -> bytes:
    return (AUDIO / bench / f"{name}.pcm").read_bytes()


def matches_lock(bench: str, lock: Path) -> bool:
    if not lock.exists():
        return False
    want = json.loads(lock.read_text())["clips"]
    for name, sha in want.items():
        p = AUDIO / bench / f"{name}.pcm"
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != sha:
            return False
    return True
