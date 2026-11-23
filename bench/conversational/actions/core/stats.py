"""The statistics every table uses: Wilson intervals with numerator and denominator, and the flip rate of repeats."""

import math


def wilson(k: int, n: int, z: float = 1.959964) -> dict:
    """95% Wilson score interval for k events in n. With n == 0 the rate is unknown (None)."""
    if n == 0:
        return {"k": 0, "n": 0, "rate": None, "lo": None, "hi": None}
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return {"k": k, "n": n, "rate": p, "lo": max(0.0, centre - half), "hi": min(1.0, centre + half)}


def fmt_rate(w: dict) -> str:
    """'3/60 = 5.0% (95% CI 1.7 to 13.7)'; zero events print the upper bound only, never a bare 0%."""
    if w["n"] == 0:
        return "n/a (0 runs)"
    if w["k"] == 0:
        return f"0/{w['n']}, under {100 * w['hi']:.1f}% (95% upper bound)"
    return f"{w['k']}/{w['n']} = {100 * w['rate']:.1f}% (95% CI {100 * w['lo']:.1f} to {100 * w['hi']:.1f})"


def flip_rate(pairs: list[tuple[str, str]]) -> dict:
    """Share of repeated items whose two runs disagree, as a Wilson interval over the items."""
    return wilson(sum(a != b for a, b in pairs), len(pairs))
