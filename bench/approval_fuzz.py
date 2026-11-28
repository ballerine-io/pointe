"""How sure is "no false approval"? Runs the adversarial approval trials of tests/test_approval_fuzz.py (offline, a fixed
seed, the daemon's real approval path with fake audio, channel and clock) and prints, per family, the trials, the false
approvals and the 95% upper bound on the false-approval rate (one-sided Clopper-Pearson, and Wilson beside it), then the
positive controls' approval rate. Free: no key, no model, no network.

  uv run --locked --group test-tools python -I bench/approval_fuzz.py
"""

import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
Z = 1.6449  # one-sided 95%


def clopper_pearson_upper(k: int, n: int, alpha: float = 0.05) -> float:
    """The exact one-sided upper bound: the p at which seeing k or fewer in n has probability alpha."""
    if k >= n:
        return 1.0
    if k == 0:
        return 1 - alpha ** (1 / n)

    def cdf(p: float) -> float:
        return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))

    lo, hi = k / n, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cdf(mid) > alpha else (lo, mid)
    return hi


def wilson_upper(k: int, n: int) -> float:
    p = k / n
    centre = p + Z * Z / (2 * n)
    margin = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n))
    return min(1.0, (centre + margin) / (1 + Z * Z / n))


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "counts.jsonl"
        env = {**os.environ, "POINTE_FUZZ_REPORT": str(report)}
        run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "-n", "2",
                              str(ROOT / "tests" / "test_approval_fuzz.py"), "-k", "no_false_approval or clear_yes"],
                             cwd=ROOT, env=env, capture_output=True, text=True)
        rows = [json.loads(line) for line in report.read_text().splitlines()] if report.exists() else []
    if not rows:
        print(run.stdout[-3000:], run.stderr[-3000:])
        return 1
    adversarial = sorted((r for r in rows if not r["control"]), key=lambda r: r["family"])
    print(f"{'family':<16}{'trials':>8}{'false':>7}{'CP 95% upper':>14}{'Wilson 95% upper':>18}")
    for r in adversarial:
        n, k = r["trials"], r["failed"]
        print(f"{r['family']:<16}{n:>8}{k:>7}{clopper_pearson_upper(k, n):>13.2%}{wilson_upper(k, n):>17.2%}")
    n, k = sum(r["trials"] for r in adversarial), sum(r["failed"] for r in adversarial)
    print(f"{'all adversarial':<16}{n:>8}{k:>7}{clopper_pearson_upper(k, n):>13.2%}{wilson_upper(k, n):>17.2%}")
    for r in (r for r in rows if r["control"]):
        ok = r["trials"] - r["failed"]
        print(f"\npositive controls: {ok} of {r['trials']} approved the request read out ({ok / r['trials']:.1%})")
    for r in rows:
        for line in r["failures"]:
            print(f"  {r['family']}: {line}")
    return 0 if k == 0 and all(r["failed"] == 0 for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
