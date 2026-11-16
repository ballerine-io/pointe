"""Where a plain answer's time goes, on a real call: the stand-in user asks short questions, and each turn's stages are
read from the daemon's `turn timing:` line (latency.py) and from the sound this client hears.

Printed: one row per turn, then the median and p90 of each stage, with the machine's load average (a busy machine adds
seconds: read the numbers with it). Judged: the time from the user's last word to the first audible sound.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-latency CLAUDE_VOICE_DAEMON_PORT=7951 CLAUDE_VOICE_TLS_PORT=7551 \
     uv run python -u -I tests/e2e/latency.py [rounds]
Calls paid APIs (the brain, Soniox, the mouth, ElevenLabs for the user's voice). POINTE_LATENCY_OUT=<file> keeps the
numbers as JSON. Every question here is made up.
"""

import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from rig import RATE, ROOT, Browser, fresh_state, log_lines, stop_daemon, synth  # noqa: E402
from scenarios import _daemon, check, results  # noqa: E402

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 1
MEDIAN_SECS, P90_SECS = 2.0, 3.0  # the goal for a plain answer: last word to first sound
QUESTIONS = [
    "Quick one. What's the difference between a mutex and a semaphore?",
    "What's a good name for a pricing microservice?",
    "Should we use feature flags for a small change like this?",
    "What's your take on Postgres versus MySQL for a small team?",
    "What time zone is Tel Aviv in?",
    "How does TCP slow start work?",
    "What is the capital of Australia?",
    "Is it better to rebase or to merge a feature branch?",
    "What does idempotent mean?",
    "Why do people use a message queue?",
    "How many bytes are in a kilobyte?",
    "What's a good way to name a boolean variable?",
]
# The path, as durations between two stamps. "heard" and "audible" are this client's: when its speech really ended and
# when the reply's sound reached it.
STAGES = [("ears: last word to final transcript", "heard", "stt_final"), ("settle: final to turn taken", "stt_final", "settled"),
          ("before the model: turn taken to request sent", "settled", "brain_sent"),
          ("model: request to first token", "brain_sent", "first_token"),
          ("model: first token to first sentence", "first_token", "first_sentence"),
          ("model: request to whole reply", "brain_sent", "reply"),
          ("checks: to words handed to the mouth", "first_sentence|reply", "checked"),
          ("mouth: handed to request sent", "checked", "tts_request"),
          ("mouth: request to first audio", "tts_request", "tts_first_byte"),
          ("output: first audio to playing", "tts_first_byte", "first_sound"),
          ("client: playing to audible", "first_sound", "audible"),
          ("turn taken to handed to the mouth", "settled", "checked"),
          ("LAST WORD TO FIRST SOUND", "heard", "audible")]


def load() -> str:
    return subprocess.run(["uptime"], capture_output=True, text=True).stdout.strip().split("load averages:")[-1].strip()


def voiced_end(pcm: np.ndarray, floor: int = 500) -> float:
    """Seconds of silence at the end of an utterance's audio: the last word ends before the audio does."""
    loud = np.flatnonzero(np.abs(pcm.astype(np.int32)) > floor)
    return (len(pcm) - 1 - int(loud[-1])) / RATE if len(loud) else 0.0


def p90(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))]


def timings() -> list[dict]:
    return [json.loads(line.split("turn timing: ", 1)[1]) for line in log_lines("turn timing: ")]


async def session(work: Path, name: str) -> None:
    """An idle synthetic session: the brain's context then looks like a call's, with sessions to speak of."""
    cwd = work / name
    cwd.mkdir(parents=True, exist_ok=True)
    transcript = work / f"latency-{name}.jsonl"
    transcript.touch()
    path = f"/tmp/latency-inbox-{name}-{os.getpid()}.sock"
    Path(path).unlink(missing_ok=True)

    async def take(reader, writer):
        await reader.read()
        writer.close()

    await asyncio.start_unix_server(take, path)
    _daemon("/voice/register", {"id": f"latency-{name}-{os.getpid()}", "cwd": str(cwd), "pid": os.getpid(), "name": name,
                                "name_given": True, "transcript": str(transcript), "inbox_socket": path})


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    fresh_state()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    work = Path(os.environ["CLAUDE_VOICE_STATE"]) / "latency-work"
    for name in ("lantern", "billing"):
        await session(work, name)
    browser = Browser()
    rows, started_load = [], load()
    try:
        await browser.connect()
        await asyncio.sleep(9)  # the greeting
        for question in QUESTIONS * ROUNDS:
            pcm = await synth(question)
            while browser.speaker.speech_spans(since=time.time() - 1.5):  # never over the voice: that is a barge-in
                await asyncio.sleep(0.3)
            await asyncio.sleep(1.5)
            n = len(timings())
            _, end = await browser.say(question)
            heard = end - voiced_end(pcm)
            deadline = heard + 15
            while time.time() < deadline and not browser.speaker.speech_spans(since=heard):
                await asyncio.sleep(0.05)
            spans = browser.speaker.speech_spans(since=heard)
            await asyncio.sleep(0.5)
            lines = timings()[n:]
            if not spans or not lines:
                print(f"no reply timed: {question!r}", flush=True)
                rows.append({"question": question})
                continue
            t = lines[0]
            zero = t["t0"]
            at = {t["from"]: zero, **{k: zero + v / 1000 for k, v in t.items() if isinstance(v, int) and k not in ("steps", "context", "cached")}}
            at.update(heard=heard, audible=spans[0][0])
            spoke = log_lines(r" speak: ")
            row = {"question": question, "at": {k: round(v - heard, 3) for k, v in at.items()}, "steps": t.get("steps"),
                   "context": t.get("context"), "cached": t.get("cached"), "early": t.get("early", False),
                   "words": len(spoke[-1].split("speak: ", 1)[1].split()) if spoke else 0}
            rows.append(row)
            print(f"{row['at']['audible']:5.2f} s  steps={row['steps']} cached={row['cached']}/{row['context']} "
                  f"words={row['words']}  {json.dumps(row['at'])}", flush=True)
    finally:
        await browser.close()
        stop_daemon()
    timed = [r for r in rows if "at" in r]
    summary = {}
    print(f"\nload average at start: {started_load}; at end: {load()}; {len(timed)} of {len(rows)} turns timed")
    print(f"{'stage':<48}{'n':>4}{'median':>9}{'p90':>8}{'max':>8}")
    for label, a, b in STAGES:
        spent = []
        for r in timed:
            start = next((r["at"][k] for k in a.split("|") if k in r["at"]), None)
            if start is not None and b in r["at"]:
                spent.append(r["at"][b] - start)
        if spent:
            summary[label] = {"n": len(spent), "median": round(statistics.median(spent), 3), "p90": round(p90(spent), 3),
                              "max": round(max(spent), 3)}
            print(f"{label:<48}{len(spent):>4}{statistics.median(spent):>9.2f}{p90(spent):>8.2f}{max(spent):>8.2f}")
    total = [r["at"]["audible"] for r in timed]
    one_step = sum(r["steps"] == 1 for r in timed)
    cached = [r["cached"] / r["context"] for r in timed if r.get("context")]
    print(f"one model step: {one_step} of {len(timed)}; cached share of the prompt, median: "
          f"{statistics.median(cached) if cached else 0:.0%}; first sentence spoken before the whole reply: "
          f"{sum(bool(r['early']) for r in timed)}")
    if os.environ.get("POINTE_LATENCY_OUT"):
        Path(os.environ["POINTE_LATENCY_OUT"]).write_text(json.dumps(
            {"load_start": started_load, "load_end": load(), "summary": summary, "rows": rows}, indent=1))
    check(f"every question got a timed reply", len(timed) == len(rows), timed=len(timed), asked=len(rows))
    if total:
        check(f"last word to first sound: median within {MEDIAN_SECS} s", statistics.median(total) <= MEDIAN_SECS,
              median=round(statistics.median(total), 2), load=started_load)
        check(f"last word to first sound: p90 within {P90_SECS} s", p90(total) <= P90_SECS, p90=round(p90(total), 2),
              max=round(max(total), 2), load=started_load)
    print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (latency)")


asyncio.run(main())
