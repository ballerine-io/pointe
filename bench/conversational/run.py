"""Pointe Conversational Coding Benchmarks: the one command (design 4.1). This build carries `identifiers`.

    uv run --locked python bench/conversational/run.py identifiers --budget-usd 12 [--adapter a,b] [--smoke] [--dry-run]
    uv run --locked python bench/conversational/run.py corpus [identifiers]     render the audio, $0
    uv run --locked python bench/conversational/run.py verify                   offline: items, checks, decoys
    uv run --locked python bench/conversational/run.py report <run-id>          rows -> summary.json and summary.md
    uv run --locked python bench/conversational/run.py freeze                   write FROZEN.json (before paid rows)

Options: --adapter keyboard-canonical,keyboard-transcript,null,naive,llm-router,pointe,pointe-text (default: all),
--budget-usd N, --port-base N (default 9400; never 7860 or 7443), --workers N (default 3), --resume <run-id>,
--items t01,t02, --smoke (2 targets, flagged, never published), --dry-run (the plan and its estimated cost).
The corpus needs the `local` extra (Kokoro); `run.py identifiers` builds it through `uv run --locked --extra local`
when it is missing.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]

from core import agent, keys, ledger, runner  # noqa: E402
from identifiers import bench, check  # noqa: E402

FROZEN = HERE / "FROZEN.json"
MODEL = "claude-haiku-5-5"
MODE = "acceptEdits"
EST = {"keyboard-canonical": 0.03, "keyboard-transcript": 0.03, "null": 0.0, "naive": 0.035, "llm-router": 0.045,
       "pointe": 0.07, "pointe-text": 0.065}  # planning figures (design 5.2), not measured
MAX_RUN_USD = 0.25


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def corpus(build_missing_only: bool = False) -> None:
    from core import corpus as c

    clips = bench.clip_plan()
    if build_missing_only and all((c.AUDIO / bench.BENCH / f"{x['name']}.pcm").exists() for x in clips) \
            and c.matches_lock(bench.BENCH, bench.LOCK):
        return
    hashes = c.build(clips, bench.BENCH)
    lock = {"bench": bench.BENCH, "seed": bench.SEED, "kokoro": "kokoro-v1.0.onnx + voices-v1.0.bin (assets.py)",
            "rate": c.RATE, "clips": hashes}
    if bench.LOCK.exists() and json.loads(bench.LOCK.read_text())["clips"] != hashes:
        print("note: the rebuilt audio differs from audio.lock; runs record audio_matches_lock: false")
        return
    bench.LOCK.write_text(json.dumps(lock, indent=1, sort_keys=True) + "\n")
    print(f"{len(hashes)} clips, audio.lock written")


def ensure_corpus() -> None:
    from core import corpus as c

    if all((c.AUDIO / bench.BENCH / f"{x['name']}.pcm").exists() for x in bench.clip_plan()):
        return
    subprocess.run(["uv", "run", "--locked", "--extra", "local", "python", "-I", str(HERE / "run.py"), "corpus"],
                   cwd=runner.REPO_ROOT, check=True)


def verify() -> int:
    it = check.load_items()
    canary = (HERE / "CANARY").read_text().strip()
    assert it["canary"] == canary and canary in (HERE / "identifiers" / "items.toml").read_text()
    check.anchor_index(it)
    bad = [t for t in it["targets"] if not check.qualifying_decoys(it, t)]
    assert not bad, f"targets without a decoy at distance <= 2: {bad}"
    assert len(it["targets"]) == 24 and len(bench.clip_plan()) == 96
    print(f"identifiers: 24 targets, {len(it['symbols'])} symbols, every target has a qualifying decoy; "
          f"{len(bench.run_plan())} runs planned")
    return 0


def freeze(pointe_commit: str) -> None:
    prompt = HERE / "adapters" / "llm_router_prompt.txt"
    record = {
        "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "pointe_commit": pointe_commit,
        "llm_router_prompt_commit": runner.git("log", "-1", "--format=%H", "--", str(prompt)),
        "llm_router_prompt_sha256": sha256(prompt),
        "unpublished_seed_manifest_sha256": None,  # identifiers has no unpublished seeds; hlk adds its manifest
        "item_order_seed": bench.SEED,
        "claude_code": agent.claude_version(),
        "agent_model": MODEL,
        "identifiers_items_sha256": sha256(HERE / "identifiers" / "items.toml"),
        "identifiers_audio_lock_sha256": sha256(bench.LOCK) if bench.LOCK.exists() else None,
    }
    FROZEN.write_text(json.dumps(record, indent=1) + "\n")
    print(json.dumps(record, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["identifiers", "corpus", "verify", "report", "freeze"])
    ap.add_argument("rest", nargs="*")
    ap.add_argument("--adapter", default=",".join(bench.ARMS))
    ap.add_argument("--budget-usd", type=float, default=12.0)
    ap.add_argument("--port-base", type=int, default=9400)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--resume")
    ap.add_argument("--items")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pointe-commit", help="freeze: the Pointe commit under test (default: origin/main)")
    a = ap.parse_args()

    if a.what == "verify":
        return verify()
    if a.what == "corpus":
        corpus()
        return 0
    if a.what == "report":
        from identifiers import report
        report.write(a.rest[0])
        return 0
    if a.what == "freeze":
        runner.git("fetch", "-q", "origin")
        freeze(a.pointe_commit or runner.git("rev-parse", "origin/main"))
        return 0

    arms = tuple(x for x in a.adapter.split(","))
    unknown = set(arms) - set(bench.ARMS)
    if unknown:
        raise SystemExit(f"unknown adapter {sorted(unknown)}; choose from {', '.join(bench.ARMS)}")
    runs = bench.run_plan(arms=arms, smoke=a.smoke, only=set(a.items.split(",")) if a.items else None)
    est = sum(EST[r["arm"]] for r in runs)
    left = a.budget_usd - ledger.spent(bench.BENCH)
    print(f"identifiers: {len(runs)} runs, estimated ${est:.2f} (planning figures), ${left:.2f} left of "
          f"${a.budget_usd:.2f}" + (" [smoke]" if a.smoke else ""))
    if a.dry_run:
        for arm in arms:
            print(f"  {arm}: {sum(r['arm'] == arm for r in runs)} runs")
        return 0

    frozen = json.loads(FROZEN.read_text()) if FROZEN.exists() else None
    if not a.smoke and not frozen:
        raise SystemExit("refused: FROZEN.json is committed before the first non-smoke paid row (design 4.6); "
                         "run `run.py freeze` and commit it")
    pointe_commit = frozen["pointe_commit"] if frozen else runner.git("rev-parse", "origin/main")
    if frozen and a.smoke is False:
        tracked = runner.git("log", "-1", "--format=%H", "--", str(FROZEN))
        if not tracked:
            raise SystemExit("refused: FROZEN.json is not committed")
    ensure_corpus()
    from core import corpus as c

    secrets = {"anthropic": keys.get("anthropic")}
    if {"naive", "llm-router"} & set(arms):
        secrets["soniox"] = keys.get("soniox")
    run_id = a.resume or time.strftime("identifiers-%Y%m%d-%H%M%S") + ("-smoke" if a.smoke else "")
    run = runner.Run(bench.BENCH, run_id, a.budget_usd, a.workers, a.port_base, MAX_RUN_USD, a.smoke)
    deny = [str(HERE), str(HERE.resolve())]
    pre = agent.preflight(run.tmp / "preflight", MODEL, secrets["anthropic"], deny, bench.ALLOW)
    from core.adapter import SpendRow
    ledger.add(bench.BENCH, run_id, "preflight", "preflight", [SpendRow("anthropic-agent", pre["usd"], "metered")])
    print(f"preflight: {json.dumps(pre)}")
    if not pre["ok"]:
        raise SystemExit("preflight failed: the session would not be billed to the API key alone; stopped")
    if frozen and pre["claude_code"] != frozen["claude_code"]:
        raise SystemExit(f"refused: Claude Code {pre['claude_code']} differs from the frozen {frozen['claude_code']}")
    ctx = {"items": check.load_items(), "model": MODEL, "mode": MODE, "deny_read": deny, "secrets": secrets,
           "run_id": run_id, "repo_commit": runner.git("rev-parse", "HEAD"), "pointe_commit": pointe_commit,
           "claude_code": pre["claude_code"], "smoke": a.smoke,
           "audio_matches_lock": c.matches_lock(bench.BENCH, bench.LOCK)}
    if any(x.startswith("pointe") for x in arms):
        ctx["pointe_root"] = runner.pointe_checkout(pointe_commit)
    record = {k: v for k, v in ctx.items() if k not in ("items", "secrets", "deny_read", "pointe_root")}
    record.update(arms=list(arms), runs=len(runs), estimate_usd=round(est, 2), cap_usd=a.budget_usd,
                  workers=a.workers, port_base=a.port_base, started=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                  preflight={k: v for k, v in pre.items() if k != "credentials_files"})
    (run.dir / "run.json").write_text(json.dumps(record, indent=1) + "\n")
    try:
        run.execute(runs, lambda r, port, d: bench.one(r, port, d, ctx))
    finally:
        left_over = runner.leftover(run.ports)
        record.update(finished=time.strftime("%Y-%m-%dT%H:%M:%S%z"), stopped_for_budget=run.stopped_for_budget,
                      listening_after=left_over, spent_usd=round(ledger.spent(bench.BENCH), 4))
        (run.dir / "run.json").write_text(json.dumps(record, indent=1) + "\n")
        print(f"done: {run_id}; identifiers ledger ${ledger.spent(bench.BENCH):.2f}; still listening: {left_over}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
