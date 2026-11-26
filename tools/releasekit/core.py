"""State, the lock, commands and the step runner of tools/release.

A release is a list of steps (steps.py). Each step records its outcome in a state file per version, kept in the clone's
git folder so every worktree of the clone sees it: done steps are never run again, so `tools/release resume` picks up
after an outage, an expired sign-in or a person's step. A step that changes something outside this Mac first asks the
outside what is already there (the tag on origin, the assets on the release, the pin on main), so a second run, or a
run after another agent's, does not do it twice.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

REPO = "ballerine-io/pointe"


class Stop(Exception):
    """The step cannot go on without a person or something outside: `how` says what to do, then `tools/release resume`."""

    def __init__(self, why: str, how: str = "", waiting: bool = False):
        super().__init__(why)
        self.why, self.how, self.waiting = why, how, waiting


class Fail(Exception):
    """A check found a defect. The release does not go on until it is fixed (a new commit, or a new patch version)."""


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def git_dir(root: Path) -> Path:
    out = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root,
                         capture_output=True, text=True, check=True).stdout.strip()
    return Path(out)


@dataclass
class Log:
    path: Path | None = None

    def write(self, text: str) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a") as f:
                f.write(text if text.endswith("\n") else text + "\n")


LOG = Log()


def sh(cmd: list[str], cwd: Path | None = None, env: dict | None = None, check: bool = True, timeout: float | None = None,
       stream: bool = False) -> subprocess.CompletedProcess:
    """Run a command; its line and exit status go to the log, its output too (no command here is given a secret)."""
    LOG.write(f"$ {' '.join(cmd)}" + (f"   (in {cwd})" if cwd else ""))
    if stream:  # long runs (the suite, a build): the person sees them move, the log keeps the tail
        try:
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        except OSError as e:  # not found, not executable: a failed command, not a crashed release run
            out = subprocess.CompletedProcess(cmd, 126, "", f"{cmd[0]}: {e.strerror}")
            LOG.write(f"  {out.stderr}")
            if check:
                raise Fail(out.stderr) from None
            return out
        lines: list[str] = []
        assert proc.stdout
        for line in proc.stdout:
            sys.stdout.write("    " + line)
            sys.stdout.flush()
            lines.append(line)
        proc.wait(timeout=timeout)
        out = subprocess.CompletedProcess(cmd, proc.returncode, "".join(lines), "")
    else:
        try:
            out = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            LOG.write(f"  timed out after {timeout} s")
            out = subprocess.CompletedProcess(cmd, 124, (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes)
                                              else (e.stdout or ""), "timed out")
        except OSError as e:
            out = subprocess.CompletedProcess(cmd, 127 if isinstance(e, FileNotFoundError) else 126, "", f"{cmd[0]}: {e.strerror}")
    LOG.write(f"  exit {out.returncode}\n" + "".join(f"  | {line}\n" for line in (out.stdout + out.stderr).splitlines()[-40:]))
    if check and out.returncode != 0 and NETWORK.search(out.stdout + out.stderr):
        raise Stop(f"the network dropped during `{' '.join(cmd[:3])}`: {tail(out.stderr or out.stdout, 2)}",
                   "When the network is back: tools/release resume", waiting=True)
    if check and out.returncode != 0:
        raise Fail(f"`{' '.join(cmd)}` failed (exit {out.returncode}): {tail(out.stdout + out.stderr)}")
    return out


NETWORK = re.compile(r"Could not resolve host|Failed to connect to|Couldn't connect to server|Connection timed out|"
                     r"Network is unreachable|Temporary failure in name resolution|error connecting to api\.github\.com", re.I)


def tail(text: str, lines: int = 6) -> str:
    return " / ".join(line.strip() for line in text.strip().splitlines()[-lines:] if line.strip())[:600]


class State:
    """One version's progress: {step: {status, at, detail, data}} plus the facts later steps read (commits, hashes)."""

    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {"steps": {}, "facts": {}}

    def step(self, name: str) -> dict:
        return self.data["steps"].get(name, {})

    def status(self, name: str) -> str:
        return self.step(name).get("status", "")

    def mark(self, name: str, status: str, detail: str = "") -> None:
        self.data["steps"][name] = {"status": status, "at": now(), "detail": detail}
        self.save()

    def fact(self, key: str, default=None):
        return self.data["facts"].get(key, default)

    def set(self, **facts) -> None:
        self.data["facts"].update(facts)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        part = self.path.with_name(self.path.name + f".{os.getpid()}")
        part.write_text(json.dumps(self.data, indent=1, sort_keys=True) + "\n")
        part.replace(self.path)


class Lock:
    """One release run at a time per clone, whatever the version: two runs race on install.sh and apps.json (0.8.6 and
    0.8.7 did). A lock left by a run that died is taken over."""

    def __init__(self, path: Path):
        self.path = path

    def holder(self) -> dict | None:
        try:
            held = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return None
        if held.get("host") != socket.gethostname():
            return held
        try:
            os.kill(int(held["pid"]), 0)
        except (OSError, ValueError, KeyError):
            return None  # that run is gone
        return held

    def __enter__(self) -> "Lock":
        held = self.holder()
        if held and held.get("pid") != os.getpid():
            raise Stop(f"another release run holds the lock: pid {held.get('pid')} on {held.get('host')}, version "
                       f"{held.get('version')}, since {held.get('since')}",
                       "Let it finish, or stop that process if it is a duplicate; never run two at once.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"pid": os.getpid(), "host": socket.gethostname(), "since": now(),
                                         "version": os.environ.get("POINTE_RELEASE_VERSION", "")}))
        return self

    def __exit__(self, *exc) -> None:
        try:
            if json.loads(self.path.read_text()).get("pid") == os.getpid():
                self.path.unlink()
        except (OSError, ValueError):
            pass


@dataclass
class Step:
    name: str
    title: str
    run: Callable
    dry: Callable | None = None   # what --dry-run does instead: every check, nothing published. None: the same as run
    needs: tuple[str, ...] = ()   # steps that must be done first; a step whose need is not done waits for it
    dry_needs: tuple[str, ...] = ("preflight.tree",)  # in a dry run, only what supplies a fact: every check runs


@dataclass
class Outcome:
    status: str   # done, waiting, stopped, failed, blocked, skipped
    detail: str = ""
    how: str = ""


@dataclass
class Ctx:
    root: Path                 # the clone tools/release was started from
    version: str
    dry_run: bool
    state: State
    work: Path                 # this version's folder: state, log, report, downloads
    tree: Path                 # the release worktree (detached), where everything is built
    args: object = None
    outcomes: dict = field(default_factory=dict)

    @property
    def tag(self) -> str:
        return f"v{self.version}"

    def say(self, text: str) -> None:
        print(text, flush=True)
        LOG.write(text)


def run_steps(ctx: Ctx, steps: list[Step]) -> dict[str, Outcome]:
    """Each step in order, skipping the done ones. A stop on one path does not hold up another: the iPhone upload
    waiting for Xcode's account does not keep the Linux checks from running. Steps that need it are blocked."""
    for step in steps:
        prior = ctx.state.status(step.name)
        if prior in ("done", "skipped"):
            ctx.outcomes[step.name] = Outcome(prior, ctx.state.step(step.name).get("detail", ""))
            ctx.say(f"  {'done':<8} {step.name}: {ctx.outcomes[step.name].detail}"[:220])
            continue
        missing = [n for n in (step.dry_needs if ctx.dry_run else step.needs) if ctx.outcomes.get(n, Outcome("")).status not in ("done", "skipped")]
        if missing:
            ctx.outcomes[step.name] = Outcome("blocked", f"waits for {', '.join(missing)}")
            ctx.say(f"  {'blocked':<8} {step.name}: waits for {', '.join(missing)}")
            continue
        ctx.say(f"\n== {step.name}: {step.title}")
        started = time.monotonic()
        try:
            fn = step.dry if ctx.dry_run and step.dry else step.run
            detail = fn(ctx) or ""
            outcome = Outcome("skipped" if detail.startswith("skip:") else "done", detail.removeprefix("skip:").strip())
        except Stop as e:
            outcome = Outcome("waiting" if e.waiting else "stopped", e.why, e.how)
        except Fail as e:
            outcome = Outcome("failed", str(e))
        ctx.outcomes[step.name] = outcome
        ctx.state.mark(step.name, outcome.status, outcome.detail + (f" | {outcome.how}" if outcome.how else ""))
        took = time.monotonic() - started
        ctx.say(f"  {outcome.status:<8} {outcome.detail}"[:900] + (f"  ({took:.0f} s)" if took >= 1 else ""))
        if outcome.how:
            ctx.say("           next: " + outcome.how.replace("\n", "\n                 "))
    return ctx.outcomes
