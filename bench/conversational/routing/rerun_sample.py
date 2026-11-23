"""A sample re-run for verification: the given conversations through pointe and llm-router, same harness and frozen
commit as the paid run; rows go to results/<id>-verify and are used in no table.

  uv run --locked python bench/conversational/routing/rerun_sample.py c06,c12
"""
import asyncio, json, os, sys, time, secrets
from pathlib import Path
WT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WT / "bench/conversational"))
import run as R  # noqa
from conversational.core import agent, corpus, ledger, scrub
from conversational.core.adapter import RunEnv
from conversational.routing import check, runner

CONVS = sys.argv[1].split(",")
ds = check.load()
frozen = json.loads(R.FROZEN.read_text())
assert frozen["pointe_commit"] == R.pointe_commit()
assert frozen["router_prompt_sha256"] == R.sha_file(R.PROMPT) and frozen["dataset_sha256"] == R.sha_file(check.DATASET)
run_id = f"routing-{time.strftime('%Y%m%d-%H%M')}-{secrets.token_hex(2)}-verify"
out = R.HERE / "results" / run_id; out.mkdir(parents=True)
root = Path("/tmp/pccb") / run_id; root.mkdir(parents=True)
env = RunEnv(run_id=run_id, root=root, checkout=R.ROOT, port_base=9670, deny_reads=[R.HERE, root / "staging"])
setup = R.resolve_setup(root / "setup-probe")
meta = {"run_id": run_id, "benchmark": "routing", "verification": True, "purpose": "adversarial verification re-run of a sample (not used in any table)",
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "repo_commit": R.git("rev-parse", "HEAD"),
        "pointe_commit": R.pointe_commit(), "claude_code_version": agent.claude_version(), "agent_model": env.model,
        "pointe_setup": setup, "router_model": setup["brain"].split(":", 1)[1], "router_effort": "low", "conversations": CONVS}
built = corpus.build(runner.clips(ds), runner.LOCK, write_lock=False)
meta["audio_matches_lock"] = built["matches_lock"]
convs = {c["id"]: c for c in ds["conversation"]}

async def main():
    for cid in CONVS:
        async def one(name):
            arm = R.make_arm(name, env, meta["router_model"])
            base = root / name / f"{cid}-r0"
            return name, await runner.run_conversation(arm, convs[cid], ds, built["paths"], base / "repos")
        for name, res in await asyncio.gather(one("pointe"), one("llm-router")):
            usd = sum(r["usd"] for r in res["spend"])
            ledger.record({"benchmark": "routing", "run_id": run_id, "arm": name, "conversation": cid, "run_index": 0,
                           "usd": round(usd, 6), "kind": "verify", "how": "computed"})
            common = {"run_id": run_id, "adapter": name, "conversation": cid, "run_index": 0, "smoke": False,
                      "verify": True, "conversation_error": res["error"]}
            R.append(out / "rows.jsonl", [R.scrubbed({**common, **r}, root) for r in res["rows"]])
            R.append(out / "events.jsonl", [R.scrubbed({**common, **e}, root) for e in res["events"]])
            R.append(out / "spend.jsonl", [{**common, **s} for s in res["spend"]])
            if name == "pointe":
                log = root / name / f"{cid}-r0" / "state" / "daemon.log"
                if log.exists():
                    (out / "pointe-logs").mkdir(exist_ok=True)
                    text = scrub.clean(log.read_text(errors="ignore"), R.ROOT).replace(str(root), "<run>").replace(os.path.realpath(root), "<run>")
                    bad = scrub.problems(text)
                    (out / "pointe-logs" / f"{cid}-r0.log").write_text(text if not bad else f"withheld: {bad}\n")
            print(cid, name, [(r["turn"], r["outcome"]) for r in res["rows"]], f"${usd:.3f}", res["error"], flush=True)
asyncio.run(main())
left = agent.leftovers(root)
meta.update(finished=time.strftime("%Y-%m-%dT%H:%M:%S%z"), leftover_processes=left)
(out / "run.json").write_text(json.dumps(R.scrubbed(meta, root), indent=1))
print("done", run_id, "leftovers", left)
