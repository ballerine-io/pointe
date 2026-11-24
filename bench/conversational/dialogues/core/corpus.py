"""The speech corpus: every line the scripted user may say, rendered once and cached in .audio/ (ignored), with noise
generated in code. English voices are Kokoro-82M v1.0 (local, Apache-2.0, $0, no key): four native panel voices and
four non-native ones (a Kokoro voice of another language reading English, for an accent). Hebrew and mixed lines, and
English with an Israeli accent, are OpenAI gpt-4o-mini-tts (the `oa-he` voice): Kokoro has no Hebrew. A "|" in a line is
a 1.6 s pause inside one turn. `run.py corpus` writes every clip and audio.lock, the SHA-256 of each."""

import hashlib
import json
import sys
import threading
import tomllib
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
AUDIO = HERE / ".audio"
LOCK = HERE / "audio.lock"
PAUSE_SECS = 1.6
OA_INSTRUCTIONS = ("Speak like a software developer from Tel Aviv talking to a voice assistant: natural pace, a clear "
                   "Israeli accent in English, native Hebrew; say code names in English.")
RATE = 24000


def voices() -> dict:
    return tomllib.loads((HERE / "voices.toml").read_text())["voice"]


def panel() -> list:
    """The four native Kokoro voices: the babble noise is made of them."""
    return ["af_heart", "am_michael", "bf_emma", "bm_george"]


class Kokoro:
    _k = None
    _lock = threading.Lock()

    @classmethod
    def get(cls):
        if cls._k is None:
            sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
            import no_telemetry  # noqa: F401
            import assets
            from kokoro_onnx import Kokoro as K
            model, voices_bin = assets.ensure_kokoro()  # verified against the pinned SHA-256; already on disk
            cls._k = K(str(model), str(voices_bin))
        return cls._k

    @classmethod
    def say(cls, text: str, voice: str, lang: str) -> np.ndarray:
        with cls._lock:
            audio, rate = cls.get().create(text, voice=voice, lang=lang, speed=1.0)
        assert rate == RATE
        return (np.clip(audio, -1, 1) * 32767).astype(np.int16)


def pink(n: int, seed: int) -> np.ndarray:
    """Pink noise by filtering white noise with a 1/f spectrum (Voss-free FFT shaping), unit RMS."""
    rng = np.random.default_rng(seed)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.arange(len(spec), dtype=np.float64)
    f[0] = 1.0
    out = np.fft.irfft(spec / np.sqrt(f), n)
    return out / (np.sqrt(np.mean(out ** 2)) or 1.0)


BABBLE_TEXT = ("We moved the meeting to Thursday and nobody told the kitchen. The bus was late again this morning. "
               "I think the blue one is cheaper but the other one lasts longer. She said the garden needs more sun.")


def babble(n: int, seed: int, exclude: str) -> np.ndarray:
    """The three other panel voices reading filler text at once, unit RMS."""
    mix = np.zeros(n, dtype=np.float64)
    for i, v in enumerate([v for v in panel() if v != exclude]):
        clip = Kokoro.say(BABBLE_TEXT, v, voices()[v]["lang"]).astype(np.float64)
        start = (seed * 7919 + i * 3001) % max(1, len(clip))
        rolled = np.roll(clip, -start)
        reps = int(np.ceil(n / len(rolled)))
        mix += np.tile(rolled, reps)[:n]
    return mix / (np.sqrt(np.mean(mix ** 2)) or 1.0)


def add_noise(clean: np.ndarray, noise: str, seed: int, voice: str) -> np.ndarray:
    kind, db = noise.split(":")
    sig = clean.astype(np.float64)
    rms = np.sqrt(np.mean(sig ** 2)) or 1.0
    n = len(sig)
    shape = pink(n, seed) if kind == "pink" else babble(n, seed, voice)
    mixed = sig + shape * rms / (10 ** (float(db) / 20))
    peak = np.abs(mixed).max()
    if peak > 32767:
        mixed *= 32767 / peak
    return mixed.astype(np.int16)


def clip_name(voice: str, text: str, noise: str | None) -> str:
    return hashlib.sha256(f"{voice}|{noise or 'clean'}|{text}".encode()).hexdigest()[:20] + ".wav"


def openai_tts(text: str) -> np.ndarray:
    """One line through OpenAI gpt-4o-mini-tts, 24 kHz PCM. The key goes only into this process's client."""
    import openai
    key = _key("OPENAI_API_KEY", "openai-api-key")
    client = openai.OpenAI(api_key=key)
    out = client.audio.speech.create(model="gpt-4o-mini-tts", voice="ash", input=text, instructions=OA_INSTRUCTIONS,
                                     response_format="pcm")
    return np.frombuffer(out.read(), dtype=np.int16).copy()


def _key(env_name: str, item: str) -> str:
    import os
    import subprocess
    if os.environ.get(env_name):
        return os.environ[env_name]
    for name in (f"pointe.{item}", item):
        got = subprocess.run(["security", "find-generic-password", "-s", name, "-w"], capture_output=True, text=True)
        if got.returncode == 0 and got.stdout.strip():
            return got.stdout.strip()
    raise RuntimeError(f"no key for {env_name}")


def speak(text: str, voice: str) -> np.ndarray:
    parts = []
    for i, part in enumerate(p.strip() for p in text.split("|")):
        if i:
            parts.append(np.zeros(int(RATE * PAUSE_SECS), np.int16))
        if voice.startswith("oa-"):
            parts.append(openai_tts(part))
        else:
            parts.append(Kokoro.say(part, voice, voices()[voice]["lang"]))
    return np.concatenate(parts)


def render(voice: str, text: str, noise: str | None) -> Path:
    AUDIO.mkdir(exist_ok=True)
    path = AUDIO / clip_name(voice, text, noise)
    if not path.exists():
        pcm = speak(text, voice)
        pcm = np.concatenate([np.zeros(RATE // 5, np.int16), pcm, np.zeros(RATE // 5, np.int16)])
        if noise:
            seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
            pcm = add_noise(pcm, noise, seed, voice)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
            w.writeframes(pcm.tobytes())
    return path


def load(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_lock() -> dict:
    return json.loads(LOCK.read_text()) if LOCK.exists() else {}
