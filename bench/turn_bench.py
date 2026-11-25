"""When is a turn taken, and is the speaker cut in on? The daemon's rule for the end of a turn (`before`: Normal)
against a candidate that listens to three signals (`after`: turns.CANDIDATE, with the words, Soniox's own endpoint
and the sound of the voice), on the same clips. The candidate is not what Pointe does: this bench is why.

  .venv/bin/python -I bench/turn_bench.py run [--concurrency 2]   # Soniox, real time: about $0.60 and 40 minutes
  .venv/bin/python -I bench/turn_bench.py report                  # prints the tables; writes nothing

Two kinds of clip. A hesitation: a sentence said in two parts with 0.5, 0.8 or 1.2 s of silence between them (the
clips keep 0.1 s around each part, and the daemon hears the voice again 0.2 s after it returns, so the turn can be
taken for 0.9, 1.2 or 1.6 s). Some first parts trail off ("and then", "um"), the others read whole, the hard case. A
turn taken before the second part is a cut-in. And a whole sentence, where what counts is how long after its last
sound the turn is taken.

Each clip is streamed to Soniox twice, as the daemon would: `before` asks Soniox for held words 0.7 s after the sound
(turns.finalize_after at Normal), `after` asks 0.3 s after it when the voice sounded finished (turnsound.score at the
voice detector's stop). Every segment Soniox closes is kept with its time, its text and whether Soniox closed it
itself (<end>) or on request (<fin>). The report replays SonioxEars on those: a segment is held while it settles, a
later one joins it, and the turn is taken once the sound has been over for the settle time.

Synthetic voices (ElevenLabs, two of them), invented sentences, clips cached in bench/.audio. A first part read
aloud by a synthetic voice ends like a sentence; a person searching for a word may not. So the rates rank the two
rules on these clips and do not predict the rate on real calls: recorded human pauses are needed for that. Hebrew
clips never get the sound's vote: the model was not measured on Hebrew."""

import argparse
import asyncio
import json
import random
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

import aiohttp
import numpy as np
import websockets

sys.path[:0] = [str(Path(__file__).parent), str(Path(__file__).parent.parent / "pointe"), str(Path(__file__).parent.parent)]
import no_telemetry  # noqa: E402,F401  (before pipecat's Silero loads onnxruntime)
import stt_bench as sb  # noqa: E402
import turns  # noqa: E402
import turnsound  # noqa: E402
from pause_bench import SENTENCES as PAUSED  # noqa: E402
from pause_bench import clip_audio  # noqa: E402
from stt_extra import DAEMON_ENDPOINT, VAD_STOP_SECS  # noqa: E402

OUT = sb.OUT / "turn.jsonl"
VOICES = ["alice", "george"]
PAUSES = [0.5, 0.8, 1.2]
VAD_START_SECS = 0.2  # the daemon hears the user again this long after the voice returns
# (id, first part, second part): hesitations. The first ten trail off, the rest read whole.
HESITATIONS = [
    ("hz01", "Open the parser and then...", "run the tests."),
    ("hz02", "So basically,", "the retry loop never gives up."),
    ("hz03", "Um,", "check the nightly export."),
    ("hz04", "I think we should, um...", "revert the last commit."),
    ("hz05", "Send it to billing, or maybe", "to the notes session."),
    ("hz06", "It fails when", "the input is empty."),
    ("hz07", "Before lunch I want to look at", "why the export job is slow."),
    ("hz08", "Move the tests, which", "are flaky anyway, to a separate job."),
    ("hz09", "The thing I keep forgetting is the", "staging migration."),
    ("hz10", "Rather than", "rewriting it, add a test first."),
    ("hw01", "The dashboard is slow", "mostly on the first load."),
    ("hw02", "Deploy to staging", "not production."),
    ("hw03", "Run the tests", "and then open the failing one."),
    ("hw04", "Check the nightly export", "it took forty minutes yesterday."),
    ("hw05", "I want to ship this today", "so keep the change small."),
    ("hw06", "Start with the migration", "the schema part only."),
    ("hw07", "Rename the module to billing", "then update the imports."),
    ("hw08", "Ask the notes session about the launch date", "and whether marketing agreed."),
    ("hw09", "The cache is stale", "after every deploy on Mondays."),
    ("hw10", "Close the old pull request", "the one from last week."),
] + list(PAUSED)
# Whole turns: what a person says and then waits for an answer.
WHOLE = [
    ("wh01", "Run the tests in the billing package and tell me what fails."),
    ("wh02", "What's the difference between a mutex and a semaphore?"),
    ("wh03", "Open a pull request against dev when the tests pass."),
    ("wh04", "Summarize what changed in the admin dashboard since Monday."),
    ("wh05", "Rename the helper to parse invoice date everywhere."),
    ("wh06", "Is the nightly export finished?"),
    ("wh07", "Tell billing to revert the last commit."),
    ("wh08", "What time zone is Tel Aviv in?"),
    ("wh09", "Deploy the fix to staging."),
    ("wh10", "Find every place we call the payments API without a timeout."),
    ("wh11", "Ask the notes session what the launch date is."),
    ("wh12", "How does the retry loop decide when to give up?"),
    ("wh13", "Check why the weekly sales query is slow."),
    ("wh14", "Which session is still running?"),
    ("wh15", "Send the summary to the notes session."),
    ("wh16", "תריץ את הבדיקות של שירות התשלומים ותגיד לי מה נכשל."),
    ("wh17", "מה ההבדל בין תור עבודות לבין משימה מתוזמנת?"),
    ("wh18", "תסכם לי מה השתנה בלוח הבקרה מאז יום שני."),
    ("wh19", "תבדוק למה השאילתה של המכירות השבועיות איטית."),
    ("wh20", "תפתח pull request מול הענף dev."),
]
POLICIES = ("before", "after")
# `now`: today's rule for taking the turn, but Soniox is asked for the words it holds as soon as the voice detector
# says the voice stopped (0.2 s of silence, the least Soniox asks for), not 0.7 s after the sound.
ALL_POLICIES = POLICIES + ("now",)


def load() -> float:
    return float(subprocess.run(["uptime"], capture_output=True, text=True).stdout.split("load averages:")[-1].split()[0])


async def stream_once(audio: np.ndarray, policy: str) -> dict:
    """One clip through Soniox as the daemon holds it: Silero says when the voice stops, the sound is judged there,
    and held words are asked for after turns.finalize_after."""
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams, VADState

    vad = SileroVADAnalyzer(sample_rate=sb.RATE, params=VADParams(stop_secs=VAD_STOP_SECS))
    vad.set_sample_rate(sb.RATE)
    async with websockets.connect("wss://stt-rt.soniox.com/transcribe-websocket") as ws:
        await ws.send(json.dumps({
            "api_key": sb.keychain("soniox-api-key"), "model": "stt-rt-v6", "audio_format": "pcm_s16le",
            "sample_rate": sb.RATE, "num_channels": 1, "language_hints": ["en", "he"],
            "enable_endpoint_detection": True, **DAEMON_ENDPOINT}))
        final: list[str] = []
        segments: list = []  # [wall time, text, "end" or "fin"]
        stops: list = []  # [wall time of the voice detector's stop, the sound's score]
        st = {"open": False, "from": 0, "sent": 0, "stopped": None, "asked": None, "voice_from": 0, "error": None}
        sent = bytearray()

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                for tok in msg.get("tokens", []):
                    if tok["text"] in ("<end>", "<fin>"):
                        if st["open"]:
                            segments.append([time.time(), "".join(final[st["from"]:]).strip(), tok["text"].strip("<>")])
                            st["from"] = len(final)
                        st["open"] = False
                        continue
                    st["open"] = True
                    if tok.get("is_final"):
                        final.append(tok["text"])
                if msg.get("finished") or msg.get("error_code"):
                    st["error"] = msg.get("error_message")
                    return

        async def send(chunk: bytes):
            await ws.send(chunk)
            sent.extend(chunk)
            st["sent"] += len(chunk) // 2
            before, now = vad._vad_state, vad._run_analyzer(chunk)
            if now == VADState.SPEAKING and before != VADState.SPEAKING and st["stopped"] is None and not stops:
                st["voice_from"] = max(0, st["sent"] - int((VAD_START_SECS + turnsound.PRE_SPEECH_SECS) * sb.RATE))
            if now == VADState.QUIET and before != VADState.QUIET:
                score = await asyncio.to_thread(turnsound.score, bytes(sent[st["voice_from"] * 2:]))
                st["stopped"] = (st["sent"], score)
                stops.append([time.time(), score])
            elif now in (VADState.STARTING, VADState.SPEAKING):
                st["stopped"] = None
            if st["open"] and st["stopped"] is not None and st["asked"] != st["stopped"][0]:
                quiet = (st["sent"] - st["stopped"][0]) / sb.RATE + VAD_STOP_SECS
                sound = st["stopped"][1] if policy == "after" and turnsound.judged("".join(final)) else None
                due = turns.FINALIZE_MIN_SECS if policy == "now" else turns.finalize_after(
                    turns.CANDIDATE if policy == "after" else "normal", sound)
                if quiet >= due:
                    st["asked"] = st["stopped"][0]
                    stops[-1].append(time.time())  # when Soniox was asked for the words it held
                    await ws.send('{"type": "finalize"}')

        task = asyncio.create_task(reader())
        began = time.time()
        await sb.stream(send, audio)
        await ws.send("")
        await asyncio.wait_for(task, 15)
    return {"began": began, "segments": segments, "stops": stops, "error": st["error"]}


def judge(row: dict, policy: str, level: str = "normal") -> dict:
    """SonioxEars on the clip's segments: where the turn was taken, in seconds from the clip's start. `ends` are the
    moments a sound ended (the first part's, the clip's); `resume` is when the second part starts, None without one."""
    began, resume = row["began"], row.get("resume")
    back = began + resume + VAD_START_SECS if resume is not None else None  # the daemon knows the user talks again
    sound_ends = [began + e for e in row["sound_ends"]]
    held, taken_at, taken_text = "", None, ""
    for arrived, text, kind in row["segments"]:
        if not text:
            continue
        joined = f"{held} {text}".strip()
        quiet_from = max(e for e in sound_ends if e <= arrived + 0.05) if any(e <= arrived + 0.05 for e in sound_ends) else arrived
        if policy != "after":
            wait = turns.settle(joined, bool(held), level)
        else:
            stop = next((s for s in reversed(row["stops"]) if s[0] <= arrived), None)
            asked = stop is not None and len(stop) > 2 and stop[2] <= arrived
            sound = stop[1] if stop and turnsound.judged(joined) else None
            wait = turns.settle(joined, bool(held), turns.CANDIDATE, endpoint=kind == "end" and not asked, sound=sound)
        at = max(arrived, quiet_from + wait)
        if back is not None and arrived < back and at >= back:
            held = joined  # the voice came back while it settled: the next segment joins it
            continue
        taken_at, taken_text = at, joined
        break
    cut = back is not None and taken_at is not None and taken_at < back
    last_end = sound_ends[-1]
    heard = " ".join(text for _, text, _ in row["segments"] if text)
    finals = [arrived - last_end for arrived, text, _ in row["segments"] if text and arrived >= last_end]
    return {"cut": cut, "taken_text": taken_text, "heard": heard, "final_delay": round(finals[0], 3) if finals else None,
            "delay": None if taken_at is None or cut else round(taken_at - last_end, 3)}


async def clips(http) -> dict:
    out = {}
    for sid, one, two in HESITATIONS:
        for voice in VOICES:
            a, b = await sb.synth(http, one, voice), await sb.synth(http, two, voice)
            for pause in PAUSES:
                audio, first_end, resume = clip_audio(a, b, pause)
                out[f"{sid}.{voice}.{pause}"] = {"id": sid, "voice": voice, "pause": pause, "audio": audio, "resume": resume,
                                                 "sound_ends": [first_end, len(audio) / sb.RATE - sb.TAIL_SILENCE],
                                                 "first": one}
    for sid, text in WHOLE:
        for voice in VOICES:
            a = sb.trim_silence(await sb.synth(http, text, voice))
            audio = np.concatenate([np.zeros(int(sb.LEAD_SILENCE * sb.RATE), np.int16), a,
                                    np.zeros(int(sb.TAIL_SILENCE * sb.RATE), np.int16)])
            out[f"{sid}.{voice}"] = {"id": sid, "voice": voice, "pause": None, "audio": audio, "resume": None,
                                     "sound_ends": [len(audio) / sb.RATE - sb.TAIL_SILENCE], "first": text}
    return out


async def collect(concurrency: int, max_load: float, policies: tuple) -> None:
    done = set()
    if OUT.exists():
        done = {(r["policy"], r["clip"]) for r in map(json.loads, OUT.read_text().splitlines()) if not r.get("error")}
    async with aiohttp.ClientSession() as http:
        every = await clips(http)
    jobs = [(p, c) for c in every for p in policies if (p, c) not in done]
    random.Random(7).shuffle(jobs)
    print(f"{len(jobs)} runs to do ({len(done)} cached), load {load()}", flush=True)
    sem, lock = asyncio.Semaphore(concurrency), asyncio.Lock()

    async def one(policy, name):
        clip = every[name]
        async with sem:
            while load() > max_load:  # a busy machine sends the audio late: the times would be its own
                await asyncio.sleep(10)
            for _ in range(3):
                try:
                    r = await stream_once(clip["audio"], policy)
                    break
                except Exception as e:
                    r = {"error": f"{type(e).__name__}: {e}"[:200]}
                    await asyncio.sleep(2)
        row = {"policy": policy, "clip": name, "load": load(), **{k: v for k, v in clip.items() if k != "audio"}, **r}
        async with lock:
            with OUT.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    await asyncio.gather(*(one(p, c) for p, c in jobs))


def p90(values: list) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))]


def words(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.lower().replace("-", " "))


def word_errors(ref: list[str], hyp: list[str]) -> int:
    """Word edit distance."""
    row = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, row[0] = row[0], i
        for j, h in enumerate(hyp, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (r != h))
    return row[-1]


def finals_report(level: str) -> None:
    """Asking Soniox at once (`now`) against today (`before`): when the last words are final, the words, the cut-ins."""
    said = {sid: f"{a} {b}" for sid, a, b in HESITATIONS} | dict(WHOLE)
    rows = {}
    for r in map(json.loads, OUT.read_text().splitlines()):
        if not r.get("error") and r["policy"] in ("before", "now"):
            rows[(r["policy"], r["clip"])] = {**r, **judge(r, r["policy"], level)}
    both = sorted({c for _, c in rows if all((p, c) in rows for p in ("before", "now"))})
    if not both:
        return
    print(f"\nAsking Soniox for its words at the voice detector's stop (`now`) against 0.7 s after the sound (`before`), "
          f"{len(both)} clips, load median {statistics.median(rows[('now', c)]['load'] for c in both):.1f}:")
    print(f"{'clips':22s} {'n':>4s} {'rule':>7s} {'final after last sound: med':>28s} {'p90':>6s} {'word errors':>12s} "
          f"{'segments':>9s} {'cut-ins':>8s}")
    for name, pick in (("whole turns", lambda r: r["pause"] is None), ("hesitations", lambda r: r["pause"] is not None)):
        cs = [c for c in both if pick(rows[("before", c)])]
        for p in ("before", "now"):
            rs = [rows[(p, c)] for c in cs]
            delays = [r["final_delay"] for r in rs if r["final_delay"] is not None]
            errs = sum(word_errors(words(said[r["id"]]), words(r["heard"])) for r in rs)
            total = sum(len(words(said[r["id"]])) for r in rs)
            segs = statistics.mean(sum(1 for _, t, _ in r["segments"] if t) for r in rs)
            print(f"{name:22s} {len(cs):4d} {p:>7s} {statistics.median(delays):28.2f} {p90(delays):6.2f} "
                  f"{errs / total:12.1%} {segs:9.2f} {sum(r['cut'] for r in rs):8d}")
    for c in both:
        a, b = rows[("before", c)], rows[("now", c)]
        if words(a["heard"]) != words(b["heard"]):
            print(f"  {c:20s} before {a['heard']!r}\n  {'':20s} now    {b['heard']!r}")


def report(level: str) -> None:
    rows = {}
    for r in map(json.loads, OUT.read_text().splitlines()):
        if not r.get("error"):
            rows[(r["policy"], r["clip"])] = {**r, **judge(r, r["policy"], level)}
    both = sorted({c for _, c in rows if all((p, c) in rows for p in POLICIES)})
    loads = [r["load"] for r in rows.values()]
    print(f"{len(both)} clips heard under both rules, before: level {level}, after: the candidate, load median {statistics.median(loads):.1f} "
          f"max {max(loads):.1f}\n")

    def lang(c):
        return "he" if not turnsound.judged(rows[("before", c)]["first"]) else "en"

    def kind(c):
        r = rows[("before", c)]
        return "whole" if r["pause"] is None else "trails off" if turns.unfinished(r["first"]) else "reads whole"

    print("Cut-ins on a hesitation (the turn taken before the second part):")
    print(f"{'first part':12s} {'lang':4s} {'pause':>5s} {'clips':>5s} {'before':>12s} {'after':>12s}")
    total = {p: [0, 0] for p in POLICIES}
    for k in ("trails off", "reads whole"):
        for lg in ("en", "he"):
            for pause in PAUSES + [None]:
                cs = [c for c in both if kind(c) == k and lang(c) == lg and (pause is None or rows[("before", c)]["pause"] == pause)]
                if not cs:
                    continue
                cells = []
                for p in POLICIES:
                    cuts = sum(rows[(p, c)]["cut"] for c in cs)
                    cells.append(f"{cuts:3d} ({cuts / len(cs):4.0%})")
                    if pause is None:
                        total[p][0] += cuts
                        total[p][1] += len(cs)
                print(f"{k:12s} {lg:4s} {'all' if pause is None else pause:>5} {len(cs):5d} {cells[0]:>12s} {cells[1]:>12s}")
    print(f"{'all':12s} {'':4s} {'':>5s} {total['before'][1]:5d} "
          + " ".join(f"{total[p][0]:3d} ({total[p][0] / max(1, total[p][1]):4.0%})".rjust(12) for p in POLICIES))
    print("\nA whole turn: seconds from its last sound to the turn being taken:")
    print(f"{'lang':4s} {'clips':>5s} {'before med':>11s} {'p90':>6s} {'after med':>10s} {'p90':>6s}")
    for lg in ("en", "he", "all"):
        cs = [c for c in both if kind(c) == "whole" and (lg == "all" or lang(c) == lg)]
        d = {p: [rows[(p, c)]["delay"] for c in cs if rows[(p, c)]["delay"] is not None] for p in POLICIES}
        if all(d.values()):
            print(f"{lg:4s} {len(cs):5d} {statistics.median(d['before']):11.2f} {p90(d['before']):6.2f} "
                  f"{statistics.median(d['after']):10.2f} {p90(d['after']):6.2f}")
    scores = {"whole": [], "trails off": [], "reads whole": []}
    for c in both:
        r = rows[("after", c)]
        if lang(c) == "en" and r["stops"] and r["stops"][0][1] is not None:
            scores[kind(c)].append(r["stops"][0][1])
    print("\nThe sound's score at the first stop of the voice (English): share at or over "
          f"{turns.SOUNDS_FINISHED} / at or under {turns.SOUNDS_OPEN}:")
    for k, v in scores.items():
        if v:
            print(f"  {k:12s} n={len(v):3d} median {statistics.median(v):.2f}  finished {sum(x >= turns.SOUNDS_FINISHED for x in v) / len(v):4.0%}"
                  f"  open {sum(x <= turns.SOUNDS_OPEN for x in v) / len(v):4.0%}")
    print("\nCut-ins under the new rule:")
    for c in both:
        if rows[("after", c)]["cut"] and not rows[("before", c)]["cut"]:
            print(f"  new   {c:20s} {rows[('after', c)]['taken_text']!r}")
    for c in both:
        if rows[("before", c)]["cut"] and not rows[("after", c)]["cut"]:
            print(f"  gone  {c:20s} {rows[('before', c)]['taken_text']!r}")
    finals_report(level)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["run", "report"])
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--max-load", type=float, default=20.0, help="run: wait while the 1-minute load is over this")
    p.add_argument("--level", default="normal", choices=list(turns.LEVELS))
    p.add_argument("--policies", default=",".join(POLICIES), help=f"run: of {', '.join(ALL_POLICIES)}")
    a = p.parse_args()
    if a.cmd == "run":
        asyncio.run(collect(a.concurrency, a.max_load, tuple(a.policies.split(","))))
    else:
        report(a.level)


if __name__ == "__main__":
    main()
