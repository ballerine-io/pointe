"""Spoken Identifiers: committed rows -> results/<run-id>/summary.json and summary.md. No number is typed by hand.

Published rows: not smoke, the frozen Pointe commit, not `invalid_out_of_tree`, not `error` (errors and invalid rows
are counted per arm in their own columns). The independent unit is the target (n = 24): intervals are Wilson on runs
and a bootstrap that resamples targets.
"""

import json
from pathlib import Path

from core import stats

HERE = Path(__file__).resolve().parents[1]
ORDER = ("keyboard-canonical", "keyboard-transcript", "pointe", "pointe-text", "llm-router", "naive", "null")
TITLE = "Spoken Identifiers, synthetic speech (Kokoro-82M, 4 voices)"


def rows(run_id: str) -> list[dict]:
    p = HERE / "results" / run_id / "rows.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def pct(k: int, n: int) -> dict:
    lo, hi = stats.wilson(k, n)
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "wilson95": [round(lo, 4), round(hi, 4)]}


def arm_table(rs: list[dict]) -> dict:
    n = len(rs)
    c = lambda o: sum(r["outcome"] == o for r in rs)  # noqa: E731
    right = [r for r in rs if r["outcome"] == "right_symbol"]
    exact = [r for r in rs if r.get("delivered_exact") is not None]
    out = {"n_runs": n, "n_targets": len({r["target"] for r in rs}),
           "right_symbol": pct(c("right_symbol"), n), "wrong_symbol": pct(c("wrong_symbol"), n),
           "no_action": pct(c("no_action"), n), "other_change": pct(c("other_change"), n), "capped": c("capped"),
           "right_symbol_bootstrap_by_target95": [round(x, 4) for x in stats.cluster_bootstrap(
               rs, lambda r: r["target"], lambda r: r["outcome"] == "right_symbol")] if rs else None,
           "marker_exact_of_right": pct(sum(bool(r.get("marker_exact")) for r in right), len(right)),
           "clarifications": sum(r.get("clarifications", 0) for r in rs),
           "median_s_to_done": median([r["s_to_done"] for r in rs if r.get("s_to_done") is not None]),
           "spend_usd": round(sum(r.get("spend_usd", 0) for r in rs), 4)}
    if exact:
        out["delivered_exact"] = pct(sum(bool(r["delivered_exact"]) for r in exact), len(exact))
    return out


def median(xs: list[float]):
    xs = sorted(xs)
    return round(xs[len(xs) // 2], 2) if xs else None


def by_target(rs: list[dict]) -> dict:
    out: dict = {}
    for r in rs:
        out.setdefault(r["target"], []).append(r["outcome"] == "right_symbol")
    return out


def summarize(run_id: str, frozen: dict | None, arm_from: dict | None = None, why: str = "") -> dict:
    """arm_from: arm -> another run id whose rows replace this run's rows of that arm (a harness bug fixed and the
    arm rerun). The replaced rows stay committed and are counted under "superseded"."""
    arm_from = arm_from or {}
    allr = rows(run_id)
    superseded = {a: sum(r["arm"] == a for r in allr) for a in arm_from}
    allr = [r for r in allr if r["arm"] not in arm_from]
    for a, other in arm_from.items():
        allr += [r for r in rows(other) if r["arm"] == a]
    bad = lambda r: r.get("smoke") or r["outcome"] in ("invalid_out_of_tree", "error")  # noqa: E731
    pub = [r for r in allr if not bad(r) and r["run_index"] == 0
           and (not frozen or r["pointe_commit"] == frozen["pointe_commit"])]
    arms = [a for a in ORDER if any(r["arm"] == a for r in allr)]
    summary = {"title": TITLE, "run_id": run_id, "frozen": frozen, "unit": "target (n = 24)",
               "excluded": {a: {"invalid_out_of_tree": sum(r["arm"] == a and r["outcome"] == "invalid_out_of_tree"
                                                         for r in allr),
                                "error": sum(r["arm"] == a and r["outcome"] == "error" for r in allr)} for a in arms},
               "arms": {}, "slices": {}, "paired": {}, "repeat": {},
               "superseded": {a: {"rows": n, "replaced_by_run": arm_from[a], "why": why} for a, n in superseded.items()}}
    for a in arms:
        rs = [r for r in pub if r["arm"] == a]
        summary["arms"][a] = arm_table(rs)
        sl = {}
        for cls in sorted({r["class"] for r in rs}):
            x = [r for r in rs if r["class"] == cls]
            sl[f"class={cls}"] = {"right_symbol": pct(sum(r["outcome"] == "right_symbol" for r in x), len(x)),
                                  "wrong_symbol": pct(sum(r["outcome"] == "wrong_symbol" for r in x), len(x))}
        for noise in sorted({r["noise"] for r in rs}):
            x = [r for r in rs if r["noise"] == noise]
            sl[f"noise={noise}"] = {"right_symbol": pct(sum(r["outcome"] == "right_symbol" for r in x), len(x)),
                                    "wrong_symbol": pct(sum(r["outcome"] == "wrong_symbol" for r in x), len(x))}
        summary["slices"][a] = sl
    for a, b in (("pointe", "llm-router"), ("pointe", "keyboard-canonical"), ("pointe", "keyboard-transcript"),
                 ("llm-router", "keyboard-canonical"), ("pointe-text", "pointe")):
        if a in arms and b in arms:
            d, lo, hi = stats.paired_bootstrap(by_target([r for r in pub if r["arm"] == a]),
                                               by_target([r for r in pub if r["arm"] == b]))
            summary["paired"][f"{a} - {b}"] = {"right_symbol_diff": round(d, 4), "bootstrap95_by_target":
                                                [round(lo, 4), round(hi, 4)]}
    for a in ("pointe", "llm-router"):
        reps = [r for r in allr if r["arm"] == a and r["run_index"] == 1 and not bad(r)]
        firsts = {r["clip"]: r for r in pub if r["arm"] == a}
        pairs = [(firsts[r["clip"]]["outcome"] == "right_symbol", r["outcome"] == "right_symbol")
                 for r in reps if r["clip"] in firsts]
        if pairs:
            summary["repeat"][a] = {"n_pairs": len(pairs), "flip_rate": round(stats.flip_rate(pairs), 4),
                                    "flips": sum(x != y for x, y in pairs),
                                    "pass2": round(stats.pass_k([[x, y] for x, y in pairs]), 4)}
    meta = pub[0] if pub else (allr[0] if allr else {})
    summary["conditions"] = {
        "dates": sorted({r["time"][:10] for r in pub}), "repo_commits": sorted({r["repo_commit"] for r in pub}),
        "run_ids": sorted({r["run_id"] for r in pub}),
        "pointe_commits": sorted({r["pointe_commit"] for r in pub}), "agent_model": meta.get("agent_model"),
        "claude_code": sorted({r["claude_code"] for r in pub}), "permission_mode": meta.get("permission_mode"),
        "router_models": sorted({r["adapter_versions"].get("router_model") for r in pub
                                 if r["adapter_versions"].get("router_model")}),
        "recognizers": sorted({r["adapter_versions"].get("recognizer") for r in pub
                               if r["adapter_versions"].get("recognizer")}),
        "voices": sorted({r["voice"] for r in pub if r.get("voice")}),
        "load_average": [min((r["load_average"] for r in pub), default=None),
                         max((r["load_average"] for r in pub), default=None)],
        "audio_matches_lock": sorted({r["audio_matches_lock"] for r in pub}),
        "spend_usd_all_rows": round(sum(r.get("spend_usd", 0) for r in allr), 4)}
    return summary


def fmt(p: dict) -> str:
    if not p or not p["n"]:
        return "n/a"
    lo, hi = p["wilson95"]
    if p["k"] == 0:
        return f"0/{p['n']} (at most {hi:.0%})"
    return f"{p['k']}/{p['n']} {p['rate']:.0%} [{lo:.0%}, {hi:.0%}]"


def markdown(s: dict) -> str:
    out = [f"# {s['title']}", "",
           f"Run `{s['run_id']}`. Independent unit: the {s['unit']}. Brackets: 95% Wilson interval on runs. "
           "A zero shows its upper bound. Every row is one fresh agent session on a copy of the fixture.", "",
           f"## Outcomes per arm, synthetic speech", "",
           "| Arm | Runs | Right symbol | Bootstrap by target | Wrong symbol (harmful) | No action | Other change | "
           "Capped | Delivered exact | Spend |", "|---|---|---|---|---|---|---|---|---|---|"]
    for a, t in s["arms"].items():
        bt = t["right_symbol_bootstrap_by_target95"]
        out.append(f"| {a} | {t['n_runs']} | {fmt(t['right_symbol'])} | "
                   f"{'n/a' if not bt else f'[{bt[0]:.0%}, {bt[1]:.0%}]'} | {fmt(t['wrong_symbol'])} | "
                   f"{fmt(t['no_action'])} | {fmt(t['other_change'])} | {t['capped']} | "
                   f"{fmt(t['delivered_exact']) if 'delivered_exact' in t else 'n/a'} | ${t['spend_usd']:.2f} |")
    out += ["", "## Paired differences in right-symbol rate, synthetic speech", "",
            "| Comparison | Difference | 95% bootstrap by target |", "|---|---|---|"]
    for k, v in s["paired"].items():
        lo, hi = v["bootstrap95_by_target"]
        out.append(f"| {k} | {v['right_symbol_diff']:+.0%} | [{lo:+.0%}, {hi:+.0%}] |")
    if s["repeat"]:
        out += ["", "## Repeat of 12 seeded items, synthetic speech", "", "| Arm | Pairs | Flips | Flip rate | pass^2 |",
                "|---|---|---|---|---|"]
        for a, v in s["repeat"].items():
            out.append(f"| {a} | {v['n_pairs']} | {v['flips']} | {v['flip_rate']:.0%} | {v['pass2']:.0%} |")
    out += ["", "## Slices, synthetic speech (right symbol / wrong symbol, each with n)", ""]
    keys = sorted({k for sl in s["slices"].values() for k in sl})
    out += ["| Slice | " + " | ".join(s["slices"]) + " |", "|---|" + "---|" * len(s["slices"])]
    for k in keys:
        cells = []
        for a in s["slices"]:
            v = s["slices"][a].get(k)
            cells.append("n/a" if not v else f"{fmt(v['right_symbol'])}; wrong {fmt(v['wrong_symbol'])}")
        out.append(f"| {k} | " + " | ".join(cells) + " |")
    for a, v in s.get("superseded", {}).items():
        out += ["", f"**{a}: {v['rows']} rows of this run superseded** by run `{v['replaced_by_run']}`: {v['why']}"]
    out += ["", "## Excluded rows", "", "| Arm | invalid_out_of_tree | error |", "|---|---|---|"]
    for a, v in s["excluded"].items():
        out.append(f"| {a} | {v['invalid_out_of_tree']} | {v['error']} |")
    c = s["conditions"]
    out += ["", "## Conditions", "", f"- Dates: {', '.join(c['dates'])}",
            f"- Bench commit(s): {', '.join(x[:12] for x in c['repo_commits'])}; Pointe commit under test: "
            f"{', '.join(x[:12] for x in c['pointe_commits'])}",
            f"- Agent: `{c['agent_model']}`, Claude Code {', '.join(c['claude_code'])}, permission mode "
            f"`{c['permission_mode']}`", f"- Router model: {', '.join(c['router_models']) or 'n/a'}; recognizer of "
            f"naive and llm-router: {', '.join(c['recognizers']) or 'n/a'}",
            f"- Voices: {', '.join(c['voices'])} (Kokoro-82M v1.0); noise: clean or 12 dB babble of the other three "
            "panel voices", f"- Load average (1 min) during rows: {c['load_average'][0]} to {c['load_average'][1]}",
            f"- Audio matches audio.lock: {c['audio_matches_lock']}",
            f"- Spend, every row of this run (computed, see spend.jsonl): ${c['spend_usd_all_rows']:.2f}", ""]
    return "\n".join(out)


def write(run_id: str, arm_from: dict | None = None, why: str = "") -> dict:
    frozen_path = HERE / "FROZEN.json"
    frozen = json.loads(frozen_path.read_text()) if frozen_path.exists() else None
    s = summarize(run_id, frozen, arm_from, why)
    d = HERE / "results" / run_id
    (d / "summary.json").write_text(json.dumps(s, indent=1) + "\n")
    (d / "summary.md").write_text(markdown(s))
    print(markdown(s))
    return s
