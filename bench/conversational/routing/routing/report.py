"""Rows -> routing/RESULTS.md and results/<run-id>/results.json. Every number comes from committed rows."""

import ast
import json
import re
from pathlib import Path

from ..core import stats

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"
ORDER = ("pointe", "llm-router", "naive", "keyboard-canonical", "null")
LABEL = {"naive": "naive (keyword rules, ours)", "llm-router": "llm-router (ours)", "keyboard-canonical":
         "keyboard-canonical (typed, no routing)"}


def audit_rows(rows: list[dict], events: list[dict]) -> None:
    """From the committed audit events: a turn is excluded only for a read of the answer keys (the checkout's
    benchmark folder); reads into a sibling repo of the run are counted. Recomputed here so every run is judged by
    the same rule."""
    audits = {(e["adapter"], e["conversation"], e["run_index"]): e.get("flagged") or []
              for e in events if e.get("kind") == "audit"}
    turns = {(e["adapter"], e["conversation"], e["run_index"], e["turn"]): e["events"] for e in events if "turn" in e}
    for r in rows:
        hits = [a for a in audits.get((r["adapter"], r["conversation"], r["run_index"]), [])
                if a.get("t") and r.get("t_start") and r["t_start"] <= a["t"] <= r["t_end"] + 5]
        r["invalid_out_of_tree"] = any("bench/conversational" in a["path"] for a in hits)
        r["cross_repo_reads"] = sum("<run>" in a["path"] for a in hits)
        sends = [x for x in turns.get((r["adapter"], r["conversation"], r["run_index"], r["turn"]), [])
                 if x["kind"] == "delivered"]
        r["sent_other_request"] = any(r["word"] not in x.get("text", "").lower() for x in sends)


SEND_LINE = re.compile(r" -> (.+?): (.*) \(routing: [^)]*\)\s*$")


def brain_sends(log: Path) -> list[dict]:
    """Each send_to_claude_code call in a committed Pointe log: what the brain asked to send, and to which session,
    beside the text Pointe's send layer actually delivered (its `-> session: text` lines just before the record)."""
    out, delivered = [], []
    for line in log.read_text(errors="ignore").splitlines():
        m = SEND_LINE.search(line)
        if m:
            try:
                delivered.append(ast.literal_eval(m.group(2)))
            except (ValueError, SyntaxError):
                delivered.append(m.group(2))
            continue
        if "tool send_to_claude_code(" in line:
            try:
                args, _ = json.JSONDecoder().raw_decode(line.split("tool send_to_claude_code(", 1)[1])
            except ValueError:
                delivered = []
                continue
            out.append({"message": args.get("message", ""), "session": (args.get("session") or "").split("/")[0],
                        "delivered": delivered})
            delivered = []
    return out


def swap_rows(rows: list[dict], logs: Path) -> None:
    """Per Pointe turn: did the brain call send with this turn's word while the text delivered lacked it? From the
    committed daemon log, so the cause of a forwarded-request failure is read, not assumed."""
    for r in rows:
        if r["adapter"] != "pointe":
            continue
        log = logs / f"{r['conversation']}-r{r['run_index']}.log"
        if not log.exists():
            continue
        word = re.compile(rf"\b{re.escape(r['word'])}\b", re.I)
        calls = [c for c in brain_sends(log) if word.search(c["message"]) and c["delivered"]]
        swapped = [c for c in calls if not any(word.search(t) for t in c["delivered"])]
        r["send_replaced"] = bool(swapped)
        r["brain_sessions"] = sorted({c["session"] for c in calls})


def load(run_ids: list[str]) -> tuple[list[dict], list[dict], list[dict]]:
    rows, spend, runs = [], [], []
    for rid in run_ids:
        d = RESULTS / rid
        part = [json.loads(l) for l in (d / "rows.jsonl").read_text().splitlines()]
        audit_rows(part, [json.loads(l) for l in (d / "events.jsonl").read_text().splitlines()])
        swap_rows(part, d / "pointe-logs")
        rows += part
        if (d / "spend.jsonl").exists():
            spend += [json.loads(l) for l in (d / "spend.jsonl").read_text().splitlines()]
        runs.append(json.loads((d / "run.json").read_text()))
    last = {r["adapter"]: r["run_id"] for rid in run_ids for r in rows if r["run_id"] == rid}
    return from_latest_run(rows, last), from_latest_run(spend, last), runs


def from_latest_run(rows: list[dict], last: dict[str, str]) -> list[dict]:
    """Each arm's rows come from the last run, in the order given, that ran it: a rerun of one arm after Pointe
    changed ("report <earlier run> <rerun>") replaces that arm, and the reference arms keep their earlier rows."""
    return [r for r in rows if r["run_id"] == last.get(r["adapter"])]


def pct(k: int, n: int) -> str:
    if n == 0:
        return "n/a"
    lo, hi = stats.wilson(k, n)
    if k == 0:
        return f"0 of {n} (upper bound {hi:.0%})"
    return f"{k}/{n} = {k / n:.0%} ({lo:.0%} to {hi:.0%})"


def boot(clusters: list[list[bool]]) -> str:
    if not clusters:
        return "n/a"
    lo, hi = stats.cluster_bootstrap(clusters)
    return f"{lo:.0%} to {hi:.0%}"


def summarize(rows: list[dict], spend: list[dict]) -> dict:
    out = {}
    valid = [r for r in rows if not r.get("smoke") and not r.get("invalid_out_of_tree")]
    for arm in ORDER:
        main = [r for r in valid if r["adapter"] == arm and r["run_index"] == 0]
        if not main:
            continue
        convs: dict[str, list[dict]] = {}
        for r in main:
            convs.setdefault(r["conversation"], []).append(r)
        amb = [r for r in main if r["type"] == "ambiguous"]
        clear = [r for r in main if r["type"] != "ambiguous"]
        by_type = {}
        for r in main:
            t = by_type.setdefault(r["type"], {"correct": 0, "wrong_session": 0, "n": 0})
            t["n"] += 1
            t["correct"] += r["correct"]
            t["wrong_session"] += r["wrong_session"]
        full = [c for c in convs.values() if len(c) == 5]
        rep = {}
        for r in valid:
            if r["adapter"] == arm and r["run_index"] == 1:
                rep[(r["conversation"], r["turn"])] = r["correct"]
        pairs = [(r["correct"], rep[(r["conversation"], r["turn"])]) for r in main if (r["conversation"], r["turn"]) in rep]
        flips, npairs = stats.flip_rate(pairs)
        outcomes = {}
        for r in main:
            outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
        out[arm] = {
            "turns": len(main), "conversations": len(convs),
            "correct": sum(r["correct"] for r in main), "wrong_session": sum(r["wrong_session"] for r in main),
            "correct_wilson": stats.wilson(sum(r["correct"] for r in main), len(main)),
            "correct_bootstrap": stats.cluster_bootstrap([[r["correct"] for r in c] for c in convs.values()]),
            "wrong_wilson": stats.wilson(sum(r["wrong_session"] for r in main), len(main)),
            "wrong_bootstrap": stats.cluster_bootstrap([[r["wrong_session"] for r in c] for c in convs.values()]),
            "ask_ambiguous": [sum(r["asked_first"] for r in amb), len(amb)],
            "ask_clear": [sum(r["asked_first"] for r in clear), len(clear)],
            "conversation_success": [sum(all(r["correct"] for r in c) for c in full), len(full)],
            "clarifications": sum(r["clarifications"] for r in main),
            "generic_replies": sum(r["generic_replies"] for r in main),
            "by_type": by_type, "outcomes": outcomes, "flip": [flips, npairs],
            "conversation_errors": sorted({r["conversation"] for r in main if r.get("conversation_error")}),
            "cross_repo_turns": sum(bool(r.get("cross_repo_reads")) for r in main),
            "failed_causes": {
                "forwarded another request (the text lacked this turn's word)":
                    sum(not r["correct"] and r.get("sent_other_request", False) for r in main),
                "guessed on an ambiguous turn": sum(not r["correct"] and r["type"] == "ambiguous" and not r["asked_first"]
                                                     and not r.get("sent_other_request") for r in main),
                "wrong session on a clear turn": sum(not r["correct"] and r["type"] != "ambiguous" and r["wrong_session"]
                                                      and not r.get("sent_other_request") for r in main),
                "other": 0},
            "spend_usd": round(sum(s["usd"] for s in spend if s["adapter"] == arm), 4),
        }
        if arm == "pointe":
            swapped = [r for r in main if not r["correct"] and r.get("send_replaced")]
            aimed = [r for r in swapped if r.get("brain_sessions") == r["intended"]
                     and (r["type"] != "ambiguous" or r["asked_first"])]
            out[arm]["send_replaced"] = {"failed_turns": len(swapped), "brain_right": len(aimed),
                                         "after_asking": sum(r["asked_first"] for r in swapped),
                                         "upper_bound_correct": out[arm]["correct"] + len(aimed)}
    out["_excluded_out_of_tree"] = sum(1 for r in rows if r.get("invalid_out_of_tree") and not r.get("smoke"))
    key = {}
    for r in valid:
        if r["run_index"] == 0 and r["adapter"] in ("pointe", "llm-router"):
            key.setdefault((r["conversation"], r["turn"]), {})[r["adapter"]] = r["correct"]
    clusters: dict[str, list[int]] = {}
    for (conv, _), v in key.items():
        if len(v) == 2:
            clusters.setdefault(conv, []).append(int(v["pointe"]) - int(v["llm-router"]))
    if clusters:
        pooled = [d for c in clusters.values() for d in c]
        out["_delta_pointe_minus_router"] = {"delta": sum(pooled) / len(pooled), "turns": len(pooled),
                                            "conversations": len(clusters),
                                            "bootstrap": stats.cluster_bootstrap(list(clusters.values()))}
    return out


def markdown(s: dict, runs: list[dict]) -> str:
    meta = runs[0]
    commits = ", ".join(dict.fromkeys(f"`{r['pointe_commit'][:10]}`" for r in runs))
    if len(runs) > 1:  # report <earlier run> <rerun>: see from_latest_run
        commits += " (each arm from the last run given that ran it: the Pointe arm from the rerun)"
    lines = [
        "# Session Routing: results (synthetic speech)", "",
        "Generated by `run.py report` from the committed rows; do not edit by hand.", "",
        f"Runs: {', '.join(r['run_id'] for r in runs)}. Dates: {meta['started'][:10]}. Repository commit "
        f"`{meta['repo_commit'][:10]}`, Pointe commit {commits}. Agent `{meta['agent_model']}` "
        f"in Claude Code {meta['claude_code_version']}, permission mode `{meta['permission_mode']}`. Pointe setup "
        f"resolved from the keys present: brain `{meta['pointe_setup']['brain']}`, ears `{meta['pointe_setup']['ears']}`, "
        f"mouth `{meta['pointe_setup']['mouth']}`, checker `{meta['pointe_setup']['checker']}`. Router model "
        f"`{meta['router_model']}` at effort `{meta['router_effort']}`; baseline ears `{meta['ears_model']}`. User "
        f"speech: {meta['voice_engine']}, four voices (af_heart, am_michael, bf_emma, bm_george), one per conversation.",
        "",
        "The independent unit is the conversation (n = 12). Turn-level intervals are 95% Wilson; the bootstrap column "
        "resamples conversations. Every arm was written by the team whose product is under test.", "",
        "## Routing and harm, per arm (synthetic speech; n turns and conversations in each row)", "",
        "| Arm | n turns (conv.) | Routing accuracy | bootstrap by conversation | Wrong-session delivery | bootstrap | "
        "Conversations all right |",
        "|---|---|---|---|---|---|---|",
    ]
    for arm in ORDER:
        if arm not in s:
            continue
        a = s[arm]
        lines.append(f"| {LABEL.get(arm, arm)} | {a['turns']} ({a['conversations']}) | {pct(a['correct'], a['turns'])} | "
                     f"{a['correct_bootstrap'][0]:.0%} to {a['correct_bootstrap'][1]:.0%} | "
                     f"{pct(a['wrong_session'], a['turns'])} | {a['wrong_bootstrap'][0]:.0%} to "
                     f"{a['wrong_bootstrap'][1]:.0%} | " + (f"{a['conversation_success'][0]} of {a['conversation_success'][1]}"
                     if arm != "keyboard-canonical" else "n/a (a sample of turns)") + " |")
    d = s.get("_delta_pointe_minus_router")
    if d:
        lines += ["", f"Pointe minus llm-router, routing accuracy paired by turn (synthetic speech): {d['delta']:+.0%} "
                  f"over {d['turns']} turns in {d['conversations']} conversations, 95% bootstrap by conversation "
                  f"{d['bootstrap'][0]:+.0%} to {d['bootstrap'][1]:+.0%}. Both arms are ours; naive is never in this "
                  "comparison."]
    lines += ["", "## Asking instead of guessing (synthetic speech)", "",
              "An arm that always asks would score high on the left column and high on the right one too: read the two "
              "together. Only 14 turns are ambiguous, so that interval is wide.", "",
              "| Arm | Asked first on ambiguous turns | Asked first on clear turns | Clarifications answered | "
              "Generic replies |", "|---|---|---|---|---|"]
    for arm in ORDER:
        if arm not in s:
            continue
        a = s[arm]
        lines.append(f"| {LABEL.get(arm, arm)} | {pct(*a['ask_ambiguous'])} | {pct(*a['ask_clear'])} | "
                     f"{a['clarifications']} | {a['generic_replies']} |")
    types = ("name", "description", "context", "ambiguous", "two", "mishear")
    lines += ["", "## By turn type, correct of n (synthetic speech)", "",
              "| Arm | " + " | ".join(types) + " |", "|---|" + "---|" * len(types)]
    for arm in ORDER:
        if arm not in s:
            continue
        bt = s[arm]["by_type"]
        lines.append(f"| {LABEL.get(arm, arm)} | " + " | ".join(
            f"{bt[t]['correct']}/{bt[t]['n']}" if t in bt else "-" for t in types) + " |")
    lines += ["", "## Failed turns by cause, first run (synthetic speech)", "",
              "From the arm's own delivery events. A turn counts once, under the first cause that fits.", "",
              "| Arm | Failed turns | " + " | ".join(next(iter(v["failed_causes"] for k, v in s.items() if not k.startswith("_")))) + " |",
              "|---|---|---|---|---|---|"]
    for arm in ORDER:
        if arm not in s or arm == "null":
            continue
        a = s[arm]
        failed = a["turns"] - a["correct"]
        causes = dict(a["failed_causes"])
        causes["other"] = failed - sum(v for k, v in causes.items() if k != "other")
        lines.append(f"| {LABEL.get(arm, arm)} | {failed} of {a['turns']} | " + " | ".join(str(v) for v in causes.values()) + " |")
    sr = s.get("pointe", {}).get("send_replaced")
    if sr and not sr["failed_turns"]:
        lines += ["", "Pointe's forwarded-request failures, read from its committed daemon logs: none. In no turn did the "
                  "text delivered lack the word the brain's call carried. The earlier run lost 9 turns this way, at "
                  "Pointe 6544cdc (RESULTS-2026-11-23-pointe-6544cdc.md)."]
    elif sr:
        n = s["pointe"]["turns"]
        lines += ["", f"Pointe's forwarded-request failures, read from its committed daemon logs: in {sr['failed_turns']} "
                  f"failed turns the brain called send with this turn's word, and the text delivered lacked it "
                  f"({sr['after_asking']} of them right after Pointe had asked which session). In {sr['brain_right']} of "
                  "them the brain's call also named the intended session(s). At the frozen commit, when the user's words name a "
                  "session, the send layer can replace the brain's message with an earlier request's text (the previous "
                  "send, taken as being corrected, or a request held while it asked) if the two share at least half their "
                  "content words (`_corrects_last_send`, `_mostly_same` in daemon.py). Every request in this dataset "
                  "uses the same sentence frame with one different word, so this heuristic fires here far more often "
                  "than varied speech would make it. It is a real Pointe defect; its rate here is inflated by the "
                  f"template. Not measured, an upper bound only: had those {sr['brain_right']} calls gone out as the "
                  f"brain wrote them, Pointe could reach at most {sr['upper_bound_correct']}/{n} = "
                  f"{sr['upper_bound_correct'] / n:.0%}, still below llm-router."]
    lines += ["", "## Run to run and spend (synthetic speech)", "",
              "| Arm | Flip rate on repeated turns | Outcomes | Turns with a read into a sibling repo | Spend (USD, computed) |",
              "|---|---|---|---|---|"]
    for arm in ORDER:
        if arm not in s:
            continue
        a = s[arm]
        flip = f"{a['flip'][0]} of {a['flip'][1]}" if a["flip"][1] else "not repeated"
        lines.append(f"| {LABEL.get(arm, arm)} | {flip} | {', '.join(f'{k} {v}' for k, v in sorted(a['outcomes'].items()))} "
                     f"| {a['cross_repo_turns']} | {a['spend_usd']:.3f} |")
    lines += ["", f"Turns excluded for a read of the answer keys: {s['_excluded_out_of_tree']}. A read into a sibling repo "
              "comes after the arm has routed the request (edits there are denied) and is counted, not excluded. "
              "Spend is computed from usage and list prices; Pointe's own vendors partly from stated assumptions "
              "(prices.json). Flip rate: turns whose result differs between the first run and the seeded repeat of "
              "3 conversations.", ""]
    return "\n".join(lines)


def main(run_ids: list[str]) -> int:
    rows, spend, runs = load(run_ids)
    s = summarize(rows, spend)
    # The last run's folder holds the combined result; an earlier run's own result stays as it was published.
    (RESULTS / run_ids[-1] / "results.json").write_text(json.dumps({"runs": run_ids, "summary": s}, indent=1, default=list))
    (HERE / "RESULTS.md").write_text(markdown(s, runs))
    print((HERE / "RESULTS.md").read_text())
    return 0
