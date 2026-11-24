"""Statistics, the same everywhere: Wilson intervals, a bootstrap that resamples the independent unit (HLK: the
family), pass^k and the flip rate."""

import math
import random


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def bootstrap_diff(pairs: dict, reps: int = 10000, seed: int = 20261123, alpha: float = 0.05) -> tuple[float, float, float]:
    """pairs: unit -> (a_pass, a_n, b_pass, b_n). The difference of pooled rates a - b, with a percentile interval
    from resampling the units with replacement."""
    units = sorted(pairs)
    if not units:
        return (0.0, 0.0, 0.0)

    def diff(sample):
        ap = sum(pairs[u][0] for u in sample)
        an = sum(pairs[u][1] for u in sample)
        bp = sum(pairs[u][2] for u in sample)
        bn = sum(pairs[u][3] for u in sample)
        return (ap / an if an else 0.0) - (bp / bn if bn else 0.0)

    rng = random.Random(seed)
    draws = sorted(diff([rng.choice(units) for _ in units]) for _ in range(reps))
    lo = draws[int(alpha / 2 * reps)]
    hi = draws[min(reps - 1, int((1 - alpha / 2) * reps))]
    return (diff(units), lo, hi)


def pass_k(groups: dict) -> tuple[int, int]:
    """groups: item -> [bool per run]. Items whose every run passed, over items with at least two runs."""
    full = [runs for runs in groups.values() if len(runs) >= 2]
    return (sum(all(r) for r in full), len(full))


def flips(groups: dict) -> tuple[int, int]:
    """Items whose two runs disagree, over items with at least two runs."""
    full = [runs for runs in groups.values() if len(runs) >= 2]
    return (sum(len(set(r[:2])) > 1 for r in full), len(full))
