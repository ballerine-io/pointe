"""Speech-recognition benchmark for the voice front end.

Streams every clip at real-time pace into each system, exactly as live use would,
then scores accuracy (WER, CER, blind intent judge) and latency.

  uv run python -I bench/stt_bench.py run [--limit N]   # collect results.jsonl
  uv run python -I bench/stt_bench.py report            # score + statistics
"""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

import aiohttp
import numpy as np
import websockets

sys.path.insert(0, str(Path(__file__).parent))
from corpus import CORPUS  # noqa: E402

HERE = Path(__file__).parent
CACHE = HERE / ".audio"
OUT = HERE / "results"
RATE = 16000
CHUNK = 320  # 20 ms
LEAD_SILENCE, TAIL_SILENCE = 0.3, 2.5
VOICES = {
    "alice": "Xb7hH8MSUJpSbSDYk0k2",
    "roger": "CwhRBWXzGAHq8TQ4Fs17",
    "sarah": "EXAVITQu4vr4xnSDxMaL",
    "george": "JBFqnCBsd6RMkjVDRZzb",
}
NOISE_SNR_DB = 12
SYSTEMS = ["soniox", "scribe", "gemini"]
ECHO_INSTRUCTION = (
    "You are a dictation echo. Repeat back exactly the words the user just said, verbatim, in the same "
    "language and script they used. Say nothing else."
)


def keychain(item: str) -> str:
    return subprocess.run(
        ["security", "find-generic-password", "-s", item, "-w"], capture_output=True, text=True, check=True
    ).stdout.strip()


# ---------- audio ----------

RECORDINGS = HERE / "recordings"


def trim_silence(pcm: np.ndarray, threshold: int = 500, pad: int = RATE // 10) -> np.ndarray:
    """Cut the keypress gaps around a real recording so speech end is known."""
    loud = np.where(np.abs(pcm.astype(np.int32)) > threshold)[0]
    if not len(loud):
        return pcm
    return pcm[max(0, loud[0] - pad) : loud[-1] + pad]


async def load_voice(session: aiohttp.ClientSession, cid: str, text: str, voice: str) -> np.ndarray | None:
    if voice == "own":
        path = RECORDINGS / f"{cid}.pcm"
        return trim_silence(np.frombuffer(path.read_bytes(), dtype=np.int16)) if path.exists() else None
    return await synth(session, text, voice)


async def synth(session: aiohttp.ClientSession, text: str, voice: str) -> np.ndarray:
    CACHE.mkdir(parents=True, exist_ok=True)
    key = voice + "_" + hashlib.sha1(text.encode()).hexdigest()[:12]
    path = CACHE / f"{key}.pcm"
    if not path.exists():
        async with session.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{VOICES[voice]}?output_format=pcm_16000",
            headers={"xi-api-key": keychain("elevenlabs-api-key")},
            json={"text": text, "model_id": "eleven_v4_turbo"},
        ) as r:
            r.raise_for_status()
            path.write_bytes(await r.read())
    return np.frombuffer(path.read_bytes(), dtype=np.int16)


def pink_noise(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(n)
    spectrum = np.fft.rfft(white)
    spectrum /= np.sqrt(np.arange(1, len(spectrum) + 1))
    pink = np.fft.irfft(spectrum, n)
    return pink / np.abs(pink).max()


def with_noise(pcm: np.ndarray, snr_db: float, seed: int) -> np.ndarray:
    speech = pcm.astype(np.float64)
    noise = pink_noise(len(speech), seed)
    p_speech = np.mean(speech**2)
    noise *= np.sqrt(p_speech / (10 ** (snr_db / 10)) / np.mean(noise**2))
    return np.clip(speech + noise, -32768, 32767).astype(np.int16)


def frame(pcm: np.ndarray) -> np.ndarray:
    lead = np.zeros(int(LEAD_SILENCE * RATE), dtype=np.int16)
    tail = np.zeros(int(TAIL_SILENCE * RATE), dtype=np.int16)
    return np.concatenate([lead, pcm, tail])


async def stream(chunks_sink, audio: np.ndarray) -> float:
    """Send audio at real-time pace; returns wall time the speech ended."""
    start = time.time()
    speech_end = start + LEAD_SILENCE + (len(audio) / RATE - LEAD_SILENCE - TAIL_SILENCE)
    for i in range(0, len(audio), CHUNK):
        await chunks_sink(audio[i : i + CHUNK].tobytes())
        wait = start + (i + CHUNK) / RATE - time.time()
        if wait > 0:
            await asyncio.sleep(wait)
    return speech_end


# ---------- systems ----------

async def run_soniox(audio: np.ndarray) -> dict:
    async with websockets.connect("wss://stt-rt.soniox.com/transcribe-websocket") as ws:
        await ws.send(json.dumps({
            "api_key": keychain("soniox-api-key"), "model": "stt-rt-v5", "audio_format": "pcm_s16le",
            "sample_rate": RATE, "num_channels": 1, "language_hints": ["en", "he"],
            "enable_endpoint_detection": True,
        }))
        final: list[str] = []
        times = {"end": None}

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                for tok in msg.get("tokens", []):
                    if tok.get("is_final"):
                        if tok["text"] == "<end>":
                            times["end"] = times["end"] or time.time()
                        elif tok["text"] != "<fin>":
                            final.append(tok["text"])
                if msg.get("finished") or msg.get("error_code"):
                    if msg.get("error_code"):
                        times["error"] = msg.get("error_message")
                    return

        task = asyncio.create_task(reader())
        speech_end = await stream(ws.send, audio)
        await ws.send("")
        await asyncio.wait_for(task, 15)
    return {"text": "".join(final).strip(), "final_at": times["end"], "speech_end": speech_end,
            "error": times.get("error")}


async def run_scribe(audio: np.ndarray) -> dict:
    url = ("wss://api.elevenlabs.io/v1/speech-to-text/realtime?model_id=scribe_v2_realtime"
           "&audio_format=pcm_16000&commit_strategy=vad&vad_silence_threshold_secs=0.5")
    async with websockets.connect(url, additional_headers={"xi-api-key": keychain("elevenlabs-api-key")}) as ws:
        committed: list[str] = []
        times: dict = {"final": None}

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                kind = msg.get("message_type")
                if kind in ("committed_transcript", "committed_transcript_with_timestamps") and msg.get("text"):
                    committed.append(msg["text"])
                    times["final"] = time.time()
                elif kind and "error" in kind:
                    times["error"] = str(msg)[:200]
                    return

        async def send(chunk: bytes):
            await ws.send(json.dumps({"message_type": "input_audio_chunk", "audio_base_64":
                                      base64.b64encode(chunk).decode(), "commit": False, "sample_rate": RATE}))

        task = asyncio.create_task(reader())
        speech_end = await stream(send, audio)
        await asyncio.sleep(1.0)
        if not committed:
            await ws.send(json.dumps({"message_type": "input_audio_chunk", "audio_base_64": "", "commit": True,
                                      "sample_rate": RATE}))
            await asyncio.sleep(2.0)
        task.cancel()
    return {"text": " ".join(committed).strip(), "final_at": times["final"], "speech_end": speech_end,
            "error": times.get("error")}


async def run_gemini(audio: np.ndarray) -> dict:
    """Gemini Live's own input transcript, plus what it understood (it echoes the words back)."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=(os.environ.get("GOOGLE_API_KEY") or keychain("gemini-api-key")))
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"], system_instruction=ECHO_INSTRUCTION,
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    heard: list[str] = []
    echoed: list[str] = []
    times: dict = {"heard": None, "first_audio": None}
    async with client.aio.live.connect(model="gemini-3.8-live", config=config) as session:
        async def reader():
            async for msg in session.receive():
                sc = msg.server_content
                if not sc:
                    continue
                if sc.input_transcription and sc.input_transcription.text:
                    heard.append(sc.input_transcription.text)
                    times["heard"] = time.time()
                if sc.model_turn and any(p.inline_data for p in sc.model_turn.parts or []):
                    times["first_audio"] = times["first_audio"] or time.time()
                if sc.output_transcription and sc.output_transcription.text:
                    echoed.append(sc.output_transcription.text)
                if sc.turn_complete and echoed:
                    return

        async def send(chunk: bytes):
            await session.send_realtime_input(audio=types.Blob(data=chunk, mime_type=f"audio/pcm;rate={RATE}"))

        task = asyncio.create_task(reader())
        speech_end = await stream(send, audio)
        try:
            await asyncio.wait_for(task, 15)
        except asyncio.TimeoutError:
            task.cancel()
    return {"text": "".join(heard).strip(), "understood": "".join(echoed).strip(),
            "final_at": times["heard"], "first_audio_at": times["first_audio"], "speech_end": speech_end}


RUNNERS = {"soniox": run_soniox, "scribe": run_scribe, "gemini": run_gemini}


async def collect(limit: int | None, systems: list[str], concurrency: int, voices: list[str]) -> None:
    OUT.mkdir(exist_ok=True)
    path = OUT / "results.jsonl"
    done = set()
    if path.exists():
        for line in path.read_text().splitlines():
            r = json.loads(line)
            if not r.get("error"):
                done.add((r["system"], r["clip"]))
    items = CORPUS[:limit] if limit else CORPUS
    clips = [(f"{cid}.{voice}.{cond}", cid, cat, text, voice, cond)
             for cid, cat, text in items for voice in voices for cond in ("clean", "noisy")]
    async with aiohttp.ClientSession() as http:
        audio = {}
        for clip, cid, cat, text, voice, cond in list(clips):
            pcm = await load_voice(http, cid, text, voice)
            if pcm is None:
                clips.remove((clip, cid, cat, text, voice, cond))
                continue
            audio[clip] = frame(with_noise(pcm, NOISE_SNR_DB, seed=int(hashlib.sha1(clip.encode()).hexdigest()[:8], 16)) if cond == "noisy" else pcm)
    sem = {s: asyncio.Semaphore(concurrency) for s in systems}
    lock = asyncio.Lock()
    jobs = [(s, c) for s in systems for c in clips if (s, c[0]) not in done]
    random.Random(7).shuffle(jobs)
    print(f"{len(jobs)} runs to do ({len(done)} cached)", flush=True)
    progress = {"n": 0}

    async def one(system, clip_info):
        clip, cid, cat, text, voice, cond = clip_info
        async with sem[system]:
            for attempt in range(3):
                try:
                    r = await RUNNERS[system](audio[clip])
                    break
                except Exception as e:  # network flake: retry, then record the error
                    r = {"error": f"{type(e).__name__}: {e}"[:300]}
                    await asyncio.sleep(2 * (attempt + 1))
        row = {"system": system, "clip": clip, "id": cid, "category": cat, "voice": voice, "cond": cond,
               "ref": text, **r}
        async with lock:
            with path.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            progress["n"] += 1
            if progress["n"] % 25 == 0:
                print(f"  {progress['n']}/{len(jobs)}", flush=True)

    await asyncio.gather(*(one(s, c) for s, c in jobs))


# ---------- scoring ----------

def normalize(text: str) -> list[str]:
    text = text.lower().replace("-", " ").replace("_", " ")
    text = re.sub(r"[^\w\s']", " ", text)
    return text.split()


def edit_distance(a: list, b: list) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def wer(ref: str, hyp: str) -> float:
    r = normalize(ref)
    return edit_distance(r, normalize(hyp)) / max(1, len(r))


def cer(ref: str, hyp: str) -> float:
    r = list("".join(normalize(ref)))
    return edit_distance(r, list("".join(normalize(hyp)))) / max(1, len(r))


JUDGE = """You grade speech-recognition output for a voice assistant that relays requests to a coding agent.
For each item compare the reference (what the user said) with the hypothesis (what the system heard).
- intent: true if a coding agent given the hypothesis would do the same thing as with the reference.
  Writing an English term in Hebrew letters or vice versa is fine. Minor grammar slips are fine.
- entities: true if every identifier, name, number and technical term is present and recognizable
  (true when there are none).
Return a JSON list of objects {"i": <index>, "intent": bool, "entities": bool}, one per item, nothing else."""


async def judge(rows: list[dict]) -> None:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=(os.environ.get("GOOGLE_API_KEY") or keychain("gemini-api-key")))
    todo = [r for r in rows if "intent" not in r]
    sem = asyncio.Semaphore(6)

    async def batch(items):
        payload = [{"i": i, "reference": r["ref"], "hypothesis": r["hyp"]} for i, r in enumerate(items)]
        async with sem:
            for _ in range(6):
                try:
                    # A socket that dies without a reset never raises, so the wait needs its own limit.
                    resp = await asyncio.wait_for(client.aio.models.generate_content(
                        model="gemini-3.5-flash", contents=json.dumps(payload, ensure_ascii=False),
                        config=types.GenerateContentConfig(temperature=0, system_instruction=JUDGE,
                                                           response_mime_type="application/json")), 120)
                    for v in json.loads(resp.text):
                        items[v["i"]]["intent"], items[v["i"]]["entities"] = bool(v["intent"]), bool(v["entities"])
                    return
                except Exception:
                    await asyncio.sleep(2)

    random.Random(3).shuffle(todo)  # mixes systems so no batch is all one system
    await asyncio.gather(*(batch(todo[i : i + 25]) for i in range(0, len(todo), 25)))


def bootstrap_ci(values: list[float], n: int = 2000, seed: int = 1) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    arr = np.array(values, dtype=float)
    means = rng.choice(arr, (n, len(arr))).mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def mcnemar_p(a: list[bool], b: list[bool]) -> float:
    """Exact two-sided McNemar test on paired outcomes."""
    from math import comb

    n01 = sum(1 for x, y in zip(a, b) if x and not y)
    n10 = sum(1 for x, y in zip(a, b) if y and not x)
    n = n01 + n10
    if n == 0:
        return 1.0
    k = min(n01, n10)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2**n)


def report(only_voice: str | None = None) -> None:
    rows = [json.loads(l) for l in (OUT / "results.jsonl").read_text().splitlines()]
    if only_voice:
        rows = [r for r in rows if r["voice"] == only_voice]
    latest: dict = {}
    for r in rows:
        if not r.get("error") or (r["system"], r["clip"]) not in latest:
            latest[(r["system"], r["clip"])] = r
    scored = []
    for r in latest.values():
        if r.get("error"):
            continue
        variants = [("gemini-heard", r["text"]), ("gemini-understood", r.get("understood", ""))] \
            if r["system"] == "gemini" else [(r["system"], r["text"])]
        for name, hyp in variants:
            lat = (r["final_at"] - r["speech_end"]) if r.get("final_at") else None
            if name == "gemini-understood":
                lat = (r["first_audio_at"] - r["speech_end"]) if r.get("first_audio_at") else None
            scored.append({**{k: r[k] for k in ("clip", "id", "category", "voice", "cond", "ref")},
                           "sys": name, "hyp": hyp, "wer": wer(r["ref"], hyp), "cer": cer(r["ref"], hyp),
                           "latency": lat})
    cache = OUT / "judged.json"
    judged = {(j["sys"], j["clip"]): j for j in json.loads(cache.read_text())} if cache.exists() else {}
    for s in scored:
        j = judged.get((s["sys"], s["clip"]))
        if j and j["hyp"] == s["hyp"] and "intent" in j:
            s["intent"], s["entities"] = j["intent"], j["entities"]
    asyncio.run(judge(scored))
    judged.update({(x["sys"], x["clip"]): x for x in scored})
    cache.write_text(json.dumps(list(judged.values()), ensure_ascii=False))

    systems = sorted({s["sys"] for s in scored})
    clips = sorted({s["clip"] for s in scored})
    by = {(s["sys"], s["clip"]): s for s in scored}
    common = [c for c in clips if all((x, c) in by and "intent" in by[(x, c)] for x in systems)]
    errors = sum(1 for r in latest.values() if r.get("error"))
    print(f"\nClips scored by every system: {len(common)} (run errors: {errors})\n")

    def table(title, subset):
        print(f"## {title} (n={len(subset)} clips)")
        print(f"{'system':20s} {'intent ok':>18s} {'entities ok':>12s} {'WER':>6s} {'CER':>6s} {'lat p50':>8s} {'lat p90':>8s}")
        for x in systems:
            rs = [by[(x, c)] for c in subset]
            intent = [float(r["intent"]) for r in rs]
            lo, hi = bootstrap_ci(intent)
            lats = sorted(r["latency"] for r in rs if r["latency"] is not None)
            p50 = f"{np.percentile(lats, 50):.2f}s" if lats else "-"
            p90 = f"{np.percentile(lats, 90):.2f}s" if lats else "-"
            print(f"{x:20s} {np.mean(intent)*100:5.1f}% [{lo*100:4.1f}-{hi*100:4.1f}] "
                  f"{np.mean([r['entities'] for r in rs])*100:11.1f}% {np.mean([r['wer'] for r in rs]):6.3f} "
                  f"{np.mean([r['cer'] for r in rs]):6.3f} {p50:>8s} {p90:>8s}")
        print()

    table("All", common)
    for cat in ("en", "he", "mix", "short"):
        table(f"Category {cat}", [c for c in common if by[(systems[0], c)]["category"] == cat])
    for cond in ("clean", "noisy"):
        table(f"Condition {cond}", [c for c in common if by[(systems[0], c)]["cond"] == cond])

    print("## Paired intent comparison (exact McNemar, all clips)")
    for i, x in enumerate(systems):
        for y in systems[i + 1 :]:
            a = [by[(x, c)]["intent"] for c in common]
            b = [by[(y, c)]["intent"] for c in common]
            print(f"{x} vs {y}: {sum(a)} vs {sum(b)} correct, p = {mcnemar_p(a, b):.2g}")
    print("\n## Sample failures")
    for x in systems:
        fails = [by[(x, c)] for c in common if not by[(x, c)]["intent"]][:6]
        for f in fails:
            print(f"{x:18s} {f['clip']:22s} ref={f['ref']!r} hyp={f['hyp']!r}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["run", "report"])
    p.add_argument("--only-voice", help="report on one voice, e.g. own")
    p.add_argument("--limit", type=int)
    p.add_argument("--systems", default=",".join(SYSTEMS))
    p.add_argument("--concurrency", type=int, default=6)
    p.add_argument("--voices", default=",".join(VOICES), help="comma list; 'own' = bench/recordings")
    a = p.parse_args()
    if a.cmd == "run":
        asyncio.run(collect(a.limit, a.systems.split(","), a.concurrency, a.voices.split(",")))
    else:
        report(a.only_voice)
