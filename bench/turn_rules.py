"""Rules for the end of a turn, replayed on what Soniox heard: no new audio, no spend.

  .venv/bin/python -I bench/turn_rules.py [--rows bench/results/turn-human.jsonl] [--split test|train|all]

Reads the `before` rows of bench/human_turns.py (recorded people) or bench/turn_bench.py (synthetic voices): every
segment Soniox closed with its time, and the sound's score at every stop of the voice. Replays SonioxEars on them
under each rule below and prints, per rule, the cut-ins on mid-sentence pauses and how long after its last sound a
whole turn is taken. Speakers are split in two by a hash of their name: rules are chosen on `train` and reported on
`test`, which was not looked at while choosing.

A rule is (reads_unfinished, wait): the words that make a final read unfinished, and the seconds a final that reads
whole waits, given how the voice sounded, whether Soniox ended it itself, and whether this speaker has already
paused inside a sentence in an earlier clip of the same recording (their clips are replayed in the order recorded)."""

import argparse
import hashlib
import json
import re
import statistics
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).parent), str(Path(__file__).parent.parent / "pointe"), str(Path(__file__).parent.parent)]
import turns  # noqa: E402
from guards import unfinished  # noqa: E402

VAD_START_SECS = 0.2
PAUSED_SECS = 120.0  # a pause inside a sentence makes its speaker "one who pauses" for this long of the recording
BEFORE = turns.Patience(complete=1.0, unfinished=3.0, maximum=10.0)  # Normal as it was when the rows were heard
# Words a spoken sentence seldom ends on, beyond guards.unfinished: possessives and determiners, subject pronouns
# with a verb to come, auxiliaries, and fillers.
MORE_DANGLING = {"its", "her", "this", "these", "those", "some", "any", "every", "each", "no", "i", "we", "they", "he", "she",
                 "it's", "i'm", "we're", "they're", "you're", "he's", "she's", "that's", "there's", "i've", "we've", "i'll", "we'll",
                 "i'd", "we'd", "be", "been", "being", "have", "has", "had", "will", "would", "should", "could", "can", "may",
                 "might", "must", "just", "really", "more", "in", "on", "by", "as", "not", "says", "well", "going", "gonna",
                 "wanna", "that", "think", "guess", "mean", "something"}
MORE_OUTSIDE_QUESTIONS = {"do", "does", "did", "it", "them", "here", "there"}
# The ones a sentence never ends on, whatever it is about: a contraction with its verb to come, "its", "every". These
# are in guards.unfinished since this bench chose them; `today` below is the list from before.
NARROW = {"its", "every", "it's", "i'm", "we're", "they're", "you're", "he's", "she's", "there's", "that's", "i've", "we've",
          "you've", "they've", "i'll", "we'll", "you'll", "they'll", "i'd", "we'd", "gonna", "wanna", "just", "says"}
_QUESTION = re.compile(r"\b(what|where|who|whom|which|when|why|how|whose)\b|\?")


def before(text: str) -> bool:
    """guards.unfinished as it was before NARROW joined it."""
    return unfinished(text) and (last_word(text)[0] not in NARROW or bool(re.search(r"(—|–|-|…|\.\.\.|,)$", text.strip())))


def last_word(text: str) -> tuple[str, str]:
    words = re.findall(r"[\w']+", re.sub(r"[.!?…]+$", "", text.strip().lower()))
    return (words[-1], " ".join(words[:-1])) if words else ("", "")


def wider(text: str) -> bool:
    word, rest = last_word(text)
    return unfinished(text) or word in MORE_DANGLING or word in MORE_OUTSIDE_QUESTIONS and not _QUESTION.search(rest)


def narrow(text: str) -> bool:
    return unfinished(text)


def rule(reads_unfinished=before, low=None, low_wait=1.0, mid=None, mid_wait=1.0, sure=None, sure_wait=1.0,
         paused_wait=None, likely_unfinished=None, likely_wait=1.6):
    """A final that reads whole waits 1.0 s; `low_wait` when the sound's score is under `low`, `mid_wait` when under
    `mid`, `sure_wait` when at or over `sure`; `paused_wait` at least, once the speaker has paused inside a sentence.
    `likely_unfinished`: words that wait `likely_wait` and not the whole 3.0 s."""
    def wait(text: str, held: bool, sound, endpoint: bool, paused: bool) -> float:
        if turns.settle(text, held, BEFORE) == 0.0:
            return 0.0
        if reads_unfinished(text):
            return BEFORE.unfinished
        w = BEFORE.complete
        if likely_unfinished is not None and likely_unfinished(text):
            w = max(w, likely_wait)
        if sound is None and low is not None and low > 1:
            w = max(w, low_wait)  # a rule for every sentence, judged or not
        if sound is not None:
            if low is not None and sound < low:
                w = max(w, low_wait)
            elif mid is not None and sound < mid:
                w = max(w, mid_wait)
            elif sure is not None and sound >= sure and not held:
                w = min(w, sure_wait)
        if paused and paused_wait is not None:
            w = max(w, paused_wait)
        return w
    return wait


RULES = {
    "Normal before (1.0 s)": rule(),
    "Patient (1.8 s)": lambda text, held, sound, endpoint, paused: turns.settle(text, held, "patient"),
    "Normal now (1.3 s, the narrow list)": lambda text, held, sound, endpoint, paused: turns.settle(text, held, "normal"),
    **{f"every whole sentence {w} s": rule(low=2.0, low_wait=w, paused_wait=w) for w in (1.1, 1.2, 1.3, 1.4, 1.6)},
    "1 words: wider list (3.0 s)": rule(wider),
    "1 words: narrow list (3.0 s)": rule(narrow),
    "1 words: wider list waits 1.6 s": rule(likely_unfinished=wider, likely_wait=1.6),
    "2 sound under 0.2 waits 1.6 s": rule(low=0.2, low_wait=1.6),
    "2 sound under 0.5 waits 1.6 s": rule(low=0.5, low_wait=1.6),
    "2 sound under 0.5 waits 1.4 s": rule(low=0.5, low_wait=1.4),
    "2 sound under 0.8 waits 1.4 s": rule(low=0.8, low_wait=1.4),
    "2 under 0.2: 2.0 s, under 0.8: 1.4 s": rule(low=0.2, low_wait=2.0, mid=0.8, mid_wait=1.4),
    "3 a speaker who paused waits 1.4 s": rule(paused_wait=1.4),
    "3 a speaker who paused waits 1.8 s": rule(paused_wait=1.8),
    "1+3 narrow list, paused 1.4 s": rule(narrow, paused_wait=1.4),
    "1 narrow list, every whole sentence 1.3 s": rule(narrow, low=2.0, low_wait=1.3, paused_wait=1.3),
    "1+2 narrow, 1.3 s unless the sound is 0.9 or over": rule(narrow, low=0.9, low_wait=1.3),
    "1+2 narrow, 1.4 s unless the sound is 0.9 or over": rule(narrow, low=0.9, low_wait=1.4),
    "1+2 narrow, wider 1.4 s, 1.4 s unless sound 0.9+": rule(narrow, low=0.9, low_wait=1.4, likely_unfinished=wider, likely_wait=1.4),
    "1+2 narrow, under 0.2: 1.8 s, under 0.9: 1.4 s": rule(narrow, low=0.2, low_wait=1.8, mid=0.9, mid_wait=1.4),
    "1+2 narrow list, under 0.5: 1.6 s": rule(narrow, low=0.5, low_wait=1.6),
    "1+2 narrow, wider 1.6 s, under 0.5: 1.6 s": rule(narrow, low=0.5, low_wait=1.6, likely_unfinished=wider, likely_wait=1.6),
    "1+2 narrow, wider 1.4 s, under 0.5: 1.4 s": rule(narrow, low=0.5, low_wait=1.4, likely_unfinished=wider, likely_wait=1.4),
    "1+2+3 narrow, wider/under 0.5: 1.6 s, paused 1.4 s": rule(narrow, low=0.5, low_wait=1.6, likely_unfinished=wider,
                                                             likely_wait=1.6, paused_wait=1.4),
    "1+2 narrow, wider/under 0.5: 1.6 s, sure 0.95: 0.8 s": rule(narrow, low=0.5, low_wait=1.6, likely_unfinished=wider,
                                                               likely_wait=1.6, sure=0.95, sure_wait=0.8),
}


def replay(row: dict, wait, paused: bool) -> dict:
    """SonioxEars on one clip. `joined`: the daemon saw this speaker go on after a final it was holding."""
    began, resume = row["began"], row.get("resume")
    back = began + resume + VAD_START_SECS if resume is not None else None
    ends = [began + e for e in row["sound_ends"]]
    held, joined = "", False
    for arrived, text, kind in row["segments"]:
        if not text:
            continue
        said = f"{held} {text}".strip()
        before = [e for e in ends if e <= arrived + 0.05]
        quiet_from = max(before) if before else arrived
        stop = next((s for s in reversed(row["stops"]) if s[0] <= arrived), None)
        asked = stop is not None and len(stop) > 2 and stop[2] <= arrived
        at = max(arrived, quiet_from + wait(said, bool(held), stop[1] if stop else None, kind == "end" and not asked, paused))
        if back is not None and arrived < back and at >= back:
            held, joined = said, True
            continue
        cut = back is not None and at < back
        return {"cut": cut, "delay": None if cut else at - ends[-1], "joined": joined, "text": said}
    return {"cut": False, "delay": None, "joined": joined, "text": ""}


def p90(values: list) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rows", default=str(Path(__file__).parent / "results" / "turn-human.jsonl"))
    p.add_argument("--split", default="test", choices=["train", "test", "all"])
    p.add_argument("--max-load", type=float, default=21.0)
    p.add_argument("--cuts", default="", help="list the cut-ins of this rule")
    a = p.parse_args()
    rows = [r for r in map(json.loads, Path(a.rows).read_text().splitlines())
            if r["policy"] == "before" and not r.get("error") and r.get("load", 0) <= a.max_load]
    half = lambda r: "train" if int(hashlib.sha256(r["voice"].encode()).hexdigest(), 16) % 2 == 0 else "test"  # noqa: E731
    when = {}
    manifest = Path(__file__).parent / "human_turns.jsonl"
    if manifest.exists():  # where in its recording each clip is: a speaker's clips are replayed in that order
        when = {m["clip"]: (m["meeting"], m["segment"][0]) for m in map(json.loads, manifest.read_text().splitlines())}
    rows = [r for r in rows if a.split == "all" or half(r) == a.split]
    pauses, ends = [r for r in rows if r["pause"] is not None], [r for r in rows if r["pause"] is None]
    print(f"{a.split}: {len({r['voice'] for r in rows})} speakers, {len(pauses)} pauses, {len(ends)} ends of turn\n")
    print(f"{'rule':52s} {'cut-ins on pauses':>18s} {'under 0.8 s':>12s} {'0.8 s and over':>15s}  "
          f"{'ends: median':>12s} {'mean':>5s} {'p90':>5s} {'over 1.05 s':>11s}")
    for name, wait in RULES.items():
        paused: dict[tuple, float] = {}  # (speaker, recording) -> when they last went on after a final being held
        got = {}
        for r in sorted(rows, key=lambda r: (r["voice"], when.get(r["clip"], ("", 0.0)))):
            meeting, at = when.get(r["clip"], ("", 0.0))
            last = paused.get((r["voice"], meeting))
            got[r["clip"]] = out = replay(r, wait, last is not None and at - last <= PAUSED_SECS)
            if out["joined"]:
                paused[(r["voice"], meeting)] = at
        cuts = [r for r in pauses if got[r["clip"]]["cut"]]
        short = [r for r in pauses if r.get("pause_secs", r["pause"]) < 0.8]
        long = [r for r in pauses if r.get("pause_secs", r["pause"]) >= 0.8]
        delays = [got[r["clip"]]["delay"] for r in ends if got[r["clip"]]["delay"] is not None]
        print(f"{name:52s} {len(cuts):4d} ({len(cuts) / max(1, len(pauses)):5.1%})      "
              f"{sum(got[r['clip']]['cut'] for r in short):3d}/{len(short):<4d}    {sum(got[r['clip']]['cut'] for r in long):3d}/{len(long):<4d}  "
              f"{statistics.median(delays):12.2f} {statistics.mean(delays):5.2f} {p90(delays):5.2f} "
              f"{sum(d > 1.05 for d in delays) / len(delays):11.0%}")
        if name == a.cuts:
            for r in cuts:
                print(f"      {r.get('pause_secs', r['pause']):.2f} s  …{' '.join(got[r['clip']]['text'].split()[-6:])}")


if __name__ == "__main__":
    main()
