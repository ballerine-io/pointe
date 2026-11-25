"""The scored conversation suite: one command runs it, with a cost ledger.

  uv run --locked --extra local python bench/conversational/dialogues/run.py corpus                 # render the speech
  uv run --locked --extra local python bench/conversational/dialogues/run.py run --arm pointe,llm-router --budget-usd 150
        [--only 'lat-*'] [--port-base 9800] [--workers 2] [--label before]
  uv run --locked --extra local python bench/conversational/dialogues/run.py score <run-id>[,<run-id>...] [...]
  uv run --locked --extra local python bench/conversational/dialogues/run.py judge <run-id> [--judge openai:gpt-6-sol]

Ports 9800-9899 only (never 7860/7443); every state folder under /tmp; keys from the Keychain or the environment into
the one process that needs them. Results: results/<run-id>/rows.jsonl (scrubbed), results/ledger.jsonl (spend).
"""

import argparse
import asyncio
import fnmatch
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))

MAX_RUN = 0.90  # the most one dialogue on one arm may cost, for the budget gate
BENCH = "dialogues"
MAX_LOAD = 20.0  # no scored dialogue starts while the 1-minute load is above this


def key(env_name: str, item: str) -> str | None:
    if os.environ.get(env_name):
        return os.environ[env_name]
    for name in (f"pointe.{item}", item):
        got = subprocess.run(["security", "find-generic-password", "-s", name, "-w"], capture_output=True, text=True)
        if got.returncode == 0 and got.stdout.strip():
            return got.stdout.strip()
    return None


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def product(commit: str) -> Path:
    """Pointe under test: a pristine export of a commit under /tmp with its own environment, so the daemon's own
    `uv sync` never touches this checkout's environment."""
    target = Path("/tmp/pccb-dlg") / f"pointe-{commit[:12]}"
    if not (target / ".ready").exists():
        target.mkdir(parents=True, exist_ok=True)
        archive = subprocess.run(["git", "-C", str(ROOT), "archive", commit], capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", str(target)], input=archive, check=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("VIRTUAL_ENV", "UV_PROJECT"))}
        subprocess.run(["uv", "sync", "--locked", "--quiet", "--project", str(target)], check=True, env=env,
                       capture_output=True, timeout=900)
        (target / ".ready").write_text(commit + "\n")
    return target


def corpus_cmd(args) -> int:
    from core import corpus
    from dialogues import spec
    lock = {}
    for d in spec.load(Path(args.suite)) if args.suite else spec.load():
        for t in d.turns:
            path = corpus.render(t.voice or d.voice, t.say, t.noise)
            lock[path.name] = corpus.sha(path)
    if not args.suite:
        corpus.LOCK.write_text(json.dumps(lock, indent=1, sort_keys=True) + "\n")
    print(f"{len(lock)} clips rendered; audio.lock written")
    return 0


async def run_all(jobs: list, ctx: dict, workers: int, port_base: int, cap: float, out: Path) -> None:
    from core import ledger
    from dialogues import play
    queue = list(jobs)

    async def worker(k: int):
        port = port_base + 4 * k
        assert 9800 <= port <= 9898, "ports 9800-9899 only"
        while queue:
            d, arm = queue.pop(0)
            try:
                ledger.gate(cap, 1, MAX_RUN, BENCH)
            except ledger.BudgetRefused as e:
                print(f"budget: {e}", flush=True)
                queue.clear()
                return
            while os.getloadavg()[0] > MAX_LOAD:  # a loaded machine measures itself, not the arm: wait it out
                print(f"[{k}] load {os.getloadavg()[0]:.1f} > {MAX_LOAD:.0f}: waiting", flush=True)
                await asyncio.sleep(30)
            t = time.time()
            row = await play.run(d, arm, ctx, port)
            with out.open("a") as f:
                f.write(play.dump(row) + "\n")
            ledger.append({"benchmark": BENCH, "run_id": ctx["run_id"], "item": d.id, "arm": arm, "kind": ctx["kind"],
                           "usd": row["spend_usd"], "label": ctx["label"], "load_avg": row.get("load_avg"),
                           "load_avg_end": round(os.getloadavg()[0], 2)})
            print(f"[{k}] {d.id} {arm}: {time.time() - t:.0f} s, ${row['spend_usd']:.3f}"
                  f"{'  ERROR ' + row['error'] if row.get('error') else ''}", flush=True)

    await asyncio.gather(*(worker(k) for k in range(workers)))


def run_cmd(args) -> int:
    from core import ledger
    from dialogues import play, spec
    sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
    import vendors
    arms = args.arm.split(",")
    loaded = spec.load(Path(args.suite)) if args.suite else spec.load()
    suite = [d for d in loaded if not args.only or any(fnmatch.fnmatch(d.id, g) for g in args.only.split(","))]
    jobs = [(d, a) for d in suite for a in arms]
    run_id = args.run_id or f"dlg-{time.strftime('%Y%m%d-%H%M%S')}-{args.label}"
    out = HERE / "results" / run_id
    out.mkdir(parents=True, exist_ok=True)
    api_key = key("ANTHROPIC_API_KEY", "anthropic-api-key")
    keys = {"anthropic": api_key, "soniox": key("SONIOX_API_KEY", "soniox-api-key")}
    if not api_key or not keys["soniox"]:
        raise SystemExit("an Anthropic and a Soniox key are needed")
    play.guard_bin()
    commit = git("rev-parse", f"{args.commit or 'HEAD'}^{{commit}}")  # a tag names its commit, not the tag object
    dirty = False if args.commit else bool(git("status", "--porcelain", "--", ".", ":!bench", ":!tests", ":!docs"))
    if dirty and "pointe" in arms:
        raise SystemExit("commit Pointe's changes first: the Pointe arm runs a pristine export of HEAD")
    ctx = {"run_id": run_id, "api_key": api_key, "keys": keys, "pointe": product(commit) if "pointe" in arms else ROOT, "brain": vendors.BRAIN_ORDER[0],
           "soniox_model": vendors.SONIOX_RT_MODEL, "errors": [], "kind": "debug" if args.debug else "paid",
           "label": args.label, "pointe_commit": commit, "pointe_dirty": dirty}
    (out / "run.json").write_text(json.dumps({"run_id": run_id, "arms": arms, "dialogues": [d.id for d in suite],
                                              "pointe_commit": commit, "pointe_dirty": dirty, "label": args.label,
                                              "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, indent=1) + "\n")
    print(f"{run_id}: {len(jobs)} runs, spent so far ${ledger.spent(BENCH):.2f} of ${args.budget_usd:.2f}", flush=True)
    asyncio.run(run_all(jobs, ctx, args.workers, args.port_base, args.budget_usd, out / "rows.jsonl"))
    if ctx["errors"]:
        (out / "errors.txt").write_text("\n\n".join(ctx["errors"]))
    print(f"done: {run_id}; spent ${ledger.spent(BENCH):.2f}", flush=True)
    return 0


def load_rows(run_ids: list) -> list:
    rows = []
    for rid in run_ids:
        path = HERE / "results" / rid / "rows.jsonl"
        rows += [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    return rows


def score_cmd(args) -> int:
    from dialogues import score
    results = {}
    for group in args.run_ids:
        rows = load_rows(group.split(","))
        latest = {}
        for r in rows:  # a later row of the same dialogue and arm replaces an earlier one
            latest[(r["dialogue"], r["arm"])] = r
        for arm in sorted({a for _, a in latest}):
            mine = [r for (d, a), r in latest.items() if a == arm]
            judge = None
            # The newest run of the group that was judged: a re-run of a few dialogues may have no judge file.
            for rid in reversed(group.split(",")):
                jpath = HERE / "results" / rid / f"judge-{arm}.json"
                if jpath.exists():
                    judge = json.loads(jpath.read_text())
                    break
            results[f"{arm}@{group.split(',')[-1][-14:]}"] = score.metrics(mine, judge)
    print(score.table(results))
    if args.turns:
        for label, m in results.items():
            print(f"\n## {label}")
            for t in m["turn_rows"]:
                print(json.dumps({k: t.get(k) for k in ("dialogue", "i", "kind", "ok", "ttfw", "ttua", "words",
                                                        "delivered_to", "confirmation", "talk_over", "barge_stop")}),
                      "|", (t["text"] or "")[:160])
    return 0


def report_cmd(args) -> int:
    """RESULTS.md from labelled run groups: `report baseline=<ids> before=<ids> after=<ids>`. Each group is scored per arm
    (the latest row of each dialogue counts), with its judge file when there is one."""
    from core import ledger
    from dialogues import score
    results = {}
    for spec_ in args.run_ids:
        label, _, ids = spec_.partition("=")
        rows = load_rows(ids.split(","))
        latest = {}
        for r in rows:
            latest[(r["dialogue"], r["arm"])] = r
        for a in sorted({a for _, a in latest}):
            mine = [r for (d, x), r in latest.items() if x == a]
            jpath = HERE / "results" / ids.split(",")[-1] / f"judge-{a}.json"
            judge = json.loads(jpath.read_text()) if jpath.exists() else None
            results[f"{label} ({a})"] = score.metrics(mine, judge)
    lines = ["<!-- Written by bench/conversational/dialogues/run.py report from the committed rows. -->", "",
             "# Conversation quality suite: results", "",
             f"Runs: {', '.join(args.run_ids)}. Rubric and targets: [RUBRIC.md](RUBRIC.md). Synthetic speech only.", "",
             score.table(results), "",
             f"Spend on this suite, every launch: ${ledger.spent('dialogues'):.2f} (computed from usage and list prices)."]
    (HERE / "RESULTS.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


def main(argv: list) -> int:
    p = argparse.ArgumentParser(prog="run.py")
    p.add_argument("command", choices=["corpus", "run", "score", "judge", "report", "human"])
    p.add_argument("run_ids", nargs="*")
    p.add_argument("--arm", default="pointe,llm-router")
    p.add_argument("--only", default=None, help="comma list of globs over dialogue ids")
    p.add_argument("--budget-usd", type=float, default=150.0)
    p.add_argument("--port-base", type=int, default=9800)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--label", default="run")
    p.add_argument("--run-id", default=None)
    p.add_argument("--debug", action="store_true")
    p.add_argument("--suite", default=None, help="another dialogues file in the same format (a tester's own dialogues)")
    p.add_argument("--commit", default=None, help="the Pointe commit to run (default HEAD, which must be clean)")
    p.add_argument("--turns", action="store_true")
    p.add_argument("--judge", default="anthropic:claude-fable-5-1", help="judge: vendor:model (anthropic or openai)")
    args = p.parse_args(argv)
    if args.command == "corpus":
        return corpus_cmd(args)
    if args.command == "run":
        return run_cmd(args)
    if args.command == "score":
        return score_cmd(args)
    if args.command == "report":
        return report_cmd(args)
    if args.command == "human":  # fetch the recorded-human clips (checked against a SHA-256) and write human.toml
        from dialogues import human
        return human.main()
    if args.command == "judge":
        from dialogues import judge
        return judge.main(args.run_ids, args.arm, args.judge)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
