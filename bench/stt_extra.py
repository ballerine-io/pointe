"""Extra speech-to-text systems for stt_bench.py, registered without editing it.

  .venv/bin/python -I bench/stt_extra.py run [--systems soniox-v6,gemini-transcribe-live] [--concurrency 6]
  .venv/bin/python -I bench/stt_extra.py report            # same scoring as stt_bench.py, written to results/report.txt

Reuses stt_bench's corpus, voices, noise, real-time pacing, result file and scorer. Rows already in
results/results.jsonl for a system are not re-run. Systems measured earlier keep their rows:
soniox (stt-rt-v5 then; the arm now runs vendors.SONIOX_RT_MODEL), scribe (scribe_v2_realtime, the only ElevenLabs
realtime model its API accepts), gemini (gemini-3.8-live echo). soniox-daemon-v5 and -v6 add the daemon's endpoint
settings (vendors.build_ears), run side by side on 2026-11-20 when v5 was about to be removed.
"""

import os
import argparse
import asyncio
import contextlib
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import websockets

sys.path[:0] = [str(Path(__file__).parent), str(Path(__file__).parent.parent / "pointe"), str(Path(__file__).parent.parent)]
import no_telemetry  # noqa: E402,F401  (before pipecat's Silero loads onnxruntime)
import stt_bench as sb  # noqa: E402
import vendors  # noqa: E402

OUT = sb.OUT
UNMEASURED = OUT / "stt-unmeasured.json"
VAD_STOP_DELAY = 0.4  # s after speech end, when a pipeline's VAD would tell Gemini the stream ended
DAEMON_ENDPOINT = {"endpoint_sensitivity": -0.5, "max_endpoint_delay_ms": 2500}  # as vendors.build_ears sets them


async def run_soniox_rt(audio: np.ndarray, model: str, endpoint: dict | None = None,
                        finalize_after_ms: int | None = None) -> dict:
    """finalize_after_ms: with words not yet ended by an <end>, ask for them (`finalize`) once the daemon's voice detector
    (Silero, stop_secs 0.2) has said the voice stopped and that much silence has passed since the sound ended, as the
    daemon does (PttGate.tick, turns.finalize_due); <fin> then ends the segment like <end>. Word times cannot tell this:
    they lag the audio."""
    async with websockets.connect("wss://stt-rt.soniox.com/transcribe-websocket") as ws:
        await ws.send(json.dumps({
            "api_key": sb.keychain("soniox-api-key"), "model": model, "audio_format": "pcm_s16le",
            "sample_rate": sb.RATE, "num_channels": 1, "language_hints": ["en", "he"],
            "enable_endpoint_detection": True, **(endpoint or {}),
        }))
        final: list[str] = []
        times: dict = {"end": None}
        ends: list = []  # [wall time, the segment's text] per <end> or <fin> that closed words
        st = {"open": False, "asked": None, "sent_ms": 0.0, "finalized": 0, "segments": 0, "stopped_ms": None, "seg_from": 0}
        vad = None
        if finalize_after_ms:
            from pipecat.audio.vad.silero import SileroVADAnalyzer
            from pipecat.audio.vad.vad_analyzer import VADParams, VADState

            vad = SileroVADAnalyzer(sample_rate=sb.RATE, params=VADParams(stop_secs=VAD_STOP_SECS))
            vad.set_sample_rate(sb.RATE)

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                for tok in msg.get("tokens", []):
                    if tok["text"] in ("<end>", "<fin>"):
                        times["end"] = times["end"] or time.time()
                        if st["open"]:
                            ends.append([time.time(), "".join(final[st["seg_from"]:]).strip()])
                            st["seg_from"] = len(final)
                        st["segments"] += st["open"]
                        st["open"] = False
                        continue
                    st["open"] = True
                    if tok.get("is_final"):
                        final.append(tok["text"])
                if msg.get("finished") or msg.get("error_code"):
                    if msg.get("error_code"):
                        times["error"] = msg.get("error_message")
                    return

        async def send(chunk: bytes):
            await ws.send(chunk)
            st["sent_ms"] += len(chunk) / 2 / sb.RATE * 1000
            if vad is None:
                return
            before, now = vad._vad_state, vad._run_analyzer(chunk)
            if now == VADState.QUIET and before != VADState.QUIET:
                st["stopped_ms"] = st["sent_ms"]
            elif now in (VADState.STARTING, VADState.SPEAKING):
                st["stopped_ms"] = None
            stopped = st["stopped_ms"]
            if st["open"] and stopped is not None and st["asked"] != stopped \
                    and st["sent_ms"] - (stopped - VAD_STOP_SECS * 1000) >= finalize_after_ms:
                st["asked"] = stopped
                st["finalized"] += 1
                await ws.send('{"type": "finalize"}')

        task = asyncio.create_task(reader())
        speech_end = await sb.stream(send, audio)
        await ws.send("")
        await asyncio.wait_for(task, 15)
    return {"text": "".join(final).strip(), "final_at": times["end"], "speech_end": speech_end,
            "error": times.get("error"), "finalized": st["finalized"], "segments": st["segments"], "ends": ends}


async def run_gemini_transcribe_live(audio: np.ndarray) -> dict:
    """gemini-3.5-transcribe-live driven as pipecat's GeminiSTTService does: TEXT modality, input transcription
    with language hints en+he, audio_stream_end sent when the speaker stops."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=(os.environ.get("GOOGLE_API_KEY") or sb.keychain("gemini-api-key")))
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.TEXT],
        input_audio_transcription=types.AudioTranscriptionConfig(
            language_hints=types.LanguageHints(language_codes=["en", "he"])),
    )
    heard: list[str] = []
    times: dict = {"heard": None}
    async with client.aio.live.connect(model="gemini-3.5-transcribe-live", config=config) as session:
        async def reader():
            async for msg in session.receive():
                sc = msg.server_content
                if sc and sc.input_transcription and sc.input_transcription.text:
                    heard.append(sc.input_transcription.text)
                    times["heard"] = time.time()

        task = asyncio.create_task(reader())
        sent_end = {"v": False}
        start = time.time()
        stop_at = start + sb.LEAD_SILENCE + (len(audio) / sb.RATE - sb.LEAD_SILENCE - sb.TAIL_SILENCE) + VAD_STOP_DELAY

        async def send(chunk: bytes):
            await session.send_realtime_input(audio=types.Blob(data=chunk, mime_type=f"audio/pcm;rate={sb.RATE}"))
            if not sent_end["v"] and time.time() >= stop_at:
                sent_end["v"] = True
                await session.send_realtime_input(audio_stream_end=True)

        speech_end = await sb.stream(send, audio)
        if not sent_end["v"]:
            await session.send_realtime_input(audio_stream_end=True)
        for _ in range(60):  # up to 6 s for the final transcript
            if times["heard"]:
                break
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.5)
        task.cancel()
        with contextlib.suppress(BaseException):
            await task
    return {"text": "".join(heard).strip(), "final_at": times["heard"], "speech_end": speech_end}


async def run_openai(audio: np.ndarray, model: str = "gpt-4o-transcribe") -> dict:
    """OpenAI realtime transcription."""
    import base64

    url = "wss://api.openai.com/v1/realtime?intent=transcription"
    headers = {"Authorization": f"Bearer {sb.keychain('openai-api-key')}"}
    async with websockets.connect(url, additional_headers=headers) as ws:
        await ws.send(json.dumps({"type": "session.update", "session": {"type": "transcription", "audio": {"input": {
            "format": {"type": "audio/pcm", "rate": 24000},
            "transcription": {"model": model},
            **({} if "live" in model else {"turn_detection": {"type": "server_vad", "silence_duration_ms": 500}})}}}}))
        final: list[str] = []
        times: dict = {"final": None}

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "conversation.item.input_audio_transcription.delta" and "live" in model:
                    times["last_word"] = time.time()  # commit waits for the tail silence, which is the bench's, not the model's
                elif msg.get("type") == "conversation.item.input_audio_transcription.completed":
                    final.append(msg["transcript"])
                    times["final"] = time.time()
                elif msg.get("type") == "error":
                    times["error"] = str(msg.get("error"))[:200]
                    return

        async def send(chunk: bytes):
            # the realtime API takes 24 kHz PCM; resample 16 kHz -> 24 kHz by linear interpolation
            x = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
            y = np.interp(np.linspace(0, len(x) - 1, int(len(x) * 1.5)), np.arange(len(x)), x).astype(np.int16)
            await ws.send(json.dumps({"type": "input_audio_buffer.append",
                                      "audio": base64.b64encode(y.tobytes()).decode()}))

        task = asyncio.create_task(reader())
        speech_end = await sb.stream(send, audio)
        if "live" in model:  # no turn detection: it transcribes as it hears, and finishes when told the audio ended
            await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        await asyncio.sleep(4.0 if "live" in model else 2.0)
        task.cancel()
    return {"text": " ".join(final).strip(), "final_at": times.get("last_word") or times["final"], "speech_end": speech_end,
            "error": times.get("error")}


VAD_STOP_SECS = 0.2  # pipecat's Silero default and the daemon's (daemon.VAD_STOP_SECS): a segment closes this long after speech ends
_WARM: set[str] = set()


async def run_local_whisper(audio: np.ndarray, repo: str) -> dict:
    """Whisper on this Mac, as vendors._mlx_ears drives it: one VAD segment, transcribed after it closes, with language
    detection and pipecat's filters. Not streaming, so latency is the VAD wait plus the time
    to transcribe the segment. Run with --concurrency 1: one model on one GPU."""
    import mlx_whisper

    speech_end_offset = len(audio) / sb.RATE - sb.TAIL_SILENCE
    segment = audio[: int((speech_end_offset + VAD_STOP_SECS) * sb.RATE)].astype(np.float32) / 32768.0
    if repo not in _WARM:  # the first call loads the model: a daemon does that once, before the first turn
        await asyncio.to_thread(mlx_whisper.transcribe, segment, path_or_hf_repo=repo, temperature=0.0, language=None)
        _WARM.add(repo)
    began = time.time()
    out = await asyncio.to_thread(mlx_whisper.transcribe, segment, path_or_hf_repo=repo, temperature=0.0, language=None)
    took = time.time() - began
    text = vendors.whisper_text(out)
    speech_end = began - VAD_STOP_SECS
    return {"text": text.strip(), "final_at": speech_end + VAD_STOP_SECS + took, "speech_end": speech_end,
            "compute_s": took, "language": out.get("language")}


EXTRA = {"local-whisper-turbo": lambda audio: run_local_whisper(audio, "mlx-community/whisper-large-v3-turbo"),
         "local-whisper-large-v3": lambda audio: run_local_whisper(audio, "mlx-community/whisper-large-v3-mlx"),
         "local-ivrit-turbo": lambda audio: run_local_whisper(audio, "mlx-community/ivrit-ai-whisper-large-v3-turbo-mlx"),
         "soniox-v6": lambda audio: run_soniox_rt(audio, "stt-rt-v6"),
         "soniox-daemon-v5": lambda audio: run_soniox_rt(audio, "stt-rt-v5", DAEMON_ENDPOINT),
         "soniox-daemon-v6": lambda audio: run_soniox_rt(audio, "stt-rt-v6", DAEMON_ENDPOINT),
         "soniox-v6-recommended": lambda audio: run_soniox_rt(audio, "stt-rt-v6", {
             "endpoint_latency_adjustment_level": 2, "endpoint_sensitivity": 0.3, "max_endpoint_delay_ms": 1500}),
         "soniox-v6-fin500": lambda audio: run_soniox_rt(audio, "stt-rt-v6", DAEMON_ENDPOINT, finalize_after_ms=500),
         "soniox-v6-fin700": lambda audio: run_soniox_rt(audio, "stt-rt-v6", DAEMON_ENDPOINT, finalize_after_ms=700),
         "soniox-v6-fin1500": lambda audio: run_soniox_rt(audio, "stt-rt-v6", DAEMON_ENDPOINT, finalize_after_ms=1500),
         "gemini-transcribe-live": run_gemini_transcribe_live, "openai": run_openai,
         "openai-mini": lambda audio: run_openai(audio, "gpt-4o-mini-transcribe"),
         "openai-live": lambda audio: run_openai(audio, "gpt-live-transcribe")}
sb.RUNNERS.update(EXTRA)


async def openai_key_ok() -> str | None:
    import aiohttp
    async with aiohttp.ClientSession() as http, http.get(
            "https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {sb.keychain('openai-api-key')}"}) as r:
        return None if r.status == 200 else f"not measured: key rejected (HTTP {r.status})"


HEADER = """# Speech-to-text benchmark report (run 2026-11-11/12)

Method: 70 corpus items x 4 synthetic voices x {clean, noisy at 12 dB SNR} = 560 clips, streamed at real-time pace;
scored by WER, CER, a system-blind LLM intent/entities judge (gemini-3.5-flash, temperature 0), and latency from speech
end to final transcript. Every system ran on the same 560 clips in one run, with 0 errors. Latency is wall time on one
laptop and one home Wi-Fi path whose latency tail was worse than in the 2026-11-06/07 run (p50 within ~60 ms of it, p90 up 0.5-1.5 s
for every system, so the tail reflects the network more than the systems), one run per clip per system, so treat
differences under ~100 ms as noise.

Systems (model as driven by the benchmark):
  soniox                  stt-rt-v5, Soniox's default endpoint settings
  soniox-v6               stt-rt-v6, same settings as soniox
  soniox-daemon-v5 / -v6  stt-rt-v5 and stt-rt-v6 with the daemon's endpoint settings (endpoint_sensitivity -0.5,
                          max_endpoint_delay_ms 2500), run together on 2026-11-20, a day apart from the rest; the
                          daemon runs v6 from 1.14.5 because Soniox removes v5 on 2026-12-15
  soniox-v6-fin500 / -fin700
                          soniox-daemon-v6, plus a finalize 0.5 or 0.7 s after the voice detector's stop while words
                          wait for an end, as the daemon does from 1.14.6 (0.7 s at Normal; -fin1500 is Patient)
  soniox-v6-recommended   stt-rt-v6 with Soniox's own lower-latency start (endpoint_latency_adjustment_level 2,
                          endpoint_sensitivity 0.3, max_endpoint_delay_ms 1500)
  scribe                  ElevenLabs scribe_v2_realtime. Its realtime endpoint accepts no other model id (probed:
                          scribe_v3_realtime and others are rejected)
  gemini-heard / -understood
                          gemini-3.8-live echo harness (a speech-to-speech model, not a transcriber)
  gemini-transcribe-live  gemini-3.5-transcribe-live, driven as pipecat's GeminiSTTService does (TEXT modality, language
                          hints en+he, audio_stream_end sent 0.4 s after speech end to mimic a VAD stop, so its latency
                          includes that 0.4 s)
  openai                  gpt-4o-transcribe over the realtime API
  openai-mini             gpt-4o-mini-transcribe over the realtime API
  openai-live             gpt-live-transcribe over the realtime API

Limitations:
  - Voices are synthetic (ElevenLabs), not real speakers; bench/recordings was empty. Real-speaker results may differ.
  - soniox-v6 latency: 3 of 560 clips never produced an endpoint token (excluded from its latency percentiles), and
    17.6% of the rest finalised only after more than 1 s, against 0 and 13.9% for v5, more often on clean clips (digital
    silence after speech). Default endpoint settings were used; tuning max_endpoint_delay/endpoint_sensitivity was not
    tried. Its accuracy edge over v5 is inside the confidence intervals overall.
  - The judge is an LLM, so its verdicts carry its own error; WER on mixed Hebrew/English is inflated for every system by
    script choice (an English term written in Hebrew letters counts as an error).
  - gemini-heard/understood come from a different model class and cannot be compared on latency like for like.
  - Intent-ok CIs are bootstrap over clips; the 4 voices and 2 conditions of one utterance are not independent,
    so the CIs are somewhat too narrow.

"""


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["run", "report"])
    p.add_argument("--systems", default="soniox-v6,gemini-transcribe-live,openai")
    p.add_argument("--limit", type=int, help="first N corpus items (all categories are not balanced; for smoke tests)")
    p.add_argument("--concurrency", type=int, default=6)
    p.add_argument("--voices", default=",".join(sb.VOICES))
    a = p.parse_args()
    if a.cmd == "run":
        systems = a.systems.split(",")
        if any(x.startswith("openai") for x in systems):
            reason = asyncio.run(openai_key_ok())
            if reason:
                UNMEASURED.write_text(json.dumps({"openai": reason}))
                print(f"openai: {reason}")
                systems = [x for x in systems if not x.startswith("openai")]
        asyncio.run(sb.collect(a.limit, systems, a.concurrency, a.voices.split(",")))
    else:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sb.report()
        text = HEADER + buf.getvalue()
        if UNMEASURED.exists():
            text += "\n## Not measured\n" + "\n".join(f"{k}: {v}" for k, v in json.loads(UNMEASURED.read_text()).items()) + "\n"
        (OUT / "report.txt").write_text(text)
        print(text)


if __name__ == "__main__":
    main()
