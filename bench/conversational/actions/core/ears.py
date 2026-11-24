"""The recognizer of the `llm-router` and `naive` arms: Soniox real-time, the model Pointe's default setup uses
(vendors.SONIOX_RT_MODEL), fed at real-time pace with the same lead and tail silence for every clip."""

import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path[0:0] = [str(Path(__file__).resolve().parents[4] / "pointe"), str(Path(__file__).resolve().parents[4])]
import vendors  # noqa: E402  (Pointe's own constant: the recognizer is the one its default setup uses)

RATE = 16000
CHUNK = 320  # 20 ms
LEAD, TAIL = 0.3, 1.2
URL = "wss://stt-rt.soniox.com/transcribe-websocket"
MODEL = vendors.SONIOX_RT_MODEL


async def transcribe(pcm: np.ndarray, api_key: str) -> dict:
    """{"text", "seconds" (audio streamed, for spend), "speech_end", "final_at"}."""
    import websockets

    audio = np.concatenate([np.zeros(int(LEAD * RATE), np.int16), pcm, np.zeros(int(TAIL * RATE), np.int16)])
    final: list[str] = []
    times: dict = {}
    async with websockets.connect(URL, max_size=None) as ws:
        await ws.send(json.dumps({"api_key": api_key, "model": MODEL, "audio_format": "pcm_s16le", "sample_rate": RATE,
                                  "num_channels": 1, "language_hints": ["en"], "enable_endpoint_detection": True}))

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                for tok in msg.get("tokens", []):
                    if tok.get("is_final") and tok["text"] not in ("<end>", "<fin>"):
                        final.append(tok["text"])
                if msg.get("error_code"):
                    times["error"] = str(msg.get("error_code"))
                    return
                if msg.get("finished"):
                    return

        task = asyncio.create_task(reader())
        start = time.time()
        times["speech_end"] = start + LEAD + len(pcm) / RATE
        for i in range(0, len(audio), CHUNK):
            await ws.send(audio[i:i + CHUNK].tobytes())
            wait = start + (i + CHUNK) / RATE - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
        await ws.send("")
        await asyncio.wait_for(task, 20)
        times["final_at"] = time.time()
    if times.get("error"):
        raise RuntimeError(f"Soniox error {times['error']}")
    return {"text": "".join(final).strip(), "seconds": len(audio) / RATE, **times}
