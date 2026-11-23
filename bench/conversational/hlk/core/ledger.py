"""The program-wide spend ledger (results/ledger.jsonl): one row per item run, smoke and debug included. Before each
launch the runner reads it and refuses to start unless cap - spent >= workers x the maximum cost of one run."""

import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
LEDGER = HERE / "results" / "ledger.jsonl"
PRICES = json.loads((HERE / "prices.json").read_text())


def token_cost(model: str, usage: dict) -> float:
    price = PRICES["tokens"].get(model) or PRICES["tokens"].get(model.split("[")[0])
    if price is None:
        price = PRICES["tokens"]["claude-sonnet-5-5"]  # an unknown model is charged at the dearer price, never at $0
    fresh = usage.get("input_tokens", 0)
    return (fresh * price[0] + usage.get("cache_read_input_tokens", 0) * price[1]
            + usage.get("cache_creation_input_tokens", 0) * price[2] + usage.get("output_tokens", 0) * price[3]) / 1e6


def rows(path: Path | None = None) -> list:
    path = path or LEDGER
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def spent(benchmark: str | None = None, path: Path | None = None) -> float:
    return round(sum(r["usd"] for r in rows(path) if benchmark is None or r.get("benchmark") == benchmark), 6)


def append(row: dict, path: Path | None = None) -> None:
    path = path or LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **row}, sort_keys=True) + "\n")


class BudgetRefused(RuntimeError):
    pass


def gate(cap: float, workers: int, max_run: float, benchmark: str, path: Path | None = None) -> float:
    """Raises BudgetRefused when the remaining cap cannot cover one more run on every worker. Returns what is left."""
    left = cap - spent(benchmark, path)
    if left < workers * max_run:
        raise BudgetRefused(f"{benchmark}: ${left:.2f} left of ${cap:.2f}, and {workers} workers x ${max_run:.2f} "
                            "a run is more than that")
    return left
