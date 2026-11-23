"""Pointe Conversational Coding Benchmarks: the one command. This build carries the `actions` benchmark.

    uv run --locked --extra local python bench/conversational/actions/run.py corpus              # render audio, $0
    uv run --locked --extra local python bench/conversational/actions/run.py verify              # offline checks, $0
    uv run --locked --extra local python bench/conversational/actions/run.py actions --budget-usd 17 [--adapter ...]
                                                                       [--smoke] [--dry-run] [--port-base 9500]
    uv run --locked --extra local python bench/conversational/actions/run.py report <run-id>     # rows -> results JSON + page

`--extra local` is needed for Kokoro and Whisper (Pointe's optional extra; no new dependency).
"""

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import threading
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(ROOT))  # Pointe's own modules (vendors, assets): the recognizer and brain it resolves to
VENDOR_STATE = Path("/tmp/pccb/vendors-state")  # vendors.config() must never read the owner's ~/.claude-voice

from core import ledger, scrub  # noqa: E402

ITEMS = HERE / "actions" / "items.toml"
RESULTS = HERE / "results"
PRICES = json.loads((HERE / "prices.json").read_text())
FROZEN = HERE / "FROZEN.json"
ARMS = ("pointe", "llm-router", "naive", "keyboard", "null")
FORBIDDEN_PORTS = (7860, 7443)
SESSION = "quillon"
MAX_RUN_USD = 0.12  # the most one item run may cost (Pointe: agent + voice vendors); the ledger gate's headroom unit
ESTIMATE = {"pointe": 0.045, "llm-router": 0.012, "naive": 0.006, "keyboard": 0.005, "null": 0.005}  # planning only
OWNER_LINK = Path.home() / ".local" / "bin" / "pointe"


def items() -> tuple[dict, list[dict]]:
    data = tomllib.loads(ITEMS.read_text())
    return data["meta"], data["item"]


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True).stdout.strip()


def adapter_for(arm: str):
    if arm == "pointe":
        from adapters.pointe import PointeAdapter
        return PointeAdapter()
    if arm == "llm-router":
        from adapters.llm_router import RouterAdapter
        return RouterAdapter()
    if arm == "naive":
        from adapters.naive import NaiveAdapter
        return NaiveAdapter()
    if arm == "keyboard":
        from adapters.keyboard import KeyboardAdapter
        return KeyboardAdapter()
    if arm == "null":
        from adapters.null import NullAdapter
        return NullAdapter()
    if arm == "echo":
        from adapters.echo import EchoAdapter
        return EchoAdapter()
    raise ValueError(arm)


def plan(all_items: list[dict], arms: list[str], seed: int, smoke: bool, repeat: bool = True) -> list[tuple]:
    """Item order shuffled by `seed`, every arm on an item before the next item, so a stop at the cap leaves a random
    subsample with every arm present. Repeats (flip rate) come last: they are the first thing trimmed."""
    rng = random.Random(seed)
    order = list(all_items)
    rng.shuffle(order)
    ids = [i["id"] for i in all_items]
    null_sample = set(random.Random(seed + 1).sample(ids, 20))
    repeat_sample = random.Random(seed + 2).sample(ids, 20)
    if smoke:  # one prompt-pending and one working-or-idle item
        order = [next(i for i in order if i["phase"] == "pending" and i["group"] == "clear_yes"),
                 next(i for i in order if i["phase"] == "working")]
        null_sample, repeat_sample = {i["id"] for i in order}, []
    runs = []
    for item in order:
        for arm in arms:
            if arm == "keyboard" and item["group"] not in ("clear_yes", "clear_no") and not smoke:
                continue
            if arm == "null" and item["id"] not in null_sample:
                continue
            runs.append((item, arm, 0))
    if repeat:
        by_id = {i["id"]: i for i in all_items}
        for iid in repeat_sample:
            for arm in ("pointe", "llm-router"):
                if arm in arms:
                    runs.append((by_id[iid], arm, 1))
    return runs


def keychain(item: str) -> str:
    for name in (f"pointe.{item}", item):
        got = subprocess.run(["security", "find-generic-password", "-s", name, "-w"], capture_output=True, text=True)
        if got.returncode == 0 and got.stdout.strip():
            return got.stdout.strip()
    raise SystemExit(f"no Keychain item for {item}")


def link_hash() -> str | None:
    return hashlib.sha256(OWNER_LINK.read_bytes()).hexdigest() if OWNER_LINK.exists() else None


def preflight(api_key: str, run_tmp: Path) -> dict:
    """The agent bills the API key, from a fresh config folder with no login and no user plugins."""
    from core import agent as agentlib

    folder = run_tmp / "preflight"
    (folder / "repo").mkdir(parents=True, exist_ok=True)
    agentlib.write_config(folder, [], [])
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_") and k not in agentlib.DROP_ENV}
    env.update(CLAUDE_CONFIG_DIR=str(folder / "cfg"), ANTHROPIC_API_KEY=api_key)
    got = subprocess.run(["claude", "-p", "--output-format", "stream-json", "--verbose", "--model", agentlib.MODEL,
                          "--permission-mode", "default", "Reply with the single word ok."],
                         cwd=folder / "repo", env=env, capture_output=True, text=True, timeout=120)
    del env
    init, result = {}, {}
    for line in got.stdout.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") == "system" and d.get("subtype") == "init":
            init = d
        if d.get("type") == "result":
            result = d
    cfg = folder / "cfg"
    creds = [p.name for p in cfg.glob("*credentials*")]
    oauth = "oauthAccount" in (cfg / ".claude.json").read_text() if (cfg / ".claude.json").exists() else False
    out = {"api_key_source": init.get("apiKeySource"), "permission_mode": init.get("permissionMode"),
           "plugins": [p.get("name") for p in init.get("plugins", []) if p.get("path") != "builtin"],
           "builtin_plugins": [p.get("name") for p in init.get("plugins", []) if p.get("path") == "builtin"], "credentials_files": creds, "oauth": oauth,
           "claude_code": init.get("claude_code_version"), "cost_usd": result.get("total_cost_usd", 0.0)}
    ok = out["api_key_source"] == "ANTHROPIC_API_KEY" and not creds and not oauth and not out["plugins"]
    out["ok"] = ok
    return out


def cleanup(run_tmp: Path, port_base: int) -> dict:
    """Every process this run started, gone: nothing listening on our ports, no agent with our config folders."""
    left = []
    for port in range(port_base, port_base + 100):
        for pid in subprocess.run(["lsof", "-t", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True,
                                  text=True).stdout.split():
            # Only a process of this run (its folder in the command line or environment): another benchmark's daemon
            # under /tmp/pccb on a port in this range is not ours to kill.
            cmd = subprocess.run(["ps", "eww", "-o", "command=", "-p", pid], capture_output=True, text=True).stdout
            if str(run_tmp) in cmd:
                os.kill(int(pid), 9)
                left.append(f"port {port}")
    ps = subprocess.run(["ps", "eww", "-o", "pid=,command="], capture_output=True, text=True).stdout
    for line in ps.splitlines():
        if str(run_tmp) in line and "run.py" not in line:
            pid = line.split()[0]
            try:
                os.kill(int(pid), 9)
                left.append("agent process")
            except (ProcessLookupError, ValueError):
                pass
    return {"killed_at_end": len(left)}


def spend_of(row: dict) -> tuple[float, dict]:
    from core.agent import usage_usd
    by = {}
    computed = usage_usd(row.get("usage") or {}, PRICES)
    slash = row.get("cost_slash")
    by["anthropic-agent"] = [round(slash, 6), "computed (Claude Code /cost)"] if slash else [round(computed, 6),
                                                                                          "computed (transcript usage)"]
    for vendor, value in (row.get("spend_extra") or {}).items():
        by[vendor] = value
    return sum(v[0] for v in by.values()), by


def actions(args) -> int:
    from actions import protocol
    from core import corpus
    from core.adapter import RunEnv
    from core.agent import claude_version

    for port in range(args.port_base, args.port_base + 100):
        assert port not in FORBIDDEN_PORTS, "the owner's live ports are never used"
    meta, all_items = items()
    arms = args.adapter.split(",") if args.adapter else list(ARMS)
    frozen = json.loads(FROZEN.read_text()) if FROZEN.exists() else None
    kind = "smoke" if args.smoke else ("paid" if frozen else "debug")
    if kind == "paid":
        assert frozen["pointe_commit"] and not git("diff", "--name-only", frozen["pointe_commit"], "HEAD", "--", ".",
                                                    ":!bench", ":!tests", ":!docs", ":!site"), \
            "Pointe's code differs from the frozen commit"
        assert hashlib.sha256((HERE / "adapters" / "llm_router_prompt.txt").read_bytes()).hexdigest() == \
            frozen["router_prompt_sha256"], "the router prompt changed after the freeze"
        seed = frozen["item_order_seed"]
    else:
        seed = 7
    runs = plan(all_items, arms, seed, args.smoke, repeat=not args.no_repeat)
    if args.items:
        wanted = set(args.items.split(","))
        runs = [r for r in runs if r[0]["id"] in wanted]
    estimate = sum(ESTIMATE[arm] for _, arm, _ in runs)
    print(f"{len(runs)} runs, arms {arms}, estimated ${estimate:.2f} (planning figures, not measured), kind {kind}")
    if args.dry_run:
        return 0
    rendered = corpus.render(all_items)
    run_id = args.resume or time.strftime("act-%Y%m%d-%H%M%S")
    out = RESULTS / run_id
    out.mkdir(parents=True, exist_ok=True)
    run_tmp = Path("/tmp/pccb") / run_id
    run_tmp.mkdir(parents=True, exist_ok=True)
    done = set()
    if (out / "rows.jsonl").exists():
        for line in (out / "rows.jsonl").read_text().splitlines():
            r = json.loads(line)
            done.add((r["item"], r["adapter"], r["run_index"], r.get("attempt", 0)))
    api_key = keychain("anthropic-api-key")
    secrets = {"soniox": keychain("soniox-api-key"), "anthropic": api_key}
    if "llm-router" in arms:
        import vendors
        from adapters.llm_router import RouterAdapter
        RouterAdapter.model = vendors.resolve().brain
    pf = preflight(api_key, run_tmp)
    ledger.add("actions", run_id, "preflight probe", pf["cost_usd"] or 0.0,
               {"anthropic-agent": [pf["cost_usd"] or 0.0, "computed (claude -p result)"]}, kind)
    print("preflight", json.dumps({k: v for k, v in pf.items()}))
    if not pf["ok"]:
        print("preflight failed: stop. Not falling back to any login.")
        return 2
    if "pointe" in arms:
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        env["UV_PROJECT_ENVIRONMENT"] = "/tmp/pccb/actions-pointe-venv"
        subprocess.run(["uv", "sync", "--locked", "--quiet", "--project", str(ROOT)], env=env, check=True)
    cc = claude_version()
    run_info = {"run_id": run_id, "benchmark": "actions", "kind": kind, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "repo_commit": git("rev-parse", "HEAD"), "pointe_commit": (frozen or {}).get("pointe_commit") or git("rev-parse", "HEAD"),
                "frozen": frozen, "claude_code": cc, "agent_model": "claude-haiku-5-5", "arms": arms, "seed": seed,
                "workers": args.workers, "budget_usd": args.budget_usd, "audio_matches_lock": rendered["matches_lock"],
                "router_model": getattr(__import__("adapters.llm_router", fromlist=["x"]).RouterAdapter, "model", None)
                if "llm-router" in arms else None, "preflight": {k: pf[k] for k in ("api_key_source", "permission_mode",
                                                                                   "plugins", "builtin_plugins", "ok")},
                "items_version": meta["version"], "planned_runs": len(runs)}
    (out / "run.json").write_text(json.dumps(run_info, indent=1))
    write = threading.Lock()
    link0 = link_hash()
    ports = [args.port_base + 10 * w for w in range(args.workers)]
    free_ports = list(ports)
    stop_all = threading.Event()

    def one(run):
        item, arm, idx = run
        if stop_all.is_set():
            return
        for attempt in (0, 1):
            if (item["id"], arm, idx, attempt) in done:
                return
            try:
                ledger.gate("actions", args.budget_usd, args.workers, MAX_RUN_USD)
            except ledger.BudgetExceeded as e:
                print("budget gate:", e)
                stop_all.set()
                return
            with write:
                port = free_ports.pop()
            folder = run_tmp / f"{item['id']}-{arm}-{idx}-{attempt}"
            adapter = adapter_for(arm)
            env = RunEnv(folder=folder, session=SESSION, api_key=api_key, port=port, item=item, secrets=secrets,
                         prices=PRICES)
            started = time.time()
            try:
                row = protocol.run_one(item, arm, adapter, env, idx)
            except Exception as e:
                row = {"status": "error", "why": f"{type(e).__name__}: {str(e)[:200]}", "usage": {}, "spend_extra": {}}
                try:
                    adapter.stop()
                except Exception:
                    pass
            finally:
                with write:
                    free_ports.append(port)
            usd, by = spend_of(row)
            if link_hash() != link0:
                print("the owner's ~/.local/bin/pointe changed during a run: stop")
                stop_all.set()
            row.update(run_id=run_id, time=time.strftime("%Y-%m-%dT%H:%M:%S%z"), benchmark="actions",
                       item=item["id"], item_version=meta["version"], phase=item["phase"], kind=item["kind"],
                       group=item["group"], label=item["label"], truncated_clip=item["truncate"],
                       side_talk=item["label"] == "side_talk", text=item["text"], voice=item["voice"],
                       expect=item["expect"], accept=item["accept"], adapter=arm, run_index=idx, attempt=attempt,
                       seed=seed, repo_commit=run_info["repo_commit"], pointe_commit=run_info["pointe_commit"],
                       agent_model="claude-haiku-5-5", claude_code=cc, kind_of_run=kind,
                       wall_seconds=round(time.time() - started, 1), load_avg=round(os.getloadavg()[0], 2),
                       audio_matches_lock=rendered["matches_lock"], spend_usd=round(usd, 6), spend_by_vendor=by,
                       noise="clean")
            for key in ("said_start", "said_end"):
                if key in row:
                    row[key] = round(row[key], 3)
            row = protocol.sanitize(row, folder, run_tmp)
            problems = scrub.problems(json.dumps(row))
            if problems:
                row = {k: row[k] for k in row if k not in ("events", "requests", "why")}
                row["scrub_dropped"] = problems[:3]
                scrub.check(row)
            with write:
                ledger.add("actions", run_id, f"{item['id']} {arm} {idx}.{attempt}", usd, by, kind)
                with open(out / "rows.jsonl", "a") as f:
                    f.write(json.dumps(row) + "\n")
            print(f"{item['id']} {arm:10} {idx}.{attempt} {row['status']:13} {row.get('observed', '-'):7} "
                  f"expect {item['expect']:7} ${usd:.4f} {row['wall_seconds']}s", flush=True)
            if row["status"] != "setup_failed":
                return

    try:
        with ThreadPoolExecutor(args.workers) as pool:
            list(pool.map(one, runs))
    finally:
        info = cleanup(run_tmp, args.port_base)
        run_info.update(finished=time.strftime("%Y-%m-%dT%H:%M:%S%z"), **info, owner_link_unchanged=link_hash() == link0,
                        spent_actions_total=ledger.spent("actions"))
        (out / "run.json").write_text(json.dumps(run_info, indent=1))
        print(json.dumps(info), "ledger total for actions:", ledger.spent("actions"))
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["actions", "corpus", "verify", "report"])
    p.add_argument("run_ids", nargs="*")
    p.add_argument("--adapter")
    p.add_argument("--budget-usd", type=float, default=17.0)
    p.add_argument("--port-base", type=int, default=9500)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--items")
    p.add_argument("--resume")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-repeat", action="store_true")
    args = p.parse_args()
    VENDOR_STATE.mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_VOICE_STATE"] = str(VENDOR_STATE)
    if args.command == "actions":
        return actions(args)
    if args.command == "corpus":
        from core import corpus
        _, all_items = items()
        print(json.dumps(corpus.render(all_items, write_lock=True)))
        return 0
    if args.command == "verify":
        return subprocess.run([sys.executable, "-m", "pytest", "-q", str(ROOT / "tests" / "test_conversational_actions.py")]).returncode
    if args.command == "report":
        from core import report
        return report.main(args.run_ids)
    return 1


if __name__ == "__main__":
    sys.exit(main())
