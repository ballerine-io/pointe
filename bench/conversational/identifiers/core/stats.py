"""Statistics used everywhere (design 4.7): Wilson interval, bootstrap by the independent unit, pass^k, flip rate."""

import math
import random


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def cluster_bootstrap(rows: list, unit, value, b: int = 2000, seed: int = 7) -> tuple[float, float]:
    """95% percentile interval of mean(value(row)) when whole units (unit(row)) are resampled with replacement."""
    groups: dict = {}
    for r in rows:
        groups.setdefault(unit(r), []).append(value(r))
    keys = sorted(groups)
    if not keys:
        return (0.0, 1.0)
    rng = random.Random(seed)
    means = []
    for _ in range(b):
        vals = [v for k in (rng.choice(keys) for _ in keys) for v in groups[k]]
        means.append(sum(vals) / len(vals))
    means.sort()
    return (means[int(0.025 * b)], means[min(b - 1, int(0.975 * b))])


def paired_bootstrap(a: dict, c: dict, b: int = 2000, seed: int = 7) -> tuple[float, float, float]:
    """a, c: unit -> list of 0/1. Difference of means (a - c) over the units both have, resampled by unit."""
    keys = sorted(set(a) & set(c))
    if not keys:
        return (0.0, -1.0, 1.0)
    m = lambda d, ks: sum(sum(d[k]) / len(d[k]) for k in ks) / len(ks)  # noqa: E731
    rng = random.Random(seed)
    diffs = sorted(m(a, s) - m(c, s) for s in ([rng.choice(keys) for _ in keys] for _ in range(b)))
    return (m(a, keys) - m(c, keys), diffs[int(0.025 * b)], diffs[min(b - 1, int(0.975 * b))])


def pass_k(runs: list[list[bool]]) -> float:
    """Share of items whose every run passed."""
    return sum(all(r) for r in runs) / len(runs) if runs else 0.0


def flip_rate(pairs: list[tuple]) -> float:
    """Share of repeated items whose two runs disagree."""
    return sum(a != b for a, b in pairs) / len(pairs) if pairs else 0.0
