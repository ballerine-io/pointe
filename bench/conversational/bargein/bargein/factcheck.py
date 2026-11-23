"""`run.py factcheck`, $0: every expected fact's canonical answer rendered in all four panel voices and recognized by
the pinned Whisper must match; the question detector runs on the labelled set rendered and recognized the same way.
Writes bargein/factcheck.json, which the offline tests read."""

import json
import random
from datetime import date
from pathlib import Path

from core import audio, corpus, user
from bargein import facts

HERE = Path(__file__).resolve().parent


def main() -> int:
    rows, voices = [], corpus.voices()
    for fact, (_, _, answer) in sorted(facts.FACTS.items()):
        for v in voices:
            heard = audio.transcribe(audio.kokoro(answer, v))
            rows.append({"fact": fact, "voice": v, "said": answer, "heard": heard, "matched": facts.states(fact, heard)})
    det = []
    rng = random.Random(20261123)
    for line, label in user.LABELLED:
        v = rng.choice(voices)
        heard = audio.transcribe(audio.kokoro(line, v))
        det.append({"line": line, "voice": v, "heard": heard, "label": label, "detected": user.is_question(heard)})
    acc = sum(d["label"] == d["detected"] for d in det) / len(det)
    out = {"date": date.today().isoformat(), "recognizer": audio.WHISPER, "voices": voices, "facts": rows,
           "detector": {"accuracy": round(acc, 4), "n": len(det), "lines": det}}
    (HERE / "factcheck.json").write_text(json.dumps(out, indent=1) + "\n")
    bad = [r for r in rows if not r["matched"]]
    print(f"facts: {len(rows) - len(bad)} of {len(rows)} matched; detector {acc:.1%} on {len(det)} lines")
    for r in bad:
        print(f"  MISS {r['fact']} {r['voice']}: heard {r['heard']!r}")
    for d in det:
        if d["label"] != d["detected"]:
            print(f"  DETECTOR {d['label']} {d['voice']}: heard {d['heard']!r}")
    return 0 if not bad and acc >= 0.95 else 1
