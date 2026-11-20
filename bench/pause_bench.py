"""Does a pause in the middle of a sentence end the turn? Each Soniox setting of stt_extra.py on sentences said in two
parts with a silence between them, scored by the daemon's own rule for taking a turn (turns.settle at Normal).

  .venv/bin/python -I bench/pause_bench.py run --systems soniox-daemon-v6,soniox-v6-fin500 [--concurrency 3]
  .venv/bin/python -I bench/pause_bench.py report [--level patient]   # writes nothing; prints the table

A segment Soniox closes (<end>, or <fin> after a finalize) before the second part starts is a candidate turn. The daemon
takes it once the user has been quiet for settle(text) since the first part's sound ended (SonioxEars._release_held), and
not while the voice detector says the user talks again, which it says start_secs (0.2 s) after the voice returns. So the
pause is cut in on when max(segment arrival, first part's end + settle) comes before the second part's start + 0.2 s.
Synthetic voices (ElevenLabs), invented sentences, cached in bench/.audio like stt_bench's clips.
"""

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

import aiohttp
import numpy as np

sys.path[:0] = [str(Path(__file__).parent), str(Path(__file__).parent.parent)]
import stt_bench as sb  # noqa: E402
import stt_extra  # noqa: E402,F401  (registers the Soniox settings in sb.RUNNERS)
import turns  # noqa: E402

OUT = sb.OUT / "pause.jsonl"
VOICES = ["alice", "george"]
PAUSES = [1.2, 2.0]
VAD_START_SECS = 0.2  # pipecat's Silero start_secs: the daemon hears the user again this long after the voice returns
# (id, first part, second part). Half the first parts read unfinished to guards.unfinished, half read whole: the hard case.
SENTENCES = [
    ("en01", "Can you check whether the", "nightly export finished?"),
    ("en02", "Let's look at the parser", "and see why it fails on empty input."),
    ("en03", "Run the tests in", "the billing package and tell me what fails."),
    ("en04", "The retry loop is wrong", "because it has no backoff."),
    ("en05", "Rename the helper", "to parse invoice date everywhere."),
    ("en06", "I think the problem is", "the connection pool size."),
    ("en07", "Open a pull request", "against dev when the tests pass."),
    ("en08", "Summarize what changed", "in the admin dashboard since Monday."),
    ("en09", "What's the difference between", "a mutex and a semaphore?"),
    ("en10", "Find every place we call", "the payments API without a timeout."),
    ("he01", "תבדוק בבקשה את", "הבדיקות של שירות התשלומים."),
    ("he02", "אני רוצה להעביר את המטמון", "לשרת החדש של הצוות."),
    ("he03", "תמצא את הקובץ", "שמגדיר את ההרשאות של המשתמשים."),
    ("he04", "תריץ את הבדיקות", "ותגיד לי אם משהו נכשל."),
    ("he05", "מה ההבדל בין", "תור עבודות לבין משימה מתוזמנת?"),
    ("he06", "תסכם לי מה השתנה", "בלוח הבקרה מאז יום שני."),
    ("he07", "אני חושב שהבעיה היא", "בחיבור למסד הנתונים."),
    ("he08", "תפתח pull request", "מול הענף dev."),
    ("he09", "תעשה rebase על dev", "ואז תפתור את הקונפליקטים."),
    ("he10", "תבדוק למה השאילתה", "של המכירות השבועיות איטית."),
]


def clip_audio(first: np.ndarray, second: np.ndarray, pause: float) -> tuple[np.ndarray, float, float]:
    """The clip, and the first part's end and the second part's start, in seconds from the clip's start."""
    a, b = sb.trim_silence(first), sb.trim_silence(second)
    lead = np.zeros(int(sb.LEAD_SILENCE * sb.RATE), np.int16)
    gap = np.zeros(int(pause * sb.RATE), np.int16)
    tail = np.zeros(int(sb.TAIL_SILENCE * sb.RATE), np.int16)
    first_end = sb.LEAD_SILENCE + len(a) / sb.RATE
    return np.concatenate([lead, a, gap, b, tail]), first_end, first_end + pause


def judge(row: dict, level: str = "normal") -> dict:
    """Where the daemon would have taken the turn, from the segments Soniox closed."""
    start = row["speech_end"] - (row["clip_secs"] - sb.TAIL_SILENCE)
    first_end, resume = start + row["first_end"], start + row["resume"] + VAD_START_SECS
    early = [(t, text) for t, text in row.get("ends") or [] if t < resume and text]
    if not early:
        return {"soniox_cut": False, "pointe_cut": False}
    arrived, text = early[0]
    taken = max(arrived, first_end + turns.settle(text, held=False, level=level))
    return {"soniox_cut": True, "pointe_cut": taken < resume, "first_text": text}


async def collect(systems: list[str], concurrency: int) -> None:
    done = set()
    if OUT.exists():
        done = {(r["system"], r["clip"]) for r in map(json.loads, OUT.read_text().splitlines()) if not r.get("error")}
    clips = {}
    async with aiohttp.ClientSession() as http:
        for sid, one, two in SENTENCES:
            for voice in VOICES:
                a, b = await sb.synth(http, one, voice), await sb.synth(http, two, voice)
                for pause in PAUSES:
                    clips[f"{sid}.{voice}.{pause}"] = (sid, voice, pause, *clip_audio(a, b, pause))
    jobs = [(s, c) for s in systems for c in clips if (s, c) not in done]
    random.Random(7).shuffle(jobs)
    print(f"{len(jobs)} runs to do ({len(done)} cached)", flush=True)
    sem = {s: asyncio.Semaphore(concurrency) for s in systems}
    lock = asyncio.Lock()

    async def one(system, clip):
        sid, voice, pause, audio, first_end, resume = clips[clip]
        async with sem[system]:
            for attempt in range(3):
                try:
                    r = await sb.RUNNERS[system](audio)
                    break
                except Exception as e:
                    r = {"error": f"{type(e).__name__}: {e}"[:200]}
                    await asyncio.sleep(2)
        row = {"system": system, "clip": clip, "id": sid, "voice": voice, "pause": pause, "first_end": first_end,
               "resume": resume, "clip_secs": len(audio) / sb.RATE, **r}
        async with lock:
            with OUT.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    await asyncio.gather(*(one(s, c) for s, c in jobs))


def report(level: str = "normal") -> None:
    rows = {}
    for r in map(json.loads, OUT.read_text().splitlines()):
        if not r.get("error"):
            rows[(r["system"], r["clip"])] = {**r, **judge(r, level)}
    systems = sorted({s for s, _ in rows})
    print(f"{'system':24s} {'lang':4s} {'clips':>5s} {'Soniox ended in the pause':>26s} {'turn taken in the pause':>24s}")
    for s in systems:
        for lang in ("en", "he", "all"):
            rs = [r for (x, _), r in rows.items() if x == s and (lang == "all" or r["id"].startswith(lang))]
            print(f"{s:24s} {lang:4s} {len(rs):5d} {sum(r['soniox_cut'] for r in rs):26d} {sum(r['pointe_cut'] for r in rs):24d}")
    print("\nTurns taken in the pause:")
    for (s, c), r in sorted(rows.items()):
        if r["pointe_cut"]:
            print(f"  {s:24s} {c:18s} {r['first_text']!r}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["run", "report"])
    p.add_argument("--systems", default="soniox-daemon-v6")
    p.add_argument("--concurrency", type=int, default=3)
    p.add_argument("--level", default="normal", choices=list(turns.LEVELS), help="report: the patience setting judged")
    a = p.parse_args()
    if a.cmd == "run":
        asyncio.run(collect(a.systems.split(","), a.concurrency))
    else:
        report(a.level)


if __name__ == "__main__":
    main()
