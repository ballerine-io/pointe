"""What every benchmark's runner shares: run folders under /tmp, ports, the freeze check, the load average, the file
watcher, and scrubbed raw rows."""

import json
import os
import subprocess
import threading
import time
from pathlib import Path

from . import scrub
from .adapter import now

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
FORBIDDEN_PORTS = (7860, 7443)
LOAD_FLAG = 12.0  # 1-minute load average above which a row is flagged: two thirds of this 18-core machine's threads


def check_ports(base: int, span: int = 2) -> None:
    for p in range(base, base + span):
        if p in FORBIDDEN_PORTS:
            raise SystemExit(f"port {p} belongs to the owner's Pointe: use another --port-base")


def check_state_dir(path: Path) -> None:
    real = os.path.realpath(path)
    if real.startswith(str(Path.home())) or not (real.startswith("/tmp/") or real.startswith("/private/tmp/")):
        raise SystemExit(f"state folder {path} must be under /tmp, never the home folder")


def load() -> float:
    return round(os.getloadavg()[0], 2)


def product_commit() -> str:
    """The last commit that changed Pointe itself (anything outside bench/, tests/ and docs/)."""
    return subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%H", "--", ".", ":!bench", ":!tests", ":!docs"],
                          capture_output=True, text=True).stdout.strip()


def head_commit() -> str:
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def frozen() -> dict | None:
    path = HERE / "FROZEN.json"
    if not path.exists():
        return None
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--error-unmatch", str(path)], capture_output=True)
    dirty = subprocess.run(["git", "-C", str(ROOT), "diff", "--quiet", "HEAD", "--", str(path)])
    if tracked.returncode != 0 or dirty.returncode != 0:
        return None  # a freeze counts only once committed
    data = json.loads(path.read_text())
    data["freeze_commit"] = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%H", "--", str(path)],
                                           capture_output=True, text=True).stdout.strip()
    return data


class FileWatcher:
    """First-seen time of every file under a folder, polled every 50 ms on the runner's clock."""

    def __init__(self, root: Path, pattern: str = "step_*.txt"):
        self.root, self.pattern = root, pattern
        self.seen: dict[str, float] = {}
        self.last_change = now()
        self._present: set[str] = set()
        self._stop = False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        while not self._stop:
            present = {str(p.relative_to(self.root)) for p in self.root.rglob(self.pattern)}
            t = now()
            for p in present - set(self.seen):
                self.seen[p] = t
            if present != self._present:
                self.last_change, self._present = t, present
            time.sleep(0.05)

    def present(self) -> set[str]:
        return {str(p.relative_to(self.root)) for p in self.root.rglob(self.pattern)}

    def stop(self) -> None:
        self._stop = True


def busy_in(root: Path) -> bool:
    """Is any process still working inside this folder (a job the agent left running)?"""
    out = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fn"], capture_output=True, text=True).stdout
    real = os.path.realpath(root)
    return any(line[1:].startswith((str(root), real)) for line in out.splitlines() if line.startswith("n"))


class Results:
    """results/<run-id>/: rows.jsonl, events.jsonl, spend.jsonl, run.json. Every line is scrubbed and refused if a home
    path or key-shaped text survives."""

    def __init__(self, run_id: str):
        self.dir = HERE / "results" / run_id
        self.dir.mkdir(parents=True, exist_ok=True)

    def append(self, name: str, obj: dict) -> None:
        line = scrub.clean(json.dumps(obj, default=str))
        bad = scrub.problems(line)
        if bad:
            raise RuntimeError(f"refused a {name} line: {bad}")
        with (self.dir / name).open("a") as f:
            f.write(line + "\n")

    def write(self, name: str, obj) -> None:
        text = scrub.clean(json.dumps(obj, indent=1, default=str))
        if scrub.problems(text):
            raise RuntimeError(f"refused {name}")
        (self.dir / name).write_text(text + "\n")
