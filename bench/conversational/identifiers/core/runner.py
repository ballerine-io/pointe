"""Workers, ports, caps, process cleanup and the budget gate (design 4.1, 4.3, 4.5).

The runner owns the order: runs are listed by the benchmark in its seeded order and taken one by one by `workers`
threads, so a stop at the cap leaves a random subsample with every arm present. Before each launch the ledger gate is
asked. Each worker has its own port (port_base + 1 + worker); 7860 and 7443, and any state folder outside /tmp, are
refused.
"""

import json
import os
import shutil
import subprocess
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import ledger, scrub

HERE = Path(__file__).resolve().parents[1]
REPO_ROOT = HERE.parents[2]
TMP = Path("/tmp/pccb")
FORBIDDEN_PORTS = {7860, 7443}


def check_ports(port_base: int, workers: int) -> list[int]:
    ports = [port_base + 1 + w for w in range(workers)]
    used = set(ports) | {p + 50 for p in ports}  # each Pointe daemon's TLS port
    if used & FORBIDDEN_PORTS or min(used) <= 1024:
        raise SystemExit(f"refused: ports {sorted(used)} include the owner's live Pointe (7860, 7443) or a system port")
    return ports


def check_state_dir(path: Path) -> None:
    real = str(path.resolve())
    if not real.startswith(("/tmp/", "/private/tmp/")) or real.startswith(str(Path.home())):
        raise SystemExit(f"refused: state folder {path} is not under /tmp")


def git(*args: str, cwd: Path = REPO_ROOT) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True).stdout.strip()


def make_repo(fixture: Path, dest: Path) -> Path:
    """The item's own git repo: a copy of the fixture, committed once, no remote."""
    shutil.copytree(fixture, dest, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
    env = {**os.environ, "GIT_AUTHOR_NAME": "bench", "GIT_AUTHOR_EMAIL": "bench@example.invalid",
           "GIT_COMMITTER_NAME": "bench", "GIT_COMMITTER_EMAIL": "bench@example.invalid"}
    for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "almanac"]):
        subprocess.run(["git", *cmd], cwd=dest, env=env, check=True, capture_output=True)
    return dest


def pointe_checkout(commit: str) -> Path:
    """The Pointe under test, exported at one commit into /tmp (no bench files, its own venv), so the runner's own
    checkout and the owner's install are never what the agent loads."""
    root = TMP / f"pointe-{commit[:12]}"
    if not (root / "COMMIT").exists():
        root.mkdir(parents=True, exist_ok=True)
        archive = subprocess.run(["git", "archive", commit], cwd=REPO_ROOT, capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", str(root)], input=archive, check=True)
        (root / "COMMIT").write_text(commit + "\n")
    return root


def load_average() -> float:
    return round(os.getloadavg()[0], 2)


def leftover(ports: list[int]) -> list[str]:
    """Anything still listening on this run's ports."""
    out = []
    for p in ports + [p + 50 for p in ports]:
        got = subprocess.run(["lsof", "-nP", f"-iTCP:{p}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True)
        out += [f"{p}:{pid}" for pid in got.stdout.split()]
    return out


class Run:
    """One benchmark run: results/<run-id>/ with rows, events, spend and the run record."""

    def __init__(self, bench: str, run_id: str, cap: float, workers: int, port_base: int, max_run_usd: float,
                 smoke: bool):
        self.bench, self.run_id, self.cap, self.workers = bench, run_id, cap, workers
        self.ports = check_ports(port_base, workers)
        self.max_run_usd, self.smoke = max_run_usd, smoke
        self.dir = HERE / "results" / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "logs").mkdir(exist_ok=True)
        self.tmp = TMP / run_id
        self.tmp.mkdir(parents=True, exist_ok=True)
        check_state_dir(self.tmp)
        self._lock = threading.Lock()
        self.stopped_for_budget = False

    def done_keys(self) -> set[str]:
        p = self.dir / "rows.jsonl"
        return {json.loads(l)["key"] for l in p.read_text().splitlines() if l.strip()} if p.exists() else set()

    def write(self, name: str, record: dict) -> None:
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        scrub.check(line)
        with self._lock, (self.dir / name).open("a") as f:
            f.write(line + "\n")

    def execute(self, runs: list[dict], one) -> None:
        """one(run, worker_port, item_dir) -> (row, spend rows, log record). Runs in order across the workers."""
        todo = [r for r in runs if r["key"] not in self.done_keys()]
        queue = list(todo)
        qlock = threading.Lock()

        def worker(w: int) -> None:
            while True:
                with qlock:
                    if not queue or self.stopped_for_budget:
                        return
                    run = queue.pop(0)
                    try:
                        ledger.gate(self.bench, self.cap, self.workers, self.max_run_usd)
                    except ledger.OverBudget as e:
                        self.stopped_for_budget = True
                        print(f"STOP {e}", flush=True)
                        return
                item_dir = self.tmp / run["key"]
                if item_dir.exists():
                    shutil.rmtree(item_dir, ignore_errors=True)
                item_dir.mkdir(parents=True)
                t0 = time.time()
                try:
                    row, spend, log = one(run, self.ports[w], item_dir)
                except Exception as e:  # noqa: BLE001  a crashed run is recorded, never silently dropped
                    row, spend, log = {"key": run["key"], "outcome": "error",
                                       "error": scrub.text(f"{type(e).__name__}: {e}")[:300]}, [], {
                        "trace": scrub.text(traceback.format_exc())[-2000:]}
                usd = ledger.add(self.bench, self.run_id, run["key"], "smoke" if self.smoke else "run", spend)
                row.update(spend_usd=round(usd, 5), wall_s=round(time.time() - t0, 1))
                self.write("rows.jsonl", row)
                self.write("spend.jsonl", {"key": run["key"], "spend": [
                    {"vendor": s.vendor, "usd": round(s.usd, 6), "how": s.how, "detail": s.detail} for s in spend]})
                (self.dir / "logs" / f"{run['key']}.json").write_text(
                    scrub.text(json.dumps(log, ensure_ascii=False, indent=1)))
                print(f"[{w}] {run['key']}: {row.get('outcome')} ${usd:.4f} {row['wall_s']}s "
                      f"(spent {ledger.spent(self.bench):.2f})", flush=True)

        with ThreadPoolExecutor(self.workers) as pool:
            for f in [pool.submit(worker, w) for w in range(self.workers)]:
                f.result()
