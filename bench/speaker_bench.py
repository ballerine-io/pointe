"""How well the owner-voice lock tells the owner from someone else, on synthetic voices (macOS `say`).

uv run python bench/speaker_bench.py [--models DIR] [--out bench/results/speaker.md]

Each voice in turn is the owner: it enrols on six lines (the same rule as the daemon: centroid of per-line embeddings),
then every voice says held-out sentences and a short "yes". Genuine trials are made harder than a clean replay: a
different speaking rate, and room noise at about 20 dB SNR. Reported: the score spread, the equal error rate, and the false
accept / false reject rates at speaker.T_HIGH and speaker.T_LOW.

What this does NOT measure: real people. Text-to-speech voices are far more consistent than a person on a cold day, on
another mic, or across a room, so the false-reject numbers here are a floor, not an estimate. Recorded owner samples (with
consent) are the gate before any default above "approvals".
"""

import argparse
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
import speaker  # noqa: E402

VOICES = ["Albert", "Daniel", "Eddy (English (US))", "Flo (English (US))", "Fred", "Grandma (English (US))",
          "Grandpa (English (US))", "Karen", "Kathy", "Moira", "Ralph", "Reed (English (US))", "Rishi",
          "Rocko (English (US))", "Sandy (English (US))", "Shelley (English (US))", "Tessa", "Aman", "Tara"]
ENROL = [
    "The quick brown fox jumps over the lazy dog near the riverbank.",
    "Please tell the build session to run the tests and report back.",
    "Seven bright kites drifted above the harbour on a windy afternoon.",
    "Good morning, I am checking that the system recognises my voice clearly.",
    "Tell the test session to run every test and report to me.",
    "Three colourful kites flew over the port on a stormy day.",
]
HELD_OUT = [
    "Switch to the pricing session and ask what is still failing.",
    "Can you summarise what the migration branch changed since lunch?",
    "Hold off on the deploy until I have looked at the logs myself.",
]
SHORT = ["Yes.", "Go ahead."]


def synth(folder: Path, voice: str, text: str, rate: int | None = None) -> np.ndarray | None:
    path = folder / f"{abs(hash((voice, text, rate)))}.wav"
    cmd = ["say", "-v", voice, "--data-format=LEI16@16000", "-o", str(path), text] + (["-r", str(rate)] if rate else [])
    if subprocess.run(cmd, capture_output=True).returncode != 0:
        return None
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def noisy(x: np.ndarray, snr_db: float, rng) -> np.ndarray:
    p = float(np.mean(x ** 2)) or 1e-9
    return (x + rng.normal(0, np.sqrt(p / 10 ** (snr_db / 10)), x.shape)).astype(np.float32)


def rates(gen: list[float], imp: list[float], t: float) -> tuple[float, float]:
    fr = sum(s < t for s in gen) / max(1, len(gen))
    fa = sum(s >= t for s in imp) / max(1, len(imp))
    return fa, fr


def eer(gen: list[float], imp: list[float]) -> tuple[float, float]:
    """The equal error rate and where it falls: the threshold at which false accepts and false rejects are closest."""
    fa, fr, t = min(((*rates(gen, imp, t), float(t)) for t in np.linspace(-0.2, 1.0, 241)), key=lambda r: abs(r[0] - r[1]))
    return (fa + fr) / 2, t


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=str(Path.home() / ".claude-voice" / "models"))
    ap.add_argument("--out")
    args = ap.parse_args()
    emb = speaker.Embedder(Path(args.models))
    rng = np.random.default_rng(7)
    folder = Path(tempfile.mkdtemp(prefix="speaker-bench-"))
    voices, enrolled, sentences, shorts = [], {}, {}, {}
    for v in VOICES:
        clips = [synth(folder, v, t) for t in ENROL]
        if any(c is None for c in clips):
            continue
        voices.append(v)
        c = np.mean([emb.embed(x) for x in clips], axis=0)
        enrolled[v] = c / np.linalg.norm(c)
        sentences[v] = [emb.embed(noisy(synth(folder, v, t, 150 if i % 2 else 220), 20, rng)) for i, t in enumerate(HELD_OUT)]
        shorts[v] = [emb.embed(noisy(synth(folder, v, t), 20, rng)) for t in SHORT]
    gen_s, imp_s, gen_y, imp_y = [], [], [], []
    for owner in voices:
        for who in voices:
            s = [float(np.dot(enrolled[owner], e)) for e in sentences[who]]
            y = [float(np.dot(enrolled[owner], e)) for e in shorts[who]]
            (gen_s if who == owner else imp_s).extend(s)
            (gen_y if who == owner else imp_y).extend(y)
    lines = [f"# Owner-voice lock: synthetic bench ({len(voices)} macOS voices, model {speaker.MODEL_NAME})", "",
             "Each voice is the owner once; every other voice is an impostor. Genuine trials: other sentences, another "
             "speaking rate, noise at 20 dB SNR. TTS voices are steadier than people: false rejects here are a floor.", "",
             "| Trials | Genuine (mean, min) | Impostor (mean, max) | EER (at threshold) |", "|---|---|---|---|"]
    for name, g, i in (("sentences (2-4 s)", gen_s, imp_s), ('short ("yes", "go ahead")', gen_y, imp_y)):
        e, t = eer(g, i)
        lines.append(f"| {name}: {len(g)} genuine, {len(i)} impostor | {np.mean(g):.2f}, {min(g):.2f} | "
                     f"{np.mean(i):.2f}, {max(i):.2f} | {e:.1%} (at {t:.2f}) |")
    lines += ["", f"The daemon uses T_HIGH = {speaker.T_HIGH} (alone, sentences) and T_LOW = {speaker.T_LOW} (a short word "
              "within a minute of a T_HIGH match on the same device profile).", "",
              "| Threshold | Trials | False accept | False reject |", "|---|---|---|---|"]
    for t in sorted({0.30, 0.45, 0.50, 0.60, speaker.T_LOW, speaker.T_HIGH}):
        for name, g, i in (("sentences", gen_s, imp_s), ("short", gen_y, imp_y)):
            fa, fr = rates(g, i, t)
            mark = " (T_HIGH)" if t == speaker.T_HIGH else " (T_LOW)" if t == speaker.T_LOW else ""
            lines.append(f"| {t:.2f}{mark} | {name} | {fa:.1%} ({round(fa * len(i))}/{len(i)}) | "
                         f"{fr:.1%} ({round(fr * len(g))}/{len(g)}) |")
    text = "\n".join(lines) + "\n"
    print(text)
    if args.out:
        Path(args.out).write_text(text)


if __name__ == "__main__":
    main()
