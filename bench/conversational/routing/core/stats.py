"""Statistics used by every table: Wilson intervals on proportions, a bootstrap over the independent unit, flip rate."""

import math
import random


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """95% Wilson score interval for k of n. With n = 0 the interval is the whole range."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def cluster_bootstrap(clusters: list[list[bool]], iters: int = 4000, seed: int = 20261123) -> tuple[float, float]:
    """95% percentile interval of the pooled proportion, resampling whole clusters (here: conversations)."""
    clusters = [c for c in clusters if c]
    if not clusters:
        return 0.0, 1.0
    rng = random.Random(seed)
    stats = []
    for _ in range(iters):
        pick = [clusters[rng.randrange(len(clusters))] for _ in clusters]
        total = sum(len(c) for c in pick)
        stats.append(sum(sum(c) for c in pick) / total)
    stats.sort()
    return stats[int(0.025 * iters)], stats[min(iters - 1, int(0.975 * iters))]


def flip_rate(pairs: list[tuple[bool, bool]]) -> tuple[int, int]:
    """How many paired runs disagree, of how many pairs."""
    return sum(a != b for a, b in pairs), len(pairs)


def pass_k(runs: list[list[bool]]) -> tuple[int, int]:
    """Items that passed in every one of their runs, of items."""
    return sum(all(r) for r in runs), len(runs)
