"""A fake adapter for the offline tests: no agent, no keys, no models. It plays the user's audio at real-time pace,
then, a planted delay after the voiced end, plays a reply (a tone burst) into its recorded output with the same
clock and frame rule as the real arms."""

import threading
import time

import numpy as np

from core import audio
from core.adapter import Event, now

FRAME = 320


class Echo:
    name = "echo"
    capabilities = frozenset({"audio_in", "speech_out"})

    def __init__(self, delay: float = 1.5, reply_s: float = 1.0, said: str = "Seven tests failed."):
        self.delay, self.reply_s, self.said = delay, reply_s, said
        self._frames: list[tuple[float, np.ndarray]] = []
        self._events: list[Event] = []

    def start(self, sessions, env) -> None:
        pass

    def setup_type(self, text: str) -> float:
        return now()

    def idle_since(self, t):
        return t

    def say(self, pcm, rate):
        arr = np.frombuffer(pcm, dtype=np.int16) if isinstance(pcm, bytes) else pcm
        start = now()
        time.sleep(len(arr) / rate)  # the mic plays it at real-time pace
        end = start + (len(arr) / rate - audio.voiced_end(arr, rate))
        threading.Thread(target=self._reply, args=(end,), daemon=True).start()
        return start, end

    def _reply(self, heard: float) -> None:
        n = int(self.reply_s * audio.RATE)
        tone = (8000 * np.sin(2 * np.pi * 440 * np.arange(n) / audio.RATE)).astype(np.int16)
        start = heard + self.delay
        for i in range(0, n, FRAME):
            at = start + i / audio.RATE
            wait = at - now()
            if wait > 0:
                time.sleep(wait)
            self._frames.append((at, tone[i:i + FRAME]))
        self._events.append(Event(now(), "said", None, self.said))

    def frames(self):
        return self._frames

    def speaking(self) -> bool:
        s = audio.spans(self._frames, since=now() - 2)
        return bool(s) and now() - s[-1][1] < 0.5

    def events(self):
        out, self._events = self._events, []
        return out

    def speech(self):
        return [(a, b, audio.cut(self._frames, a, b).tobytes()) for a, b in audio.spans(self._frames)]

    def versions(self):
        return {"echo": "1"}

    def spend(self):
        return []

    def stop(self) -> None:
        pass
