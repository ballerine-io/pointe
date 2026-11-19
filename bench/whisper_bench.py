"""Whisper mode: what whispered speech does to the ears, the voice detector, the voice lock and barge-in.

  uv run python -I bench/whisper_bench.py synth      # make the corpus (ElevenLabs, cached in bench/.audio/whisper)
  uv run python -I bench/whisper_bench.py soniox     # stream every clip at real-time pace into Soniox (paid)
  uv run python -I bench/whisper_bench.py offline    # voice detector, voice lock and barge-in (free, local)
  uv run python -I bench/whisper_bench.py report     # bench/results/whisper.md

The corpus is synthetic, two kinds of whisper:
- "unvoiced": a normal ElevenLabs clip re-synthesised from its LPC envelope over white noise. No vocal-fold tone at all,
  which is what makes a real whisper hard; the formants (the words) stay. Measured voiced-frame share: about 3%.
- "breathy": ElevenLabs v3 with its [whispers] tag. It sounds hushed but keeps most of its tone (about 80% voiced frames),
  so it is closer to a soft voice than to a whisper.
Neither is a person whispering into a laptop in an open office: no recorded whisper corpus exists yet. Levels are relative
to the normal clip (about -18 dBFS): a whisper at -18 dB and at -30 dB, over the same pink office noise at -55 dBFS.
"""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import aiohttp
import numpy as np
import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))
import no_telemetry  # noqa: E402,F401  (before pipecat's Silero loads onnxruntime)
import vendors  # noqa: E402
import whisper  # noqa: E402
import echo as echo_mod  # noqa: E402
from echo import LevelGate  # noqa: E402

HERE = Path(__file__).parent
CACHE = HERE / ".audio" / "whisper"
RESULTS = HERE / "results"
RATE = 16000
CHUNK = 320
VOICES = {"sarah": "EXAVITQu4vr4xnSDxMaL", "george": "JBFqnCBsd6RMkjVDRZzb"}
BOT_VOICE = "Xb7hH8MSUJpSbSDYk0k2"  # the bot's voice in the barge-in simulation
NOISE_DBFS = -55.0  # a quiet open office: HVAC and distant talk, as pink noise

CORPUS = [
    ("c01", "Run the tests on the billing service."),
    ("c02", "Switch to the pricing session."),
    ("c03", "What is lantern waiting on?"),
    ("c04", "Tell docs to open a pull request against dev."),
    ("c05", "Revert the last commit but keep the changes staged."),
    ("c06", "Check the logs for the edge proxy on staging."),
    ("c07", "Add a unit test for the null price case."),
    ("c08", "How many sessions are still running?"),
    ("c09", "Ask billing why the migration failed."),
    ("c10", "Read me the last message from orbit."),
    ("c11", "Stop the dev server and restart it."),
    ("c12", "Summarize what changed since this morning."),
    ("s01", "Yes."),
    ("s02", "No."),
    ("s03", "Yes, go ahead."),
    ("s04", "Approve it."),
    ("s05", "No, don't run it."),
    ("s06", "Whisper mode."),
    ("s07", "Back to normal."),
    ("h01", "תריץ את הבדיקות."),
    ("h02", "מה המצב של הסשן?"),
    ("h03", "כן."),
    ("h04", "לא."),
]
ENROL = [
    "The quick brown fox jumps over the lazy dog near the riverbank.",
    "Please tell the build session to run the tests and report back.",
    "Seven bright kites drifted above the harbour on a windy afternoon.",
    "Good morning, I am checking that the system recognises my voice clearly.",
]
VARIANTS = {  # name -> (source, level in dB relative to the normal clip)
    "normal": ("normal", 0.0),
    "unvoiced-18": ("unvoiced", -18.0),
    "unvoiced-30": ("unvoiced", -30.0),
    "breathy-18": ("breathy", -18.0),
}
GAINS = {"none": 1.0, "x2.5": 2.5}
SONIOX_CONFIGS = {  # the daemon's settings (vendors.build_ears), and the plan's whisper candidate
    "daemon": {"endpoint_sensitivity": -0.5, "max_endpoint_delay_ms": 2500},
    "plan-whisper": {"endpoint_sensitivity": 0.0, "max_endpoint_delay_ms": 1800},
}


def keychain(item: str) -> str:
    return subprocess.run(["security", "find-generic-password", "-s", item, "-w"], capture_output=True, text=True,
                          check=True).stdout.strip()


# ---------- audio ----------

def _lpc(frame: np.ndarray, order: int) -> np.ndarray:
    r = np.correlate(frame, frame, "full")[len(frame) - 1:len(frame) + order]
    a = np.zeros(order + 1)
    a[0] = 1.0
    if r[0] <= 0:
        return a
    r = r.copy()
    r[0] *= 1.0001
    err = r[0]
    for i in range(1, order + 1):
        k = -(r[i] + a[1:i] @ r[i - 1:0:-1]) / err
        a[1:i + 1] = a[1:i + 1] + k * np.concatenate([a[i - 1:0:-1], [1.0]])
        err *= 1 - k * k
    return a


def _all_pole(a: np.ndarray, x: np.ndarray) -> np.ndarray:
    y = np.zeros(len(x))
    for t in range(len(x)):
        lo = max(0, t - len(a) + 1)
        y[t] = x[t] - a[1:t - lo + 1] @ y[t - 1:lo - 1 if lo else None:-1] if t else x[t]
    return y


def unvoice(pcm: np.ndarray, order: int = 18, seed: int = 0) -> np.ndarray:
    """The clip's spectral envelope over white noise: the words without the voice's tone."""
    rng = np.random.default_rng(seed)
    x = pcm.astype(np.float64)
    pre = np.append(x[0], x[1:] - 0.97 * x[:-1])
    n = int(0.025 * RATE)
    hop, win = n // 2, np.hanning(n)
    out = np.zeros(len(x) + n)
    for i in range(0, len(x) - n, hop):
        f = pre[i:i + n] * win
        y = _all_pole(_lpc(f, order), rng.standard_normal(n))
        out[i:i + n] += y * win * np.sqrt(np.sum(f ** 2) / max(np.sum((y * win) ** 2), 1e-9))
    out = out[:len(x)]
    de = np.zeros_like(out)
    for t in range(len(out)):
        de[t] = out[t] + (0.97 * de[t - 1] if t else 0.0)
    de *= np.sqrt(np.mean(x ** 2) / max(np.mean(de ** 2), 1e-9))
    return np.clip(de, -32768, 32767).astype(np.int16)


def voiced_share(pcm: np.ndarray) -> float:
    """Share of loud 40 ms frames with a clear pitch (autocorrelation peak > 0.5 between 70 and 400 Hz)."""
    x = pcm.astype(np.float64)
    n, hop = int(0.04 * RATE), int(0.01 * RATE)
    floor = 0.3 * np.sqrt(np.mean(x ** 2))
    voiced = total = 0
    for i in range(0, len(x) - n, hop):
        f = x[i:i + n] - x[i:i + n].mean()
        if np.sqrt(np.mean(f ** 2)) < floor:
            continue
        ac = np.correlate(f, f, "full")[n - 1:]
        if ac[0] <= 0:
            continue
        total += 1
        voiced += (ac[RATE // 400:RATE // 70] / ac[0]).max() > 0.5
    return voiced / max(total, 1)


def pink(n: int, seed: int) -> np.ndarray:
    spectrum = np.fft.rfft(np.random.default_rng(seed).standard_normal(n))
    spectrum /= np.sqrt(np.arange(1, len(spectrum) + 1))
    x = np.fft.irfft(spectrum, n)
    return x / np.sqrt(np.mean(x ** 2))


def dbfs_rms(db: float) -> float:
    return 32768 * 10 ** (db / 20)


def scene(clip: np.ndarray, level_db: float, seed: int, lead: float = 0.5, tail: float = 3.0) -> np.ndarray:
    """The clip at its level, with silence around it, over office noise."""
    body = clip.astype(np.float64) * 10 ** (level_db / 20)
    x = np.concatenate([np.zeros(int(lead * RATE)), body, np.zeros(int(tail * RATE))])
    x += pink(len(x), seed) * dbfs_rms(NOISE_DBFS)
    return np.clip(x, -32768, 32767).astype(np.int16)


def gained(pcm: np.ndarray, gain: float) -> np.ndarray:
    return pcm if gain == 1.0 else np.frombuffer(whisper.apply_gain(pcm.tobytes(), gain), dtype=np.int16)


# ---------- corpus ----------

async def _tts(session, text: str, voice: str, model: str, path: Path) -> np.ndarray:
    if not path.exists():
        for attempt in range(4):
            async with session.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=pcm_16000",
                headers={"xi-api-key": keychain("elevenlabs-api-key")}, json={"text": text, "model_id": model},
            ) as r:
                if r.status == 429:
                    await asyncio.sleep(3 * (attempt + 1))
                    continue
                r.raise_for_status()
                path.write_bytes(await r.read())
                break
    return np.frombuffer(path.read_bytes(), dtype=np.int16)


def _key(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


async def synth() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    async with aiohttp.ClientSession() as s:
        jobs = []
        for vname, vid in VOICES.items():
            for cid, text in CORPUS:
                jobs.append(_tts(s, text, vid, "eleven_v4_turbo", CACHE / f"normal_{vname}_{cid}.pcm"))
                jobs.append(_tts(s, f"[whispers] {text}", vid, "eleven_v3", CACHE / f"breathy_{vname}_{cid}.pcm"))
            for i, text in enumerate(ENROL):
                jobs.append(_tts(s, text, vid, "eleven_v4_turbo", CACHE / f"enrol_{vname}_{i}.pcm"))
        jobs.append(_tts(s, "Lantern finished the migration and all forty two tests pass. Billing is still waiting "
                            "for your approval to run the deploy script on staging.", BOT_VOICE, "eleven_v4_turbo",
                         CACHE / "bot.pcm"))
        sem = asyncio.Semaphore(4)

        async def one(job):
            async with sem:
                return await job
        await asyncio.gather(*(one(j) for j in jobs))
    for vname in VOICES:
        for cid, _ in CORPUS:
            out = CACHE / f"unvoiced_{vname}_{cid}.pcm"
            if not out.exists():
                out.write_bytes(unvoice(clip("normal", vname, cid)).tobytes())
    shares = {k: round(float(np.mean([voiced_share(clip(k, v, c)) for v in VOICES for c, _ in CORPUS])), 3)
              for k in ("normal", "unvoiced", "breathy")}
    (CACHE / "voicing.json").write_text(json.dumps(shares))
    print("voiced-frame share:", shares)


def clip(source: str, voice: str, cid: str) -> np.ndarray:
    return np.frombuffer((CACHE / f"{source}_{voice}_{cid}.pcm").read_bytes(), dtype=np.int16)


def items():
    for vname in VOICES:
        for n, (cid, text) in enumerate(CORPUS):
            yield vname, cid, text, n


# ---------- Soniox ----------

async def soniox_once(audio: np.ndarray, config: dict, lead: float) -> dict:
    async with websockets.connect("wss://stt-rt.soniox.com/transcribe-websocket") as ws:
        await ws.send(json.dumps({"api_key": keychain("soniox-api-key"), "model": vendors.SONIOX_RT_MODEL,
                                  "audio_format": "pcm_s16le", "sample_rate": RATE, "num_channels": 1,
                                  "language_hints": ["en", "he"], "enable_endpoint_detection": True, **config}))
        final, got = [], {}

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                for tok in msg.get("tokens", []):
                    if tok.get("is_final"):
                        if tok["text"] == "<end>":
                            got.setdefault("end", time.time())
                        elif tok["text"] != "<fin>":
                            final.append(tok["text"])
                if msg.get("error_code"):
                    got["error"] = f"{msg.get('error_code')} {msg.get('error_message')}"
                    return
                if msg.get("finished"):
                    return

        task = asyncio.create_task(reader())
        start = time.time()
        for i in range(0, len(audio), CHUNK):
            await ws.send(audio[i:i + CHUNK].tobytes())
            wait = start + (i + CHUNK) / RATE - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
        await ws.send("")
        await asyncio.wait_for(task, 20)
    return {"text": "".join(final).strip(), "end": got.get("end"), "start": start, "error": got.get("error")}


async def soniox_run() -> None:
    out = RESULTS / "whisper_soniox.jsonl"
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            r = json.loads(line)
            if not r.get("error"):
                done.add((r["voice"], r["cid"], r["variant"], r["gain"], r["config"]))
    jobs = []
    for vname, cid, text, n in items():
        for variant, (source, level) in VARIANTS.items():
            for gname, gain in GAINS.items():
                if variant == "normal" and gname != "none":
                    continue
                configs = SONIOX_CONFIGS if variant == "unvoiced-18" and gname == "none" else {"daemon": None}
                for cname in configs:
                    if (vname, cid, variant, gname, cname) not in done:
                        jobs.append((vname, cid, text, n, variant, source, level, gname, gain, cname))
    for seed, (gname, gain) in enumerate(GAINS.items()):  # noise alone: does anything get transcribed?
        if ("noise", f"noise{seed}", "noise", gname, "daemon") not in done:
            jobs.append(("noise", f"noise{seed}", "", 1000 + seed, "noise", None, 0.0, gname, gain, "daemon"))
    print(f"{len(jobs)} streams")
    sem = asyncio.Semaphore(3)
    lock = asyncio.Lock()

    async def one(job):
        vname, cid, text, n, variant, source, level, gname, gain, cname = job
        if source is None:
            audio = gained(scene(np.zeros(RATE * 20, dtype=np.int16), 0.0, n, lead=0, tail=0), gain)
            speech_end_offset = len(audio) / RATE
        else:
            src = clip(source, vname, cid)
            audio = gained(scene(src, level, n), gain)
            speech_end_offset = 0.5 + len(src) / RATE
        async with sem:
            for attempt in range(5):
                try:
                    r = await soniox_once(audio, SONIOX_CONFIGS[cname], 0.5)
                except Exception as e:
                    r = {"text": "", "error": f"{type(e).__name__}: {e}"[:160]}
                if not r.get("error") or "429" not in str(r.get("error")) and "limit" not in str(r.get("error")).lower():
                    break
                await asyncio.sleep(10 * (attempt + 1))
        row = {"voice": vname, "cid": cid, "ref": text, "variant": variant, "gain": gname, "config": cname,
               "hyp": r.get("text", ""), "error": r.get("error"),
               "endpoint_secs": round(r["end"] - r["start"] - speech_end_offset, 3) if r.get("end") else None}
        async with lock:
            with out.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    await asyncio.gather(*(one(j) for j in jobs))


# ---------- offline: voice detector, voice lock, barge-in ----------

def vad_run(audio: np.ndarray, params) -> dict:
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADState

    vad = SileroVADAnalyzer(sample_rate=RATE, params=params)
    vad.set_sample_rate(RATE)
    starts, first, speaking, prev = 0, None, 0, VADState.QUIET
    for i in range(0, len(audio) - CHUNK + 1, CHUNK):
        st = vad._run_analyzer(audio[i:i + CHUNK].tobytes())
        if st == VADState.SPEAKING and prev != VADState.SPEAKING:
            starts += 1
            first = first if first is not None else i / RATE
        speaking += st == VADState.SPEAKING
        prev = st
    return {"starts": starts, "first": first, "speaking_secs": speaking * CHUNK / RATE}


def offline() -> None:
    from pipecat.audio.vad.vad_analyzer import VADParams

    rows = []
    profiles = {"default": VADParams(), "whisper": VADParams(**whisper.VAD_WHISPER)}
    for vname, cid, text, n in items():
        for variant, (source, level) in VARIANTS.items():
            src = clip(source, vname, cid)
            for gname, gain in GAINS.items():
                audio = gained(scene(src, level, n), gain)
                for pname, params in profiles.items():
                    r = vad_run(audio, params)
                    rows.append({"voice": vname, "cid": cid, "variant": variant, "gain": gname, "profile": pname,
                                 "detected": r["starts"] > 0, "onset": None if r["first"] is None else r["first"] - 0.5})
    noise = []  # false starts on office noise with keyboard clicks, 60 s
    rng = np.random.default_rng(7)
    base = pink(RATE * 60, 99) * dbfs_rms(-50)
    for at in rng.uniform(0, 59.9, 150):  # 2.5 clicks a second: typing
        i = int(at * RATE)
        base[i:i + 80] += rng.standard_normal(80) * dbfs_rms(-30) * np.exp(-np.arange(80) / 15)
    noisy = np.clip(base, -32768, 32767).astype(np.int16)
    for gname, gain in GAINS.items():
        for pname, params in profiles.items():
            r = vad_run(gained(noisy, gain), params)
            noise.append({"gain": gname, "profile": pname, "starts_per_min": r["starts"], "speaking_secs": r["speaking_secs"]})
    (RESULTS / "whisper_vad.json").write_text(json.dumps({"rows": rows, "noise": noise}))
    speaker_scores()
    barge_in()


def speaker_scores() -> None:
    import speaker

    emb = speaker.Embedder(Path(os.environ.get("POINTE_MODELS", "/tmp/pointe-models")))
    if not emb.ensure():
        print("no speaker model:", emb.error)
        return

    def vec(pcm):
        return emb.embed(pcm.astype(np.float32) / 32768.0)

    owners = {v: np.mean([vec(np.frombuffer((CACHE / f"enrol_{v}_{i}.pcm").read_bytes(), dtype=np.int16))
                          for i in range(len(ENROL))], axis=0) for v in VOICES}
    owners = {v: c / np.linalg.norm(c) for v, c in owners.items()}
    rows = []
    for vname, cid, text, n in items():
        for variant, (source, level) in VARIANTS.items():
            audio = scene(clip(source, vname, cid), level, n, lead=0.0, tail=0.0)
            v = vec(audio)
            for owner, centroid in owners.items():
                rows.append({"owner": owner, "voice": vname, "cid": cid, "variant": variant,
                             "secs": round(len(audio) / RATE, 2), "score": float(v @ centroid)})
    (RESULTS / "whisper_speaker.json").write_text(json.dumps({"rows": rows, "T_HIGH": speaker.T_HIGH,
                                                              "T_LOW": speaker.T_LOW, "MIN_SECS": speaker.MIN_SECS}))


def barge_in() -> None:
    """LevelGate on a simulated laptop: the bot's echo (an echo canceller's residue at -30 dB) and a whispered "wait,
    stop" starting 3 s into its turn. Counts frames where loudness alone would cut the bot, before and during the whisper."""
    bot = np.frombuffer((CACHE / "bot.pcm").read_bytes(), dtype=np.int16).astype(np.float64)
    user = clip("unvoiced", "sarah", "s05").astype(np.float64)
    rows = []
    for out_gain in (1.0, 0.5, 0.0):  # 0.0: headphones, no echo at all
        for user_db in (-18.0, -24.0, -30.0):
            for in_gain in (1.0, 2.5):
                for floor in (300, 120):  # echo.MIN_SPEECH_RMS, and the plan's whisper floor
                    echo = bot * 10 ** (-30 / 20) * out_gain
                    mic = echo.copy()
                    at = 3 * RATE
                    seg = user * 10 ** (user_db / 20)
                    mic[at:at + len(seg)] += seg[:len(mic) - at]
                    mic += pink(len(mic), 5) * dbfs_rms(NOISE_DBFS)
                    mic = gained(np.clip(mic, -32768, 32767).astype(np.int16), in_gain).astype(np.float64)
                    gate = LevelGate()
                    echo_mod.MIN_SPEECH_RMS = floor
                    false = hit = 0
                    first = None
                    for i in range(0, len(mic) - CHUNK, CHUNK):
                        f = mic[i:i + CHUNK]
                        gate.frame(float(np.sqrt(np.mean(f * f))), True)
                        loud = gate.loud()
                        if i < at:
                            false += loud
                        elif i < at + len(seg):
                            hit += loud
                            if loud and first is None:
                                first = (i - at) / RATE
                    echo_mod.MIN_SPEECH_RMS = 300
                    rows.append({"output_gain": out_gain, "user_db": user_db, "input_gain": in_gain, "floor": floor,
                                 "false_frames": int(false), "hit_frames": int(hit), "first_cut_secs": first})
    (RESULTS / "whisper_level.json").write_text(json.dumps(rows))


# ---------- report ----------

def report() -> None:
    sys.path.insert(0, str(HERE))
    from stt_bench import wer

    lines = ["# Whisper mode: synthetic bench", "",
             "Synthetic only: two ElevenLabs voices, 23 utterances each (12 commands, 7 short answers and mode phrases, "
             "4 Hebrew). No person whispered for this; see the module docstring of `bench/whisper_bench.py` for how the "
             "whispers are made, and treat every number as a direction, not a promise.", ""]
    voicing = json.loads((CACHE / "voicing.json").read_text()) if (CACHE / "voicing.json").exists() else {}
    if voicing:
        lines += [f"Voiced-frame share: normal {voicing['normal']:.0%}, unvoiced {voicing['unvoiced']:.0%}, "
                  f"breathy {voicing['breathy']:.0%} (a real whisper is near 0%).", ""]
    path = RESULTS / "whisper_soniox.jsonl"
    if path.exists():
        rows = [json.loads(l) for l in path.read_text().splitlines()]
        rows = list({(r["voice"], r["cid"], r["variant"], r["gain"], r["config"]): r
                     for r in rows if not r.get("error")}.values())  # a retried stream counts once
        lines += [f"## Soniox ({vendors.SONIOX_RT_MODEL}, real-time streaming, the daemon's settings)", "",
                  "| Variant | Input gain | Config | Clips | WER | Exact | Yes/no right | Endpoint p50 / p90 (s) |",
                  "|---|---|---|---|---|---|---|---|"]
        keyset = sorted({(r["variant"], r["gain"], r["config"]) for r in rows if r["variant"] != "noise"},
                        key=lambda k: (list(VARIANTS).index(k[0]), k[1], k[2]))
        for variant, gname, cname in keyset:
            sub = [r for r in rows if (r["variant"], r["gain"], r["config"]) == (variant, gname, cname)]
            ws = [wer(r["ref"], r["hyp"]) for r in sub]
            exact = sum(w == 0 for w in ws)
            yn = [r for r in sub if r["cid"] in ("s01", "s02", "s03", "s05", "h03", "h04")]
            yn_ok = sum(_polarity(r["ref"]) == _polarity(r["hyp"]) for r in yn)
            eps = sorted(r["endpoint_secs"] for r in sub if r["endpoint_secs"] is not None)
            ep = f"{eps[len(eps) // 2]:.2f} / {eps[int(len(eps) * 0.9)]:.2f}" if eps else "-"
            lines.append(f"| {variant} | {gname} | {cname} | {len(sub)} | {np.mean(ws):.1%} | {exact}/{len(sub)} | "
                         f"{yn_ok}/{len(yn)} | {ep} |")
        noise = [r for r in rows if r["variant"] == "noise"]
        if noise:
            lines += ["", "Office noise alone (20 s): " + "; ".join(
                f"gain {r['gain']}: {r['hyp']!r}" for r in noise), ""]
        wrong = [r for r in rows if r["variant"] != "noise" and r["cid"] in ("s01", "s02", "s03", "s05", "h03", "h04")
                 and _polarity(r["ref"]) != _polarity(r["hyp"])]
        if wrong:
            lines += ["Yes/no heard wrong (a flipped answer is the dangerous case; a missing one only waits):", ""]
            lines += [f"- {r['variant']} {r['gain']} {r['voice']}: {r['ref']!r} heard as {r['hyp']!r}" for r in wrong]
            lines.append("")
    vad = RESULTS / "whisper_vad.json"
    if vad.exists():
        data = json.loads(vad.read_text())
        lines += ["## Voice detector (Silero, offline)", "",
                  f"Whisper profile: `{whisper.VAD_WHISPER}`; default: pipecat's `VADParams()`.", "",
                  "| Variant | Input gain | Profile | Detected | Onset p50 (s) |", "|---|---|---|---|---|"]
        keys = sorted({(r["variant"], r["gain"], r["profile"]) for r in data["rows"]},
                      key=lambda k: (list(VARIANTS).index(k[0]), k[1], k[2]))
        for k in keys:
            sub = [r for r in data["rows"] if (r["variant"], r["gain"], r["profile"]) == k]
            on = sorted(r["onset"] for r in sub if r["onset"] is not None)
            lines.append(f"| {k[0]} | {k[1]} | {k[2]} | {sum(r['detected'] for r in sub)}/{len(sub)} | "
                         f"{on[len(on) // 2]:.2f} |" if on else f"| {k[0]} | {k[1]} | {k[2]} | 0/{len(sub)} | - |")
        lines += ["", "False starts on 60 s of office noise (-50 dBFS) with typing clicks:", ""]
        lines += [f"- gain {r['gain']}, {r['profile']}: {r['starts_per_min']} starts, {r['speaking_secs']:.1f} s "
                  f"marked as speech" for r in data["noise"]]
        lines.append("")
    spk = RESULTS / "whisper_speaker.json"
    if spk.exists():
        data = json.loads(spk.read_text())
        rows = data["rows"]
        lines += ["## Voice lock (ERes2Net, enrolled on four normal sentences)", "",
                  f"T_HIGH {data['T_HIGH']}, T_LOW {data['T_LOW']}, MIN_SECS {data['MIN_SECS']}.", "",
                  "| Variant | Owner: mean score | Owner: ≥ T_HIGH (sentences) | Owner: ≥ T_LOW (all) | "
                  "Other voice: max score |", "|---|---|---|---|---|"]
        for variant in VARIANTS:
            own = [r for r in rows if r["variant"] == variant and r["owner"] == r["voice"]]
            sent = [r for r in own if r["cid"].startswith("c")]
            other = [r for r in rows if r["variant"] == variant and r["owner"] != r["voice"]]
            lines.append(f"| {variant} | {np.mean([r['score'] for r in own]):.2f} | "
                         f"{sum(r['score'] >= data['T_HIGH'] and r['secs'] >= data['MIN_SECS'] for r in sent)}/{len(sent)}"
                         f" | {sum(r['score'] >= data['T_LOW'] for r in own)}/{len(own)} | "
                         f"{max(r['score'] for r in other):.2f} |")
        lines.append("")
    lvl = RESULTS / "whisper_level.json"
    if lvl.exists():
        rows = json.loads(lvl.read_text())
        lines += ["## Loudness barge-in (LevelGate, simulated echo at -30 dB)", "",
                  "Frames (20 ms) where loudness alone would cut the bot: before the user speaks (false) and during a "
                  "whispered \"no, don't run it\" (hit). Input gain 2.5 rows match their 1.0 rows (gain scales echo and "
                  "voice alike) and are left out.", "",
                  "| Bot volume | Whisper level | Input gain | RMS floor | False | Hit | First cut (s) |",
                  "|---|---|---|---|---|---|---|"]
        for r in rows:
            if r["input_gain"] != 1.0:
                continue
            first = "-" if r["first_cut_secs"] is None else f"{r['first_cut_secs']:.2f}"
            vol = "headphones" if r["output_gain"] == 0 else f"{r['output_gain']:.0%}"
            lines.append(f"| {vol} | {r['user_db']:+.0f} dB | {r['input_gain']} | {r['floor']} | "
                         f"{r['false_frames']} | {r['hit_frames']} | {first} |")
        lines.append("")
    (RESULTS / "whisper.md").write_text("\n".join(lines))
    print("\n".join(lines))


def _polarity(text: str) -> str:
    """allow / deny / none: what the approval check (guards.permission_answer) makes of the words."""
    import guards

    return guards.permission_answer(text) or "none"


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("step", choices=["synth", "soniox", "offline", "report"])
    step = p.parse_args().step
    if step == "synth":
        asyncio.run(synth())
    elif step == "soniox":
        asyncio.run(soniox_run())
    elif step == "offline":
        offline()
    else:
        report()
