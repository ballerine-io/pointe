"""The program-wide spend ledger: one line per paid launch (smoke and debug included). The runner reads it before every
launch and refuses to start unless the benchmark's cap still covers `workers` worst-case runs."""

import json
import time
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "results" / "ledger.jsonl"


class BudgetExceeded(RuntimeError):
    pass


def rows(path: Path = LEDGER) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def spent(benchmark: str, path: Path = LEDGER) -> float:
    return round(sum(r["usd"] for r in rows(path) if r["benchmark"] == benchmark), 6)


def gate(benchmark: str, cap: float, workers: int, max_run_usd: float, path: Path = LEDGER) -> float:
    """Raises BudgetExceeded when cap - spent < workers x the most one run can cost. Returns what is left."""
    left = cap - spent(benchmark, path)
    if left < workers * max_run_usd:
        raise BudgetExceeded(f"{benchmark}: ${left:.4f} left of ${cap}, need ${workers * max_run_usd:.2f} headroom")
    return left


def add(benchmark: str, run_id: str, what: str, usd: float, by_vendor: dict, kind: str, path: Path = LEDGER) -> None:
    """`kind`: paid | smoke | debug. `by_vendor` values carry their basis: {"anthropic-agent": [0.003, "computed"]}."""
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "benchmark": benchmark, "run_id": run_id, "what": what,
           "usd": round(usd, 6), "by_vendor": by_vendor, "kind": kind}
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")
