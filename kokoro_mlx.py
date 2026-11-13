"""Kokoro on the Mac's GPU (mlx-audio): the mouth of "Voice stays on your Mac", `mouth: local:kokoro-mlx[:voice]`.

The same Kokoro-82M weights as kokoro-onnx, run by MLX, so speech starts sooner: 0.2 s to the first English audio against
1.3 s (bench/results/local.md). misaki turns English into phonemes, with spaCy and eSpeak NG (GPL-3.0, in the optional
extra only) for words it does not know. No Hebrew voice: Kokoro has none.
"""

import asyncio
import concurrent.futures
import threading
import time
from collections.abc import AsyncGenerator

import numpy as np
from loguru import logger
from pipecat.audio.utils import create_stream_resampler
from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService

MODEL = "mlx-community/Kokoro-82M-bf16"  # Apache-2.0 (hexgrad/Kokoro-82M)
DEFAULT_VOICE = "af_heart"  # the voice Kokoro's own card grades highest; samples of the others: docs/features/voice-stays-local.md
RATE = 24000
# One thread for every MLX call of the mouth: the model and its pipelines are made and used on it, never concurrently.
_THREAD = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="kokoro-mlx")
_loaded = None
_lock = threading.Lock()


def lang_code(voice: str) -> str:
    """Kokoro's voices name their accent first: af_/am_ American English, bf_/bm_ British."""
    return voice[:1] if voice[:1] in ("a", "b") else "a"


def _model():
    """Loaded once per daemon, on the mouth's thread, from the local copy (the Hub is asked only when it is missing)."""
    global _loaded
    with _lock:
        if _loaded is None:
            from huggingface_hub import snapshot_download
            from mlx_audio.tts.utils import load_model

            try:
                path = snapshot_download(MODEL, local_files_only=True)
            except Exception:
                path = MODEL
            _loaded = load_model(path, model_type="kokoro")  # from a folder, mlx-audio guesses the type from its name
        return _loaded


def warm(voice: str = DEFAULT_VOICE) -> str | None:
    """The first sentence builds misaki's pipeline and compiles the kernels: about 20 s. Done at daemon start, on the
    mouth's thread, so the greeting does not wait for it. Returns the failure, or None."""
    def run():
        for _ in _model().generate("Ready.", voice=voice, lang_code=lang_code(voice), speed=1.0, verbose=False):
            pass

    began = time.time()
    try:
        _THREAD.submit(run).result()
        logger.info(f"local mouth ready in {time.time() - began:.1f} s")
    except Exception as e:
        logger.warning(f"local mouth not warmed: {type(e).__name__}: {e}")
        return f"{type(e).__name__}: {e}"
    return None


class KokoroMLXTTSService(TTSService):
    """Speaks each sentence as Kokoro makes it: a segment is sent as soon as it exists, not after the whole reply."""

    def __init__(self, *, voice: str = DEFAULT_VOICE, speed: float = 1.0, **kwargs):
        super().__init__(push_start_frame=True, push_stop_frames=True,
                         settings=TTSSettings(model=MODEL, voice=voice, language=None), **kwargs)
        self._voice, self._speed = voice, speed
        self._resampler = create_stream_resampler()

    def can_generate_metrics(self) -> bool:
        return True

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        stop = threading.Event()  # a cut-off reply stops making audio at the next segment

        def make():
            try:
                for result in _model().generate(text, voice=self._voice, lang_code=lang_code(self._voice),
                                                 speed=self._speed, verbose=False):
                    if stop.is_set():
                        break
                    loop.call_soon_threadsafe(queue.put_nowait, np.asarray(result.audio, dtype=np.float32))
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, e)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        await self.start_tts_usage_metrics(text)
        _THREAD.submit(make)
        try:
            while (item := await queue.get()) is not None:
                if isinstance(item, Exception):
                    yield ErrorFrame(error=f"local mouth: {type(item).__name__}: {item}")
                    continue
                await self.stop_ttfb_metrics()
                pcm = (np.clip(item, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
                yield TTSAudioRawFrame(audio=await self._resampler.resample(pcm, RATE, self.sample_rate),
                                       sample_rate=self.sample_rate, num_channels=1, context_id=context_id)
        finally:
            stop.set()
            await self.stop_ttfb_metrics()
