"""Ears and mouth for the reference arms (`naive`, `llm-router`): Soniox real-time, the recognizer of Pointe's default
setup, for speech in; local Kokoro for speech out, played at real-time pace into a recorded stream.

Times are on the runner's clock (adapter.now). A recorded frame's time is when its first sample would reach a speaker.
"""

import json
import queue
import re
import sys
import threading
import time
from pathlib import Path

import numpy as np

from . import audio, keys
from .adapter import now

sys.path[0:0] = [str(Path(__file__).resolve().parents[4] / "pointe"), str(Path(__file__).resolve().parents[4])]
import vendors  # noqa: E402  (SONIOX_RT_MODEL: the model Pointe's ears use)

FRAME = 320  # 20 ms at 16 kHz
SONIOX_URL = "wss://stt-rt.soniox.com/transcribe-websocket"


class SonioxEars:
    """One real-time stream per utterance. `hear` blocks while the audio plays at real-time pace and returns the
    final transcript and the time Soniox's endpoint arrived."""

    def __init__(self):
        self.stream_seconds = 0.0

    def hear(self, pcm: np.ndarray, on_start=None) -> dict:
        from websockets.sync.client import connect

        lead = np.zeros(int(0.3 * audio.RATE), dtype=np.int16)
        tail = np.zeros(int(6.0 * audio.RATE), dtype=np.int16)
        stream = np.concatenate([lead, pcm, tail])
        final, got = [], {"end": None, "error": None}
        opened = now()
        with connect(SONIOX_URL, open_timeout=10) as ws:
            ws.send(json.dumps({"api_key": keys.get("SONIOX_API_KEY"), "model": vendors.SONIOX_RT_MODEL,
                                "audio_format": "pcm_s16le", "sample_rate": audio.RATE, "num_channels": 1,
                                "language_hints": ["en"], "enable_endpoint_detection": True}))

            def reader():
                try:
                    for raw in ws:
                        msg = json.loads(raw)
                        for tok in msg.get("tokens", []):
                            if tok.get("is_final"):
                                if tok["text"] == "<end>":
                                    got["end"] = got["end"] or now()
                                elif tok["text"] != "<fin>":
                                    final.append(tok["text"])
                        if msg.get("error_code"):
                            got["error"] = msg.get("error_message")
                        if msg.get("finished") or msg.get("error_code"):
                            return
                except Exception as e:  # a closed stream ends the reader; the error is kept, never read as silence
                    got["error"] = got["error"] or type(e).__name__

            t = threading.Thread(target=reader, daemon=True)
            t.start()
            start = now()
            speech = (start + len(lead) / audio.RATE, start + (len(lead) + len(pcm)) / audio.RATE)
            if on_start:
                on_start(speech)
            for i in range(0, len(stream), FRAME):
                if got["end"] and i > len(lead) + len(pcm):
                    break
                ws.send(stream[i:i + FRAME].tobytes())
                wait = start + (i + FRAME) / audio.RATE - now()
                if wait > 0:
                    time.sleep(wait)
            try:
                ws.send("")
            except Exception:
                pass
            t.join(8)
        self.stream_seconds += now() - opened
        return {"text": "".join(final).strip(), "final_at": got["end"] or now(), "speech": speech,
                "error": got["error"]}


class LocalMouth:
    """Kokoro, sentence by sentence: the first sentence plays while the next renders. Every voiced frame is recorded
    with its play time."""

    def __init__(self, voice: str = "af_heart"):
        self.voice = voice
        self.frames: list[tuple[float, np.ndarray]] = []
        self._q: queue.Queue = queue.Queue()
        self._pcm: queue.Queue = queue.Queue()
        self.spoken: list[tuple[float, str]] = []
        self._stop = False
        self.playing = False
        self._rendering = False
        threading.Thread(target=self._render, daemon=True).start()
        threading.Thread(target=self._play, daemon=True).start()

    def say(self, text: str) -> None:
        self._q.put(text)

    def _render(self) -> None:
        audio.warm()
        while not self._stop:
            try:
                text = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            self._rendering = True
            self.spoken.append((now(), text))
            for sentence in [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]:
                self._pcm.put(audio.kokoro(sentence, self.voice))
            self._rendering = False

    def _play(self) -> None:
        while not self._stop:
            try:
                pcm = self._pcm.get(timeout=0.05)
            except queue.Empty:
                continue
            self.playing, start = True, now()
            for i in range(0, len(pcm), FRAME):
                chunk = pcm[i:i + FRAME]
                at = start + i / audio.RATE
                wait = at - now()
                if wait > 0:
                    time.sleep(wait)
                if np.abs(chunk.astype(np.int32)).max(initial=0) > 0:
                    self.frames.append((at, chunk))
            self.playing = self._pcm.qsize() > 0

    def busy(self) -> bool:
        return self.playing or not self._q.empty() or not self._pcm.empty() or self._rendering

    def close(self) -> None:
        self._stop = True
