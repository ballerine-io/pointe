"""Rows -> docs/benchmarks/hlk.md and site/pointe/benchmarks/hlk/index.html. Every number on both pages is computed
here from the committed rows; tests/test_conversational_hlk.py regenerates both and fails on any difference.
The reporter refuses a published row with another Pointe commit than FROZEN.json names, or one older than the freeze."""

import html
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

from core import ledger, stats
from hlk import FAMILIES

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
PRERELEASE = json.loads((HERE.parent / "prerelease.json").read_text())["builds"]


def cite(commit: str) -> str:
    """A page's words for a commit: a pre-release build by name (its history is not public), else the hash."""
    return next((words for sha, words in PRERELEASE.items() if sha.startswith(commit) or commit.startswith(sha)), commit[:7])
DOC = ROOT / "docs" / "benchmarks" / "hlk.md"
PAGE = ROOT / "site" / "pointe" / "benchmarks" / "hlk" / "index.html"
ARMS = ["keyboard-canonical", "keyboard-transcript", "pointe", "llm-router", "naive", "null"]
SPOKEN = ["pointe", "llm-router", "naive"]
LABEL = {"keyboard-canonical": "keyboard, canonical", "keyboard-transcript": "keyboard, transcript",
         "pointe": "Pointe", "llm-router": "LLM router", "naive": "keyword rules, ours", "null": "null (does nothing)"}
SUBTITLE = "a pilot voice-only coding benchmark, v0.1, synthetic speech, n = 36 in 12 families"
GROUP = {}


class ReportRefused(RuntimeError):
    pass


def load(results: Path = HERE / "results") -> tuple[list, list, dict]:
    frozen = json.loads((HERE / "FROZEN.json").read_text())
    published, unpublished = [], []
    for path in sorted(results.glob("hlk-*/rows.jsonl")):
        meta = path.parent / "run.json"
        if meta.exists() and json.loads(meta.read_text()).get("stopped"):
            continue  # a run stopped by the operator and not used (its run.json says why)
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("kind") not in ("paid", "unpublished"):
                continue
            if frozen.get("standalone"):
                # Every arm was run again at this freeze: rows of an earlier freeze are not mixed in.
                if row["pointe_commit"] != frozen["pointe_commit"] or row["time"] < frozen["frozen_at"]:
                    continue
                earlier = None
            else:
                earlier = next((e for e in frozen.get("earlier", []) if row["run_id"] in e.get("runs", [])), None)
            if earlier is not None:
                # A run at an earlier freeze: its reference arms run no Pointe code and stand; its Pointe rows are the
                # earlier result, replaced by the rerun at the frozen commit.
                if row["adapter"] == "pointe":
                    continue
                if row["pointe_commit"] != earlier["pointe_commit"] or row["time"] < earlier["frozen_at"]:
                    raise ReportRefused(f"{row['run_id']} {row['item']}: not the earlier freeze it is listed under")
            elif row["pointe_commit"] != frozen["pointe_commit"]:
                raise ReportRefused(f"{row['run_id']} {row['item']}: Pointe commit {row['pointe_commit'][:10]} is not the frozen one")
            elif row["time"] < frozen["frozen_at"]:
                raise ReportRefused(f"{row['run_id']} {row['item']}: older than the freeze")
            (published if row["kind"] == "paid" else unpublished).append(row)
    return replace_reruns(published), replace_reruns(unpublished), frozen


RERUNS: dict = {}


def replace_reruns(rows: list) -> list:
    """A row rerun after a harness fault (core.runner.harness_fault) takes the place of the first row of the same item,
    arm and run index; the first rows stay in the raw data and are counted on the page."""
    reruns = {(r["rerun_of"], r["item"], r["adapter"], r["run_index"]): r for r in rows if r.get("rerun_of")}
    out = []
    for r in rows:
        if r.get("rerun_of"):
            continue
        key = (r["run_id"], r["item"], r["adapter"], r["run_index"])
        if key in reruns:
            RERUNS[r["adapter"]] = RERUNS.get(r["adapter"], 0) + 1
            out.append(reruns[key])
        else:
            out.append(r)
    return out


def brain_timeouts(rows: list, frozen: dict, results: Path = HERE / "results") -> dict:
    """Pointe runs in which it said its brain model took too long, from the raw events: in the published rows, and in
    the earlier freeze's runs (for comparison)."""
    def count(run_ids, keep):
        n = k = 0
        for rid in sorted(run_ids):
            path = results / rid / "events.jsonl"
            for line in path.read_text().splitlines() if path.exists() else []:
                e = json.loads(line)
                if e.get("adapter") != "pointe" or not keep(e):
                    continue
                n += 1
                k += any("The model took too long" in str(h.get("text")) for h in e.get("harness", []) if h["kind"] == "said")
        return k, n

    used = {(r["run_id"], r["item"], r["run_index"]) for r in rows if r["adapter"] == "pointe"}
    earlier = {r for e in frozen.get("earlier", []) for r in e["runs"]}
    return {"now": count({rid for rid, _, _ in used}, lambda e: (e["run_id"], e["item"], e["run_index"]) in used),
            "earlier": count(earlier, lambda e: "unpublished" not in e["item"])}


def read_outs(rows: list, frozen: dict, results: Path = HERE / "results") -> dict:
    """Permission requests Pointe put to the user, from the raw events: read out (a spoken yes can approve them) or
    tap-only ("an approval I can't read out"), in the published Pointe rows and in the earlier freeze's runs."""
    def count(run_ids, keep):
        read = tap = 0
        for rid in sorted(run_ids):
            path = results / rid / "events.jsonl"
            for line in path.read_text().splitlines() if path.exists() else []:
                e = json.loads(line)
                if e.get("adapter") != "pointe" or not keep(e):
                    continue
                for h in e.get("harness", []):
                    text = str(h.get("text")) if h["kind"] == "said" else ""
                    tap += "can't read out" in text
                    read += "can't read out" not in text and bool(re.search(r"wants to .*Should it\?", text))
        return read, tap

    used = {(r["run_id"], r["item"], r["run_index"]) for r in rows if r["adapter"] == "pointe"}
    earlier = {r for e in frozen.get("earlier", []) for r in e["runs"]}
    return {"now": count({rid for rid, _, _ in used}, lambda e: (e["run_id"], e["item"], e["run_index"]) in used),
            "earlier": count(earlier, lambda e: "unpublished" not in e["item"])}


def finals(results: Path = HERE / "results") -> dict:
    """(run, item, arm, run index) -> whether the agent left any task file changed, from results/<run>/final.jsonl."""
    out = {}
    for path in sorted(results.glob("hlk-*/final.jsonl")):
        for f in map(json.loads, path.read_text().splitlines()):
            out[(f["run_id"], f["item"], f["adapter"], f["run_index"])] = any(f["files"].values())
    return out


def underspecified(rows: list) -> str:
    """spelled-out seed 2 spells a dunder name letter by letter without its case; the hidden test wants lower case."""
    item = [r for r in rows if r["item"] == "spelled-out-2" and r.get("outcome") not in ("invalid_out_of_tree", "unsupported")]
    cells = ", ".join(f"{LABEL[a]} {sum(bool(r['success']) for r in item if r['adapter'] == a)} of "
                      f"{sum(1 for r in item if r['adapter'] == a)}" for a in ARMS if any(r["adapter"] == a for r in item))
    return ("One item does not say all that it scores: spelled-out seed 2 spells a dunder name letter by letter and does "
            "not say its case, and the hidden test wants lower case. It stays as frozen. Passes on it: " + cells + ".")


def pct(k, n):
    return f"{100 * k / n:.0f}%" if n else "n/a"


def wil(k, n):
    lo, hi = stats.wilson(k, n)
    if n == 0:
        return "n = 0"
    if k == 0:
        return f"0 of {n} (95% upper bound {100 * hi:.0f}%)"
    return f"{k} of {n}, {100 * k / n:.0f}% (95% CI {100 * lo:.0f} to {100 * hi:.0f}%)"


def analyse(rows: list) -> dict:
    valid = [r for r in rows if r.get("outcome") not in ("invalid_out_of_tree", "unsupported")]
    by = defaultdict(list)
    for r in valid:
        by[(r["adapter"], r["family"])].append(r)
    arms = [a for a in ARMS if any(r["adapter"] == a for r in rows)]
    cells = {(a, f): (sum(bool(r["success"]) for r in by[(a, f)]), len(by[(a, f)])) for a in arms for f in FAMILIES}
    totals = {a: (sum(cells[(a, f)][0] for f in FAMILIES), sum(cells[(a, f)][1] for f in FAMILIES)) for a in arms}
    groups = {}
    for a in arms:
        for g in ("naming", "language", "control"):
            fam = [f for f in FAMILIES if GROUP.get(f) == g]
            groups[(a, g)] = (sum(cells[(a, f)][0] for f in fam), sum(cells[(a, f)][1] for f in fam))

    def gap(a, b):
        pairs = {f: (*cells[(a, f)], *cells[(b, f)]) for f in FAMILIES if cells.get((a, f), (0, 0))[1] and cells.get((b, f), (0, 0))[1]}
        return stats.bootstrap_diff(pairs) if pairs else None

    gaps = {}
    for s in SPOKEN:
        if s in arms:
            gaps[s] = {"canonical": gap("keyboard-canonical", s) if "keyboard-canonical" in arms else None,
                       "transcript": gap("keyboard-transcript", s) if "keyboard-transcript" in arms else None}
    head = gap("pointe", "llm-router") if "pointe" in arms and "llm-router" in arms else None
    runs = defaultdict(lambda: defaultdict(list))
    for r in sorted(valid, key=lambda r: r["run_index"]):
        runs[r["adapter"]][r["item"]].append(bool(r["success"]))
    per_arm = {}
    for a in arms:
        mine = [r for r in rows if r["adapter"] == a]
        ok = [r for r in mine if r.get("outcome") not in ("invalid_out_of_tree", "unsupported")]
        failed = [r for r in ok if not r["success"]]
        passed = [r for r in ok if r["success"]]
        times = [r["wall_secs"] for r in ok if r.get("wall_secs") is not None]
        spend = [r.get("spend_usd", 0.0) for r in mine]
        per_arm[a] = {
            "n": len(ok), "pass2": stats.pass_k(runs[a]), "flips": stats.flips(runs[a]),
            "false_done": (sum(r.get("claim") == "yes" for r in failed), len(failed)),
            # A "no" is false only where the task can be done: on an impossible item it is the right answer.
            "false_not_done": (sum(r.get("claim") == "no" and r.get("expect_done", True) for r in passed), len(passed)),
            "no_claim": sum(r.get("claim") is None for r in ok),
            "clar": sum(r.get("clarifications", 0) for r in ok), "corr": sum(r.get("correctives", 0) for r in ok),
            "time_median": statistics.median(times) if times else None,
            "time_p90": sorted(times)[int(0.9 * (len(times) - 1))] if times else None,
            "spend": sum(spend), "spend_task": (sum(spend) / len(mine)) if mine else 0.0,
            "capped": sum(bool(r.get("capped")) for r in mine), "invalid": sum(r.get("outcome") == "invalid_out_of_tree" for r in mine),
            "errors": sum(r.get("outcome") == "error" for r in mine),
            "no_after_yes": sum(r.get("approvals_no_after_refused_yes") or 0 for r in mine), "unsupported": sum(r.get("outcome") == "unsupported" for r in mine),
            "audio_lock": (sum(r.get("audio_matches_lock") is True for r in mine),
                           sum(r.get("audio_matches_lock") is not None for r in mine)),
        }
    meta = {"dates": sorted({r["time"][:10] for r in rows}), "claude": sorted({r["claude_code_version"] for r in rows}),
            "models": sorted({r["agent_model"] for r in rows}), "runs": sorted({r["run_id"] for r in rows}),
            "brain": sorted({(r.get("adapter_versions") or {}).get("brain") for r in rows if r["adapter"] == "llm-router"} - {None}),
            "items": len({r["item"] for r in rows})}
    return {"arms": arms, "cells": cells, "totals": totals, "groups": groups, "gaps": gaps, "head": head,
            "per_arm": per_arm, "meta": meta}


def refusals(rows: list) -> tuple[list, int, int, int]:
    """Pointe's failed runs; how many of them had a spoken yes that did not take; of those, how many had changed files;
    and how many passed runs had one."""
    prow = [r for r in rows if r["adapter"] == "pointe" and r.get("outcome") not in ("invalid_out_of_tree", "unsupported")]
    pf = [r for r in prow if not r["success"]]
    pf_no_rows = [r for r in pf if r.get("approvals_no_after_refused_yes")]
    pp_no = sum(1 for r in prow if r["success"] and r.get("approvals_no_after_refused_yes"))
    touched = finals()
    pf_edit = sum(1 for r in pf_no_rows if touched.get((r["run_id"], r["item"], r["adapter"], r["run_index"])))
    return pf, len(pf_no_rows), pf_edit, pp_no


def summary(rows, unpub, frozen) -> dict:
    """The headline numbers as data, for the suite pages (bench/conversational/publish.py): results/summary.json."""
    a = analyse(rows)
    ua = defaultdict(lambda: [0, 0])
    for r in unpub:
        if r.get("outcome") not in ("invalid_out_of_tree", "unsupported"):
            ua[r["adapter"]][0] += bool(r["success"])
            ua[r["adapter"]][1] += 1
    pf, pf_no, pf_edit, _ = refusals(rows)
    m = a["meta"]
    return {"benchmark": "hlk", "title": "Humanity's Last Keystroke (HLK)", "subtitle": SUBTITLE, "unit": "family",
            "runs": m["runs"], "dates": m["dates"], "agent_model": m["models"], "claude_code": m["claude"],
            "permission_mode": "acceptEdits", "pointe_commit": frozen["pointe_commit"][:12], "router_brain": m["brain"],
            "families": list(FAMILIES), "arms": a["arms"],
            "passes": {x: list(a["totals"][x]) for x in a["arms"]},
            "per_family": {x: {f: list(a["cells"][(x, f)]) for f in FAMILIES} for x in a["arms"]},
            "gaps": {"keyboard-canonical minus pointe": list(a["gaps"]["pointe"]["canonical"]),
                     "keyboard-canonical minus llm-router": list(a["gaps"]["llm-router"]["canonical"]),
                     "pointe minus llm-router": list(a["head"])},
            "flips": {x: list(a["per_arm"][x]["flips"]) for x in a["arms"]},
            "unpublished": {x: ua[x] for x in ARMS if x in ua},
            "pointe_failed": len(pf), "pointe_failed_refused_yes": pf_no, "pointe_failed_refused_yes_files_changed": pf_edit,
            "spend_usd": round(ledger.spent("hlk"), 2), "cap_usd": 55}


def fmt_gap(g):
    if g is None:
        return "not run"
    d, lo, hi = g
    return f"{100 * d:+.0f} points (95% CI {100 * lo:+.0f} to {100 * hi:+.0f})"


def sections(rows, unpub, frozen) -> list:
    """The page as a list of (kind, payload) blocks, shared by the Markdown and the HTML writers."""
    import hlk
    for f in FAMILIES:
        GROUP[f] = hlk.family(f).GROUP
    a = analyse(rows) if rows else None
    det = json.loads((HERE / "results" / "hlk-detector.json").read_text())
    spent = ledger.spent("hlk")
    B = []
    B.append(("h1", "Humanity's Last Keystroke (HLK)"))
    B.append(("sub", SUBTITLE))
    B.append(("p", "Part of Pointe's release benchmarks (docs/benchmarks/README.md): a self-evaluation harness with an "
                   "adapter interface. One system under test (Pointe) and reference arms written by the same team, on "
                   "synthetic speech. The authors know Pointe's internals. This is not a ranking of products."))
    B.append(("p", "HLK asks whether a small scripted multi-step coding task is finished by voice only, graded by "
                   "hidden tests on the final state of the repository, compared with the keyboard on the same terminal. "
                   "The coding agent is held fixed (claude-haiku-5-5 in Claude Code, permission mode acceptEdits), so the "
                   "score is the loss the voice interface adds, not the strength of the agent. The tasks are small "
                   "Python standard-library edits sized for that agent."))
    B.append(("p", "The name follows Humanity's Last Exam (CAIS and Scale AI, arXiv 2501.14249); HLK is not affiliated "
                   "with it. Humanity's Last Exam has about 2,500 expert questions; HLK has 36 generated tasks: 36 "
                   "instances in 12 families. Seeds only swap names and numbers, so the effective sample size is close to "
                   "12, the families, and the intervals are wide. The suite can show a large gap; it cannot rank two "
                   "close systems."))
    B.append(("h2", "Limits, plainly"))
    earlier_runs = set() if frozen.get("standalone") else {r for e in frozen.get("earlier", []) for r in e.get("runs", [])}
    B.append(("ul", [
        "Synthetic speech is an upper bound for everyone: four clean US and British Kokoro voices are easier than "
        "people. Every table title says synthetic speech.",
        "The arms do not hear or speak alike. The LLM router is handed each utterance whole after it ends, so it never "
        "decides when a turn is over; its recognizer call is retried on a dropped connection, and Pointe's live call is "
        "not. The router speaks through local Kokoro, which the scoring Whisper reads easily; Pointe speaks through "
        "ElevenLabs. The router's own decisions are not logged.",
        "Since 2026-11-25 an item passes only if its task reached the agent (a user prompt between the first scripted "
        "turn and the final question), and the agent's folder has an opaque name: the earlier runs named the item "
        "(\"impossible-as-stated-2-…\") and the arm in the path, which agents read aloud.",
        "No outside product is tested. Every reference arm is written by Pointe's team; we found no way to give audio to "
        "another voice coding tool without a virtual microphone, and the rules forbid microphones.",
        "Pointe's own model sits between the user and the agent and may rewrite an instruction, so a spoken arm can beat "
        "the keyboard arm. The keyboard-transcript arm (the exact spoken words, typed) helps read that.",
        "The scripted user is deterministic, not a person: it answers the questions an item foresees, says one generic "
        "line to any other question, and repeats an instruction at most once.",
        "Costs are computed from usage and list prices, not metered bills.",
        "The keyword-rules arm is ours and is built to fail the adversarial items; no headline number compares Pointe "
        "with it.",
        "Voice only means voice only. Pointe counts a spoken yes only after it has read the request in full, and reads a "
        "command without a short form word for word; the scripted user cannot tap, so after two spoken yeses that did "
        "not take it says no. The count is in the table below.",
        "Other benchmark processes shared the machine during the runs; no row started while the 1-minute load was over "
        "20, and the load at each row's start and end is in the row. Times are wall-clock times of one laptop and one "
        "network."]
        + ([underspecified(rows)] if rows else [])
        + ([f"The first-run rows ran on "
            f"{', '.join(sorted({cite(r['repo_commit']) for r in rows if not r.get('rerun_of') and r['run_id'] in earlier_runs}))}"
            ". A fault of that runner "
            "(an approval answer credited to the next request) was fixed after the run; the rows it hit were rerun by "
            "the rule below, on "
            f"{', '.join(sorted({cite(r['repo_commit']) for r in rows if r.get('rerun_of')})) or 'n/a'}."]
           if rows and earlier_runs else [])
        + ([f"The Pointe arm was run again after Pointe fixed what this suite found: Pointe: {cite(frozen['pointe_commit'])}, "
            "the same agent, instances, voices, seeds and settings. The reference arms run no Pointe code; their rows come "
            f"from the earlier runs ({', '.join(sorted(earlier_runs))}, Pointe: "
            f"{', '.join(sorted({cite(e['pointe_commit']) for e in frozen.get('earlier', [])}))}). The earlier page is "
            "kept as published in docs/benchmarks/earlier/."] if earlier_runs else [])))
    if not a:
        B.append(("p", "No published run yet."))
        return B
    m = a["meta"]
    B.append(("p", f"Runs: {', '.join(m['runs'])}. Dates: {', '.join(m['dates'])}. Agent: {', '.join(m['models'])} in "
                   f"Claude Code {', '.join(m['claude'])}. Pointe: {cite(frozen['pointe_commit'])}, frozen before "
                   f"its first paid row ({frozen['frozen_at'][:10]}). Router brain: {', '.join(m['brain']) or 'n/a'}. "
                   f"Spoken output of every arm is read by one pinned local Whisper (large-v3-turbo)."))
    stops = []
    for rid in m["runs"]:
        meta_path = HERE / "results" / rid / "run.json"
        if meta_path.exists() and json.loads(meta_path.read_text()).get("stopped"):
            stops.append(json.loads(meta_path.read_text())["stopped"])
    B.append(("p", ("The run stopped early: " + "; ".join(stops) + ". Trim order, had it been needed: unpublished seeds, then "
                    "the keyword-rules arm, then the second keyboard-transcript run.") if stops else
              "Every planned run finished inside the cap; nothing was trimmed."))
    arms = a["arms"]
    head = ["family", "group"] + [LABEL[x] for x in arms]
    body = [[f, GROUP[f]] + [f"{a['cells'][(x, f)][0]}/{a['cells'][(x, f)][1]}" for x in arms] for f in FAMILIES]
    body.append(["all 12 families", ""] + [f"{a['totals'][x][0]}/{a['totals'][x][1]}" for x in arms])
    B.append(("h2", "Passes per family (synthetic speech)"))
    counts = defaultdict(int)
    for r in rows:
        if r["adapter"] == "pointe":
            counts[r["item"]] += 1
    per_item = max(counts.values(), default=0)
    B.append(("p", "Cells are passes over runs of the 3 instances of a family" +
                   (f" ({per_item} runs of each)" if per_item else "") + ". A pass is: the task reached the agent, the "
                   "hidden tests pass and the protected files are unchanged; for impossible-as-stated, the files are "
                   "unchanged and the answer to the last question is an explicit no."))
    B.append(("table", (head, body)))
    B.append(("h2", "The voice gap (synthetic speech)"))
    B.append(("p", "Keyboard minus the spoken arm, in percentage points, paired by family, with a 95% bootstrap interval "
                   "over the 12 families. A negative gap means the spoken arm passed more often."))
    gb = []
    for s in [x for x in ("pointe", "llm-router") if x in a["gaps"]]:
        gb.append([LABEL[s], fmt_gap(a["gaps"][s]["canonical"]), fmt_gap(a["gaps"][s]["transcript"])])
    B.append(("table", (["spoken arm", "keyboard, canonical minus it", "keyboard, transcript minus it"], gb)))
    B.append(("p", f"Pointe minus the LLM router, paired by family: {fmt_gap(a['head'])}."))
    B.append(("p", "Overall pass rates (runs, not independent; for orientation only): " +
                   "; ".join(f"{LABEL[x]} {wil(*a['totals'][x])}" for x in arms) + "."))
    B.append(("h2", "Claims at the end of the task, paired (synthetic speech)"))
    B.append(("p", "Every task ends with \"Is it done, and do the tests pass? Yes or no.\" False done is a yes on a run "
                   "that failed, over the failed runs; false not done is a no on a run that passed, over the passed runs. "
                   "The denominators are small, so this is not a robust number. An answer that cannot be read is no claim."))
    cb = [[LABEL[x], wil(*a["per_arm"][x]["false_done"]), wil(*a["per_arm"][x]["false_not_done"]), str(a["per_arm"][x]["no_claim"])]
          for x in arms]
    B.append(("table", (["arm", "false done", "false not done", "no claim"], cb)))
    B.append(("h2", "Stability, effort, time and spend (synthetic speech)"))
    sb = []
    for x in arms:
        p = a["per_arm"][x]
        tm = f"{p['time_median']:.0f} s / {p['time_p90']:.0f} s" if p["time_median"] is not None else "n/a"
        sb.append([LABEL[x], f"{p['pass2'][0]}/{p['pass2'][1]}" if p["pass2"][1] else "n/a",
                   f"{p['flips'][0]}/{p['flips'][1]}" if p["flips"][1] else "n/a",
                   f"{p['clar'] / p['n']:.2f}" if p["n"] else "n/a", f"{p['corr'] / p['n']:.2f}" if p["n"] else "n/a",
                   tm, f"${p['spend_task']:.3f}", str(p["capped"]), str(p["invalid"]), str(p["errors"]), str(p["no_after_yes"])])
    B.append(("table", (["arm", "pass^k (items)", "flips (items)", "clarifications per task", "corrective turns per task",
                         "time median / p90", "spend per task", "capped", "invalid (out of tree)", "errors",
                         "no said after two yeses did not take"], sb)))
    B.append(("p", "pass^k: instances whose every run passed. Flips: instances whose first two runs disagree. A clarification "
                   "is a question the item foresaw, answered (no penalty); a corrective turn is a repeated instruction. "
                   "Capped runs (12 user turns, 10 minutes, or $0.60) count as failures. Invalid runs named a path outside "
                   "the item's folder in a tool call and are excluded from the passes. Errors are runs the harness could "
                   "not finish; they count as failures."))
    if "pointe" in arms:
        pf, pf_no, pf_edit, pp_no = refusals(rows)
        B.append(("p", f"Where Pointe lost runs: in {pf_no} of its {len(pf)} failed runs at least one spoken yes did not "
                       "take and the scripted user then said no. That counts runs, not causes. "
                       f"In {pf_no - pf_edit} of those {pf_no} the agent changed no file, so the work stopped at the "
                       f"refusal or after it. In the other {pf_edit} the agent had already changed files and the hidden "
                       f"tests still failed. {pp_no} runs passed despite such a refusal. The other arms act on a "
                       "spoken yes for any command: they have no such guard."))
    if "pointe" in arms:
        slow = brain_timeouts(rows, frozen)
        if slow["now"][0]:
            B.append(("p", f"The brain model was slow during the Pointe runs: in {slow['now'][0]} of {slow['now'][1]} its step "
                           "passed Pointe's 8 s limit (its fallback's too) and Pointe said \"The model took too long to "
                           "answer\"" + (f"; in the earlier Pointe runs, {slow['earlier'][0]} of {slow['earlier'][1]}"
                                          if slow["earlier"][1] else "") + ". Those runs measure the vendor's latency at "
                           "the time as much as Pointe."))
        ro = read_outs(rows, frozen)
        if earlier_runs:
            B.append(("p", f"Permission requests Pointe put to the user: {ro['now'][0]} read out, which a spoken yes can "
                           f"approve, and {ro['now'][1]} tap-only; in the earlier Pointe runs, {ro['earlier'][0]} and "
                           f"{ro['earlier'][1]}."))
    reruns = ", ".join(f"{LABEL[k]} {v}" for k, v in sorted(RERUNS.items())) or "none"
    B.append(("p", "Harness faults: a run in which Claude Code showed a permission prompt without firing its hook, the "
                   "runner credited an answer to the wrong request, or the agent made no step for 8 minutes was rerun "
                   f"once with the same voice and run index, by that rule and in every arm. Reruns: {reruns}. The first "
                   "rows stay in the raw data."))
    B.append(("h2", "Passes by stressor group (synthetic speech)"))
    gr = [[g] + [f"{a['groups'][(x, g)][0]}/{a['groups'][(x, g)][1]}" for x in arms] for g in ("naming", "language", "control")]
    B.append(("table", (["group"] + [LABEL[x] for x in arms], gr)))
    if unpub:
        ua = defaultdict(lambda: [0, 0])
        for r in unpub:
            if r.get("outcome") in ("invalid_out_of_tree", "unsupported"):
                continue
            ua[r["adapter"]][0] += bool(r["success"])
            ua[r["adapter"]][1] += 1
        B.append(("h2", "Unpublished seeds, an overfit check (synthetic speech)"))
        B.append(("p", "One extra seed per family, kept out of the repository (its manifest SHA-256 is in FROZEN.json), "
                       "one run each. This is not a held-out split: the team that scores its own product holds it, and the "
                       "generators are public. It only shows whether the results depend on the published seeds."))
        B.append(("table", (["arm", "passes"], [[LABEL[x], wil(*ua[x])] for x in ARMS if x in ua])))
    B.append(("h2", "How it was measured"))
    B.append(("ul", [
        "One launch line for every arm: interactive claude --model claude-haiku-5-5 --permission-mode acceptEdits in a "
        "pseudo-terminal in the task repository, with a fresh CLAUDE_CONFIG_DIR and the API key in its environment only "
        "(Bash commands still ask). The Pointe arm adds only --plugin-dir and joins with /pointe:voice. No arm uses "
        "claude -p or --bare. A preflight checked that sessions are billed to the API key, load no user plugins and run "
        "in acceptEdits.",
        "Arms: keyboard, canonical (the instruction as a person would type it; approve, deny and Escape as keypresses at "
        "the same triggers; the reference ceiling); keyboard, transcript (the exact spoken words, typed: perfect ears); "
        "null (starts the sessions, does nothing: the floor); keyword rules, ours (Soniox ears, first word naming a "
        "session, yes, no and stop keywords, speaks the agent's final message through local Kokoro); LLM router (Soniox "
        "ears, one call per utterance to the brain model of Pointe's default setup with a published 20-line prompt, "
        "speech through local Kokoro: the baseline for the head-to-head); Pointe (an isolated daemon in its default "
        "setup, audio in over the page's call, audio out recorded).",
        "Answer keys: hidden tests and the reference patch are written before the session to a folder no arm is given; "
        "every config dir denies reads of it and of the bench; every transcript was audited for tool calls naming a path "
        "outside the item.",
        f"Scripted user: triggers, slot answers, a question detector (final sentence a question, a wh-word or an "
        f"auxiliary first, or phrases such as \"which one\"). On {det['lines']} labelled lines rendered by Kokoro and read "
        f"by Whisper it was right on {det['correct']} ({100 * det['accuracy']:.0f}%).",
        "Item order was shuffled by a recorded seed and the runner went item by item across all arms in one launch, so "
        "every arm met the same hours of vendor latency, and a stop at the budget would have left a random subsample "
        "with every arm present.",
        "Speech: Kokoro-82M v1.0 (Apache-2.0), four voices (US and British, female and male), one seeded voice per "
        "instance for both runs; noise made in code (babble from the three other voices at 6 dB for the noisy-paths "
        "instruction, pink noise at 12 dB for the rest of that item)."]))
    B.append(("h2", "Run it, add to it"))
    B.append(("code", "uv run --locked --extra local python bench/conversational/hlk/run.py corpus\n"
                      "uv run --locked --extra local python bench/conversational/hlk/run.py verify\n"
                      "HLK_POINTE_CHECKOUT=<a checkout at the frozen commit> uv run --locked --extra local python "
                      "bench/conversational/hlk/run.py hlk --adapter keyboard-canonical,null,llm-router,pointe --runs 3 "
                      "--workers 2 --port-base 9300 --budget-usd <the ledger's total plus this run>"))
    B.append(("p", "An adapter implements start, say, type, key, events, speech, versions, spend and stop "
                   "(bench/conversational/hlk/core/adapter.py); a missing capability shows as coverage, never as a failure. "
                   "A family is a generator in bench/conversational/hlk/hlk/families/; hlk/CONTRIBUTING.md says how, and "
                   "run.py verify (free) proves its check goes red and green. Accepted authors are named here. A better "
                   "router prompt is welcome as a pull request. Family authors so far: the Pointe team."))
    B.append(("p", f"Spend: ${spent:.2f} for HLK in all, every launch since 2026-11-23 (smoke and debugging included), computed from usage and "
                   "list prices in bench/conversational/hlk/prices.json. Raw rows and the final files of every published run "
                   "(run.py verify re-scores them): bench/conversational/hlk/results/. Text and "
                   "tasks CC BY 4.0, code MIT."))
    return B


def markdown(blocks) -> str:
    out = []
    for kind, x in blocks:
        if kind == "h1":
            out.append(f"# {x}\n")
        elif kind == "sub":
            out.append(f"*{x}*\n")
        elif kind == "h2":
            out.append(f"## {x}\n")
        elif kind == "p":
            out.append(x + "\n")
        elif kind == "ul":
            out.append("\n".join(f"- {i}" for i in x) + "\n")
        elif kind == "code":
            out.append(f"```\n{x}\n```\n")
        elif kind == "table":
            head, body = x
            out.append("| " + " | ".join(head) + " |\n|" + "---|" * len(head) + "\n" +
                       "\n".join("| " + " | ".join(r) + " |" for r in body) + "\n")
    return "<!-- Written by bench/conversational/hlk/run.py report from the committed rows. Do not edit by hand. -->\n\n" + "\n".join(out)


def page(blocks) -> str:
    e = html.escape
    parts = []
    for kind, x in blocks:
        if kind == "h1":
            parts.append(f'  <section class="pg-hero">\n    <p class="pg-kicker">Benchmarks</p>\n    <h1 class="pg-h1">{e(x)}</h1>')
        elif kind == "sub":
            parts.append(f'    <p class="pg-lead">{e(x)}</p>\n  </section>')
        elif kind == "h2":
            parts.append(f'  <div class="pg-section-head"><h2 class="pg-h2">{e(x)}</h2></div>')
        elif kind == "p":
            parts.append(f"  <p>{e(x)}</p>")
        elif kind == "ul":
            parts.append("  <ul>\n" + "\n".join(f"    <li>{e(i)}</li>" for i in x) + "\n  </ul>")
        elif kind == "code":
            parts.append(f'  <pre class="pg-term"><code>{e(x)}</code></pre>')
        elif kind == "table":
            head, body = x
            parts.append('  <div class="bm-scroll"><table class="bm-table">\n    <thead><tr>' +
                         "".join(f"<th>{e(h)}</th>" for h in head) + "</tr></thead>\n    <tbody>\n" +
                         "\n".join("      <tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in body) +
                         "\n    </tbody>\n  </table></div>")
    return TEMPLATE.replace("{BODY}", "\n".join(parts))


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Humanity's Last Keystroke: Pointe benchmarks</title>
<meta name="description" content="Humanity's Last Keystroke: a pilot voice-only coding benchmark, v0.1, synthetic speech, n = 36 in 12 families.">
<meta name="referrer" content="no-referrer">
<meta name="color-scheme" content="light dark">
<meta property="og:title" content="Humanity's Last Keystroke">
<meta property="og:description" content="A pilot voice-only coding benchmark, v0.1, synthetic speech, n = 36 in 12 families.">
<meta property="og:image" content="https://eng.ballerine.com/pointe/social.png">
<meta property="og:url" content="https://eng.ballerine.com/pointe/benchmarks/hlk/">
<script>
  // The old address: Cloudflare Pages cannot redirect by host, so the page does it.
  if (location.hostname === 'pointe.ballerine.com') location.replace('https://eng.ballerine.com/pointe/benchmarks/hlk/' + location.hash);
</script>
<link rel="icon" href="../../brand/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="../../style.css">
<link rel="stylesheet" href="../../pages.css">
<style>
  .bm-scroll { overflow-x: auto; margin: 1rem 0 1.5rem; }
  .bm-table { border-collapse: collapse; font-size: 0.9rem; min-width: 100%; }
  .bm-table th, .bm-table td { border-bottom: 1px solid color-mix(in srgb, currentColor 18%, transparent); padding: 0.4rem 0.6rem; text-align: left; vertical-align: top; }
  .bm-table th { font-weight: 600; }
  main p, main li { max-width: 72ch; }
</style>
</head>
<body class="pg">
<a class="pg-skip" href="#main">Skip to content</a>
<header class="pg-wrap pg-header">
  <a class="pg-wordmark" href="../../"><picture><source srcset="../../brand/lockup-small-on-dark.svg" media="(prefers-color-scheme: dark)"><img src="../../brand/lockup-small.svg" width="112" height="32" alt="Pointe"></picture></a>
  <nav aria-label="Pages">
    <a href="../../features/">Features</a>
    <a href="../../docs/">Docs</a>
    <a href="../" aria-current="true">Benchmarks</a>
    <a href="../../roadmap/">Roadmap</a>
    <a href="../../contribute/">Contribute</a>
    <a class="pg-gh" href="https://github.com/ballerine-io/pointe">GitHub</a>
  </nav>
</header>
<main id="main" class="pg-wrap">
{BODY}
</main>
<footer class="pg-wrap"><p>Pointe <span data-version>VERSION</span>. Written by bench/conversational/hlk/run.py report from the committed rows.</p></footer>
</body>
</html>
"""


SUMMARY = HERE / "results" / "summary.json"


def build() -> tuple[str, str]:
    return build_all()[:2]


def build_all() -> tuple[str, str, str]:
    rows, unpub, frozen = load()
    blocks = sections(rows, unpub, frozen)
    data = json.dumps(summary(rows, unpub, frozen), indent=1) + "\n"
    version = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    text = markdown(blocks)
    html_page = page(blocks).replace("<span data-version>VERSION</span>", f"<span data-version>{version}</span>")
    for name, body in (("doc", text), ("page", html_page)):
        if re.search(r"\bleaderboard\b|\breal\b", body, re.I):
            raise ReportRefused(f"the {name} uses a word the page must not use")
    return text, html_page, data


def main(args=None) -> int:
    text, html_page, data = build_all()
    SUMMARY.write_text(data)
    DOC.write_text(text)
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(html_page)
    print(f"wrote {DOC.relative_to(ROOT)}, {PAGE.relative_to(ROOT)} and {SUMMARY.relative_to(ROOT)}")
    return 0
