"""Recognizers. `Whisper` is the one pinned local recognizer that scores every adapter's spoken output (and runs the
question detector on it). `soniox` is the ears of Pointe's default setup, used by the naive and llm-router arms."""

import asyncio
import json
import sys
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
WHISPER_REPO = "mlx-community/whisper-large-v3-turbo"
SONIOX_URL = "wss://stt-rt.soniox.com/transcribe-websocket"


def resample(pcm: np.ndarray, rate: int, to: int) -> np.ndarray:
    if rate == to or not len(pcm):
        return pcm.astype(np.float32)
    n = int(len(pcm) * to / rate)
    return np.interp(np.linspace(0, len(pcm), n, endpoint=False), np.arange(len(pcm)), pcm).astype(np.float32)


class Whisper:
    """Whisper large-v3-turbo at the commit pinned in assets.py, read from the local cache only (no download)."""

    _lock = threading.Lock()
    _path = None

    @classmethod
    def path(cls) -> str:
        if cls._path is None:
            sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
            import no_telemetry  # noqa: F401
            import assets
            cls._path = assets.snapshot(WHISPER_REPO, local_files_only=True)
        return cls._path

    @classmethod
    def revision(cls) -> str:
        sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
        import assets
        return assets.revision(WHISPER_REPO)

    @classmethod
    def transcribe(cls, pcm_int16: np.ndarray, rate: int, language: str | None = "en") -> str:
        if len(pcm_int16) < rate // 4:
            return ""
        audio = resample(pcm_int16.astype(np.float32) / 32768.0, rate, 16000)
        import mlx_whisper
        with cls._lock:
            out = mlx_whisper.transcribe(audio, path_or_hf_repo=cls.path(), language=language, temperature=0.0,
                                         condition_on_previous_text=False)
        return (out.get("text") or "").strip()

    @classmethod
    async def atranscribe(cls, pcm_int16: np.ndarray, rate: int) -> str:
        return await asyncio.to_thread(cls.transcribe, pcm_int16, rate)


async def soniox(pcm_int16: np.ndarray, rate: int, key: str, model: str, realtime: bool = True) -> tuple[str, float]:
    """One utterance through Soniox real-time (the model Pointe's ears use), streamed at real-time pace.
    Returns (text, seconds of audio sent) for the spend row."""
    import websockets
    pcm16 = resample(pcm_int16.astype(np.float32), rate, 16000).clip(-32768, 32767).astype(np.int16)
    tail = np.zeros(16000, dtype=np.int16)  # a second of silence so the endpoint is found
    audio = np.concatenate([pcm16, tail])
    final: list = []
    for attempt in range(3):
        try:
            async with websockets.connect(SONIOX_URL, open_timeout=15) as ws:
                await ws.send(json.dumps({"api_key": key, "model": model, "audio_format": "pcm_s16le",
                                          "sample_rate": 16000, "num_channels": 1, "language_hints": ["en", "he"],
                                          "enable_endpoint_detection": True}))
                final = []

                async def reader():
                    async for raw in ws:
                        msg = json.loads(raw)
                        for tok in msg.get("tokens", []):
                            if tok.get("is_final") and tok["text"] not in ("<end>", "<fin>"):
                                final.append(tok["text"])
                        if msg.get("finished") or msg.get("error_code"):
                            return

                task = asyncio.create_task(reader())
                step = 1600  # 100 ms
                t0 = time.time()
                for i in range(0, len(audio), step):
                    await ws.send(audio[i:i + step].tobytes())
                    if realtime:
                        wait = t0 + (i + step) / 16000 - time.time()
                        if wait > 0:
                            await asyncio.sleep(wait)
                await ws.send("")
                await asyncio.wait_for(task, 20)
            return "".join(final).strip(), len(audio) / 16000
        except Exception:
            if attempt == 2:
                raise
            await asyncio.sleep(2 * (attempt + 1))
    return "", len(audio) / 16000
