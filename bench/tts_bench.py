"""Streaming text-to-speech benchmark: latency, round-trip intelligibility, Hebrew check, cost.

  .venv/bin/python -I bench/tts_bench.py run [--reps 3] [--models a,b] [--limit N]
  .venv/bin/python -I bench/tts_bench.py report

Keys are read from the macOS Keychain into this process only. To add a vendor, write an
Adapter subclass (name, sample_rate, `stream(text, lang)` yielding PCM s16le bytes) and
register it in ADAPTERS.

Method: each clip is synthesised REPS times, sequentially per vendor (vendors run in parallel).
TTFB = request sent to first audio byte, on a connection that is already open (HTTP keep-alive
or an open WebSocket, as in a live pipeline). Round trip: every synthesised clip is transcribed
by Soniox real-time and scored against the source text.
"""

import os
import argparse
import asyncio
import base64
import json
import random
import re
import subprocess
import sys
import time
import unicodedata
import wave
from pathlib import Path

import aiohttp
import numpy as np
import websockets

sys.path.insert(0, str(Path(__file__).parent))
from tts_corpus import SAMPLE_IDS, TTS_CORPUS  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE / "results"
RAW = OUT / "tts-raw.jsonl"
SAMPLES = OUT / "tts-samples"
STT_MODEL = "stt-rt-v6"
EL_VOICE = "EXAVITQu4vr4xnSDxMaL"  # a stock ElevenLabs voice, same for every language
GEMINI_VOICE = "Charon"
SONIOX_VOICE = "Adrian"
OPENAI_VOICE = "ash"
_SECRETS: set[str] = set()


def keychain(item: str) -> str:
    value = subprocess.run(["security", "find-generic-password", "-s", item, "-w"],
                           capture_output=True, text=True, check=True).stdout.strip()
    _SECRETS.add(value)
    return value


def scrub(text: str) -> str:
    for s in _SECRETS:
        text = text.replace(s, "***")
    return text[:300]


# ---------- adapters ----------

class Adapter:
    name = ""
    vendor = ""
    sample_rate = 24000
    claims_hebrew: bool | None = None  # vendor's own published language list, None = unknown

    async def setup(self, http: aiohttp.ClientSession) -> None:
        self.http = http

    async def preflight(self) -> str | None:
        """Return a reason string if this adapter cannot be measured, else None."""
        return None

    async def stream(self, text: str, lang: str):
        raise NotImplementedError
        yield b""


class ElevenLabs(Adapter):
    vendor = "elevenlabs"

    def __init__(self, model: str, claims_hebrew: bool):
        self.model, self.name, self.claims_hebrew = model, f"elevenlabs/{model}", claims_hebrew

    async def setup(self, http):
        await super().setup(http)
        self.key = keychain("elevenlabs-api-key")

    async def stream(self, text, lang):
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{EL_VOICE}/stream?output_format=pcm_24000"
        async with self.http.post(url, headers={"xi-api-key": self.key},
                                  json={"text": text, "model_id": self.model}) as r:
            if r.status >= 400:
                raise RuntimeError(f"HTTP {r.status}: {(await r.text())[:200]}")
            async for chunk in r.content.iter_any():
                yield chunk


class GeminiTTS(Adapter):
    vendor = "gemini"
    claims_hebrew = True

    def __init__(self, model: str):
        self.model, self.name = model, f"gemini/{model}"

    async def setup(self, http):
        await super().setup(http)
        from google import genai
        self.client = genai.Client(api_key=(os.environ.get("GOOGLE_API_KEY") or keychain("gemini-api-key")))

    async def stream(self, text, lang):
        from google.genai import types
        cfg = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=GEMINI_VOICE))))
        got = False
        async for chunk in await self.client.aio.models.generate_content_stream(
                model=self.model, contents=text, config=cfg):
            for cand in chunk.candidates or []:
                for part in (cand.content.parts if cand.content else None) or []:
                    if part.inline_data and part.inline_data.data:
                        got = True
                        yield part.inline_data.data
        if not got:
            raise RuntimeError("no audio returned")


class SonioxTTS(Adapter):
    vendor = "soniox"
    claims_hebrew = True
    model = "tts-rt-v2"
    name = "soniox/tts-rt-v2"

    async def setup(self, http):
        await super().setup(http)
        self.key = keychain("soniox-api-key")
        self.ws = None
        self.n = 0

    async def _conn(self):
        if self.ws is None or self.ws.close_code is not None:
            self.ws = await websockets.connect("wss://tts-rt.soniox.com/tts-websocket",
                                               additional_headers={"Authorization": f"Bearer {self.key}"})
        return self.ws

    async def stream(self, text, lang):
        ws = await self._conn()
        self.n += 1
        sid = f"s{self.n}"
        await ws.send(json.dumps({"stream_id": sid, "model": self.model, "voice": SONIOX_VOICE,
                                  "language": "en" if lang == "en" else "he",
                                  "audio_format": "pcm_s16le", "sample_rate": self.sample_rate}))
        await ws.send(json.dumps({"text": text, "text_end": True, "stream_id": sid}))
        try:
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 30))
                if msg.get("error_code") is not None:
                    raise RuntimeError(f"soniox {msg.get('error_code')}: {msg.get('error_message')}")
                if msg.get("audio"):
                    yield base64.b64decode(msg["audio"])
                if msg.get("terminated"):
                    return
        except BaseException:
            await ws.close()
            self.ws = None
            raise


class OpenAITTS(Adapter):
    vendor = "openai"
    claims_hebrew = True
    model = "gpt-4o-mini-tts"
    name = "openai/gpt-4o-mini-tts"

    async def setup(self, http):
        await super().setup(http)
        self.key = keychain("openai-api-key")

    async def preflight(self):
        async with self.http.get("https://api.openai.com/v1/models",
                                 headers={"Authorization": f"Bearer {self.key}"}) as r:
            return None if r.status == 200 else f"not measured: key rejected (HTTP {r.status})"

    async def stream(self, text, lang):
        async with self.http.post("https://api.openai.com/v1/audio/speech",
                                  headers={"Authorization": f"Bearer {self.key}"},
                                  json={"model": self.model, "voice": OPENAI_VOICE, "input": text,
                                        "response_format": "pcm"}) as r:
            if r.status >= 400:
                raise RuntimeError(f"HTTP {r.status}: {(await r.text())[:200]}")
            async for chunk in r.content.iter_any():
                yield chunk


ADAPTERS: list[Adapter] = [
    ElevenLabs("eleven_flash_v2_5", claims_hebrew=False),
    ElevenLabs("eleven_turbo_v2_5", claims_hebrew=False),
    ElevenLabs("eleven_v4_turbo", claims_hebrew=True),
    ElevenLabs("eleven_v4", claims_hebrew=True),
    ElevenLabs("eleven_v3_conversational", claims_hebrew=True),
    GeminiTTS("gemini-3.8-flash-tts"),
    GeminiTTS("gemini-3.8-flash-lite-tts"),
    SonioxTTS(),
    OpenAITTS(),
]

# Public list prices, USD, read 2026-11-05. Gemini, Soniox and OpenAI bill tokens, so their per-1k-character
# figure is derived from the measured audio seconds and text length (see cost_per_1k_chars).
PRICING = {
    "elevenlabs/eleven_flash_v2_5": ("per_char", 0.04, "elevenlabs.io/pricing/api, row 'Flash / Turbo'"),
    "elevenlabs/eleven_turbo_v2_5": ("per_char", 0.04, "elevenlabs.io/pricing/api, row 'Flash / Turbo'"),
    "elevenlabs/eleven_v4_turbo": ("per_char", 0.04, "elevenlabs.io/pricing/api, row 'v4 Turbo'"),
    "elevenlabs/eleven_v4": ("per_char", 0.08, "elevenlabs.io/pricing/api, row 'v4'"),
    "elevenlabs/eleven_v3_conversational": ("per_char", 0.04, "elevenlabs.io/pricing/api, row 'v3 Conversational'"),
    # text $/1M tokens, audio $/1M tokens, audio tokens per second
    "gemini/gemini-3.8-flash-tts": ("tokens", (0.50, 9.00, 25), "ai.google.dev/gemini-api/docs/pricing; intro price to 2026-12-31, doubles on 2027-01-01"),
    "gemini/gemini-3.8-flash-lite-tts": ("tokens", (0.50, 6.00, 25), "ai.google.dev/gemini-api/docs/pricing; intro price to 2026-12-31, doubles on 2027-01-01"),
    "soniox/tts-rt-v2": ("tokens", (4.00, 21.50, 25), "soniox.com/pricing; audio tokens per second NOT published on the page: 25/s ASSUMED (same as Gemini)"),
    "openai/gpt-4o-mini-tts": ("tokens", (0.60, 12.00, 25), "developers.openai.com/api/docs/pricing; audio tokens per second NOT published: 25/s ASSUMED"),
}


# ---------- audio ----------

def write_wav(path: Path, pcm: bytes, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


async def transcribe(pcm: bytes, rate: int, key: str) -> str:
    """Soniox real-time transcription of a finished clip (sent faster than real time)."""
    async with websockets.connect("wss://stt-rt.soniox.com/transcribe-websocket") as ws:
        await ws.send(json.dumps({"api_key": key, "model": STT_MODEL, "audio_format": "pcm_s16le",
                                  "sample_rate": rate, "num_channels": 1, "language_hints": ["en", "he"]}))
        parts: list[str] = []

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("error_code"):
                    raise RuntimeError(f"stt {msg['error_code']}: {msg.get('error_message')}")
                for tok in msg.get("tokens", []):
                    if tok.get("is_final") and tok["text"] not in ("<end>", "<fin>"):
                        parts.append(tok["text"])
                if msg.get("finished"):
                    return

        task = asyncio.create_task(reader())
        step = rate * 2 // 5  # 200 ms
        for i in range(0, len(pcm), step):
            await ws.send(pcm[i:i + step])
        await ws.send(b"\x00" * (rate * 2))  # 1 s of silence so the last word finalises
        await ws.send("")
        await asyncio.wait_for(task, 60)
    return "".join(parts).strip()


# ---------- run ----------

async def synth_once(ad: Adapter, text: str, lang: str) -> dict:
    t0 = time.perf_counter()
    first = None
    chunks: list[bytes] = []
    try:
        async for c in ad.stream(text, lang):
            if c and first is None:
                first = time.perf_counter() - t0
            chunks.append(c)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {scrub(str(e))}"}
    total = time.perf_counter() - t0
    pcm = b"".join(chunks)
    pcm = pcm[: len(pcm) // 2 * 2]
    if first is None or not pcm:
        return {"error": "no audio"}
    return {"ttfb": first, "total": total, "pcm": pcm, "audio_s": len(pcm) / 2 / ad.sample_rate}


async def run_vendor(ads: list[Adapter], clips, reps: int, done: set, http, stt_key: str,
                     lock: asyncio.Lock, stt_sem: asyncio.Semaphore) -> None:
    jobs = []
    for ad in ads:
        await ad.setup(http)
        reason = await ad.preflight()
        if reason:
            print(f"{ad.name}: {reason}", flush=True)
            async with lock:
                with RAW.open("a") as f:
                    f.write(json.dumps({"model": ad.name, "unmeasured": reason}) + "\n")
            continue
        jobs.append(ad)
    pending: list[asyncio.Task] = []

    async def finish(ad, cid, lang, text, rep, r):
        row = {"model": ad.name, "clip": cid, "lang": lang, "rep": rep, "chars": len(text), "ref": text}
        if "error" in r:
            row["error"] = r["error"]
        else:
            row.update({k: r[k] for k in ("ttfb", "total", "audio_s")})
            if rep == 0 and SAMPLE_IDS[lang] == cid:
                write_wav(SAMPLES / f"{ad.name.replace('/', '_')}_{lang}.wav", r["pcm"], ad.sample_rate)
            try:
                async with stt_sem:
                    row["hyp"] = await transcribe(r["pcm"], ad.sample_rate, stt_key)
            except Exception as e:
                row["stt_error"] = f"{type(e).__name__}: {scrub(str(e))}"
        async with lock:
            with RAW.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    for rep in range(reps):
        for cid, lang, text in clips:
            for ad in jobs:
                if (ad.name, cid, rep) in done:
                    continue
                r = await synth_once(ad, text, lang)
                if "error" in r:  # one retry; a failed run stays recorded as an error
                    await asyncio.sleep(2)
                    r = await synth_once(ad, text, lang)
                pending.append(asyncio.create_task(finish(ad, cid, lang, text, rep, r)))
        print(f"  {ads[0].vendor}: rep {rep + 1}/{reps} synthesised", flush=True)
    await asyncio.gather(*pending)


async def collect(reps: int, models: list[str] | None, limit: int | None) -> None:
    OUT.mkdir(exist_ok=True)
    done = set()
    if RAW.exists():
        for line in RAW.read_text().splitlines():
            r = json.loads(line)
            if "clip" in r and not r.get("error") and "hyp" in r:
                done.add((r["model"], r["clip"], r["rep"]))
    clips = TTS_CORPUS[:limit] if limit else TTS_CORPUS
    if limit:  # keep the three languages balanced
        clips = [c for lang in ("en", "he", "mix") for c in [x for x in TTS_CORPUS if x[1] == lang][: max(1, limit // 3)]]
    ads = [a for a in ADAPTERS if not models or any(m in a.name for m in models)]
    stt_key = keychain("soniox-api-key")
    lock, stt_sem = asyncio.Lock(), asyncio.Semaphore(4)
    by_vendor: dict[str, list[Adapter]] = {}
    for a in ads:
        by_vendor.setdefault(a.vendor, []).append(a)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as http:
        await asyncio.gather(*(run_vendor(v, clips, reps, done, http, stt_key, lock, stt_sem)
                               for v in by_vendor.values()))


# ---------- scoring ----------

ONES = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
HEB_RE = re.compile(r"[֐-׿]")


def words_to_digits(tokens: list[str]) -> list[str]:
    """English number words to digits: 'two hundred and twelve' -> '212'. Hebrew number words are not handled."""
    out, i = [], 0
    while i < len(tokens):
        t = tokens[i]
        if t in ONES or t in TENS or (t == "hundred") or (t == "thousand"):
            total = cur = 0
            j, seen = i, False
            while j < len(tokens):
                w = tokens[j]
                if w in ONES:
                    cur += ONES[w]
                elif w in TENS:
                    cur += TENS[w]
                elif w == "hundred" and seen:
                    cur = max(cur, 1) * 100
                elif w == "thousand" and seen:
                    total += max(cur, 1) * 1000
                    cur = 0
                elif w == "and" and seen and j + 1 < len(tokens) and (tokens[j + 1] in ONES or tokens[j + 1] in TENS):
                    pass
                else:
                    break
                seen = True
                j += 1
            out.append(str(total + cur))
            i = j
        else:
            out.append(t)
            i += 1
    return out


def normalize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[֑-ׇ]", "", text)  # niqqud, cantillation
    text = text.replace("׳", "'").replace("’", "'")
    text = re.sub(r"(\d),(\d{3})", r"\1\2", text)  # 4,250 -> 4250
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text)  # 14th -> 14
    text = re.sub(r"\$\s?(\d+(?:\.\d+)?)", r"\1 dollars", text)
    text = re.sub(r"(\d+)\s?%", r"\1 percent", text)
    text = re.sub(r"[-_־]", " ", text)
    text = re.sub(r"[^\w\s']", " ", text)
    return words_to_digits(text.split())


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


def hebrew_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum(1 for c in letters if HEB_RE.match(c)) / max(1, len(letters))


WER_PASS = 0.5
HEB_SHARE_MIN = 0.8


def heard_as_hebrew(lang: str, ref: str, hyp: str) -> bool:
    """A Hebrew clip counts as spoken Hebrew if the round trip is intelligible (WER <= 0.5) AND comes back in
    Hebrew script. Mixed clips: intelligible AND at least half the reference's Hebrew-script share."""
    if wer(ref, hyp) > WER_PASS:
        return False
    need = HEB_SHARE_MIN if lang == "he" else 0.5 * hebrew_share(ref)
    return hebrew_share(hyp) >= need


def pct(values, q):
    return float(np.percentile(values, q))


def cluster_bootstrap(rows: list[dict], key: str, q: float, n: int = 2000, seed: int = 1) -> tuple[float, float]:
    """95% CI of a percentile, resampling clips (repetitions of one clip are not independent)."""
    rng = np.random.default_rng(seed)
    groups: dict[str, list[float]] = {}
    for r in rows:
        groups.setdefault(r["clip"], []).append(r[key])
    arrs = list(groups.values())
    est = []
    for _ in range(n):
        pick = rng.integers(0, len(arrs), len(arrs))
        est.append(np.percentile(np.concatenate([arrs[i] for i in pick]), q))
    return float(np.percentile(est, 2.5)), float(np.percentile(est, 97.5))


def mean_ci(values: list[float], n: int = 2000, seed: int = 2) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    arr = np.array(values, dtype=float)
    m = rng.choice(arr, (n, len(arr))).mean(axis=1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def cost_per_1k_chars(model: str, rows: list[dict]) -> tuple[float, str]:
    kind, val, src = PRICING[model]
    if kind == "per_char":
        return val, src
    text_p, audio_p, tps = val
    chars = sum(r["chars"] for r in rows)
    secs = sum(r["audio_s"] for r in rows)
    text_tokens = chars * 0.3  # ~0.3 tokens per character (Soniox's own rule of thumb); an assumption for Hebrew
    usd = text_tokens * text_p / 1e6 + secs * tps * audio_p / 1e6
    return usd / chars * 1000, src


def report() -> None:
    raw = [json.loads(l) for l in RAW.read_text().splitlines()]
    unmeasured = {r["model"]: r["unmeasured"] for r in raw if "unmeasured" in r}
    latest: dict = {}
    for r in raw:
        if "clip" in r and (not r.get("error") or (r["model"], r["clip"], r["rep"]) not in latest):
            latest[(r["model"], r["clip"], r["rep"])] = r
    rows = list(latest.values())
    models = [a.name for a in ADAPTERS]
    out: list[str] = []
    ok = lambda m, lang=None: [r for r in rows if r["model"] == m and "ttfb" in r and (lang is None or r["lang"] == lang)]
    n_clips = len({r["clip"] for r in rows})
    out.append(f"clips: {n_clips}, repetitions per clip: {1 + max(r['rep'] for r in rows)}\n")

    out.append("## Latency and speed (all languages pooled)\n")
    out.append("| model | runs ok/tried | TTFB p50 [95% CI] | TTFB p95 [95% CI] | total p50 | RTF p50 | audio s/clip |")
    out.append("|---|---|---|---|---|---|---|")
    for m in models:
        if m in unmeasured:
            out.append(f"| {m} | not measured | {unmeasured[m]} | | | | |")
            continue
        g = ok(m)
        tried = [r for r in rows if r["model"] == m]
        if not g:
            out.append(f"| {m} | 0/{len(tried)} | all runs failed | | | | |")
            continue
        for r in g:
            r["rtf"] = r["total"] / r["audio_s"]
        c50, c95 = cluster_bootstrap(g, "ttfb", 50), cluster_bootstrap(g, "ttfb", 95)
        out.append(f"| {m} | {len(g)}/{len(tried)} | {pct([r['ttfb'] for r in g], 50)*1000:.0f} ms "
                   f"[{c50[0]*1000:.0f}-{c50[1]*1000:.0f}] | {pct([r['ttfb'] for r in g], 95)*1000:.0f} ms "
                   f"[{c95[0]*1000:.0f}-{c95[1]*1000:.0f}] | {pct([r['total'] for r in g], 50):.2f} s | "
                   f"{pct([r['rtf'] for r in g], 50):.2f} | {np.mean([r['audio_s'] for r in g]):.1f} |")

    out.append("\n## TTFB p50 by language (ms)\n")
    out.append("| model | en | he | mix |\n|---|---|---|---|")
    for m in models:
        if m in unmeasured or not ok(m):
            continue
        cells = [f"{pct([r['ttfb'] for r in ok(m, l)], 50)*1000:.0f}" if ok(m, l) else "-" for l in ("en", "he", "mix")]
        out.append(f"| {m} | " + " | ".join(cells) + " |")

    out.append("\n## Round-trip intelligibility (Soniox " + STT_MODEL + " transcribes each clip)\n")
    out.append("Mean WER, 95% bootstrap CI over clips; Hebrew-as-Hebrew = share of clips that are intelligible "
               "(WER <= 0.5) and returned in Hebrew script.\n")
    out.append("| model | WER en | WER he | WER mix | CER mix | Hebrew-as-Hebrew he | Hebrew-as-Hebrew mix | Hebrew verdict | vendor claims Hebrew |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    ads = {a.name: a for a in ADAPTERS}
    for m in models:
        if m in unmeasured:
            out.append(f"| {m} | not measured | | | | | | not measured | {ads[m].claims_hebrew} |")
            continue
        sc = {}
        for l in ("en", "he", "mix"):
            g = [r for r in ok(m, l) if "hyp" in r]
            sc[l] = g
        cells = []
        for l in ("en", "he", "mix"):
            g = sc[l]
            if not g:
                cells.append("-")
                continue
            w = [wer(r["ref"], r["hyp"]) for r in g]
            lo, hi = mean_ci(w)
            cells.append(f"{np.mean(w):.3f} [{lo:.3f}-{hi:.3f}] (n={len(g)})")
        cm = [cer(r["ref"], r["hyp"]) for r in sc["mix"]]
        hh = {l: np.mean([heard_as_hebrew(l, r["ref"], r["hyp"]) for r in sc[l]]) if sc[l] else None for l in ("he", "mix")}
        verdict = "-" if hh["he"] is None else ("PASS" if hh["he"] >= 0.8 else "PARTIAL" if hh["he"] >= 0.3 else "FAIL")
        fmt = lambda v: "-" if v is None else f"{v*100:.0f}%"
        out.append(f"| {m} | " + " | ".join(cells) + f" | {np.mean(cm):.3f} | {fmt(hh['he'])} | {fmt(hh['mix'])} | {verdict} | {ads[m].claims_hebrew} |")

    out.append("\n## Cost per 1,000 characters (USD, list price read 2026-11-05)\n")
    out.append("| model | $/1k chars | basis |\n|---|---|---|")
    for m in models:
        if m in unmeasured and m not in PRICING:
            continue
        g = ok(m)
        if PRICING[m][0] == "tokens" and not g:
            out.append(f"| {m} | not computed (no audio measured) | {PRICING[m][2]} |")
            continue
        c, src = cost_per_1k_chars(m, g) if g else (PRICING[m][1], PRICING[m][2])
        out.append(f"| {m} | {c:.4f} | {src} |")
    errs = [r for r in rows if r.get("error") or r.get("stt_error")]
    out.append(f"\nFailed runs: {len(errs)}")
    for m in models:
        e = [r for r in errs if r["model"] == m]
        if e:
            out.append(f"- {m}: {len(e)} failed, e.g. {e[0].get('error') or e[0].get('stt_error')}")
    text = "\n".join(out)
    print(text)
    (OUT / "tts-tables.md").write_text(text + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["run", "report"])
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--models", help="comma list of substrings, e.g. flash,soniox")
    p.add_argument("--limit", type=int, help="clips per run (balanced across languages), for smoke tests")
    a = p.parse_args()
    if a.cmd == "run":
        asyncio.run(collect(a.reps, a.models.split(",") if a.models else None, a.limit))
    else:
        report()
