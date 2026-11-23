"""The recognizer of the baseline arms: Pointe's default ears (Soniox real-time, the model in vendors.py), streamed at
real-time pace at 16 kHz, biased with the four session names as Pointe biases its own stream with session names.
Transcripts are cached by clip and terms, so every baseline hears the same words for the same audio."""

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
CACHE = HERE / ".audio" / "transcripts.json"
RATE = 16000
CHUNK = 320  # 20 ms
_key: list[str] = []
_locks: dict = {}


def model() -> str:
    sys.path.insert(0, str(ROOT))
    import vendors  # noqa: E402

    return vendors.SONIOX_RT_MODEL


def _soniox_key() -> str:
    """Read once from the Keychain into this process; never printed, written or put in an argument list."""
    if not _key:
        for item in ("pointe.soniox-api-key", "soniox-api-key"):
            got = subprocess.run(["security", "find-generic-password", "-s", item, "-w"], capture_output=True, text=True)
            if got.returncode == 0 and got.stdout.strip():
                _key.append(got.stdout.strip())
                break
        else:
            raise RuntimeError("no Soniox key in the Keychain")
    return _key[0]


async def _stream(pcm16: np.ndarray, terms: list[str]) -> str:
    import websockets

    audio = np.concatenate([np.zeros(int(0.3 * RATE), np.int16), pcm16, np.zeros(int(1.2 * RATE), np.int16)])
    async with websockets.connect("wss://stt-rt.soniox.com/transcribe-websocket") as ws:
        await ws.send(json.dumps({"api_key": _soniox_key(), "model": model(), "audio_format": "pcm_s16le",
                                  "sample_rate": RATE, "num_channels": 1, "language_hints": ["en"],
                                  "context": {"terms": terms}}))
        final: list[str] = []

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                final.extend(t["text"] for t in msg.get("tokens", []) if t.get("is_final") and t["text"] not in ("<end>", "<fin>"))
                if msg.get("error_code"):
                    raise RuntimeError(f"Soniox: {msg.get('error_code')} {msg.get('error_message', '')[:80]}")
                if msg.get("finished"):
                    return

        task = asyncio.create_task(reader())
        start = time.time()
        for i in range(0, len(audio), CHUNK):
            await ws.send(audio[i:i + CHUNK].tobytes())
            wait = start + (i + CHUNK) / RATE - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
        await ws.send("")
        await asyncio.wait_for(task, 20)
    return "".join(final).strip()


def _cache() -> dict:
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


async def transcribe(clip_id: str, pcm16: np.ndarray, terms: list[str]) -> tuple[str, float, bool]:
    """(transcript, seconds of audio streamed, from cache)."""
    key = f"{model()}|{clip_id}|{','.join(terms)}"
    async with _locks.setdefault(key, asyncio.Lock()):
        return await _transcribe(key, pcm16, terms)


async def _transcribe(key: str, pcm16: np.ndarray, terms: list[str]) -> tuple[str, float, bool]:
    cache = _cache()
    seconds = len(pcm16) / RATE + 1.5
    if key in cache:
        return cache[key], seconds, True
    text = ""
    for attempt in range(3):
        try:
            text = await _stream(pcm16, terms)
            break
        except Exception:
            if attempt == 2:
                raise
            await asyncio.sleep(2 * (attempt + 1))
    cache = _cache()
    cache[key] = text
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=0))
    return text, seconds, False
