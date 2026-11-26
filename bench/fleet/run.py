"""The fleet benchmark: scripted user turns typed into one voice with H machines and S sessions each, and where every
send landed. Paid (the real brain, reader and checker); never in CI. The simulator is bench/fleet/sim.py.

    uv run --locked python -I bench/fleet/run.py up 10x30                      the simulator alone, stubbed models: free
    uv run --locked python -I bench/fleet/run.py turns 5x20 --arm fleet-on --runs 3 --budget-usd 15
    uv run --locked python -I bench/fleet/run.py turns 1x4 --arm fleet-on --models stub --limit 6      a dry run: free
    uv run --locked python -I bench/fleet/run.py burst 5x20 --arm fleet-on --budget-usd 15
    uv run --locked python -I bench/fleet/run.py readers 5x20 --arm fleet-on    reader calls, stubbed models: free
    uv run --locked python -I bench/fleet/report.py                             writes bench/fleet/RESULTS.md

Arms: `fleet-on` and `fleet-off` are this checkout with POINTE_FLEET=on or off; `baseline` is another checkout
(--checkout, a worktree of the commit before the fleet work), which has no such switch.

Rules written before any paid row:
- The dataset is frozen (FROZEN.json); a run refuses to start when the files on disk are not the frozen ones.
- Where a send landed is read from the stand-ins' inboxes and from nothing else.
- A turn is watched from the moment its line is typed until the next line is typed; the next line waits until no
  model call is in flight and nothing has happened for QUIET_SECS (at most SETTLE_MAX_SECS, then the row says
  `unsettled` and is scored as it is).
- Every turn of a started run is a row. A turn that could not be driven is a row with `error`; a run that ended early
  writes a "crash" row and a row with `error` for each turn it did not reach. No row is deleted or run again.
- A row that began or ended with the 1-minute load over 20 keeps its routing outcome and loses its timings
  (score.LOAD_MAX); the report counts them.
- Turn order is shuffled by the run's seed (--seed + the run's number); the manifest has the seed and the order.
- Spend is computed from each model call's token counts at list price (prices.json) and written to
  results/ledger.jsonl after every launch, smoke runs included. A launch refuses to start unless the ledger's total
  plus --headroom-usd fits under --budget-usd, and stops typing turns once it has spent its headroom.
- A paid launch waits while the 1-minute load is over 15.
"""

import argparse
import ast
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import gen  # noqa: E402
import score  # noqa: E402
import sim  # noqa: E402
import turns as dataset  # noqa: E402

RESULTS = HERE / "results"
LEDGER = RESULTS / "ledger.jsonl"
PRICES = json.loads((HERE / "prices.json").read_text())
NOTES = HERE / "dataset-notes"
QUIET_SECS = 4.5  # past the 3 s after a send at which the daemon looks at the session's notes again
MIN_TURN_SECS = 3.0
SETTLE_MAX_SECS = 75.0
HEADROOM = {"1x4": 1.0, "2x3": 1.0, "5x20": 3.0, "10x30": 6.0}  # the most one paid launch may spend, by default
LOAD_WAIT_OVER = 15.0
ARMS = {"baseline": None, "fleet-on": "on", "fleet-off": "off"}


# ---------- spend ----------

def usd(call: dict) -> tuple[float, str]:
    """A model call's price at list, and how it was computed: from the vendor's own counts, or estimated from sizes."""
    model = call["choice"].split(":", 1)[1]
    p = PRICES["tokens"].get(model)
    if p is None:
        return 0.0, f"no price for {model}"
    m = 1e-6
    if call["kind"] == "text" and call.get("exact"):
        e = call["exact"]
        return (e.get("input", 0) * p["in"] + e.get("cache_read", 0) * p["cache_read"] + e.get("cache_write", 0) * p["cache_write"]
                + e.get("output", 0) * p["out"]) * m, "vendor counts"
    if call["kind"] == "step" and call.get("usage"):
        u = call["usage"]
        cached = u.get("cached", 0)
        # the daemon keeps the whole prompt and its cached part: the rest is priced as written to the cache, the
        # dearer of the two it can be
        return ((u.get("context", 0) - cached) * p["cache_write"] + cached * p["cache_read"] + u.get("reply", 0) * p["out"]) * m, "vendor counts"
    # failed, cancelled or not counted: the request's characters over 3 as input at full price, and a reply allowance
    out = (call.get("reply_chars", 0) / 3 + (PRICES["thinking_allowance_tokens"] if call.get("thinking") else 0)) if not call.get("error") else 0
    return (call.get("sent_chars", 0) / 3 * p["in"] + out * p["out"]) * m, "estimate from characters"


def priced(calls: list[dict]) -> dict:
    total, by = 0.0, {}
    for c in calls:
        if c["kind"] not in ("step", "text"):
            continue
        cost, how = usd(c)
        total += cost
        key = f"{c['choice']} {'brain' if c['kind'] == 'step' else c.get('caller', 'text')} ({how})"
        row = by.setdefault(key, {"calls": 0, "usd": 0.0, "tokens_in": 0, "tokens_out": 0})
        row["calls"] += 1
        row["usd"] = round(row["usd"] + cost, 6)
        row["tokens_in"] += (c.get("usage") or {}).get("context", 0) or (c.get("exact") or {}).get("input", 0)
        row["tokens_out"] += (c.get("usage") or {}).get("reply", 0) or (c.get("exact") or {}).get("output", 0)
    return {"usd": round(total, 6), "by": by}


def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    return sum(json.loads(line)["usd"] for line in LEDGER.read_text().splitlines() if line.strip())


def gate(cap: float, headroom: float) -> float:
    so_far = spent()
    if cap - so_far < headroom:
        raise SystemExit(f"${so_far:.2f} spent of ${cap:.2f}: a launch needs ${headroom:.2f} of headroom")
    return so_far


def record(row: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    with LEDGER.open("a") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **row}) + "\n")


def wait_for_load() -> float:
    for _ in range(120):
        load = os.getloadavg()[0]
        if load <= LOAD_WAIT_OVER:
            return load
        print(f"load {load:.1f}: waiting", flush=True)
        time.sleep(30)
    raise SystemExit("the 1-minute load stayed over 15 for an hour: not run")


# ---------- reading what the daemon wrote ----------

class Tail:
    """New complete lines of a file since the last look."""

    def __init__(self, path: Path):
        self.path, self.at, self.rest = path, 0, ""

    def lines(self) -> list[str]:
        if not self.path.exists():
            return []
        with self.path.open("r", errors="replace") as f:
            f.seek(self.at)
            data = f.read()
            self.at = f.tell()
        data = self.rest + data
        *whole, self.rest = data.split("\n")
        return whole


def spoken(line: str) -> str | None:
    """The reply in a daemon log line `speak: '...'` (one a reply, whole), or None."""
    if " - speak: " not in line:
        return None
    try:
        said = ast.literal_eval(line.split(" - speak: ", 1)[1].strip())
    except (ValueError, SyntaxError):
        return None
    return said if isinstance(said, str) else None


class Watch:
    """Everything that happens in a fleet, as it happens: deliveries, model calls, replies. poll() every POLL_SECS."""

    def __init__(self, fleet: sim.FleetSim):
        self.fleet = fleet
        self.calls, self.log = Tail(fleet.calls), Tail(fleet.voice.state.parent / f"{fleet.voice.name}.log")
        self.all_calls: list[dict] = []
        self.open: set[int] = set()
        self.needs: dict[str, int | None] = {}
        self.last = time.time()

    def poll(self) -> dict:
        now = time.time()
        got = {"deliveries": self.fleet.deliveries(), "calls": [], "said": []}
        for line in self.calls.lines():
            try:
                c = json.loads(line)
            except ValueError:
                continue
            if c["kind"] == "begin":
                self.open.add(c["n"])
            elif c["kind"] == "needs_tokens":
                self.needs[c["sha"]] = c["tokens"]
            else:
                self.open.discard(c.get("n"))
                got["calls"].append(c)
                self.all_calls.append(c)
        for line in self.log.lines():
            if (said := spoken(line)) is not None:
                got["said"].append({"at": now, "text": said})
        if got["deliveries"] or got["calls"] or got["said"]:
            self.last = now
        return got

    def quiet(self) -> bool:
        return not self.open and time.time() - self.last >= QUIET_SECS

    def settle(self, into: dict | None = None, least: float = 0.0, most: float = SETTLE_MAX_SECS) -> bool:
        """Poll until quiet (True) or `most` seconds (False), adding what happens to `into`."""
        began = time.time()
        while True:
            got = self.poll()
            if into is not None:
                for k in got:
                    into[k] += got[k]
            waited = time.time() - began
            if waited >= least and self.quiet():
                return True
            if waited >= most:
                return False
            time.sleep(sim.POLL_SECS)


# ---------- a launch ----------

def commit_of(checkout: Path) -> dict:
    git = lambda *a: subprocess.run(["git", "-C", str(checkout), *a], capture_output=True, text=True).stdout.strip()  # noqa: E731
    return {"commit": git("rev-parse", "HEAD"), "dirty_pointe": bool(git("status", "--porcelain", "--", "pointe"))}


class Launch:
    """One fleet brought up for one run: its folder in /tmp, its results folder, its spend."""

    def __init__(self, what: str, size: str, arm: str, models: str, checkout: Path, label: str = ""):
        assert arm in ARMS
        assert (arm == "baseline") == (checkout != ROOT), "baseline is another checkout (--checkout); the fleet arms are this one"
        self.what, self.size, self.arm, self.models, self.checkout = what, size, arm, models, checkout
        self.id = f"fleet-{time.strftime('%Y%m%d-%H%M%S')}-{what}-{size}-{arm}{'-stub' if models == 'stub' else ''}{label}"
        self.described = dataset.load(size)[0] if size in dataset.SIZES else gen.fleet(size)
        self.out = RESULTS / self.id
        self.root = Path(tempfile.mkdtemp(prefix="pfb-", dir="/tmp"))
        env = {"POINTE_FLEET": ARMS[arm]} if ARMS[arm] else {}
        notes = NOTES / arm / size if models == "real" else None
        self.fleet = sim.FleetSim(self.described, self.root / "f", models, env, notes, checkout)
        self.watch: Watch | None = None
        self.rows: list[dict] = []
        self.manifest = {"run": self.id, "what": what, "size": size, "arm": arm, "models": models,
                         "pointe": commit_of(checkout), "harness_commit": commit_of(ROOT)["commit"],
                         "fleet_sha256": self.described["sha256"], "dataset_sha256": dataset.dataset_sha(),
                         "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "load_start": os.getloadavg()[0],
                         "machine": f"{os.uname().machine}, {os.cpu_count()} cores"}

    def up(self) -> "Launch":
        f = self.fleet
        f.up()
        self.manifest["notes_restored"] = f.settle_notes()
        self.manifest["footprint_before_call"] = f.footprint()
        self.watch = Watch(f)
        f.open_call()
        f.start_states()
        # the reader reads now what it will read (every session with no notes on disk, or the ones the build chooses):
        # the first line waits until that is over
        self.watch.settle(least=8.0, most=300.0)
        noted = f.noted()
        if f.notes is not None and not f.notes.exists() and noted:
            f.save_notes()
        setup = [c for c in self.watch.all_calls]
        self.manifest.update(
            timing=f.timing, sessions_with_notes=len(noted), names=f.names(),
            notes_sha256=hashlib.sha256(json.dumps(noted, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            setup_calls={"reader": sum(c["kind"] == "text" for c in setup), "brain": sum(c["kind"] == "step" for c in setup)},
            setup_line=next((line.split("setup: ", 1)[1][:300] for line in f.voice.log(400_000).splitlines() if " setup: " in line), ""),
            footprint_call_up=f.footprint())
        return self

    def run_spend(self) -> float:
        return priced(self.watch.all_calls)["usd"] if self.watch else 0.0

    def write(self, row: dict) -> None:
        self.rows.append(row)
        self.out.mkdir(parents=True, exist_ok=True)
        text = json.dumps(row, ensure_ascii=False)
        assert str(Path.home()) not in text, "a home path in a row"
        with (self.out / "rows.jsonl").open("a") as f:
            f.write(text + "\n")

    def close(self, error: str = "") -> None:
        try:
            if self.watch is not None:
                self.watch.poll()
            self.manifest.update(ended=time.strftime("%Y-%m-%dT%H:%M:%S%z"), load_end=os.getloadavg()[0],
                                 footprint_end=self.fleet.footprint() if self.fleet.voice.proc else None, error=error)
        finally:
            self.fleet.close()
        calls = self.watch.all_calls if self.watch else []
        if not calls and self.fleet.calls.exists():  # a launch that died before it was watched still spent what it spent
            calls = [c for c in map(json.loads, self.fleet.calls.read_text().splitlines()) if c["kind"] in ("step", "text")]
        spend = priced(calls) if self.models == "real" else {"usd": 0.0, "by": {}}
        self.manifest["spend"] = spend
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "manifest.json").write_text(json.dumps(self.manifest, indent=1, ensure_ascii=False) + "\n")
        (self.out / "fleet.json").write_text(json.dumps(self.described, indent=1, ensure_ascii=False) + "\n")
        with (self.out / "calls.jsonl").open("w") as f:
            for c in calls:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        if self.models == "real":
            record({"launch": self.id, "what": self.what, "usd": spend["usd"], "calls": len(calls)})
        if error:
            (self.out / "voice-log-tail.txt").write_text(self.fleet.voice.log(20_000).replace(str(Path.home()), "~"))
        shutil.rmtree(self.root, ignore_errors=True)
        print(f"{self.id}: {len(self.rows)} rows, ${spend['usd']:.4f}{', ' + error if error else ''}", flush=True)


def launch(what: str, a, label: str = "") -> Launch:
    if a.models == "real":
        problems = dataset.check()
        if problems:
            raise SystemExit("; ".join(problems))
        gate(a.budget_usd, a.headroom_usd or HEADROOM[a.size])
        wait_for_load()
    return Launch(what, a.size, a.arm, a.models, Path(a.checkout).resolve() if a.checkout else ROOT, label)


# ---------- turns ----------

def turn_row(run: Launch, n: int, turn: dict, seed: int) -> dict:
    """Type one line and watch until the fleet is quiet again."""
    w = run.watch
    seen = {"deliveries": [], "calls": [], "said": []}
    row = {"kind": "turn", "run": run.id, "arm": run.arm, "size": run.size, "seed": seed, "order": n, "turn": turn["id"],
           "turn_kind": turn["kind"], "text": turn["text"], "expect": turn["expect"], "this_mac_holds": turn.get("this_mac_holds"),
           "load_start": os.getloadavg()[0], "error": None}
    w.poll()
    t0 = time.time()
    failed: list[str] = []

    def post() -> None:
        try:
            run.fleet.type(turn["text"])
        except Exception as e:
            failed.append(f"the line could not be typed: {type(e).__name__}: {str(e)[:200]}")

    typing = threading.Thread(target=post, daemon=True)
    typing.start()
    settled = w.settle(seen, least=MIN_TURN_SECS)
    typing.join(1)
    own, steps, mine = turn["text"].strip(), [], False
    for c in seen["calls"]:
        if c["kind"] != "step":
            continue
        answers = str(c.get("answers") or "")
        mine = answers.strip().endswith(own) or (mine and answers == "tool")
        steps.append({"model": c["choice"], "own": mine, "began_secs": round(c["began"] - t0, 3),
                      "first_token_secs": round(c["first"] - t0, 3) if c.get("first") else None,
                      "secs": round(c["ended"] - c["began"], 3), "input_tokens": (c.get("usage") or {}).get("context"),
                      "cached_tokens": (c.get("usage") or {}).get("cached"), "output_tokens": (c.get("usage") or {}).get("reply"),
                      "tools": [k["name"] for k in c.get("calls") or []], "error": c.get("error"),
                      "needs_sha": c.get("needs_sha"), "needs_chars": c.get("needs_chars")})
    owned = [s for s in steps if s["own"] and not s["error"]]
    first = owned[0] if owned else None
    if first and first["needs_sha"] and w.needs.get(first["needs_sha"]) is None:
        w.settle(least=0.5, most=3.0)  # the vendor's count of this block is on its way
    texts = [c for c in seen["calls"] if c["kind"] == "text"]
    reader = run.manifest.get("reader_model", "")
    row.update(
        t0=t0, settled=settled, secs=round(time.time() - t0, 2),
        deliveries=[{"session": d["session"], "secs": round(d["at"] - t0, 3), "text": d["text"][:300]} for d in seen["deliveries"]],
        said=[s["text"] for s in seen["said"]],
        first_said_secs=round(seen["said"][0]["at"] - t0, 3) if seen["said"] else None,
        steps=steps,
        first_token_secs=next((s["first_token_secs"] for s in owned if s["first_token_secs"] is not None), None),
        first_send_secs=round(seen["deliveries"][0]["at"] - t0, 3) if seen["deliveries"] else None,
        brain_input_tokens=sum(s["input_tokens"] or 0 for s in owned) or None,
        brain_input_first_step=first["input_tokens"] if first else None,
        needs_tokens=w.needs.get(first["needs_sha"]) if first and first["needs_sha"] else None,
        needs_chars=first["needs_chars"] if first else None,
        other_steps=sum(not s["own"] for s in steps),
        reader_calls=sum(c["choice"] == reader for c in texts), checker_calls=sum(c["choice"] != reader for c in texts),
        text_callers=sorted({c.get("caller", "") for c in texts}),
        load_end=os.getloadavg()[0])
    if failed:
        row["error"] = failed[0]
    elif not settled:
        row["unsettled"] = True
    return row


def cmd_turns(a) -> None:
    fleet, all_turns = dataset.load(a.size) if a.size in dataset.SIZES else (gen.fleet(a.size), dataset.turns(gen.fleet(a.size)))
    for r in range(1, a.runs + 1):
        seed = a.seed + r
        order = random.Random(seed).sample(all_turns, len(all_turns))[: a.limit or None]
        run = launch("turns", a, f"-r{r}")
        run.manifest.update(seed=seed, order=[t["id"] for t in order], limit=a.limit)
        headroom = a.headroom_usd or HEADROOM[a.size]
        error, done = "", 0
        try:
            run.up()
            run.manifest["reader_model"] = _role(run.manifest["setup_line"], "reader")
            for n, turn in enumerate(order):
                if run.models == "real" and run.run_spend() >= headroom:
                    error = f"stopped after {done} turns: this launch reached its spend limit of ${headroom:.2f}"
                    break
                row = turn_row(run, n, turn, seed)
                run.write(row)
                done += 1
                print(f"  {n + 1:2}/{len(order)} {turn['id']:26} {score.outcome(row):8} {len(row['deliveries'])} sent, "
                      f"in {row['brain_input_tokens']}, needs {row['needs_tokens']}, first {row['first_token_secs']}, "
                      f"${run.run_spend():.3f}", flush=True)
        except BaseException as e:
            error = f"{type(e).__name__}: {str(e)[:300]}".replace(str(Path.home()), "~")
            if not isinstance(e, Exception):
                raise
        finally:
            if error:
                run.write({"kind": "crash", "run": run.id, "arm": run.arm, "size": run.size, "error": error, "turns_done": done})
                for n, turn in enumerate(order[done:], start=done):
                    run.write({"kind": "turn", "run": run.id, "arm": run.arm, "size": run.size, "seed": seed, "order": n,
                               "turn": turn["id"], "turn_kind": turn["kind"], "text": turn["text"], "expect": turn["expect"],
                               "error": f"not run: {error}"})
            run.close(error)


def _role(setup_line: str, role: str) -> str:
    import re

    found = re.search(rf"{role}='([^']*)'", setup_line)
    return found.group(1) if found else ""


# ---------- the burst: many sessions end their turn within a minute ----------

def cmd_burst(a) -> None:
    run = launch("burst", a)
    error = ""
    try:
        run.up()
        w, f = run.watch, run.fleet
        due = sorted((s["finish_at"], s["id"]) for s in run.described["sessions"] if s["finish_at"] is not None)
        seen = {"deliveries": [], "calls": [], "said": []}
        t0, finals = time.time(), {}
        for at, sid in due:
            while time.time() - t0 < at:
                got = w.poll()
                for k in got:
                    seen[k] += got[k]
                time.sleep(sim.POLL_SECS)
            finals[sid] = f.sessions[sid].finish()
        settled = w.settle(seen, least=gen.BURST_SECS - (time.time() - t0) + 10, most=240.0)
        status = f.voice.status()
        context = f.voice.call("/voice/context")[1]
        fleet_view = context.get("fleet") if isinstance(context, dict) else None
        held = [str(item) for item in ((status.get("held") or {}).get("items") or [])]
        by_id = {s["id"]: s for s in run.described["sessions"]}
        said = " ".join(s["text"] for s in seen["said"])
        told = [sid for sid in finals if score.names(said, by_id[sid]["name"])]
        kept = [sid for sid in finals if sid not in told and any(score.names(h, by_id[sid]["name"]) for h in held)]
        row = {"kind": "burst", "run": run.id, "arm": run.arm, "size": run.size, "finished": sorted(finals),
               "window_secs": round(max(at for at, _ in due), 1), "watched_secs": round(time.time() - t0, 1), "settled": settled,
               "spoken": [s["text"] for s in seen["said"]], "spoken_at": [round(s["at"] - t0, 1) for s in seen["said"]],
               "held": held, "held_view": status.get("held"), "fleet_stats": (fleet_view or {}).get("stats"),
               "named_in_speech": len(told), "named_in_held": len(kept),
               "lost": sorted(sid for sid in finals if sid not in told and sid not in kept),
               "reader_calls": sum(c["kind"] == "text" and c.get("caller") in ("_read_model",) for c in seen["calls"]),
               "brain_steps": sum(c["kind"] == "step" for c in seen["calls"]), "load_end": os.getloadavg()[0], "error": None}
        run.write(row)
        print(f"  {len(finals)} finished: {len(row['spoken'])} spoken, {len(held)} held, {len(row['lost'])} lost", flush=True)
    except Exception as e:
        error = f"{type(e).__name__}: {str(e)[:300]}".replace(str(Path.home()), "~")
        run.write({"kind": "burst", "run": run.id, "arm": run.arm, "size": run.size, "finished": [], "spoken": [], "held": [],
                   "lost": [], "error": error})
    finally:
        run.close(error)


# ---------- reader calls: every session active, or 80% of them quiet ----------

READERS_SECS = 120.0
READERS_EVERY = 60.0  # an active session ends a turn this often


def cmd_readers(a) -> None:
    """With stubbed models: how often the daemon calls the reader is the daemon's decision, not a model's."""
    assert a.models == "stub", "reader calls are counted with stubbed models"
    for scenario, active_share in (("all_active", 1.0), ("quiet_80", 0.2)):
        run = launch("readers", a, f"-{scenario}")
        error = ""
        try:
            run.up()
            w, f = run.watch, run.fleet
            ids = sorted(f.sessions)
            active = random.Random(a.seed).sample(ids, max(1, round(len(ids) * active_share)))
            rng = random.Random(a.seed + 1)
            due = sorted((rng.uniform(0, READERS_EVERY) + k * READERS_EVERY, sid) for sid in active
                         for k in range(int(READERS_SECS // READERS_EVERY)))
            seen = {"deliveries": [], "calls": [], "said": []}
            t0 = time.time()
            for at, sid in due:
                while time.time() - t0 < at:
                    got = w.poll()
                    for k in got:
                        seen[k] += got[k]
                    time.sleep(0.05)
                f.sessions[sid].tool("Bash", command="pytest -q")
                f.sessions[sid].finish()
            w.settle(seen, least=READERS_SECS - (time.time() - t0) + 5, most=READERS_SECS + 90)
            calls = sum(c["kind"] == "text" and c["choice"] == _role(run.manifest["setup_line"], "reader") for c in seen["calls"])
            context = f.voice.call("/voice/context")[1]
            run.write({"kind": "readers", "run": run.id, "arm": run.arm, "size": run.size, "scenario": scenario, "models": "stubbed",
                       "active_sessions": len(active), "sessions": len(ids), "turns_ended": len(due), "window_secs": READERS_SECS,
                       "reader_calls": calls, "per_hour": calls * 3600 / READERS_SECS,
                       "callers": sorted({c.get("caller", "") for c in seen["calls"] if c["kind"] == "text"}),
                       "fleet_stats": (context.get("fleet") or {}).get("stats") if isinstance(context, dict) else None, "error": None})
            print(f"  {scenario}: {calls} reader calls for {len(due)} ended turns", flush=True)
        except Exception as e:
            error = f"{type(e).__name__}: {str(e)[:300]}".replace(str(Path.home()), "~")
            run.write({"kind": "readers", "run": run.id, "arm": run.arm, "size": run.size, "scenario": scenario, "error": error})
        finally:
            run.close(error)


# ---------- the simulator alone ----------

def cmd_up(a) -> None:
    """Bring a fleet up with stubbed models, hold a call for a minute, and say what it cost this machine."""
    run = Launch("up", a.size, a.arm, "stub", Path(a.checkout).resolve() if a.checkout else ROOT)
    error = ""
    try:
        began = time.monotonic()
        run.up()
        run.manifest["up_secs"] = round(time.monotonic() - began, 1)
        seen = run.fleet.machines_seen()
        want = {s["id"]: s["machine"] for s in run.described["sessions"]}
        first = run.fleet.footprint()
        time.sleep(a.hold)
        last = run.fleet.footprint()
        run.write({"kind": "sim", "run": run.id, "size": a.size, "arm": a.arm, "sessions": len(want),
                   "on_their_machine": sum(seen.get(k) == v for k, v in want.items()), "up_secs": run.manifest["up_secs"],
                   "timing": run.fleet.timing, "hold_secs": a.hold, "processes": 1 + last["nodes"] + 1,
                   "voice_rss_mb": last["voice"]["rss_mb"], "nodes_rss_mb": last["nodes_rss_mb"], "runner_rss_mb": last["runner"]["rss_mb"],
                   "voice_cpu_share": round((last["voice"]["cpu_secs"] - first["voice"]["cpu_secs"]) / a.hold, 3),
                   "nodes_cpu_share": round((last["nodes_cpu_secs"] - first["nodes_cpu_secs"]) / a.hold, 3),
                   "runner_cpu_share": round((last["runner"]["cpu_secs"] - first["runner"]["cpu_secs"]) / a.hold, 3),
                   "load": os.getloadavg()[0]})
        print(json.dumps(run.rows[-1], indent=1))
    except Exception as e:
        error = f"{type(e).__name__}: {str(e)[:300]}"
        raise
    finally:
        run.close(error)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["up", "turns", "burst", "readers"])
    ap.add_argument("size", choices=sorted(gen.SIZES))
    ap.add_argument("--arm", choices=sorted(ARMS), default="fleet-on")
    ap.add_argument("--checkout", help="the Pointe checkout of the baseline arm")
    ap.add_argument("--models", choices=["real", "stub"], default=None)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--seed", type=int, default=gen.SEED)
    ap.add_argument("--limit", type=int, default=0, help="only the first N turns of the shuffled order (a smoke run)")
    ap.add_argument("--budget-usd", type=float, default=15.0)
    ap.add_argument("--headroom-usd", type=float, default=0.0)
    ap.add_argument("--hold", type=float, default=60.0)
    a = ap.parse_args()
    a.models = a.models or ("stub" if a.command in ("up", "readers") else "real")
    {"up": cmd_up, "turns": cmd_turns, "burst": cmd_burst, "readers": cmd_readers}[a.command](a)
