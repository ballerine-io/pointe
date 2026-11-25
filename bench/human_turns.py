"""Recorded people, where the turn benchmark had synthetic voices: real mid-sentence pauses and real ends of turn.

A synthetic voice reads the first half of a sentence as if it were a whole one, so bench/turn_bench.py could rank two
rules for the end of a turn and not say how often either cuts in on a person. These clips are people talking in
meetings: the AMI Meeting Corpus (Carletta et al., 2005; https://groups.inf.ed.ac.uk/ami/corpus/), released with its
annotations under Creative Commons Attribution 4.0. Each speaker's own headset microphone, 16 kHz.

Two kinds of clip, in turn_bench's own shape, so its Soniox run and its judge are used unchanged:

  pause   a stretch of one person's speech with one silence of 0.5 to 2.0 s inside a sentence: the words before it and
          after it have no sentence end between them in the corpus's transcript, the silence is measured on the sound
          itself (the transcript's word times only say where to look), and nobody else's microphone has words in it.
          A turn taken inside that silence is a cut-in.
  backchannel  not for this benchmark: one "mm-hmm", "yeah" or "okay" a speaker, said while a colleague talked, for
          the dialogue suite's backchannel turns (bench/conversational/dialogues/dialogues/human.py).
  end     a whole utterance that ends a sentence, after which its speaker says nothing for at least 2 s, with no
          silence of 0.45 s or more inside it. What counts is how long after its last sound the turn is taken.

  uv run --no-project --with pyarrow --with numpy python -I bench/human_turns.py build   # writes the clips and the manifest
  .venv/bin/python -I bench/human_turns.py run [--concurrency 2]                          # Soniox, real time
  .venv/bin/python -I bench/human_turns.py prune                                          # drops rows taken over load 20; run again
  .venv/bin/python -I bench/human_turns.py report [--level normal]

`build` reads the corpus from bench/.human/ami/ (ignored by git; nothing of it is redistributed here): the manual
annotations (ami_public_manual_1.6.2.zip, unpacked to ann/) and the headset segments as Hugging Face publishes them
(edinburghcstr/ami, ihm, the test and validation splits, as parquet in pq/). SOURCES lists each file with its SHA-256
and `fetch` downloads them (3 GB). bench/human_turns.jsonl, which is committed, names every clip by meeting, speaker and
time, so the same set is cut again from the same corpus.

Limits, said plainly. These are people talking to each other in English, in a meeting, not to an assistant, and not
in Hebrew. A pause while a colleague waits is not a pause while a machine does; the words are about a remote control,
not about code. The headset is close to the mouth, with the room's other voices faint behind it. What the clips do
give is what no synthetic voice has: the sound of a person who has not finished.
"""

import argparse
import asyncio
import hashlib
import json
import sys
import urllib.request
import wave
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CORPUS = HERE / ".human" / "ami"
CLIPS = CORPUS / "clips"
MANIFEST = HERE / "human_turns.jsonl"
RATE = 16000
LEAD, TAIL = 0.3, 2.5  # turn_bench's clip shape (stt_bench.LEAD_SILENCE, TAIL_SILENCE)
PAUSE_MIN, PAUSE_MAX = 0.5, 2.0
BINS = (0.5, 0.8, 1.2)  # a pause is reported in the bin it reaches: 0.5 to 0.8, 0.8 to 1.2, 1.2 to 2.0
BEFORE_MAX, AFTER_MAX = 8.0, 6.0  # at most this much speech kept before and after the pause
END_QUIET = 2.0  # after an end of turn its speaker says nothing this long
INNER_QUIET = 0.45  # an end clip has no silence this long inside it
PER_SPEAKER = 8  # of each kind: no one voice is the benchmark
FRAME = 320  # 20 ms
HF = "https://huggingface.co/datasets/edinburghcstr/ami/resolve/0c2aaba73353af9145afbdea75badca51196ef12/ihm/"
SOURCES = {  # file under bench/.human/ami -> (url, SHA-256)
    "ami_public_manual_1.6.2.zip": ("https://groups.inf.ed.ac.uk/ami/AMICorpusAnnotations/ami_public_manual_1.6.2.zip",
                                    "b56e5babb2496b8795deeeda7e71178d7fbc9963f94276cf2a3f4b56ebbc9f9d"),
}
SHARDS = [f"test/{n:04d}" for n in range(4)] + [f"validation/{n:04d}" for n in range(5)]
TERMINAL = set(".?!")
BACKCHANNELS = {"MM-HMM", "UH-HUH", "MM", "MHM", "YEAH", "OKAY", "RIGHT"}  # a listener's sounds: one clip a speaker, for the dialogues


def fetch() -> None:
    """Downloads what `build` reads, checks each SHA-256 that is pinned, and unpacks the annotations."""
    (CORPUS / "pq").mkdir(parents=True, exist_ok=True)
    wanted = dict(SOURCES)
    for shard in SHARDS:
        wanted[f"pq/{shard.replace('/', '-')}.parquet"] = (HF + shard + ".parquet", SHARD_SHA256.get(shard))
    for name, (url, digest) in wanted.items():
        path = CORPUS / name
        if not path.exists():
            print(f"fetching {name}", flush=True)
            urllib.request.urlretrieve(url, path)
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest and got != digest:
            raise SystemExit(f"{name}: SHA-256 {got}, expected {digest}")
    if not (CORPUS / "ann" / "words").exists():
        with zipfile.ZipFile(CORPUS / "ami_public_manual_1.6.2.zip") as z:
            z.extractall(CORPUS / "ann")


SHARD_SHA256 = {  # as `build --pin` prints them
    "test/0000": "d95920dccc6924c15215239461bf5d1152fe07c9c61add073bd12da26dd602e0",
    "test/0001": "07a2b1c407cf36bc1e66c1362b0248ed32c897edc2a116549d1dc6b456dc2325",
    "test/0002": "83cde21e55fc884295585327b0ee334cba47ad53bdb787dd5f97437067aca5f8",
    "test/0003": "3312bb79400ddef62d5a0097e124dfabe86a693b4643e7fef7d72a62588280d7",
    "validation/0000": "30a90f2fc82658c2f749864236813d1ca106060fc3870676a7e9afb423d45f47",
    "validation/0001": "a9414394253a17fcdad4f03455b84c6b4b965a46df9f7c7f1d45ba22bedcaec1",
    "validation/0002": "95f38f49576d75388de4f57033852e64601ad3eefca4210406619edb93882821",
    "validation/0003": "3422d00c865db1233defe58658b29cd7eef5dd535fa5c4e2c74f1ff80046f989",
    "validation/0004": "299346934fce77a8c5da10f1727f8b0842dff33f13234fc23445d0c7cac97cfb",
}


def agents() -> dict:
    """(meeting, the speaker's corpus-wide name) -> the letter its word file is named by."""
    out = {}
    root = ET.parse(CORPUS / "ann" / "corpusResources" / "meetings.xml").getroot()
    for meeting in root.iter("meeting"):
        for sp in meeting.iter("speaker"):
            out[(meeting.get("observation"), sp.get("global_name"))] = sp.get("nxt_agent")
    return out


_WORDS: dict = {}


def words(meeting: str, agent: str) -> list:
    """(start, end, text, sentence end after it) of each word the speaker said, in order."""
    key = (meeting, agent)
    if key not in _WORDS:
        out = []
        path = CORPUS / "ann" / "words" / f"{meeting}.{agent}.words.xml"
        if path.exists():
            for w in ET.parse(path).getroot():
                if not w.tag.endswith("w") or w.get("starttime") is None or w.get("endtime") is None:
                    continue
                text = (w.text or "").strip()
                if w.get("punc") == "true":
                    if out and text in TERMINAL:
                        out[-1][3] = True
                    continue
                if text:
                    out.append([float(w.get("starttime")), float(w.get("endtime")), text, False])
        _WORDS[key] = out
    return _WORDS[key]


def others_talk(meeting: str, agent: str, a: float, b: float) -> bool:
    for other in "ABCDE":
        if other != agent and any(s < b and e > a for s, e, _, _ in words(meeting, other)):
            return True
    return False


def pcm_of(blob: bytes) -> np.ndarray | None:
    """A segment's sound as 16-bit samples. The published segments are 16 kHz mono WAV, 32-bit float or 16-bit."""
    if blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        return None
    at, fmt, data = 12, None, None
    while at + 8 <= len(blob):
        name, size = blob[at:at + 4], int.from_bytes(blob[at + 4:at + 8], "little")
        body = blob[at + 8:at + 8 + size]
        if name == b"fmt ":
            fmt = (int.from_bytes(body[0:2], "little"), int.from_bytes(body[2:4], "little"),
                   int.from_bytes(body[4:8], "little"), int.from_bytes(body[14:16], "little"))
        elif name == b"data":
            data = body
        at += 8 + size + (size & 1)
    if fmt is None or data is None or fmt[1] != 1 or fmt[2] != RATE:
        return None
    if fmt[0] == 3 and fmt[3] == 32:
        return (np.clip(np.frombuffer(data[:len(data) // 4 * 4], dtype="<f4"), -1, 1) * 32767).astype(np.int16)
    if fmt[0] == 1 and fmt[3] == 16:
        return np.frombuffer(data[:len(data) // 2 * 2], dtype="<i2").copy()
    return None


def quiet_runs(pcm: np.ndarray) -> list:
    """(start, end) in seconds of each stretch quieter than the speech around it: frames under a tenth of the clip's
    loud level (its 90th percentile), and never over an absolute floor a headset's room tone stays under."""
    n = len(pcm) // FRAME
    if n < 5:
        return []
    rms = np.sqrt((pcm[:n * FRAME].astype(np.float32).reshape(n, FRAME) ** 2).mean(axis=1))
    loud = float(np.percentile(rms, 90))
    quiet = rms < max(60.0, min(loud * 0.1, 400.0))
    runs, start = [], None
    for i, q in enumerate(list(quiet) + [False]):
        if q and start is None:
            start = i
        elif not q and start is not None:
            runs.append((start * FRAME / RATE, i * FRAME / RATE))
            start = None
    return runs


def candidates(row: dict, agent: str) -> list:
    """The pause and end clips one headset segment holds, each as a manifest row with its sound."""
    meeting, begin, end = row["meeting_id"], row["begin_time"], row["end_time"]
    pcm = pcm_of(row["audio"]["bytes"])
    if pcm is None or len(pcm) < RATE:
        return []
    mine = words(meeting, agent)
    said = [w for w in mine if w[0] >= begin - 0.05 and w[1] <= end + 0.05]
    if len(said) < 4:
        return []
    runs = quiet_runs(pcm)
    out = []
    base = {"meeting": meeting, "speaker": row["speaker_id"], "agent": agent, "segment": [round(begin, 2), round(end, 2)]}
    # A pause: the sound itself is quiet for 0.5 to 2.0 s, and the transcript has no sentence end between the word
    # before it and the word after it. The corpus's word times often run through a silence, so they only say which
    # words sit on each side: a word belongs to the side its middle falls on.
    total = len(pcm) / RATE
    for a, b in runs:
        if not (PAUSE_MIN <= b - a <= PAUSE_MAX) or a < 1.0 or total - b < 0.6:
            continue
        mid = begin + (a + b) / 2
        before = [w for w in said if (w[0] + w[1]) / 2 < mid]
        after = [w for w in said if (w[0] + w[1]) / 2 >= mid]
        if len(before) < 3 or not after or before[-1][3]:
            continue
        if before[-1][1] > begin + b - 0.1 and after[0][0] < begin + a + 0.1:
            continue  # the words say nobody paused here: the quiet is a soft consonant or a breath, not a silence
        if others_talk(meeting, agent, begin + a - 0.2, begin + b + 0.2):
            continue
        start = max(0.0, a - BEFORE_MAX)
        if any(x >= start and y < a - 0.05 and y - x >= INNER_QUIET for x, y in runs):
            start = max(y for x, y in runs if x >= start and y < a - 0.05 and y - x >= INNER_QUIET) - 0.1  # one pause to a clip
        later_quiet = [x for x, y in runs if x > b + 0.05 and y - x >= INNER_QUIET]
        stop = min(total, b + AFTER_MAX, later_quiet[0] + 0.1 if later_quiet else total)
        if a - start < 1.0 or stop - b < 0.6:
            continue
        first = " ".join(w[2] for w in before if w[1] - begin > start)
        rest = " ".join(w[2] for w in after if w[0] - begin < stop)
        if len(first.split()) < 3 or not rest:
            continue
        out.append(({**base, "kind": "pause", "pause_secs": round(b - a, 2), "cut": [round(start, 2), round(stop, 2)],
                     "first_end": round(LEAD + a - start, 3), "resume": round(LEAD + b - start, 3),
                     "first": first, "rest": rest}, pcm[int(start * RATE):int(stop * RATE)]))
        break  # one clip from a segment
    # An end of turn: the segment ends a sentence, its speaker then says nothing for END_QUIET, and nothing inside it is a pause.
    last = said[-1]
    later = [w for w in mine if w[0] > last[1] + 0.01]
    lead_quiet = runs[0][1] if runs and runs[0][0] == 0.0 else 0.0
    tail_from = runs[-1][0] if runs and abs(runs[-1][1] - len(pcm) // FRAME * FRAME / RATE) < 0.03 else len(pcm) / RATE
    inner = [(x, y) for x, y in runs if x > lead_quiet and y < tail_from and y - x >= INNER_QUIET]
    if (not out and last[3] and 4 <= len(said) <= 30 and 1.2 <= tail_from - lead_quiet <= 12.0 and not inner
            and (not later or later[0][0] - last[1] >= END_QUIET)
            and not others_talk(meeting, agent, begin + max(lead_quiet, tail_from - 1.0), begin + tail_from + 0.3)):
        start, stop = max(0.0, lead_quiet - 0.1), min(len(pcm) / RATE, tail_from + 0.1)
        out.append(({**base, "kind": "end", "pause_secs": None, "cut": [round(start, 2), round(stop, 2)],
                     "first_end": None, "resume": None, "first": " ".join(w[2] for w in said), "rest": ""},
                    pcm[int(start * RATE):int(stop * RATE)]))
    return out


def build(pin: bool) -> None:
    import pyarrow.parquet as pq
    CLIPS.mkdir(parents=True, exist_ok=True)
    letter = agents()
    found = defaultdict(list)  # (kind, speaker) -> [(row, pcm)]
    for shard in SHARDS:
        path = CORPUS / "pq" / f"{shard.replace('/', '-')}.parquet"
        if not path.exists():
            print(f"missing {path.name}: run `fetch`", flush=True)
            continue
        if pin:
            print(f'    "{shard}": "{hashlib.sha256(path.read_bytes()).hexdigest()}",')
        f = pq.ParquetFile(path)
        for g in range(f.num_row_groups):
            for row in f.read_row_group(g).to_pylist():
                agent = letter.get((row["meeting_id"], row["speaker_id"]))
                if agent is None:
                    continue
                if row["text"].strip().upper() in BACKCHANNELS and 0.3 <= row["end_time"] - row["begin_time"] <= 1.3:
                    pcm = pcm_of(row["audio"]["bytes"])
                    if pcm is not None and float(np.abs(pcm.astype(np.int32)).max()) >= 2000:  # said into the headset, not a murmur
                        found[("backchannel", row["speaker_id"])].append((
                            {"meeting": row["meeting_id"], "speaker": row["speaker_id"], "agent": agent, "kind": "backchannel",
                             "segment": [round(row["begin_time"], 2), round(row["end_time"], 2)], "pause_secs": None,
                             "cut": None, "first_end": None, "resume": None, "first": row["text"].strip().lower(), "rest": ""}, pcm))
                    continue
                for item, pcm in candidates(row, agent):
                    found[(item["kind"], item["speaker"])].append((item, pcm))
    rows = []
    for (kind, speaker), items in sorted(found.items()):
        # The same clips on every machine: by meeting and time; a speaker's pauses spread over the three bins first.
        items.sort(key=lambda x: (x[0]["meeting"], x[0]["segment"][0]))
        if kind == "pause":
            by_bin = defaultdict(list)
            for it in items:
                by_bin[max(b for b in BINS if it[0]["pause_secs"] >= b)].append(it)
            picked = []
            while len(picked) < PER_SPEAKER and any(by_bin.values()):
                for b in BINS:
                    if by_bin[b] and len(picked) < PER_SPEAKER:
                        picked.append(by_bin[b].pop(0))
            items = picked
        for n, (item, pcm) in enumerate(items[:1 if kind == "backchannel" else PER_SPEAKER]):
            item["clip"] = f"{kind}.{speaker}.{n:02d}"
            audio = pcm if kind == "backchannel" else np.concatenate(
                [np.zeros(int(LEAD * RATE), np.int16), pcm, np.zeros(int(TAIL * RATE), np.int16)])
            item["secs"] = round(len(audio) / RATE, 2)
            with wave.open(str(CLIPS / f"{item['clip']}.wav"), "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
                w.writeframes(audio.tobytes())
            rows.append(item)
    MANIFEST.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows))
    kinds = defaultdict(int)
    for r in rows:
        kinds[r["kind"]] += 1
    print(f"{len(rows)} clips: {dict(kinds)}, {len({r['speaker'] for r in rows})} speakers, "
          f"{sum(r['secs'] for r in rows) / 60:.0f} minutes; {MANIFEST.name} written")


def manifest() -> list:
    return [json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()]


def load_clips() -> dict:
    """The clips as turn_bench.clips() gives its own."""
    out = {}
    for r in manifest():
        if r["kind"] == "backchannel":
            continue  # for the dialogue suite (dialogues/human.py), not for the end of a turn
        with wave.open(str(CLIPS / f"{r['clip']}.wav"), "rb") as w:
            audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        last_end = len(audio) / RATE - TAIL
        if r["kind"] == "pause":
            out[r["clip"]] = {"id": r["clip"], "voice": r["speaker"], "pause": max(b for b in BINS if r["pause_secs"] >= b),
                              "pause_secs": r["pause_secs"], "audio": audio, "resume": r["resume"],
                              "sound_ends": [r["first_end"], last_end], "first": r["first"]}
        else:
            out[r["clip"]] = {"id": r["clip"], "voice": r["speaker"], "pause": None, "audio": audio, "resume": None,
                              "sound_ends": [last_end], "first": r["first"]}
    return out


def bench():
    """turn_bench, pointed at these clips and at its own results file for them."""
    sys.path[:0] = [str(HERE), str(HERE.parent / "pointe"), str(HERE.parent)]
    import turn_bench as tb

    async def clips(_http) -> dict:
        return load_clips()

    tb.clips, tb.OUT, tb.PAUSES = clips, tb.sb.OUT / "turn-human.jsonl", list(BINS)
    return tb


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["fetch", "build", "run", "prune", "report"])
    p.add_argument("--pin", action="store_true", help="build: print the SHA-256 of each shard read")
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--max-load", type=float, default=20.0)
    p.add_argument("--level", default="normal")
    p.add_argument("--policies", default="before,after", help="run: the report needs both")
    a = p.parse_args()
    if a.cmd == "fetch":
        fetch()
    elif a.cmd == "build":
        build(a.pin)
    elif a.cmd == "run":
        tb = bench()
        asyncio.run(tb.collect(a.concurrency, a.max_load, tuple(a.policies.split(","))))
    elif a.cmd == "prune":
        # A row taken on a busy machine holds that machine's lateness, not the rule's: dropped, and `run` hears it again.
        out = bench().OUT
        rows = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
        kept = [r for r in rows if r.get("load", 0) <= a.max_load]
        out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept))
        print(f"{len(rows) - len(kept)} rows over load {a.max_load} dropped, {len(kept)} kept")
    else:
        bench().report(a.level)


if __name__ == "__main__":
    main()
