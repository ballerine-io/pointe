"""rows -> results.json and RESULTS.md for bargein, every number computed from committed rows; and the freeze."""

import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path

from core import agent as agent_mod
from core import runner, stats
from bargein import bench

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"
STOP_KINDS = ("stop", "undo", "redirect")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze() -> int:
    """FROZEN.json, committed before the first paid row: the Pointe commit under test and what the runs depend on."""
    prompt = HERE.parent / "adapters" / "llm_router_prompt.txt"
    prompt_commit = subprocess.run(["git", "-C", str(runner.ROOT), "log", "-1", "--format=%H", "--", str(prompt)],
                                   capture_output=True, text=True).stdout.strip()
    if not prompt_commit:
        raise SystemExit("commit llm_router_prompt.txt first")
    data = {"benchmark": "bargein", "pointe_commit": runner.product_commit(), "router_prompt_commit": prompt_commit,
            "unpublished_seed_manifest_sha256": None, "item_order_seed": bench.SEED,
            "claude_code_version": agent_mod.claude_version(), "agent_model": agent_mod.MODEL,
            "items_sha256": _sha(HERE / "items.toml"), "audio_lock_sha256": _sha(HERE / "audio.lock"),
            "frozen_on": date.today().isoformat()}
    (HERE.parent / "FROZEN.json").write_text(json.dumps(data, indent=1) + "\n")
    print(json.dumps(data, indent=1))
    return 0


def load_rows(run_ids: list[str]) -> list[dict]:
    rows = []
    for rid in run_ids:
        rows += [json.loads(line) for line in (RESULTS / rid / "rows.jsonl").read_text().splitlines() if line.strip()]
    return rows


def _rate(k: int, n: int) -> str:
    if n == 0:
        return "n/a"
    p = stats.proportion(k, n)
    lo, hi = p["ci95"]
    if k == 0:
        return f"0/{n} (upper bound {hi:.0%})"
    return f"{k}/{n} = {k / n:.0%} [{lo:.0%}, {hi:.0%}]"


def _t(t: dict) -> str:
    if not t["observed"]:
        return f"n/a ({t['censored']} censored)"
    return f"{t['median']:.2f} s / {t['p90']:.2f} s ({t['censored']} censored of {t['n']})"


def part_a(rows: list[dict]) -> dict:
    out = {}
    for arm in bench.ARMS_A:
        mine = [r for r in rows if r["part"] == "a" and r["adapter"] == arm and r["run_index"] == 0]
        if not mine:
            continue
        scored = [r for r in mine if r["status"] in ("ok", "capped")]
        stops = [r for r in scored if r["kind"] in STOP_KINDS]
        backs = [r for r in scored if r["kind"] == "backchannel"]
        halted = [r for r in stops if r["halted"]]
        only_stop = [r for r in scored if r["kind"] == "stop"]
        redirects = [r for r in scored if r["kind"] == "redirect"]
        undos = [r for r in scored if r["kind"] == "undo"]
        out[arm] = {
            "runs": len(mine), "scored": len(scored), "setup_failed": sum(r["status"] == "setup_failed" for r in mine),
            "errors": sum(r["status"] == "error" for r in mine), "capped": sum(r["status"] == "capped" for r in mine),
            "load_flagged": sum(bool(r.get("load_flag")) for r in mine),
            "halt": stats.proportion(len(halted), len(stops)),
            "missed_stop": stats.proportion(len(stops) - len(halted), len(stops)),
            "false_stop_backchannel": stats.proportion(sum(r["false_stop"] for r in backs), len(backs)),
            "overshoot_files": stats.times([r["overshoot"] for r in stops if r["halted"]]),
            "time_to_halt_stop_items": stats.times([r["time_to_halt"] for r in only_stop]),
            "redirect": stats.proportion(sum(bool(r.get("redirected")) for r in redirects), len(redirects)),
            "redirect_end_states": {s: sum(r.get("redirect_end_state") == s and bool(r.get("redirected")) for r in redirects)
                                    for s in ("left", "moved")},
            "undo": stats.proportion(sum(bool(r.get("undone")) for r in undos), len(undos)),
            "stayed_stopped": stats.proportion(sum(bool(r.get("stayed_stopped")) for r in scored if r["kind"] in ("stop", "undo")),
                                               sum(r["kind"] in ("stop", "undo") for r in scored)),
            "restarted_in_root": sum(bool(r.get("restarted_in_root")) for r in scored),
            "clarifications": sum(r.get("clarifications", 0) for r in scored),
            "spend_usd": round(sum(r.get("spend_usd", 0) for r in mine), 4)}
    return out


def _success(r: dict) -> bool:
    if r["part"] == "b":
        return bool(r.get("correct"))
    return {"stop": r.get("halted"), "undo": r.get("undone"), "redirect": r.get("redirected"),
            "backchannel": r.get("false_stop") is False}[r["kind"]] is True


def part_b(rows: list[dict]) -> dict:
    out = {}
    for arm in bench.ARMS_B:
        mine = [r for r in rows if r["part"] == "b" and r["adapter"] == arm and r["run_index"] == 0]
        if not mine:
            continue
        scored = [r for r in mine if r["status"] == "ok"]
        out[arm] = {
            "runs": len(mine), "scored": len(scored), "setup_failed": sum(r["status"] == "setup_failed" for r in mine),
            "errors": sum(r["status"] == "error" for r in mine), "load_flagged": sum(bool(r.get("load_flag")) for r in mine),
            "measure": "time to correct text on the terminal" if arm == "keyboard" else "audio",
            "correct": stats.proportion(sum(r["correct"] for r in scored), len(scored)),
            "first_audio": stats.times([r["first_output"] for r in scored]) if arm != "keyboard" else None,
            "ttca": stats.times([r["ttca"] for r in scored]),
            "within_10s": stats.proportion(sum(r["within_10s"] for r in scored), len(scored)),
            "within_30s": stats.proportion(sum(r["within_30s"] for r in scored), len(scored)),
            "clarifications": sum(r.get("clarifications", 0) for r in scored),
            "spend_usd": round(sum(r.get("spend_usd", 0) for r in mine), 4)}
    return out


def repeats(rows: list[dict]) -> dict:
    out = {}
    for part in ("a", "b"):
        for arm in ("pointe", "llm-router"):
            again = {r["item"]: r for r in rows if r["part"] == part and r["adapter"] == arm and r["run_index"] == 1
                     and r["status"] in ("ok", "capped")}
            first = {r["item"]: r for r in rows if r["part"] == part and r["adapter"] == arm and r["run_index"] == 0
                     and r["status"] in ("ok", "capped")}
            pairs = [(_success(first[i]), _success(again[i])) for i in sorted(set(again) & set(first))]
            if pairs:
                out[f"{part}:{arm}"] = stats.flip_rate(pairs)
    return out


def paired(rows: list[dict], part: str) -> dict | None:
    """Pointe minus llm-router on the same items (the headline comparison), 95% bootstrap over items."""
    first = lambda arm: {r["item"]: _success(r) for r in rows if r["part"] == part and r["adapter"] == arm  # noqa: E731
                         and r["run_index"] == 0 and r["status"] in ("ok", "capped")}
    p, q = first("pointe"), first("llm-router")
    both = sorted(set(p) & set(q))
    if not both:
        return None
    diffs = {i: [p[i] - q[i]] for i in both}
    import random
    rng = random.Random(1)
    boots = sorted(sum(diffs[rng.choice(both)][0] for _ in both) / len(both) for _ in range(2000))
    return {"items": len(both), "pointe": sum(p[i] for i in both), "llm_router": sum(q[i] for i in both),
            "delta": round(sum(d[0] for d in diffs.values()) / len(both), 4), "ci95": [round(boots[50], 4), round(boots[1949], 4)]}


def markdown(res: dict) -> str:
    a, b = res["part_a"], res["part_b"]
    lines = [f"# bargein: Barge-in and Time to a Correct Answer (synthetic speech), v{res['item_version']}", "",
             "A reproducible self-evaluation on synthetic speech, not a leaderboard. One system under test (Pointe) and "
             "reference arms written by the same team. Every number below is computed by `run.py report` from the "
             "committed rows.", "",
             f"Runs: {', '.join(res['run_ids'])}. Dates: {res['dates']}. Agent: `{res['agent_model']}` in Claude Code "
             f"{res['claude_code']}, `--permission-mode acceptEdits`, one worker. Pointe commit `{res['pointe_commit'][:12]}`, "
             f"setup {res['pointe_setup']}, roles {res['pointe_roles']}. Ledger: ${res['spend_usd']:.2f} of $14.00 "
             f"(computed from token usage and list prices, not metered).", "",
             "## Part A: stopping a working agent (synthetic speech, 24 items, one Kokoro voice each)", "",
             "| Arm | Halt (stop, undo, redirect) | Missed stop | False stop on backchannels | Overshoot, files (median / p90) "
             "| Time to halt, stop items (median / p90) | Redirect | Undo | Stayed stopped (stop, undo) | Setup failed / errors / capped | Load-flagged |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for arm, r in a.items():
        lines.append(f"| {arm} | {_rate(r['halt']['k'], r['halt']['n'])} | {_rate(r['missed_stop']['k'], r['missed_stop']['n'])} "
                     f"| {_rate(r['false_stop_backchannel']['k'], r['false_stop_backchannel']['n'])} "
                     f"| {_t(r['overshoot_files']).replace(' s', '')} | {_t(r['time_to_halt_stop_items'])} "
                     f"| {_rate(r['redirect']['k'], r['redirect']['n'])} (left {r['redirect_end_states']['left']}, moved "
                     f"{r['redirect_end_states']['moved']}) | {_rate(r['undo']['k'], r['undo']['n'])} "
                     f"| {_rate(r['stayed_stopped']['k'], r['stayed_stopped']['n'])} "
                     f"| {r['setup_failed']} / {r['errors']} / {r['capped']} | {r['load_flagged']} of {r['runs']} |")
    lines += ["", "`null` ran on a seeded 8 items: the job runs to its end by construction and each run still costs an "
              "agent session, so the floor is confirmed on a sample. Halt means the job that was running when the user "
              "spoke stopped before `step_20.txt` (its files come every 2 s; a file after a gap of more than 4 s belongs "
              "to a later run the agent started); stayed stopped means no later run wrote step files in the repo root "
              "either. Time to halt is the last root step file's time after the end of the user's speech (or the "
              "keypress), at the job's 2 s resolution. Overshoot is files written after that point minus one file in "
              "flight. A redirect counts when the job stopped, `out/` ends with steps 04 to 20, and steps 01 to 03 are "
              "either left in place or moved to `out/` (both accepted).", "",
              "## Part B: time to the first correct answer (synthetic speech, 30 questions, one Kokoro voice each)", "",
              "| Arm | Correct within 45 s | First audio (median / p90) | Time to correct answer (median / p90, censored) "
              "| Correct within 10 s | Correct within 30 s | Clarifications | Load-flagged |", "|---|---|---|---|---|---|---|---|"]
    for arm, r in b.items():
        fa = _t(r["first_audio"]) if r["first_audio"] else "n/a (text)"
        name = "keyboard (time to correct text, not comparable with spoken times)" if arm == "keyboard" else arm
        lines.append(f"| {name} | {_rate(r['correct']['k'], r['correct']['n'])} | {fa} | {_t(r['ttca'])} "
                     f"| {_rate(r['within_10s']['k'], r['within_10s']['n'])} | {_rate(r['within_30s']['k'], r['within_30s']['n'])} "
                     f"| {r['clarifications']} | {r['load_flagged']} of {r['runs']} |")
    lines += ["", "Times run from the end of the user's speech (keyboard: the Enter key) on the runner's monotonic clock. "
              "Spoken answers are scored on the recorded audio through the one pinned Whisper large-v3-turbo, the same "
              "for every arm; an item never answered correctly within 45 s is censored and counted beside each median. "
              "When an arm asks a question back, the scripted user answers it once (a clarification, not a penalty) and "
              "the clock keeps running from the first question.", "",
              "## Pointe against llm-router, paired by item (synthetic speech)", ""]
    for part, label in (("a", "Part A success (halt, undo, redirect; no false stop)"), ("b", "Part B correct answer")):
        p = res["paired"].get(part)
        if p:
            lines.append(f"- {label}: Pointe {p['pointe']}/{p['items']}, llm-router {p['llm_router']}/{p['items']}, "
                         f"difference {p['delta']:+.0%} [95% bootstrap over items {p['ci95'][0]:+.0%}, {p['ci95'][1]:+.0%}].")
    lines += ["", "## Run-to-run (synthetic speech)", ""]
    for key, f in res["repeats"].items():
        lines.append(f"- {key}: {f['n']} repeated items, flips {f['flips']}, pass^2 {f['pass2']:.0%}.")
    lines += ["", "## Limits", ""] + [f"- {x}" for x in res["limits"]] + [""]
    return "\n".join(lines)


LIMITS = [
    "Synthetic speech only (four Kokoro voices, no noise): an upper bound for every arm. Kokoro is also Pointe's local "
    "voice.",
    "The reference arms (`naive`, `llm-router`, `keyboard`) were written by the team that builds Pointe. No outside "
    "product is tested.",
    "Spend is computed from token usage and list prices (Claude Code session usage; Pointe's daemon log with an assumed "
    "300 output tokens a brain step and a flat allowance for its reader and checker), not metered by the vendors. Claude "
    "Code's own background calls (session titles) are not in its transcript.",
    "The machine ran other workloads, including other benchmark agents, during the runs; the runner waited up to 45 s "
    "(Part A) or 2 minutes (Part B, the latency result) for the 1-minute load average to fall under 12 before each run and flags rows that started above it. "
    "Latency rows with a flag are less reliable.",
    "Small samples: 18 stop-type items and 6 backchannels per arm in Part A, 30 questions in Part B. Intervals are wide; "
    "the tables do not rank arms whose intervals overlap.",
    "Part B's facts were read into the agent's context by a typed setup turn before the question (the same in every "
    "arm), so the time measures the voice path, not the agent's search.",
    "The agent's settings file allows the job's shell commands and a hook allows commands that stay inside the item "
    "repo, the same in every arm, so no permission prompt stands between the user and the outcome.",
]


def main(run_id: str | None) -> int:
    ids = [run_id] if run_id else sorted(p.name for p in RESULTS.iterdir() if p.is_dir() and p.name.startswith("bargein-")
                                         and not p.name.endswith("smoke"))
    rows = [r for r in load_rows(ids) if r.get("kind_of_run") == "paid"]
    freeze_data = json.loads((HERE.parent / "FROZEN.json").read_text())
    bad = [r for r in rows if r["pointe_commit"] != freeze_data["pointe_commit"]]
    if bad:
        raise SystemExit(f"{len(bad)} rows carry another Pointe commit than FROZEN.json")
    pointe_rows = [r for r in rows if r["adapter"] == "pointe" and isinstance(r.get("versions"), dict)]
    res = {"benchmark": "bargein", "item_version": rows[0]["item_version"] if rows else "", "run_ids": ids,
           "dates": f"{min(r['time'] for r in rows)[:10]} to {max(r['time'] for r in rows)[:10]}" if rows else "",
           "agent_model": agent_mod.MODEL, "claude_code": freeze_data["claude_code_version"],
           "pointe_commit": freeze_data["pointe_commit"],
           "pointe_setup": pointe_rows[0]["versions"].get("pointe_setup") if pointe_rows else "",
           "pointe_roles": pointe_rows[0]["versions"].get("pointe_roles") if pointe_rows else "",
           "spend_usd": round(sum(r.get("spend_usd", 0) for r in rows), 4), "rows": len(rows),
           "part_a": part_a(rows), "part_b": part_b(rows), "repeats": repeats(rows),
           "paired": {p: paired(rows, p) for p in ("a", "b")}, "limits": LIMITS}
    out = RESULTS / ids[-1] if len(ids) == 1 else RESULTS
    (out / "results.json").write_text(json.dumps(res, indent=1) + "\n")
    (HERE / "RESULTS.md").write_text(markdown(res))
    print(markdown(res))
    return 0
