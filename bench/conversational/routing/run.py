"""Pointe Conversational Engineering Benchmarks: the one command. This build carries the `routing` benchmark.

  uv run --locked python bench/conversational/routing/run.py routing --budget-usd 9 [--adapter ...] [--smoke] [--dry-run]
  uv run --locked python bench/conversational/routing/run.py corpus          # render the audio only, $0
  uv run --locked python bench/conversational/routing/run.py verify          # offline checks, $0
  uv run --locked python bench/conversational/routing/run.py report <run-id> # rows -> routing/RESULTS.md and results.json
"""

import argparse
import asyncio
import hashlib
import json
import os
import random
import secrets
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parents[1]))

from conversational.routing.core import agent, corpus, ledger, scrub  # noqa: E402
from conversational.routing.routing import check, report, runner  # noqa: E402

ARMS = ("pointe", "llm-router", "naive", "keyboard-canonical", "null")
ESTIMATE = {"pointe": 0.055, "llm-router": 0.035, "naive": 0.025, "keyboard-canonical": 0.025, "null": 0.0}  # $/turn
HEADROOM = {"pointe": 0.6, "llm-router": 0.35, "naive": 0.25, "keyboard-canonical": 0.25, "null": 0.05}  # $/conversation
SEED = 20261123
REPEATS = 3
FROZEN = HERE / "FROZEN.json"
PROMPT = HERE / "adapters" / "llm_router_prompt.txt"
PRODUCT_EXCLUDES = [":(exclude)bench/conversational", ":(exclude)tests/test_conversational_routing.py", ":(exclude).gitignore"]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def pointe_commit() -> str:
    """The last commit that changed Pointe itself (anything outside this benchmark's own files)."""
    return git("log", "-1", "--format=%H", "--", ".", *PRODUCT_EXCLUDES)


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def resolve_setup(state: Path) -> dict:
    """What an isolated daemon with no setup chosen will run, from the keys present (vendors.resolve), in a child."""
    state.mkdir(parents=True, exist_ok=True)
    code = ("import vendors, json; s = vendors.resolve(); "
            "print(json.dumps({k: getattr(s, k) for k in ('brain', 'reader', 'checker', 'ears', 'mouth')}))")
    out = subprocess.run(["uv", "run", "--no-sync", "python", "-c", code], cwd=ROOT / "pointe", capture_output=True, text=True,
                         env=agent.clean_env({"CLAUDE_VOICE_STATE": str(state)}))
    return json.loads(out.stdout.strip().splitlines()[-1])


def preflight(root: Path, model: str) -> dict:
    """4.3: a fresh config folder starts without the Keychain login and bills the API key (apiKeyHelper)."""
    home = root / "preflight"
    cfg = home / "config"
    repo = home / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    s = agent.AgentSession("preflight", repo, home, model, "acceptEdits")
    s.prepare()
    out = subprocess.run(["claude", "-p", "--output-format", "stream-json", "--verbose", "--model", model,
                          "--max-budget-usd", "0.05", "Reply with the word ok."], cwd=repo, capture_output=True,
                         text=True, stdin=subprocess.DEVNULL, env=agent.clean_env({"CLAUDE_CONFIG_DIR": str(cfg)}),
                         timeout=120)
    init, result = {}, {}
    for line in out.stdout.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "system" and e.get("subtype") == "init":
            init = e
        if e.get("type") == "result":
            result = e
    creds = [p.name for p in cfg.rglob("*") if "credential" in p.name.lower()]
    account = json.loads((cfg / ".claude.json").read_text()).get("oauthAccount") if (cfg / ".claude.json").exists() else None
    ok = init.get("apiKeySource") == "apiKeyHelper" and not creds and not account and result.get("subtype") == "success"
    return {"ok": ok, "apiKeySource": init.get("apiKeySource"), "model": init.get("model"),
            "credentials_files": creds, "oauth_account": bool(account), "usd": result.get("total_cost_usd") or 0.0}


def make_arm(name: str, env, router_model: str):
    from conversational.routing.adapters.keyboard import KeyboardArm
    from conversational.routing.adapters.llm_router import LLMRouterArm
    from conversational.routing.adapters.naive import NaiveArm
    from conversational.routing.adapters.null import NullArm
    from conversational.routing.adapters.pointe import PointeArm

    return {"pointe": lambda: PointeArm(env, env.port_base + 10), "llm-router": lambda: LLMRouterArm(env, router_model),
            "naive": lambda: NaiveArm(env), "keyboard-canonical": lambda: KeyboardArm(env),
            "null": lambda: NullArm(env)}[name]()


def plan(ds: dict, arms: list[str], seed: int, smoke: bool, repeat: bool) -> list[dict]:
    convs = [c["id"] for c in ds["conversation"]]
    order = convs[:]
    random.Random(seed).shuffle(order)
    kb = runner.keyboard_turns(ds, seed)
    jobs = []
    if smoke:
        order = order[:1]
    for cid in order:
        for arm in arms:
            only = None
            if arm == "keyboard-canonical":
                only = {i for c, i in kb if c == cid}
                if not only:
                    continue
            jobs.append({"arm": arm, "conv": cid, "run_index": 0, "only": sorted(only) if only else None,
                         "max_turns": 2 if smoke else None})
    if repeat and not smoke:
        for cid in random.Random(seed + 1).sample(convs, REPEATS):
            for arm in ("pointe", "llm-router"):
                if arm in arms:
                    jobs.append({"arm": arm, "conv": cid, "run_index": 1, "only": None, "max_turns": None})
    return jobs


def turns_of(job: dict) -> int:
    return len(job["only"]) if job["only"] else (job["max_turns"] or 5)


def append(path: Path, rows: list[dict]) -> None:
    with path.open("a") as f:
        for r in rows:
            text = json.dumps(r, default=str)
            bad = scrub.problems(text)
            if bad:
                raise RuntimeError(f"refusing to write a row with {bad}")
            f.write(text + "\n")


def scrubbed(obj, root: Path):
    return json.loads(scrub.clean(json.dumps(obj, default=str), ROOT).replace(str(root), "<run>")
                      .replace(os.path.realpath(root), "<run>"))


async def routing(args) -> int:
    ds = check.load()
    arms = args.adapter.split(",") if args.adapter else list(ARMS)
    assert all(a in ARMS for a in arms), f"unknown adapter in {arms}"
    assert args.port_base not in (7860, 7443) and 9600 <= args.port_base <= 9688, "use this run's port range"
    frozen = json.loads(FROZEN.read_text()) if FROZEN.exists() else None
    seed = frozen["item_order_seed"] if frozen else SEED
    jobs = plan(ds, arms, seed, args.smoke, not args.no_repeat)
    est = sum(turns_of(j) * ESTIMATE[j["arm"]] for j in jobs)
    print(f"{len(jobs)} conversation runs, {sum(turns_of(j) for j in jobs)} turns, estimated ${est:.2f} "
          f"(cap ${args.budget_usd:.2f}; spent so far ${ledger.spent('routing'):.2f})")
    for j in jobs:
        print(f"  {j['conv']} {j['arm']:<19} run {j['run_index']} turns {j['only'] or (j['max_turns'] or 'all')}")
    if args.dry_run:
        return 0
    if not args.smoke:
        assert frozen, "commit FROZEN.json before the first paid row (run.py freeze)"
        assert frozen["pointe_commit"] == pointe_commit(), "Pointe changed after the freeze: a new run needs a new FROZEN.json"
        assert frozen["router_prompt_sha256"] == sha_file(PROMPT), "the router prompt changed after the freeze"
        assert frozen["dataset_sha256"] == sha_file(check.DATASET), "the dataset changed after the freeze"
    run_id = args.resume or f"routing-{time.strftime('%Y%m%d-%H%M')}-{secrets.token_hex(2)}{'-smoke' if args.smoke else ''}"
    out = HERE / "results" / run_id
    out.mkdir(parents=True, exist_ok=True)
    root = Path("/tmp/pccb") / run_id
    root.mkdir(parents=True, exist_ok=True)
    link_before = sha_file(Path.home() / ".local/bin/pointe") if (Path.home() / ".local/bin/pointe").exists() else None
    from conversational.routing.core.adapter import RunEnv

    env = RunEnv(run_id=run_id, root=root, checkout=ROOT, port_base=args.port_base,
                 deny_reads=[HERE, root / "staging"])
    run_json = out / "run.json"
    meta = json.loads(run_json.read_text()) if run_json.exists() else {}
    if not meta:
        pf = preflight(root, env.model)
        ledger.record({"benchmark": "routing", "run_id": run_id, "arm": "preflight", "usd": pf["usd"],
                       "kind": "smoke" if args.smoke else "paid", "how": "metered"})
        if not pf["ok"]:
            print(f"preflight failed, stopping: {pf}")
            return 2
        setup = resolve_setup(root / "setup-probe")
        meta = {"run_id": run_id, "benchmark": "routing", "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "repo_commit": git("rev-parse", "HEAD"), "pointe_commit": pointe_commit(),
                "claude_code_version": agent.claude_version(), "agent_model": env.model, "permission_mode": env.mode,
                "pointe_setup": setup, "router_model": setup["brain"].split(":", 1)[1], "router_effort": "low",
                "ears_model": "soniox:" + __import__("conversational.routing.core.ears", fromlist=["model"]).model(),
                "voice_engine": "Kokoro-82M (mlx-community/Kokoro-82M-bf16, Apache-2.0)", "seed": seed,
                "smoke": args.smoke, "frozen": frozen, "preflight": pf, "dataset_version": ds["version"],
                "arms": arms, "budget_usd": args.budget_usd, "trimmed": []}
        run_json.write_text(json.dumps(meta, indent=1))
    built = corpus.build(runner.clips(ds), runner.LOCK, write_lock=not runner.LOCK.exists())
    meta["audio_matches_lock"] = built["matches_lock"]
    done = set()
    if (out / "rows.jsonl").exists():
        done = {(r["adapter"], r["conversation"], r["run_index"]) for r in map(json.loads, (out / "rows.jsonl").read_text().splitlines())}
    convs = {c["id"]: c for c in ds["conversation"]}
    by_key: dict[tuple, list[dict]] = {}
    for j in jobs:
        by_key.setdefault((j["conv"], j["run_index"]), []).append(j)
    for (cid, run_index), group in by_key.items():
        group = [j for j in group if (j["arm"], cid, run_index) not in done]
        if not group:
            continue
        headroom = sum(HEADROOM[j["arm"]] for j in group)
        try:
            ledger.gate("routing", args.budget_usd, headroom)
        except ledger.BudgetExceeded as e:
            print(f"stopping at the cap: {e}")
            meta["trimmed"].append({"conv": cid, "run_index": run_index, "arms": [j["arm"] for j in group]})
            break
        print(f"{cid} run {run_index}: {', '.join(j['arm'] for j in group)}", flush=True)

        async def one(j):
            arm = make_arm(j["arm"], env, meta["router_model"])
            base = root / j["arm"] / f"{cid}-r{run_index}"
            res = await runner.run_conversation(arm, convs[cid], ds, built["paths"], base / "repos",
                                                only=set(j["only"]) if j["only"] else None, max_turns=j["max_turns"])
            return j, arm, res

        results = await asyncio.gather(*(one(j) for j in group))
        for j, arm, res in results:
            left = agent.leftovers(root / j["arm"] / f"{cid}-r{run_index}")
            usd = sum(r["usd"] for r in res["spend"])
            ledger.record({"benchmark": "routing", "run_id": run_id, "arm": j["arm"], "conversation": cid,
                           "run_index": run_index, "usd": round(usd, 6), "kind": "smoke" if args.smoke else "paid",
                           "how": "computed"})
            common = {"run_id": run_id, "benchmark": "routing", "item_version": ds["version"],
                      "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "repo_commit": meta["repo_commit"],
                      "pointe_commit": meta["pointe_commit"], "adapter": j["arm"], "agent_model": env.model,
                      "claude_code_version": meta["claude_code_version"], "voice": convs[cid]["voice"],
                      "noise": "clean", "seed": seed, "run_index": run_index, "conversation": cid,
                      "smoke": args.smoke, "audio_matches_lock": built["matches_lock"],
                      "load_avg": round(os.getloadavg()[0], 2), "versions": res["versions"],
                      "router_model": meta["router_model"] if j["arm"] == "llm-router" else None,
                      "pointe_setup": meta["pointe_setup"] if j["arm"] == "pointe" else None,
                      "conversation_error": res["error"],
                      "leftover_processes": len(left)}
            append(out / "rows.jsonl", [scrubbed({**common, **r}, root) for r in res["rows"]])
            append(out / "events.jsonl", [scrubbed({"run_id": run_id, "adapter": j["arm"], "conversation": cid,
                                                    "run_index": run_index, **e}, root) for e in res["events"]]
                   + [scrubbed({"run_id": run_id, "adapter": j["arm"], "conversation": cid, "run_index": run_index,
                                "kind": "audit", "flagged": res["audit"], "error": res["error"],
                                "leftovers": left}, root)])
            append(out / "spend.jsonl", [{"run_id": run_id, "adapter": j["arm"], "conversation": cid,
                                          "run_index": run_index, **s} for s in res["spend"]])
            if j["arm"] == "pointe":
                log = root / j["arm"] / f"{cid}-r{run_index}" / "state" / "daemon.log"
                if log.exists():
                    (out / "pointe-logs").mkdir(exist_ok=True)
                    text = scrub.clean(log.read_text(errors="ignore"), ROOT).replace(str(root), "<run>").replace(
                        os.path.realpath(root), "<run>")
                    bad = scrub.problems(text)
                    (out / "pointe-logs" / f"{cid}-r{run_index}.log").write_text(
                        text if not bad else f"withheld: the scrubber found {bad}\n")
            print(f"  {j['arm']:<19} {sum(r['correct'] for r in res['rows'])}/{len(res['rows'])} correct, "
                  f"${usd:.3f}, error={res['error']}, leftovers={len(left)}", flush=True)
        run_json.write_text(json.dumps(meta, indent=1))
    left = agent.leftovers(root)
    link_after = sha_file(Path.home() / ".local/bin/pointe") if (Path.home() / ".local/bin/pointe").exists() else None
    meta.update(finished=time.strftime("%Y-%m-%dT%H:%M:%S%z"), leftover_processes=left,
                installed_pointe_link_unchanged=link_before == link_after, spent_usd=round(ledger.spent("routing"), 4))
    run_json.write_text(json.dumps(scrubbed(meta, root), indent=1))
    print(f"done: {run_id}; spent ${meta['spent_usd']:.2f} on routing; leftovers {left}; "
          f"installed pointe link unchanged: {meta['installed_pointe_link_unchanged']}")
    return 0 if not left else 3


def freeze(_args) -> int:
    ds = check.load()
    data = {"benchmark": "routing", "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "pointe_commit": pointe_commit(),
            "router_prompt_sha256": sha_file(PROMPT), "dataset_sha256": sha_file(check.DATASET),
            "item_order_seed": SEED, "claude_code_version": agent.claude_version(), "dataset_version": ds["version"],
            "unpublished_seed_manifest_sha256": None,
            "note": "routing has no unpublished seeds; the router prompt commit is the commit that adds this file"}
    FROZEN.write_text(json.dumps(data, indent=1) + "\n")
    print(json.dumps(data, indent=1))
    return 0


def corpus_cmd(_args) -> int:
    built = corpus.build(runner.clips(check.load()), runner.LOCK, write_lock=not runner.LOCK.exists())
    print(f"{len(built['paths'])} clips; matches audio.lock: {built['matches_lock']}")
    return 0


def verify(_args) -> int:
    return subprocess.run(["uv", "run", "--locked", "pytest", "-q", "tests/test_conversational_routing.py"], cwd=ROOT).returncode


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("routing")
    r.add_argument("--adapter", default="")
    r.add_argument("--budget-usd", type=float, default=9.0)
    r.add_argument("--port-base", type=int, default=9600)
    r.add_argument("--smoke", action="store_true")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--no-repeat", action="store_true")
    r.add_argument("--resume", default="")
    sub.add_parser("corpus")
    sub.add_parser("verify")
    sub.add_parser("freeze")
    rep = sub.add_parser("report")
    rep.add_argument("run_ids", nargs="+")
    args = p.parse_args()
    if args.cmd == "routing":
        return asyncio.run(routing(args))
    return {"corpus": corpus_cmd, "verify": verify, "freeze": freeze,
            "report": lambda a: report.main(a.run_ids)}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
