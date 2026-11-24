"""The recognizer of the `naive` and `llm-router` arms: Soniox real-time, the model Pointe's default setup uses
(vendors.SONIOX_RT_MODEL), English hint, no context terms. Audio is streamed at real-time pace, then one second of
silence, then the end of stream. The key goes in the first message on the socket, never on a command line."""

import asyncio
import json
import sys
import time
from pathlib import Path

import websockets

sys.path[0:0] = [str(Path(__file__).resolve().parents[4] / "pointe"), str(Path(__file__).resolve().parents[4])]
import vendors  # noqa: E402

URL = "wss://stt-rt.soniox.com/transcribe-websocket"
MODEL = vendors.SONIOX_RT_MODEL
CHUNK = 320 * 2  # 20 ms of 16 kHz int16


async def _transcribe(pcm: bytes, rate: int, key: str) -> dict:
    async with websockets.connect(URL, max_size=None) as ws:
        await ws.send(json.dumps({"api_key": key, "model": MODEL, "audio_format": "pcm_s16le", "sample_rate": rate,
                                  "num_channels": 1, "language_hints": ["en"]}))
        final: list[str] = []

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("error_code"):
                    raise RuntimeError(f"soniox: {msg.get('error_code')} {str(msg.get('error_message'))[:120]}")
                final.extend(t["text"] for t in msg.get("tokens", []) if t.get("is_final") and t["text"] not in ("<end>", "<fin>"))
                if msg.get("finished"):
                    return

        task = asyncio.create_task(reader())
        audio = pcm + bytes(rate * 2)  # one second of silence after the speech
        start = time.time()
        for i in range(0, len(audio), CHUNK):
            await ws.send(audio[i:i + CHUNK])
            wait = start + (i + CHUNK) / (2 * rate) - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
        await ws.send("")
        await asyncio.wait_for(task, 20)
    return {"text": "".join(final).strip(), "seconds": len(audio) / (2 * rate), "model": MODEL}


def transcribe(pcm: bytes, rate: int, key: str) -> dict:
    for attempt in range(3):
        try:
            return asyncio.run(_transcribe(pcm, rate, key))
        except (OSError, asyncio.TimeoutError, websockets.WebSocketException):
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
