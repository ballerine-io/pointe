"""Spend ledger: one row per paid launch, checked before every launch against the cap."""

import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
LEDGER = HERE / "results" / "ledger.jsonl"
PRICES = json.loads((HERE / "prices.json").read_text())


def anthropic_usd(model: str, usage: dict) -> float:
    p = PRICES["anthropic"][model]
    return (usage.get("input_tokens", 0) * p["in"] + usage.get("output_tokens", 0) * p["out"]
            + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
            + usage.get("cache_creation_input_tokens", 0) * p["cache_write"]) / 1e6


def spent(benchmark: str, path: Path = LEDGER) -> float:
    if not path.exists():
        return 0.0
    return sum(r["usd"] for r in map(json.loads, path.read_text().splitlines()) if r["benchmark"] == benchmark)


def record(row: dict, path: Path = LEDGER) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **row}) + "\n")


class BudgetExceeded(RuntimeError):
    pass


def gate(benchmark: str, cap: float, headroom: float, path: Path = LEDGER) -> float:
    """Refuses a launch unless cap - spent >= headroom (workers x the most one launch can cost). Returns spent."""
    s = spent(benchmark, path)
    if cap - s < headroom:
        raise BudgetExceeded(f"{benchmark}: ${s:.2f} spent of ${cap:.2f}; a launch needs ${headroom:.2f} of headroom")
    return s
