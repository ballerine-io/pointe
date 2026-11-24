"""Local text-to-speech on this Mac: time to first audio, speed, and intelligibility by round trip through local Whisper.

  uv run --extra local python -I bench/local_tts_bench.py synth --engine kokoro
  uv run --no-project --with mlx-audio==0.6.5 python -I bench/local_tts_bench.py synth --engine chatterbox
  uv run --no-project --with mlx-audio==0.6.5 --with "misaki[en]==0.9.4" --with <spaCy en_core_web_sm 3.8.0 wheel> \
      python -I bench/local_tts_bench.py synth --engine kokoro-mlx
  uv run --extra local python -I bench/local_tts_bench.py synth --engine kokoro-mlx-daemon   # the daemon's own mouth
  uv run --extra local python -I bench/local_tts_bench.py score     # Whisper large-v3-turbo transcribes each clip
  uv run --extra local python -I bench/local_tts_bench.py voices    # one passage per candidate voice, to listen to

The corpus is bench/tts_corpus.py (8 English, 8 Hebrew, 8 mixed), as in tts_bench.py. Synthesis is sequential, one model in
memory, after one warm-up clip. Kokoro is driven as pipecat's KokoroTTSService drives it (create_stream, lang en-us: the
daemon sets no other). Chatterbox Multilingual is mlx-audio's streaming generator with its language code set per clip.
No key is used. The recognizer is local Whisper, not tts_bench's Soniox, so word error here is not comparable to tts.md.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE), str(HERE.parent / "pointe"), str(HERE.parent)]
import no_telemetry  # noqa: E402,F401  (before kokoro-onnx loads onnxruntime)
from tts_corpus import TTS_CORPUS  # noqa: E402

OUT = HERE / "results"
RAW = OUT / "local-tts-raw.jsonl"
AUDIO = HERE / ".audio" / "local-tts"
REPS = 3


def kokoro_engine():
    from kokoro_onnx import Kokoro
    from pipecat.services.kokoro.tts import KOKORO_CACHE_DIR, _ensure_model_files

    model, voices = KOKORO_CACHE_DIR / "kokoro-v1.0.onnx", KOKORO_CACHE_DIR / "voices-v1.0.bin"
    _ensure_model_files(model, voices)
    kokoro = Kokoro(str(model), str(voices))

    async def stream(text: str, lang: str):
        async for samples, rate in kokoro.create_stream(text, voice="af_heart", lang="en-us", speed=1.0):
            yield np.asarray(samples, dtype=np.float32), rate

    return "kokoro-v1.0 (kokoro-onnx, en-us)", stream


def kokoro_mlx_engine():
    """The same Kokoro weights on the GPU through mlx-audio, which phonemizes with misaki (eSpeak NG for unknown words)."""
    from mlx_audio.tts.utils import load_model

    model = load_model("mlx-community/Kokoro-82M-bf16")

    async def stream(text: str, lang: str):
        for result in model.generate(text, voice="af_heart", lang_code="a", speed=1.0, verbose=False):
            yield np.asarray(result.audio, dtype=np.float32), 24000
            await asyncio.sleep(0)

    return "kokoro-82m (mlx-audio, en-us)", stream


def kokoro_mlx_daemon_engine():
    """kokoro_mlx.KokoroMLXTTSService, the service the daemon runs for `mouth: local:kokoro-mlx`, at the call's 24 kHz."""
    sys.path[0:0] = [str(HERE.parent / "pointe"), str(HERE.parent)]
    import kokoro_mlx

    kokoro_mlx.warm()
    tts = kokoro_mlx.KokoroMLXTTSService(sample_rate=24000)
    tts._sample_rate = 24000  # set by the pipeline's start frame in a call

    async def stream(text: str, lang: str):
        async for frame in tts.run_tts(text, "bench"):
            if hasattr(frame, "audio"):
                yield np.frombuffer(frame.audio, dtype=np.int16).astype(np.float32) / 32768.0, 24000

    return f"kokoro-82m (daemon: kokoro_mlx, {kokoro_mlx.DEFAULT_VOICE})", stream


VOICES = ["af_heart", "af_bella", "af_nicole", "bf_emma", "am_michael", "am_fenrir", "bm_george"]
PASSAGE = ("Billing finished the migration. Three tests failed, all in the invoice module, and it wants to know whether "
           "to retry them or roll back. Should I tell it to retry?")


def voices() -> None:
    """A passage per voice, as WAV files to listen to, with first audio and a round trip through local Whisper."""
    import wave

    import mlx_whisper

    sys.path[0:0] = [str(HERE.parent / "pointe"), str(HERE.parent)]
    import kokoro_mlx

    folder = HERE / ".audio" / "voice-samples"
    folder.mkdir(parents=True, exist_ok=True)
    model = kokoro_mlx._model()
    print("| voice | first audio | word error (round trip) | file |\n|---|---|---|---|")
    for voice in VOICES:
        kokoro_mlx.warm(voice)
        began, first, parts = time.perf_counter(), None, []
        for r in model.generate(PASSAGE, voice=voice, lang_code=kokoro_mlx.lang_code(voice), speed=1.0, verbose=False):
            first = first or time.perf_counter() - began
            parts.append(np.asarray(r.audio, dtype=np.float32))
        audio = np.concatenate(parts)
        path = folder / f"{voice}.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000)
            w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        pcm16 = np.interp(np.arange(0, len(audio), 1.5), np.arange(len(audio)), audio).astype(np.float32)
        heard = mlx_whisper.transcribe(pcm16, path_or_hf_repo="mlx-community/whisper-large-v3-turbo", temperature=0.0,
                                       language="en")["text"]
        from tts_bench import wer

        print(f"| {voice} | {first * 1000:.0f} ms | {wer(PASSAGE, heard):.2f} | {path.relative_to(HERE.parent)} |")


def chatterbox_engine():
    from huggingface_hub import snapshot_download
    from mlx_audio.tts.utils import load_model

    # The multilingual weights ship no default voice: the English release's conds.safetensors (its stock voice) is put
    # beside them, so no voice is cloned from anyone.
    folder = HERE / ".audio" / "chatterbox-multilingual"
    folder.mkdir(parents=True, exist_ok=True)
    for f in Path(snapshot_download("mlx-community/chatterbox-multilingual-v3")).iterdir():
        (folder / f.name).unlink(missing_ok=True)
        (folder / f.name).symlink_to(f.resolve())
    conds = Path(snapshot_download("mlx-community/chatterbox-fp16", allow_patterns=["conds.safetensors"])) / "conds.safetensors"
    (folder / "conds.safetensors").unlink(missing_ok=True)
    (folder / "conds.safetensors").symlink_to(conds.resolve())
    model = load_model(str(folder))

    async def stream(text: str, lang: str):
        for result in model.generate(text, lang_code="he" if lang in ("he", "mix") else "en", stream=True,
                                     streaming_interval=0.5, verbose=False):
            yield np.asarray(result.audio, dtype=np.float32), model.sample_rate
            await asyncio.sleep(0)

    return "chatterbox-multilingual-v3 (mlx-audio)", stream


async def synth(engine: str) -> None:
    name, stream = {"kokoro": kokoro_engine, "kokoro-mlx": kokoro_mlx_engine, "chatterbox": chatterbox_engine,
                    "kokoro-mlx-daemon": kokoro_mlx_daemon_engine}[engine]()
    AUDIO.mkdir(parents=True, exist_ok=True)
    async for _ in stream("Warming up.", "en"):
        pass
    with RAW.open("a") as out:
        for rep in range(REPS):
            for cid, lang, text in TTS_CORPUS:
                began, first, parts, rate = time.perf_counter(), None, [], 24000
                async for samples, rate in stream(text, lang):
                    if first is None and len(samples):
                        first = time.perf_counter() - began
                    parts.append(samples)
                total = time.perf_counter() - began
                pcm = (np.clip(np.concatenate(parts), -1, 1) * 32767).astype(np.int16) if parts else np.zeros(0, np.int16)
                path = AUDIO / f"{engine}_{cid}_{rep}.pcm"
                path.write_bytes(pcm.tobytes())
                out.write(json.dumps({"engine": name, "clip": cid, "lang": lang, "rep": rep, "ref": text, "ttfb": first,
                                      "total": total, "audio_s": len(pcm) / rate, "rate": rate, "pcm": str(path)},
                                     ensure_ascii=False) + "\n")
                out.flush()
            print(f"{name}: rep {rep + 1}/{REPS}", flush=True)


def score() -> None:
    from tts_bench import heard_as_hebrew, wer

    rows = [json.loads(line) for line in RAW.read_text().splitlines()]
    for r in rows:
        if "hyp" in r:
            continue
        import mlx_whisper

        pcm = np.frombuffer(Path(r["pcm"]).read_bytes(), dtype=np.int16).astype(np.float32) / 32768.0
        if r["rate"] != 16000:  # Whisper takes 16 kHz
            idx = np.arange(0, len(pcm), r["rate"] / 16000)
            pcm = np.interp(idx, np.arange(len(pcm)), pcm).astype(np.float32)
        r["hyp"] = mlx_whisper.transcribe(pcm, path_or_hf_repo="mlx-community/whisper-large-v3-turbo", temperature=0.0,
                                          language=None)["text"].strip()
    RAW.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print("| mouth | first audio, English p50 / p95 | first audio, all p50 / p95 | real-time factor p50 | word error EN / HE / mixed | Hebrew heard as Hebrew |")
    print("|---|---|---|---|---|---|")
    for engine in dict.fromkeys(r["engine"] for r in rows):
        g = [r for r in rows if r["engine"] == engine and r["ttfb"] is not None]
        ttfb = np.array([r["ttfb"] for r in g]) * 1000
        en = np.array([r["ttfb"] for r in g if r["lang"] == "en"]) * 1000
        rtf = np.median([r["total"] / r["audio_s"] for r in g if r["audio_s"]])
        werr = {lang: np.mean([wer(r["ref"], r["hyp"]) for r in g if r["lang"] == lang]) for lang in ("en", "he", "mix")}
        he = [r for r in g if r["lang"] == "he"]
        heard = sum(heard_as_hebrew("he", r["ref"], r["hyp"]) for r in he)
        print(f"| {engine} | {np.percentile(en, 50):.0f} / {np.percentile(en, 95):.0f} ms | "
              f"{np.percentile(ttfb, 50):.0f} / {np.percentile(ttfb, 95):.0f} ms | {rtf:.2f} | "
              f"{werr['en']:.2f} / {werr['he']:.2f} / {werr['mix']:.2f} | {heard} of {len(he)} |")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["synth", "score", "voices"])
    p.add_argument("--engine", choices=["kokoro", "kokoro-mlx", "chatterbox", "kokoro-mlx-daemon"], default="kokoro")
    a = p.parse_args()
    OUT.mkdir(exist_ok=True)
    if a.cmd == "voices":
        return voices()
    asyncio.run(synth(a.engine)) if a.cmd == "synth" else score()


if __name__ == "__main__":
    main()
