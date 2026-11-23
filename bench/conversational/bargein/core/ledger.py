"""The program-wide spend ledger (results/ledger.jsonl) and the gate checked before every paid launch."""

import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
LEDGER = HERE / "results" / "ledger.jsonl"
PRICES = json.loads((HERE / "prices.json").read_text())


class BudgetExceeded(RuntimeError):
    pass


def rows(path: Path = LEDGER) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def spent(benchmark: str, path: Path = LEDGER) -> float:
    return round(sum(r["usd"] for r in rows(path) if r.get("benchmark") == benchmark), 6)


def gate(benchmark: str, cap: float, workers: int, max_run_usd: float, path: Path = LEDGER) -> float:
    """Refuses a launch unless cap - spent >= workers x the most one run can cost. Returns what is left."""
    left = cap - spent(benchmark, path)
    if left < workers * max_run_usd:
        raise BudgetExceeded(f"{benchmark}: ${left:.2f} left of ${cap:.2f}, a launch needs ${workers * max_run_usd:.2f}")
    return left


def record(benchmark: str, run_id: str, item: str, arm: str, kind: str, spend: list, path: Path = LEDGER) -> float:
    """One ledger row per run: kind is paid | smoke | debug. spend: SpendRow-like dicts."""
    usd = round(sum(s["usd"] for s in spend), 6)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "benchmark": benchmark, "run_id": run_id,
                            "item": item, "arm": arm, "kind": kind, "usd": usd, "spend": spend}) + "\n")
    return usd


def anthropic_usd(model: str, usage: dict) -> float:
    p = PRICES["anthropic_per_mtok"][model]
    return (usage.get("input_tokens", 0) * p["input"] + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
            + usage.get("cache_creation_input_tokens", 0) * p["cache_write"] + usage.get("output_tokens", 0) * p["output"]) / 1e6


def soniox_usd(stream_seconds: float) -> float:
    return stream_seconds / 3600 * PRICES["soniox_rt_per_stream_hour"]
