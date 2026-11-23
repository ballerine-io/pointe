"""Pointe Conversational Coding Benchmarks: the one command.

    uv run --locked python bench/conversational/run.py hlk --budget-usd 55     # Humanity's Last Keystroke, every arm
    uv run --locked python bench/conversational/run.py hlk --adapter pointe --smoke
    uv run --locked python bench/conversational/run.py corpus                  # render the synthetic speech, $0
    uv run --locked python bench/conversational/run.py verify                  # offline: items, checks, detector, results
    uv run --locked python bench/conversational/run.py freeze                  # write FROZEN.json before paid runs
    uv run --locked python bench/conversational/run.py report                  # rows -> docs and site page

Options: --adapter keyboard,null,naive,llm-router,pointe  --budget-usd N  --port-base N (never 7860 or 7443)
--workers N  --smoke (2 items, never published)  --dry-run (the plan and its estimated cost, spends nothing)
--items GLOB  --unpublished PATH (the private seed list; scores only are committed)  --runs N

Keys come from the environment or the macOS Keychain and go only to the one process that needs them: the agent's
Anthropic key into each agent's environment; Soniox and Anthropic keys to the router's and naive arm's own calls; the
Pointe daemon reads its own.
"""

import argparse
import asyncio
import fnmatch
import hashlib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from core import corpus, ledger, runner  # noqa: E402
import hlk  # noqa: E402

FROZEN = HERE / "FROZEN.json"
ORDER_SEED = 20261123
ESTIMATE = {"keyboard-canonical": 0.10, "keyboard-transcript": 0.10, "pointe": 0.25, "llm-router": 0.13, "naive": 0.11,
            "null": 0.0}
ALIASES = {"keyboard": ["keyboard-canonical", "keyboard-transcript"]}


def arms_from(text: str | None) -> list:
    if not text:
        return list(runner.ARMS)
    out = []
    for a in text.split(","):
        out += ALIASES.get(a.strip(), [a.strip()])
    bad = [a for a in out if a not in runner.ARMS and a != "echo"]
    if bad:
        raise SystemExit(f"unknown adapter: {bad}")
    return out


def unpublished(path: str | None) -> tuple[list, str | None]:
    """The unpublished seeds (an overfit check, not a held-out split): kept outside the repository; only the SHA-256 of
    the manifest and the scores are committed."""
    if not path:
        return [], None
    data = Path(path).read_bytes()
    seeds = json.loads(data)
    insts = [hlk.instance(f, s) for f, s in seeds["seeds"]]
    return insts, hashlib.sha256(data).hexdigest()


def rerun_jobs(run_id: str, insts: list) -> list:
    """The rows of run_id that hit a harness fault (core.runner.prompt_without_hook, recorded in the row or, for a run
    made before the row carried it, in faults.json), as jobs to run once more with the same voice and run index."""
    out = HERE / "results" / run_id
    faults = set(json.loads((out / "faults.json").read_text())["slots"]) if (out / "faults.json").exists() else set()
    by_id = {(i.id if i.seed in hlk.PUBLIC_SEEDS else f"{i.family}-unpublished"): i for i in insts}
    jobs = []
    for line in (out / "rows.jsonl").read_text().splitlines():
        r = json.loads(line)
        slot = f"{r['item']}-{r['adapter']}-{r['run_index']}"
        if r.get("harness_fault") or slot in faults:
            inst = by_id[r["item"]]
            jobs.append(runner.Job(inst, r["adapter"], r["run_index"], r["kind"],
                                   runner.voice_for(inst, ORDER_SEED if r["kind"] == "paid" else ORDER_SEED + 1), run_id))
    return jobs


def ctx_for(args, run_id: str, out: Path) -> dict:
    pointe = Path(args.pointe).resolve() if args.pointe else ROOT
    api_key = runner.key("ANTHROPIC_API_KEY", "anthropic-api-key")
    if not api_key:
        raise SystemExit("no Anthropic API key in the environment or the Keychain")
    keys = {"anthropic": api_key, "soniox": runner.key("SONIOX_API_KEY", "soniox-api-key")}
    present = {v for v, item in (("anthropic", "anthropic-api-key"), ("gemini", "gemini-api-key"),
                                 ("openai", "openai-api-key"), ("soniox", "soniox-api-key"),
                                 ("elevenlabs", "elevenlabs-api-key")) if runner.keychain(item)}
    from adapters.llm_router import default_brain
    sys.path.insert(0, str(pointe))
    import vendors
    return {"run_id": run_id, "out": out, "api_key": api_key, "keys": keys, "pointe": pointe,
            "brain": default_brain(pointe, present), "soniox_model": vendors.SONIOX_RT_MODEL,
            "claude_version": runner.claude_version(), "repo_commit": runner.git("rev-parse", "HEAD"),
            "pointe_commit": runner.git("rev-parse", "HEAD", cwd=pointe), "errors": [], "present_keys": sorted(present)}


def cmd_hlk(args) -> int:
    arms = arms_from(args.adapter)
    for p in (args.port_base, args.port_base + 2 * args.workers):
        if p in runner.FORBIDDEN_PORTS or any(x in runner.FORBIDDEN_PORTS for x in range(args.port_base, p + 2)):
            raise SystemExit("the port range includes 7860 or 7443: never")
    insts = hlk.public()
    if args.items:
        insts = [i for i in insts if any(fnmatch.fnmatch(i.id, g) for g in args.items.split(","))]
    kind = "debug" if args.debug else "smoke" if args.smoke else "paid"
    runs = {a: (1 if a == "null" else args.runs) for a in arms}
    if args.smoke and not args.items:
        insts = [i for i in insts if i.id in ("dictated-literals-0", "two-repo-handoff-1")]
    if args.smoke or args.debug:
        runs = {a: 1 for a in arms}
    jobs = runner.plan(insts, arms, ORDER_SEED, kind, runs)
    extra, manifest_sha = unpublished(args.unpublished)
    if args.rerun_faults:
        jobs = rerun_jobs(args.rerun_faults, insts + extra)
        extra = []
    if extra:
        jobs += runner.plan(extra, [a for a in arms if a in ("keyboard-canonical", "pointe")], ORDER_SEED + 1,
                            "unpublished", {"keyboard-canonical": 1, "pointe": 1})
    est = sum(ESTIMATE.get(j.arm, 0.1) for j in jobs)
    print(f"plan: {len(jobs)} item runs, {len(insts)} public instances, arms {arms}; planning estimate ${est:.2f} "
          f"(not measured); hlk spent so far ${ledger.spent('hlk'):.2f} of ${args.budget_usd:.2f}")
    if args.dry_run:
        for j in jobs[:40]:
            print(f"  {j.inst.id if j.kind != 'unpublished' else j.inst.family + '-unpublished'} {j.arm}#{j.run_index} {j.voice}")
        return 0
    if kind == "paid":
        frozen = json.loads(FROZEN.read_text()) if FROZEN.exists() else None
        if not frozen:
            raise SystemExit("FROZEN.json is missing: commit it (run.py freeze) before the first non-smoke paid row")
        if runner.git("log", "-1", "--format=%H", "--", str(FROZEN.relative_to(ROOT))) == "":
            raise SystemExit("FROZEN.json is not committed")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_id = f"hlk-{kind + '-' if kind != 'paid' else ''}{stamp}"
    out = HERE / "results" / run_id
    out.mkdir(parents=True, exist_ok=True)
    ctx = ctx_for(args, run_id, out)
    from core import scrub
    scrub.REPLACE += [(str(ctx["pointe"]), "<pointe>"), (str(ROOT), "<repo>")]
    if kind == "paid" and ctx["pointe_commit"] != json.loads(FROZEN.read_text())["pointe_commit"]:
        raise SystemExit("the Pointe checkout is not at the frozen commit")
    print("preflight ...", flush=True)
    pre = runner.preflight(ctx["api_key"], Path("/tmp/pccb") / run_id)
    ledger.append({"benchmark": "hlk", "run_id": run_id, "kind": "preflight", "usd": pre.get("probe_cost_usd") or 0.0})
    print(json.dumps({k: v for k, v in pre.items() if k != "plugins"}), flush=True)
    if not pre["ok"]:
        print("preflight failed: stopping, never falling back to the owner's login")
        return 2
    runner.guard_bin()
    meta = {"run_id": run_id, "benchmark": "hlk", "kind": kind, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "arms": arms, "workers": args.workers, "order_seed": ORDER_SEED, "budget_usd": args.budget_usd,
            "agent_model": runner.AGENT_MODEL, "permission_mode": runner.PERMISSION_MODE,
            "claude_code_version": ctx["claude_version"], "pointe_commit": ctx["pointe_commit"],
            "repo_commit": ctx["repo_commit"], "router_brain": ctx["brain"], "ears_model": f"soniox:{ctx['soniox_model']}",
            "scoring_recognizer": f"mlx-community/whisper-large-v3-turbo@{runner.Whisper.revision()}",
            "keys_present": ctx["present_keys"], "preflight": {k: v for k, v in pre.items() if k != "plugins"},
            "unpublished_manifest_sha256": manifest_sha, "jobs": len(jobs),
            "cost_limit_per_run": runner.COST_LIMIT, "planning_estimate_usd": round(est, 2)}
    (out / "run.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    rows = asyncio.run(runner.run_all(jobs, ctx, args.workers, args.port_base, args.budget_usd))
    meta.update(finished=time.strftime("%Y-%m-%dT%H:%M:%S%z"), rows=len(rows), stopped=ctx.get("stopped"),
                errors=len(ctx["errors"]), spent_usd=round(sum(r.get("spend_usd", 0) for r in rows), 4))
    (out / "run.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    if ctx["errors"]:
        (Path("/tmp/pccb") / f"{run_id}-errors.txt").write_text("\n\n".join(ctx["errors"]))
        print(f"{len(ctx['errors'])} errors, tracebacks in /tmp/pccb/{run_id}-errors.txt")
    print(f"done: {len(rows)} rows, ${meta['spent_usd']:.2f}; hlk ledger ${ledger.spent('hlk'):.2f}")
    return 0


def cmd_corpus(args) -> int:
    """Every utterance of every public instance in its drawn voice, the common lines in all four voices, and the
    question-detector set, with audio.lock holding the SHA-256 of every clip."""
    lock = {}
    insts = hlk.public()
    extra, _ = unpublished(args.unpublished)
    todo = []
    for inst in insts + extra:
        v = runner.voice_for(inst, ORDER_SEED if inst in insts else ORDER_SEED + 1)
        todo += [(v, text, noise) for _, text, noise in inst.utterances()]
    from core import detector
    todo += [(v, text, None) for (text, _), v in zip(detector.LABELLED, [corpus.panel()[i % 4] for i in range(len(detector.LABELLED))])]
    todo = sorted(set(todo), key=lambda x: (x[0], x[1], x[2] or ""))
    t0 = time.time()
    for i, (v, text, noise) in enumerate(todo):
        p = corpus.render(v, text, noise)
        if not (extra and any(text == t for inst in extra for _, t, _ in inst.utterances())):
            lock[p.name] = corpus.sha(p)
        if i % 25 == 0:
            print(f"  {i}/{len(todo)} clips, {time.time() - t0:.0f} s", flush=True)
    corpus.LOCK.write_text(json.dumps(lock, indent=0, sort_keys=True) + "\n")
    print(f"{len(todo)} clips in {corpus.AUDIO.relative_to(ROOT)}; audio.lock has {len(lock)} hashes")
    return 0


def cmd_freeze(args) -> int:
    _, manifest = unpublished(args.unpublished)
    pointe = Path(args.pointe).resolve() if args.pointe else ROOT
    prompt = HERE / "adapters" / "llm_router_prompt.txt"
    frozen = {"benchmark": "hlk", "pointe_commit": runner.git("rev-parse", "HEAD", cwd=pointe),
              "llm_router_prompt_commit": runner.git("log", "-1", "--format=%H", "--", str(prompt.relative_to(ROOT))),
              "llm_router_prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
              "unpublished_manifest_sha256": manifest, "item_order_seed": ORDER_SEED,
              "claude_code_version": runner.claude_version(), "agent_model": runner.AGENT_MODEL,
              "instances_sha256": hashlib.sha256("".join(i.digest() for i in hlk.public()).encode()).hexdigest(),
              "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    FROZEN.write_text(json.dumps(frozen, indent=1, sort_keys=True) + "\n")
    print(json.dumps(frozen, indent=1))
    return 0


def cmd_faults(args) -> int:
    """Apply the harness-fault rules (core.runner.harness_fault) to a finished run whose rows predate the field, from
    the agents' hook logs left in /tmp/pccb/<run>/, and write results/<run>/faults.json."""
    from datetime import datetime
    run_id = args.rerun_faults
    out = HERE / "results" / run_id
    slots, reasons = [], {}
    for line in (out / "rows.jsonl").read_text().splitlines():
        r = json.loads(line)
        slot_name = f"{r['item']}-{r['adapter']}-{r['run_index']}"
        disk = Path(f"/tmp/pccb/{run_id}")
        found = [p for p in disk.glob(f"*-{r['adapter']}-{r['run_index']}") if p.name == slot_name or
                 (r["kind"] == "unpublished" and p.name.startswith(r["family"] + "-") and not p.name[len(r["family"]) + 1:].split("-")[0] in ("0", "1", "2"))]
        if not found:
            continue
        ended = datetime.strptime(r["time"], "%Y-%m-%dT%H:%M:%S%z").timestamp() + (r.get("wall_secs") or 0)
        why = runner.harness_fault(found[0], ended, r.get("approvals"))
        if why:
            slots.append(slot_name)
            reasons[slot_name] = why
    (out / "faults.json").write_text(json.dumps({"rule": "core.runner.harness_fault", "slots": sorted(slots),
                                                 "reasons": reasons}, indent=1, sort_keys=True) + "\n")
    print(f"{len(slots)} rows hit a harness fault: {reasons}")
    return 0


def cmd_verify(args) -> int:
    from core import verify
    return verify.main(args)


def cmd_report(args) -> int:
    from core import report
    return report.main(args)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["hlk", "all", "corpus", "verify", "freeze", "report", "faults"])
    ap.add_argument("--adapter")
    ap.add_argument("--budget-usd", type=float, default=55.0)
    ap.add_argument("--port-base", type=int, default=7900)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--debug", action="store_true", help="adapter debugging: rows go to the ledger as debug, never published")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--items")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--rerun-faults", metavar="RUN_ID", help="rerun once the rows of RUN_ID that hit a harness fault")
    ap.add_argument("--unpublished", default=os.environ.get("HLK_UNPUBLISHED_SEEDS"))
    ap.add_argument("--pointe", default=os.environ.get("HLK_POINTE_CHECKOUT"), help="the Pointe checkout under test")
    ap.add_argument("--fast", action="store_true", help="verify: skip the Kokoro and Whisper detector check")
    args = ap.parse_args()
    if args.command in ("hlk", "all"):
        return cmd_hlk(args)
    return {"corpus": cmd_corpus, "verify": cmd_verify, "freeze": cmd_freeze, "report": cmd_report,
            "faults": cmd_faults}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
