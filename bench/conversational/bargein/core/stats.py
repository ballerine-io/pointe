"""The statistics every table uses: Wilson intervals, median and p90 with a censored count, bootstrap by unit."""

import math
import random
import statistics


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for k of n. (0, 0) for n = 0: there is nothing to bound."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def proportion(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": (k / n) if n else None, "ci95": [round(lo, 4), round(hi, 4)]}


def p90(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))]


def times(values: list[float | None]) -> dict:
    """Median and p90 over the observed values; None is a censored item (never reached), counted and never dropped."""
    seen = [v for v in values if v is not None]
    return {"n": len(values), "observed": len(seen), "censored": len(values) - len(seen),
            "median": round(statistics.median(seen), 3) if seen else None,
            "p90": round(p90(seen), 3) if seen else None}


def bootstrap_rate(units: dict[str, list[bool]], n: int = 2000, seed: int = 1) -> tuple[float, float]:
    """95% percentile interval of the pooled rate, resampling whole units (the benchmark's independent unit)."""
    keys = sorted(units)
    if not keys:
        return (0.0, 0.0)
    rng = random.Random(seed)
    rates = []
    for _ in range(n):
        pick = [units[rng.choice(keys)] for _ in keys]
        total = sum(len(p) for p in pick)
        rates.append(sum(sum(p) for p in pick) / total if total else 0.0)
    rates.sort()
    return (rates[int(0.025 * n)], rates[int(0.975 * n) - 1])


def flip_rate(pairs: list[tuple[bool, bool]]) -> dict:
    """Share of repeated items whose two runs disagree, and pass^2 (both runs pass)."""
    n = len(pairs)
    flips = sum(a != b for a, b in pairs)
    both = sum(a and b for a, b in pairs)
    return {"n": n, "flips": flips, "flip_rate": (flips / n) if n else None, "pass2": (both / n) if n else None}
