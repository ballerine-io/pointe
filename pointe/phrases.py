"""Short lines the voice says again and again, kept as audio: "Sent to billing." is heard at once, not a request later.

A turn the daemon answers itself ("Asking quarry.", "Sent to atlas.", "Approved.") waits for no model, so the mouth's
own request is most of what is left after the end of the turn: about 0.3 s at the median and 0.6 s at p90 on the
release suite (turn timing: tts_request to tts_first_byte). The same few lines come back on every call, and they sound
the same each time. So the mouth keeps the audio of every short line it made, keyed by the line and the mouth's
settings (voice, model, speed, rate), and plays it again from memory, in this call and the next. A call warms the lines it will need for the
sessions it has (warm), so even the first "Sent to billing." of a call is a hit.

What is kept is the audio only, never the words' timings: a line from memory gives no word timestamps, which the
brain front does not read (it tells the echo guard the whole line up front, daemon._bot_says). Only whole lines are
kept: one cut short, or one with an error in it, is not. A change of voice or speed is a new key, not a stale hit.
"""

import asyncio
import uuid
from collections import OrderedDict

from loguru import logger
from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame

MAX_WORDS = 6  # longer lines seldom repeat word for word
MAX_ITEMS = 128  # about 70 kB each at 24 kHz: under 10 MB
KEPT: OrderedDict[tuple, tuple[int, list[bytes]]] = OrderedDict()  # across calls: each call builds a new mouth


class Phrases:
    def __init__(self, mouth, store: OrderedDict | None = None) -> None:
        self.mouth = mouth
        self.kept = KEPT if store is None else store
        self.hits = self.misses = 0
        self._warming: set[str] = set()  # context ids of warm-ups: their word timestamps go nowhere
        self._made = mouth.run_tts
        self._timestamps = mouth.add_word_timestamps
        mouth.run_tts = self.run_tts
        mouth.add_word_timestamps = self._add_word_timestamps

    def key(self, text: str) -> tuple | None:
        text = " ".join(text.split())
        if not text or len(text.split()) > MAX_WORDS:
            return None
        return text, type(self.mouth).__name__, repr(getattr(self.mouth, "_settings", None)), self.mouth.sample_rate

    async def run_tts(self, text: str, context_id: str):
        key = self.key(text)
        kept = self.kept.get(key) if key else None
        if kept is not None:
            self.hits += 1
            self.kept.move_to_end(key)
            rate, chunks = kept
            logger.debug(f"phrase from memory: {text!r}")
            await self.mouth.stop_ttfb_metrics()
            for chunk in chunks:
                yield TTSAudioRawFrame(chunk, rate, 1, context_id=context_id)
            return
        if key:
            self.misses += 1
        chunks, rate, whole = [], self.mouth.sample_rate, False
        try:
            async for frame in self._made(text, context_id):
                if isinstance(frame, TTSAudioRawFrame):
                    chunks.append(frame.audio)
                    rate = frame.sample_rate
                elif isinstance(frame, ErrorFrame):
                    key = None
                yield frame
            whole = True
        finally:
            if whole and key and chunks:
                self._keep(key, rate, chunks)

    def _keep(self, key: tuple, rate: int, chunks: list[bytes]) -> None:
        self.kept[key] = (rate, chunks)
        self.kept.move_to_end(key)
        while len(self.kept) > MAX_ITEMS:
            self.kept.popitem(last=False)

    async def _add_word_timestamps(self, word_times, context_id=None, *args, **kwargs):
        if context_id in self._warming:
            return
        await self._timestamps(word_times, context_id, *args, **kwargs)

    async def warm(self, texts: list[str]) -> int:
        """Makes the lines not kept yet, one at a time, off the call: none of their audio reaches the call. The mouth's
        running context (ElevenLabs' previous_text, its timeline) is put back after each, so the next real line is
        asked exactly what it would have been. Returns how many were made."""
        made = 0
        for text in dict.fromkeys(texts):
            key = self.key(text)
            if key is None or key in self.kept:
                continue
            context_id = f"warm-{uuid.uuid4()}"
            saved = {a: getattr(self.mouth, a) for a in ("_previous_text", "_cumulative_time") if hasattr(self.mouth, a)}
            self._warming.add(context_id)
            try:
                async for _ in self.run_tts(text, context_id):
                    pass
                made += key in self.kept
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"phrase not warmed: {type(e).__name__}: {str(e)[:120]}")
            finally:
                self._warming.discard(context_id)
                for a, v in saved.items():
                    setattr(self.mouth, a, v)
        return made
