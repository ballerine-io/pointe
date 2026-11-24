"""Record your own voice for the benchmark: uv run python -I bench/record.py

Shows each corpus line; press Enter to start, Enter to stop. Saves 16 kHz mono PCM to
bench/recordings/<id>.pcm. Already recorded lines are skipped; type s to skip, q to quit.
Then: uv run python -I bench/stt_bench.py run --voices own && ... report
"""

import sys
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd

sys.path.insert(0, str(Path(__file__).parent))
from corpus import CORPUS  # noqa: E402

OUT = Path(__file__).parent / "recordings"
RATE = 16000


def record() -> np.ndarray:
    chunks: list[np.ndarray] = []
    stop = threading.Event()

    def callback(indata, frames, t, status):
        chunks.append(indata[:, 0].copy())

    with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", callback=callback):
        threading.Thread(target=lambda: (input(), stop.set()), daemon=True).start()
        stop.wait()
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    print(f"Mic: {sd.query_devices(kind='input')['name']}. Speak naturally, as you would to the assistant.\n")
    todo = [c for c in CORPUS if not (OUT / f"{c[0]}.pcm").exists()]
    for n, (cid, _, text) in enumerate(todo, 1):
        cmd = input(f"[{n}/{len(todo)}] {text}\n  Enter = record, s = skip, q = quit: ").strip().lower()
        if cmd == "q":
            break
        if cmd == "s":
            continue
        print("  recording... Enter to stop")
        pcm = record()
        if len(pcm) < RATE // 2:
            print("  too short, skipped")
            continue
        (OUT / f"{cid}.pcm").write_bytes(pcm.tobytes())
        print(f"  saved {len(pcm) / RATE:.1f}s\n")


if __name__ == "__main__":
    main()
