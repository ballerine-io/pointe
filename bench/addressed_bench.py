"""Addressed speech, measured on sound: is side talk acted on, and are words said to Pointe taken?

"Only when I say Pointe" (pointe/addressed.py) reads the recognizer's text. This benchmark gives a recognizer Pointe
ships 100 clips and judges each transcript with the same function the daemon calls:

  side       50 whole utterances of people talking to each other in a meeting: the "end" clips of the recorded-human
             set (bench/human_turns.jsonl), the AMI Meeting Corpus (Carletta et al., 2005;
             https://groups.inf.ed.ac.uk/ami/corpus/), Creative Commons Attribution 4.0. Each speaker's own headset
             microphone. Two a speaker at most, in the manifest's order. Acted on: must be 0 of 50.
  addressed  50 lines said to Pointe or to a session by name, in the eight Kokoro voices of the dialogue suite
             (bench/conversational/dialogues/voices.toml, Apache-2.0, synthetic). Taken: must be 50 of 50.

  uv run --locked --extra local python -I bench/addressed_bench.py run [--ears whisper|soniox] [--clips DIR]
  uv run --locked python -I bench/addressed_bench.py report

`run` reads the AMI clips from bench/.human/ami/clips (cut there by `bench/human_turns.py build`; ignored by git, and
nothing of the corpus is redistributed here: only the recognizer's text of each clip, with this attribution). It
writes bench/addressed_heard.<ears>.jsonl, which is committed (beside human_turns.jsonl, which names the clips), and
tests/test_addressed.py judges that text again on every run of the suite.

The ears: `whisper` is Whisper large-v3-turbo on this Mac at the commit pinned in pointe/assets.py, the ears of the
local setup: no key, no network, nothing leaves. `soniox` is the default setup's ears and needs its key; it is given
the name "Pointe" and the session names as context terms, as the daemon gives them in this mode.

Limits, said plainly. The side talk is real people, but in a meeting about a remote control, in English, on a headset:
not a phone call at a developer's desk, not Hebrew, not a far voice through a laptop microphone. The addressed lines
are synthetic voices reading clean sentences: no recorded person said "Pointe" for this. What the numbers do show is
that the rule does not fire on fifty real stretches of other people's talk, and does fire on the name as a recognizer
writes it.
"""

import argparse
import asyncio
import json
import sys
import wave
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[0:0] = [str(HERE / "conversational" / "dialogues"), str(ROOT / "pointe"), str(ROOT)]
import addressed  # noqa: E402

MANIFEST = HERE / "human_turns.jsonl"
CLIPS = HERE / ".human" / "ami" / "clips"
SESSIONS = ["billing/main", "docs", "river-lantern", "harbor"]  # invented, as in every test
PER_SPEAKER, WANT = 2, 50
VOICES = ["af_heart", "am_michael", "bf_emma", "bm_george", "hm_omega", "ef_dora", "ff_siwis", "im_nicola"]

LINES = [  # 50: the name first, the name last, a session by name
    "Pointe, what's billing doing?", "Pointe, give me the status.", "Hey Pointe, is the build green?",
    "Pointe, tell docs to update the changelog.", "Okay Pointe, what did harbor say?", "Pointe, yes.",
    "Pointe, no.", "Pointe, approve it.", "Pointe, read it again.", "Hey Pointe, which sessions need me?",
    "Pointe, ask billing to run the tests again.", "Pointe, how long has river lantern been working?",
    "Pointe, switch to docs.", "Pointe, stop.", "So, Pointe, what changed since this morning?",
    "Pointe, start a new session in the billing folder.", "Hey Pointe, what was the last thing docs finished?",
    "Pointe, deny that one.", "Pointe, tell harbor to open a pull request.", "Okay, Pointe, brief me on the night.",
    "Pointe, did the migration finish?", "Pointe, keep me posted.", "Hey Pointe, mute yourself.",
    "Pointe, what is river lantern waiting for?", "Pointe, send that to billing.",
    "What's billing doing, Pointe?", "Approve it, Pointe.", "Is the build green, Pointe?", "Give me the status, Pointe.",
    "Yes, Pointe.", "No, Pointe.", "Read it again, Pointe.", "Which sessions need me, Pointe?",
    "Tell docs to update the changelog, Pointe.", "That's enough, Pointe.",
    "Billing, run the tests again.", "Docs, update the changelog for the release.", "Harbor, open a pull request.",
    "Billing, are you done with the retry fix?", "Docs, what did you change?",
    "Tell docs to update the changelog.", "Ask billing whether the retry budget is five.",
    "Tell harbor to rebase on main.", "Ask river lantern what it is waiting for.", "Switch to harbor.",
    "Tell billing to open the pull request.", "Ask docs to fix the broken link.", "Switch to billing.",
    "Okay, tell harbor to run the linter.", "Hey Pointe, thanks, that's all.",
]
assert len(LINES) == WANT


def side_clips() -> list[dict]:
    """The first two "end" clips of each speaker, in the manifest's order, until there are fifty."""
    rows = [json.loads(line) for line in MANIFEST.read_text().splitlines()]
    taken: dict[str, int] = defaultdict(int)
    out = []
    for r in sorted((r for r in rows if r["kind"] == "end"), key=lambda r: r["clip"]):
        if taken[r["speaker"]] < PER_SPEAKER and len(out) < WANT:
            taken[r["speaker"]] += 1
            out.append(r)
    assert len(out) == WANT, f"{len(out)} side-talk clips"
    return out


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2, path
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).copy(), w.getframerate()


def ears_terms() -> list[str]:
    """What the daemon gives the ears in this mode: the name, then the session names' words (daemon._recognition_terms)."""
    return ["Pointe"] + [part for name in SESSIONS for part in name.replace("/", " ").replace("-", " ").split()]


async def hear(pcm: np.ndarray, rate: int, ears: str) -> str:
    from core import asr

    if ears == "whisper":
        return await asr.Whisper.atranscribe(pcm, rate)
    import vendors
    from core.corpus import _key

    return await soniox(asr.resample(pcm.astype(np.float32), rate, 16000).clip(-32768, 32767).astype(np.int16),
                        _key("SONIOX_API_KEY", "soniox-api-key"), vendors.SONIOX_RT_MODEL)


async def soniox(pcm16: np.ndarray, key: str, model: str) -> str:
    """One clip through Soniox real-time at real-time pace, with the context terms the daemon gives it in this mode."""
    import websockets

    audio = np.concatenate([pcm16, np.zeros(16000, dtype=np.int16)])  # a second of silence so the endpoint is found
    final: list[str] = []
    async with websockets.connect("wss://stt-rt.soniox.com/transcribe-websocket", open_timeout=15) as ws:
        await ws.send(json.dumps({"api_key": key, "model": model, "audio_format": "pcm_s16le", "sample_rate": 16000, "num_channels": 1,
                                  "language_hints": ["en", "he"], "enable_endpoint_detection": True, "context": {"terms": ears_terms()}}))

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                final.extend(t["text"] for t in msg.get("tokens", []) if t.get("is_final") and t["text"] not in ("<end>", "<fin>"))
                if msg.get("finished") or msg.get("error_code"):
                    return

        task = asyncio.create_task(reader())
        for i in range(0, len(audio), 1600):  # 100 ms at a time
            await ws.send(audio[i:i + 1600].tobytes())
            await asyncio.sleep(0.1)
        await ws.send("")
        await asyncio.wait_for(task, 20)
    return "".join(final).strip()


def row(clip: str, kind: str, said: str, heard: str, ears: str, **more) -> dict:
    to = addressed.address(heard, SESSIONS)
    return {"clip": clip, "kind": kind, "said": said, "heard": heard, "ears": ears, "sessions": SESSIONS,
            "acted": to is not None, "who": to.who if to else None, **more}


async def run(ears: str, clips: Path) -> None:
    from core import corpus

    out = HERE / f"addressed_heard.{ears}.jsonl"
    rows = []
    for r in side_clips():
        pcm, rate = read_wav(clips / f"{r['clip']}.wav")
        heard = await hear(pcm, rate, ears)
        rows.append(row(r["clip"], "side", " ".join(x for x in (r["first"], r["rest"]) if x), heard, ears,
                        source="AMI Meeting Corpus, CC BY 4.0", meeting=r["meeting"], speaker=r["speaker"]))
        print(f"side       {'ACTED ON' if rows[-1]['acted'] else 'dropped '}  {heard[:90]}", flush=True)
    for i, line in enumerate(LINES):
        voice = VOICES[i % len(VOICES)]
        pcm = corpus.Kokoro.say(line, voice, corpus.voices()[voice]["lang"])
        heard = await hear(pcm, corpus.RATE, ears)
        rows.append(row(f"addressed.{i:02d}.{voice}", "addressed", line, heard, ears, source="Kokoro-82M v1.0, Apache-2.0, synthetic", voice=voice))
        print(f"addressed  {'taken   ' if rows[-1]['acted'] else 'MISSED  '}  {heard[:90]}", flush=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows))
    report(out)


def report(path: Path) -> int:
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    side = [r for r in rows if r["kind"] == "side"]
    aimed = [r for r in rows if r["kind"] == "addressed"]
    acted = [r for r in side if addressed.address(r["heard"], r["sessions"]) is not None]
    missed = [r for r in aimed if addressed.address(r["heard"], r["sessions"]) is None]
    print(f"{path.name} ({rows[0]['ears']}): side talk acted on {len(acted)} of {len(side)}; addressed taken {len(aimed) - len(missed)} of {len(aimed)}")
    for r in acted:
        print(f"  acted on: {r['clip']}: {r['heard']!r}")
    for r in missed:
        print(f"  missed: {r['clip']}: said {r['said']!r}, heard {r['heard']!r}")
    return 1 if acted or missed else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("what", choices=["run", "report"])
    parser.add_argument("--ears", default="whisper", choices=["whisper", "soniox"])
    parser.add_argument("--clips", type=Path, default=CLIPS)
    args = parser.parse_args()
    if args.what == "run":
        asyncio.run(run(args.ears, args.clips))
        return 0
    return max(report(p) for p in sorted(HERE.glob("addressed_heard.*.jsonl")))


if __name__ == "__main__":
    sys.exit(main())
