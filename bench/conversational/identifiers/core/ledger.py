"""The spend ledger: one row per vendor call group per item run, smoke and debugging included (design 4.5).

Before each launch the runner asks `gate`: it refuses unless cap - spent >= workers x the most one run may cost.
"""

import json
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
LEDGER = HERE / "results" / "ledger.jsonl"
PRICES = json.loads((HERE / "prices.json").read_text())
_lock = threading.Lock()


class OverBudget(Exception):
    pass


def tokens_usd(model: str, usage: dict) -> float:
    """usage: input (fresh), cache_read, cache_write, output. An unknown model is priced as Sonnet, the dearest here."""
    p = PRICES["per_million_tokens"].get(model) or PRICES["per_million_tokens"]["claude-sonnet-5-5"]
    return sum(usage.get(k, 0) * p[k] for k in ("input", "cache_read", "cache_write", "output")) / 1e6


def rows(path: Path = LEDGER) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def spent(bench: str, path: Path = LEDGER) -> float:
    return sum(r["usd"] for r in rows(path) if r["bench"] == bench)


def add(bench: str, run_id: str, item: str, phase: str, spend: list, path: Path = LEDGER) -> float:
    total = 0.0
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            for s in spend:
                total += s.usd
                f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "bench": bench, "run_id": run_id,
                                    "item": item, "phase": phase, "vendor": s.vendor, "usd": round(s.usd, 6),
                                    "how": s.how}) + "\n")
    return total


def gate(bench: str, cap: float, workers: int, max_run_usd: float, path: Path = LEDGER) -> float:
    left = cap - spent(bench, path)
    if left < workers * max_run_usd:
        raise OverBudget(f"{bench}: ${left:.2f} left of ${cap:.2f}, a launch needs {workers} x ${max_run_usd:.2f}")
    return left
