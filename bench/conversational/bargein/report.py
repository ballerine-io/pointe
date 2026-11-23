"""rows -> results.json and RESULTS.md for bargein, every number computed from committed rows; and the freeze."""

import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path

from core import agent as agent_mod
from core import ledger, runner, stats
from bargein import bench, check

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"
STOP_KINDS = ("stop", "undo", "redirect")
# Part B facts whose label was wrong for the repo the runs saw; a row is excluded unless it records the fixed fixture.
LABEL_ERRORS = {"branch": ("cedar", "the runner made each fixture a fresh git repo on `master` while STATUS.md, the "
                           "label, says `cedar`; most agents checked git and answered `master`. The keyboard arm was "
                           "credited for printing `cedar` beside it; Whisper at times hears the spoken arms' \"cedar\" as "
                           "\"CDER\". Fixed in the runner (the repo is now on `cedar`); these rows are not scored")}


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


def rescore(row: dict, event: dict) -> dict:
    """The row's scores computed again from its own raw log by the current scorer (check.py, facts.py)."""
    if row["status"] not in ("ok", "capped"):
        return row
    entries = event["log"]
    log = {k: v for x in entries for k, v in x.items()}
    if row["part"] == "a":
        return {**row, **check.part_a(row["kind"], log["files"], set(log["final"]), 0.0)}
    if row["adapter"] == "keyboard":
        said = [(t, t, x["keyboard_text"]) for x in entries if "keyboard_text" in x
                for t in [x["t_pty"] if x["pty_match"] else x["t_seen"]]]
        return {**row, **check.part_b(row["kind"], 0.0, said, bench.WINDOW_B), "first_output": None}
    said = [(u["t"], u["end"], u["text"]) for u in log["spoken"]]
    return {**row, **check.part_b(row["kind"], 0.0, said, bench.WINDOW_B)}


def load_runs(run_ids: list[str]) -> list[tuple[dict, dict]]:
    """(row, event) as written together, each row re-scored from its event."""
    pairs = []
    for rid in run_ids:
        read = lambda name: [json.loads(x) for x in (RESULTS / rid / name).read_text().splitlines() if x.strip()]  # noqa: E731
        rows, events = read("rows.jsonl"), read("events.jsonl")
        if len(rows) != len(events) or any((r["item"], r["adapter"], r["run_index"]) != (e["item"], e["adapter"], e["k"])
                                           for r, e in zip(rows, events)):
            raise SystemExit(f"{rid}: rows.jsonl and events.jsonl are not in step")
        pairs += [(rescore(r, e), e) for r, e in zip(rows, events)]
    return pairs


def label_error(r: dict) -> bool:
    return r["part"] == "b" and r["kind"] in LABEL_ERRORS and r.get("fixture_branch") != LABEL_ERRORS[r["kind"]][0]


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


def from_logs(standing: list[tuple[dict, dict]]) -> dict:
    """Counts read from the committed raw logs (events.jsonl), by code: what Pointe did with a spoken stop, and what the
    typed reference's agent did with a redirect. Each log is read with its own row; a superseded attempt is not read."""
    import re

    out = {"pointe_roles": None, "pointe_a_runs": 0, "pointe_a_forwarded_as_message": 0, "pointe_a_forwarded_and_job_ran_on": 0,
           "keyboard_redirect_runs": 0, "keyboard_redirect_agent_asked": 0, "pointe_b_runs": 0, "pointe_b_permission_request": 0}
    for row, e in standing:
        if row.get("status") not in ("ok", "capped"):
            continue
        log = {k: v for x in e["log"] for k, v in x.items()}
        if e["adapter"] == "pointe":
            daemon = log.get("daemon_log_tail", "")
            found = re.search(r"setup: Setup\(([^)]*)\)", daemon)
            if found and not out["pointe_roles"]:
                out["pointe_roles"] = found.group(1).replace("'", "")
            if e["item"].startswith("a") and row.get("kind") != "backchannel":
                out["pointe_a_runs"] += 1
                said = daemon.split("user said:", 1)
                sent = len(said) > 1 and re.search(r"-> kiln: ", said[1]) is not None
                out["pointe_a_forwarded_as_message"] += sent
                out["pointe_a_forwarded_and_job_ran_on"] += sent and not row.get("halted")
            if row["part"] == "b" and not label_error(row):
                out["pointe_b_runs"] += 1
                out["pointe_b_permission_request"] += "[permission request]" in daemon.split("user said:", 1)[-1]
        if e["adapter"] == "keyboard" and row.get("kind") == "redirect" and e["k"] == 0:
            out["keyboard_redirect_runs"] += 1
            texts = [t for _, t in log.get("agent_text", [])]
            asks = re.compile(r"\?|need to know|should i|tell me|let me know|which (one|option)|do you want", re.I)
            out["keyboard_redirect_agent_asked"] += bool(texts) and not log.get("tool_uses", [])[1:] and \
                bool(asks.search(texts[-1]))
    return out


def markdown(res: dict) -> str:
    a, b = res["part_a"], res["part_b"]
    lines = [f"# bargein: Barge-in and Time to a Correct Answer (synthetic speech), v{res['item_version']}", "",
             "A reproducible self-evaluation on synthetic speech, not a leaderboard. One system under test (Pointe) and "
             "reference arms written by the same team. Every number below is computed by `run.py report` from the "
             "committed rows.", "",
             f"Runs: {', '.join(res['run_ids'])}. Dates: {res['dates']}. Agent: `{res['agent_model']}` in Claude Code "
             f"{res['claude_code']}, `--permission-mode acceptEdits`, one worker. Pointe commit `{res['pointe_commit'][:12]}`, "
             f"setup {res['pointe_setup']} ({res['logs']['pointe_roles']}). Spend: ${res['spend_usd']:.2f} in these rows; "
             f"${res['ledger_usd']:.2f} for bargein in the ledger with adapter debugging and preflight probes, of a $14.00 "
             f"cap (computed from token usage and list prices, not metered).", "",
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
              f"## Part B: time to the first correct answer (synthetic speech, {res['part_b_items']} questions, one "
              "Kokoro voice each)", "",
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
              "the clock keeps running from the first question."]
    for fact, x in res.get("label_errors", {}).items():
        lines += ["", f"Not scored: the {len(x['items'])} `{fact}` questions ({', '.join(x['items'])}; {x['runs']} runs), "
                  f"a label error: {x['why']}."]
    lines += ["",
              "## Pointe against llm-router, paired by item (synthetic speech)", ""]
    for part, label in (("a", "Part A success (halt, undo, redirect; no false stop)"), ("b", "Part B correct answer")):
        p = res["paired"].get(part)
        if p:
            lines.append(f"- {label}: Pointe {p['pointe']}/{p['items']}, llm-router {p['llm_router']}/{p['items']}, "
                         f"difference {p['delta']:+.0%} [95% bootstrap over items {p['ci95'][0]:+.0%}, {p['ci95'][1]:+.0%}].")
    lg = res["logs"]
    lines += ["", "## What the raw logs show (counted by `run.py report` from events.jsonl)", "",
              f"- Pointe, Part A stop, undo and redirect runs (repeats included): in {lg['pointe_a_forwarded_as_message']} "
              f"of {lg['pointe_a_runs']} the daemon log shows the spoken request sent to the session as a message "
              f"(`-> kiln:`), and in {lg['pointe_a_forwarded_and_job_ran_on']} of those the job still ran to its end. "
              "The voice model's tools at this commit (`daemon.py`, `TOOLS`) have no action that interrupts a working "
              "agent; a message waits while the agent's shell command runs.",
              f"- Keyboard reference, redirect items: in {lg['keyboard_redirect_agent_asked']} of "
              f"{lg['keyboard_redirect_runs']} runs the agent ran nothing after Escape and the typed redirect and its "
              "last reply asked how to redirect (or which option to take). The keyboard arm has no scripted answer to questions, so the redirect "
              "column measures the agent and this scripted user more than the voice path; it does not separate the arms.",
              f"- Pointe, Part B runs (repeats included): in {lg['pointe_b_permission_request']} of {lg['pointe_b_runs']} the "
              "daemon log shows a permission request after the question: the voice model sent the agent to check the "
              "repo, and the agent ran a command outside the item repo, which the settings file does not allow. The "
              "scripted user answers no permission prompt.",
              ""]
    lines += ["## Run-to-run (synthetic speech)", ""]
    for key, f in res["repeats"].items():
        lines.append(f"- {key}: {f['n']} repeated items, flips {f['flips']}, pass^2 {f['pass2']:.0%}.")
    lines += ["", "## Limits", ""] + [f"- {x}" for x in res["limits"]] + [""]
    return "\n".join(lines)


LIMITS = [
    "Synthetic speech only (four Kokoro voices, no noise): an upper bound for every arm. Kokoro is also Pointe's local "
    "voice.",
    "The arms do not share a mouth: the reference arms speak the agent's reply through local Kokoro (no network), "
    "Pointe through its default ElevenLabs voice over the network. First audio and time to a correct answer include "
    "that difference, and the one Whisper transcribes two different voices.",
    "The reference arms (`naive`, `llm-router`, `keyboard`) were written by the team that builds Pointe. No outside "
    "product is tested.",
    "The llm-router prompt was written with the items: the acknowledgements it gives as examples (\"mm-hm\", "
    "\"okay\", \"right\") are words of the backchannel items. Backchannels do not separate the arms: no arm made a "
    "false stop, the keyword arm included.",
    "The fact matcher is regular expressions, checked on canonical answers in every voice. On the run's own answers it "
    "gave one false positive (a \"no\" that began \"No build has run\"); the matcher was fixed and every row "
    "re-scored from its raw log. No person or model judges the answers.",
    "Spend is computed from token usage and list prices (Claude Code session usage; Pointe's daemon log with an assumed "
    "300 output tokens a brain step and a flat allowance for its reader and checker), not metered by the vendors. Claude "
    "Code's own background calls (session titles) are not in its transcript.",
    "The machine ran other workloads, including other benchmark agents, during the runs; the runner waited up to 45 s "
    "(Part A) or 2 minutes (Part B, the latency result) for the 1-minute load average to fall under 12 before each run and flags rows that started above it. "
    "Latency rows with a flag are less reliable.",
    "Small samples: 18 stop-type items and 6 backchannels per arm in Part A, {b} scored questions in Part B. Intervals are wide; "
    "the tables do not rank arms whose intervals overlap.",
    "Part B's facts were read into the agent's context by a typed setup turn before the question (the same in every "
    "arm), so the time measures the voice path, not the agent's search.",
    "The agent's settings file allows the job's shell commands and a hook allows commands that stay inside the item "
    "repo, the same in every arm, so the job's own commands never wait at a prompt; a command outside the item repo "
    "still does, and the scripted user answers no prompt. The hook refuses "
    "any command with `..`, even one that stays inside the repo: such a run waits at a prompt and ends as capped.",
    "The scripted user answers a spoken question back (question detector, slot answers); it does not answer a "
    "question the agent asks in text on the keyboard arm.",
    "The run was resumed twice: once to shorten the load wait for Part A (from 2 minutes to 45 s, after 49 runs), "
    "once to run again the 6 Pointe runs that had failed to start because a Pointe daemon started from /tmp "
    "still held the port (once visibly another benchmark's, run on the same machine and ports). The failed rows stay in rows.jsonl; the later row for the same run is the one counted. Each row carries "
    "the bench commit it ran at; Pointe's commit is the same in every row.",
]


def main(run_id: str | None) -> int:
    ids = [run_id] if run_id else sorted(p.name for p in RESULTS.iterdir() if p.is_dir() and p.name.startswith("bargein-")
                                         and not p.name.endswith("smoke"))
    paid = [(r, e) for r, e in load_runs(ids) if r.get("kind_of_run") == "paid"]
    every = [r for r, _ in paid]
    last = {}
    for r, e in paid:  # a resumed run repeats an errored run: the later row stands, the superseded ones are counted
        last[(r["run_id"], r["part"], r["item"], r["adapter"], r["run_index"])] = (r, e)
    standing = list(last.values())
    excluded = [r for r, _ in standing if label_error(r)]
    rows = [r for r, _ in standing if not label_error(r)]
    superseded = len(every) - len(standing)
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
           "logs": from_logs(standing), "ledger_usd": ledger.spent("bargein"),
           "spend_usd": round(sum(r.get("spend_usd", 0) for r in every), 4), "rows": len(rows),
           "superseded_error_rows": superseded,
           "label_errors": {fact: {"runs": sum(r["kind"] == fact for r in excluded),
                                   "items": sorted({r["item"] for r in excluded if r["kind"] == fact}), "why": why}
                            for fact, (_, why) in LABEL_ERRORS.items() if any(r["kind"] == fact for r in excluded)},
           "part_a": part_a(rows), "part_b": part_b(rows),
           "part_b_items": len({r["item"] for r in rows if r["part"] == "b"}), "repeats": repeats(rows),
           "paired": {p: paired(rows, p) for p in ("a", "b")}}
    res["limits"] = [x.format(b=res["part_b_items"]) for x in LIMITS]
    out = RESULTS / ids[-1] if len(ids) == 1 else RESULTS
    (out / "results.json").write_text(json.dumps(res, indent=1) + "\n")
    (HERE / "RESULTS.md").write_text(markdown(res))
    print(markdown(res))
    return 0
