"""Does the dictionary help? Soniox with and without the learned terms, on synthetic clips of invented names.

Every clip runs twice through the same Soniox real-time model the daemon uses (stt-rt-v5, en+he hints), streamed at
real-time pace: once with no context, once with `context.terms` built the way the daemon builds it
(vocabulary.terms_for with these names in the dictionary). Scored:

- names: the name appears in the final transcript spelled as in the dictionary (whole word, case ignored).
- controls: sentences with no dictionary name, among them plain yes/no answers and a non-answer that sounds like one
  ("Yesterday's build is green"). Word error rate with and without terms, and whether a non-answer ever came back as a
  bare yes or no. The terms must not hurt them.

  uv run python -I bench/vocab_bench.py run [--voices alice,roger]   # collect bench/results/vocab.jsonl
  uv run python -I bench/vocab_bench.py report                       # the table, also bench/results/vocab.md

Keys from the macOS Keychain (soniox-api-key, elevenlabs-api-key), as bench/stt_bench.py. Every name is made up.
"""

import argparse
import asyncio
import hashlib
import json
import random
import sys
from pathlib import Path

import aiohttp
import websockets

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1]))
from stt_bench import NOISE_SNR_DB, RATE, frame, keychain, normalize, stream, synth, wer, with_noise  # noqa: E402

import vocabulary  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE / "results" / "vocab.jsonl"

# (id, sentence, the dictionary term it says). Invented repos, services and people.
NAMES = [
    ("n01", "Open the Quillfeather repo and run the tests.", "Quillfeather"),
    ("n02", "Tell Marrowind to rebase on dev.", "Marrowind"),
    ("n03", "Did Kestrelbay finish the migration?", "Kestrelbay"),
    ("n04", "Bump vellichor-ui to the latest minor version.", "vellichor-ui"),
    ("n05", "What does the Brontide worker do when a job times out?", "Brontide"),
    ("n06", "Merge Lumenquist into main after the review.", "Lumenquist"),
    ("n07", "Send the release notes to Ysolde Varnatt.", "Varnatt"),
    ("n08", "Check why Zephyrine keeps failing on staging.", "Zephyrine"),
    ("n09", "Ask Okonkwo-api for the error budget.", "Okonkwo-api"),
    ("n10", "Rename the Tarnwick queue to orders.", "Tarnwick"),
    ("n11", "Is Halvorsen still blocked on the schema change?", "Halvorsen"),
    ("n12", "Deploy Pellucine to the preview environment.", "Pellucine"),
    ("h01", "תפתח את Quillfeather ותריץ את הבדיקות.", "Quillfeather"),
    ("h02", "תבדוק למה Marrowind נופל בכל פעם.", "Marrowind"),
    ("h03", "תשאל את Kestrelbay אם המיגרציה הסתיימה.", "Kestrelbay"),
    ("h04", "תעדכן את vellichor-ui לגרסה האחרונה.", "vellichor-ui"),
]
CONTROLS = [
    ("c01", "Yes, go ahead."),
    ("c02", "No, don't do that."),
    ("c03", "Yesterday's build is green."),
    ("c04", "Run the typecheck on orbit-api and tell me if it passes."),
    ("c05", "Why is the weekly sales query so slow on production?"),
    ("c06", "כן, תמשיך."),
    ("c07", "מה המצב של הבדיקות בענף הזה?"),
]
NON_ANSWERS = {"c03", "c04", "c05", "c07"}
DICTIONARY = sorted({t for _, _, t in NAMES})


def context_terms() -> list[str]:
    """The daemon's list: these names in the dictionary, nothing else (vocabulary.terms_for drops consent words)."""
    book = vocabulary.Dictionary(Path("/nonexistent/vocab-bench.json"))
    book.entries = [{"term": t, "lang": "en", "source": "manual", "hits": 0, "added_at": 0.0, "confirmed": True}
                    for t in DICTIONARY]
    return vocabulary.terms_for(book, [], {}, [])


async def run_soniox(audio, terms: list[str] | None) -> dict:
    async with websockets.connect("wss://stt-rt.soniox.com/transcribe-websocket") as ws:
        config = {"api_key": keychain("soniox-api-key"), "model": "stt-rt-v5", "audio_format": "pcm_s16le",
                  "sample_rate": RATE, "num_channels": 1, "language_hints": ["en", "he"], "enable_endpoint_detection": True}
        if terms:
            config["context"] = {"terms": terms}
        await ws.send(json.dumps(config))
        final: list[str] = []
        error: dict = {}

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                for tok in msg.get("tokens", []):
                    if tok.get("is_final") and tok["text"] not in ("<end>", "<fin>"):
                        final.append(tok["text"])
                if msg.get("error_code"):
                    error.update(code=msg["error_code"], message=msg.get("error_message"))
                    return
                if msg.get("finished"):
                    return

        task = asyncio.create_task(reader())
        await stream(ws.send, audio)
        await ws.send("")
        await asyncio.wait_for(task, 20)
    if error:
        raise RuntimeError(f"soniox {error.get('code')}: {error.get('message')}")
    return {"text": "".join(final).strip()}


async def collect(voices: list[str], concurrency: int) -> None:
    OUT.parent.mkdir(exist_ok=True)
    done = set()
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            r = json.loads(line)
            if not r.get("error"):
                done.add((r["clip"], r["arm"]))
    items = [(cid, text, term) for cid, text, term in NAMES] + [(cid, text, None) for cid, text in CONTROLS]
    terms = context_terms()
    async with aiohttp.ClientSession() as http:
        audio = {}
        for cid, text, term in items:
            for voice in voices:
                pcm = await synth(http, text, voice)
                for cond in ("clean", "noisy"):
                    clip = f"{cid}.{voice}.{cond}"
                    seed = int(hashlib.sha1(clip.encode()).hexdigest()[:8], 16)
                    audio[clip] = (cid, text, term, voice, cond, frame(with_noise(pcm, NOISE_SNR_DB, seed) if cond == "noisy" else pcm))
    jobs = [(clip, arm) for clip in audio for arm in ("none", "dictionary") if (clip, arm) not in done]
    random.Random(7).shuffle(jobs)
    print(f"{len(jobs)} runs to do ({len(done)} cached), {len(terms)} terms", flush=True)
    sem, lock = asyncio.Semaphore(concurrency), asyncio.Lock()

    async def one(clip, arm):
        cid, text, term, voice, cond, pcm = audio[clip]
        async with sem:
            for attempt in range(5):
                try:
                    r = await run_soniox(pcm, terms if arm == "dictionary" else None)
                    break
                except Exception as e:  # a 429 or a dropped socket: wait, then try again
                    r = {"error": f"{type(e).__name__}: {e}"[:300]}
                    await asyncio.sleep(5 * (attempt + 1))
        row = {"clip": clip, "id": cid, "arm": arm, "voice": voice, "cond": cond, "ref": text, "term": term, **r}
        async with lock:
            with OUT.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    await asyncio.gather(*(one(c, a) for c, a in jobs))


def name_hit(term: str, text: str) -> bool:
    import re
    return bool(re.search(rf"(?<![\w-]){re.escape(term.lower())}(?![\w-])", text.lower()))


def bare_answer(text: str) -> bool:
    words = normalize(text)
    return 0 < len(words) <= 3 and bool(set(words) & {"yes", "no", "yeah", "כן", "לא"})


def report() -> str:
    rows = [json.loads(line) for line in OUT.read_text().splitlines()]
    rows = [r for r in rows if not r.get("error")]
    by = {(r["clip"], r["arm"]): r for r in rows}
    clips = sorted({r["clip"] for r in rows})
    paired = [c for c in clips if (c, "none") in by and (c, "dictionary") in by]
    lines = ["# Dictionary terms on Soniox (stt-rt-v5), synthetic clips", ""]
    names = [c for c in paired if by[(c, "none")]["term"]]
    controls = [c for c in paired if not by[(c, "none")]["term"]]

    def rate(subset, arm):
        hits = sum(name_hit(by[(c, arm)]["term"], by[(c, arm)]["text"]) for c in subset)
        return hits, len(subset)

    lines += ["| Names | Without terms | With the dictionary |", "|---|---|---|"]
    for label, pick in [("all", lambda c: True), ("English sentences", lambda c: c.startswith("n")),
                        ("Hebrew sentences", lambda c: c.startswith("h")), ("clean", lambda c: ".clean" in c),
                        ("noisy (12 dB pink)", lambda c: ".noisy" in c)]:
        subset = [c for c in names if pick(c)]
        if subset:
            (a, n), (b, _) = rate(subset, "none"), rate(subset, "dictionary")
            lines.append(f"| {label} | {a}/{n} ({100 * a / n:.0f}%) | {b}/{n} ({100 * b / n:.0f}%) |")
    flips = {"fixed": [], "broken": []}
    for c in names:
        a, b = name_hit(by[(c, "none")]["term"], by[(c, "none")]["text"]), name_hit(by[(c, "dictionary")]["term"], by[(c, "dictionary")]["text"])
        if a != b:
            flips["fixed" if b else "broken"].append(c)
    lines += ["", f"Clips the terms fixed: {len(flips['fixed'])}; clips they broke: {len(flips['broken'])}."]
    if controls:
        w0 = sum(wer(by[(c, "none")]["ref"], by[(c, "none")]["text"]) for c in controls) / len(controls)
        w1 = sum(wer(by[(c, "dictionary")]["ref"], by[(c, "dictionary")]["text"]) for c in controls) / len(controls)
        bare = [c for c in controls if c.split(".")[0] in NON_ANSWERS and bare_answer(by[(c, "dictionary")]["text"])]
        lines += ["", "| Controls (no dictionary name) | Without terms | With the dictionary |", "|---|---|---|",
                  f"| mean WER, {len(controls)} clips | {w0:.3f} | {w1:.3f} |",
                  "", f"Non-answers heard as a bare yes or no with the dictionary: {len(bare)}."]
    lines += ["", "Misses with the dictionary:"]
    for c in names:
        r = by[(c, "dictionary")]
        if not name_hit(r["term"], r["text"]):
            lines.append(f"- {c}: {r['term']} -> \"{r['text']}\"")
    lines += ["", "What the terms changed (without -> with):"]
    for c in flips["fixed"] + flips["broken"]:
        lines.append(f"- {c}: \"{by[(c, 'none')]['text']}\" -> \"{by[(c, 'dictionary')]['text']}\"")
    out = "\n".join(lines) + "\n"
    (HERE / "results" / "vocab.md").write_text(out)
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["run", "report"])
    p.add_argument("--voices", default="alice,roger")
    p.add_argument("--concurrency", type=int, default=4)
    a = p.parse_args()
    if a.cmd == "run":
        asyncio.run(collect(a.voices.split(","), a.concurrency))
    print(report())


if __name__ == "__main__":
    main()
