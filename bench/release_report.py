"""The numbers a release publishes, recomputed from its raw rows: `bench/results/<date>-<tag>/manifest.json` names every
run, and this writes `summary.json` beside it. Nothing here calls a model or a vendor.

  .venv/bin/python -I bench/release_report.py bench/results/2026-11-25-v0.8.5

Rules, fixed before the runs were read:
- A dialogue row counts only when the 1-minute load was at most 20 at its start and at its end and it has no error.
  Rows that fail this are listed in the summary, and their dialogue is run again in a separate run id.
- Each repeat is scored on its own; the spread is the repeats' range. The 95% interval resamples dialogues (all the
  repeats of one dialogue together), 2,000 times, with a fixed seed.
- A turn that got no word is counted as the slowest first word (score.py), not dropped.
"""

import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DLG = HERE / "conversational" / "dialogues"
sys.path.insert(0, str(DLG))

from dialogues import score  # noqa: E402

MAX_LOAD = 20.0
SEED, DRAWS = 20261125, 2000


def wilson(k: int, n: int) -> tuple:
    if not n:
        return (None, None)
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return (round((c - h) / d, 3), round((c + h) / d, 3))


def rows_of(run_dir: Path) -> list:
    return [json.loads(line) for line in (run_dir / "rows.jsonl").read_text().splitlines() if line.strip()]


def ledger_end_loads(ledger: Path) -> dict:
    out = {}
    for line in ledger.read_text().splitlines():
        r = json.loads(line)
        if r.get("benchmark") == "dialogues" and r.get("item") not in (None, "judge"):
            out[(r["run_id"], r["item"], r["arm"])] = r.get("load_avg_end")
    return out


def counted(rows: list, end_load: dict) -> tuple:
    keep, dropped = [], []
    for r in rows:
        end = end_load.get((r["run_id"], r["dialogue"], r["arm"]))
        why = ("error: " + r["error"][:80]) if r.get("error") else (
            f"load {r.get('load_avg')} at start" if (r.get("load_avg") or 0) > MAX_LOAD else (
                f"load {end} at end" if (end or 0) > MAX_LOAD else None))
        (dropped if why else keep).append((r, why))
    return [r for r, _ in keep], [{"run_id": r["run_id"], "dialogue": r["dialogue"], "arm": r["arm"], "why": w}
                                  for r, w in dropped]


MEASURES = ["ttfw_median", "ttfw_p90", "silent_turns", "speech_turns", "first_sound_median", "ttua_median",
            "ttua_session_answer_median", "right_session", "right_action", "wrong_sends", "false_approvals",
            "voice_approval_ok", "unheard_held", "words_over_need_median", "confirmations_per_10", "code_names_exact",
            "hebrew_right_action", "english_right_action", "talk_over_rate"]


def clean(v):
    if isinstance(v, float):
        return "silent" if v == float("inf") else round(v, 3)
    return v


def dialogues(spec: dict, root: Path) -> dict:
    """spec: {"runs": [[run_id, ...], ...] one list per repeat (a repeat's re-runs after it), "arms": [...]}."""
    end_load = ledger_end_loads(root / "ledger.jsonl")  # the release's own copy of its ledger rows
    out = {"arms": {}, "dropped": []}
    for arm in spec["arms"]:
        repeats = []
        for ids in spec["runs"]:
            latest = {}
            for rid in ids:
                rows, dropped = counted([r for r in rows_of(root / "dialogues" / rid) if r["arm"] == arm], end_load)
                out["dropped"] += dropped
                for r in rows:  # a re-run of a dropped dialogue fills its place; nothing kept is replaced
                    latest.setdefault(r["dialogue"], r)
            judges = {}
            for rid in ids:
                for f in sorted((root / "dialogues" / rid).glob(f"judge-{arm}*.json")):
                    j = json.loads(f.read_text())
                    for d, v in j["runs"].items():
                        if isinstance(v.get("score"), (int, float)) and d in latest and latest[d]["run_id"] == rid:
                            judges.setdefault(j["model"], {})[d] = v["score"]
            repeats.append((list(latest.values()), judges))
        per = []
        for rows, judges in repeats:
            m = score.metrics(rows)
            per.append({**{k: clean(m.get(k)) for k in MEASURES}, "dialogues": len(rows),
                        "judges": {k: round(statistics.mean(v.values()), 2) for k, v in judges.items()}})
        out["arms"][arm] = {"repeats": per, "pooled": pooled(repeats), "agreement": agreement(repeats)}
        out.setdefault("_rows", {})[arm] = [r for rows, _ in repeats for r in rows]
    rows = out.pop("_rows")
    if len(spec["arms"]) == 2:
        out["paired"] = paired(*(rows[a] for a in spec["arms"]))
    return out


def paired(a_rows: list, b_rows: list) -> dict:
    """First arm minus second, on the dialogues both ran: the same dialogues resampled for both, 2,000 times."""
    A, B = defaultdict(list), defaultdict(list)
    for r in a_rows:
        A[r["dialogue"]].append(r)
    for r in b_rows:
        B[r["dialogue"]].append(r)
    names = sorted(set(A) & set(B))
    keys = ("right_action", "right_session", "ttua_median", "ttua_session_answer_median", "words_over_need_median")

    def diff(pick):
        ma = score.metrics([r for n in pick for r in A[n]])
        mb = score.metrics([r for n in pick for r in B[n]])
        return {k: (ma[k] - mb[k]) if None not in (ma.get(k), mb.get(k)) else None for k in keys}

    point = diff(names)
    rng = random.Random(SEED)
    draws = defaultdict(list)
    for _ in range(DRAWS):
        d = diff(rng.choices(names, k=len(names)))
        for k, v in d.items():
            if v is not None:
                draws[k].append(v)
    out = {"dialogues": len(names)}
    for k in keys:
        xs = sorted(draws[k])
        out[k] = {"diff": clean(point[k]), "ci95": [clean(xs[int(0.025 * len(xs))]), clean(xs[int(0.975 * len(xs)) - 1])]
                  if xs else None}
    return out


def pooled(repeats: list) -> dict:
    """Every repeat's turns together, with a 95% interval from resampling dialogues."""
    by_dlg = defaultdict(list)
    for rows, _ in repeats:
        for r in rows:
            by_dlg[r["dialogue"]].append(r)
    names = sorted(by_dlg)
    m = score.metrics([r for n in names for r in by_dlg[n]])
    res = {k: clean(m.get(k)) for k in MEASURES}
    rng = random.Random(SEED)
    boot = defaultdict(list)
    for _ in range(DRAWS):
        pick = [r for n in rng.choices(names, k=len(names)) for r in by_dlg[n]]
        b = score.metrics(pick)
        for k in ("ttfw_median", "ttfw_p90", "ttua_median", "right_session", "right_action", "words_over_need_median"):
            if b.get(k) is not None:
                boot[k].append(b[k])
    res["ci95"] = {}
    for k, xs in boot.items():
        xs.sort()
        lo, hi = xs[int(0.025 * len(xs))], xs[int(0.975 * len(xs)) - 1]
        res["ci95"][k] = [clean(lo), clean(hi)]
    scored = [t for t in m["turn_rows"] if t["ok"] is not None]
    k = sum(1 for t in scored if t["ok"])
    res["right_action_k_n"] = [k, len(scored)]
    rs = [t for t in m["turn_rows"] if t.get("right_session") is not None and not t["dialogue"].startswith("amb-")]
    res["right_session_k_n"] = [sum(1 for t in rs if t["right_session"]), len(rs)]
    res["dialogue_runs"] = sum(len(v) for v in by_dlg.values())
    return res


def agreement(repeats: list) -> dict:
    """How far two judges agree on the same dialogue runs: exact, within one point, and Spearman's rho."""
    pairs = defaultdict(list)
    for rows, judges in repeats:
        models = sorted(judges)
        for i, a in enumerate(models):
            for b in models[i + 1:]:
                for d in judges[a]:
                    if d in judges[b]:
                        pairs[f"{a} vs {b}"].append((judges[a][d], judges[b][d]))
    out = {}
    for name, xs in pairs.items():
        n = len(xs)
        out[name] = {"n": n, "exact": round(sum(a == b for a, b in xs) / n, 3),
                     "within_one": round(sum(abs(a - b) <= 1 for a, b in xs) / n, 3), "spearman": spearman(xs),
                     "mean_difference": round(statistics.mean(a - b for a, b in xs), 2)}
    return out


def ranks(xs: list) -> list:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(pairs: list):
    a, b = ranks([x for x, _ in pairs]), ranks([y for _, y in pairs])
    if len(set(a)) < 2 or len(set(b)) < 2:
        return None
    return round(statistics.correlation(a, b), 3)


def human(spec: dict, root: Path) -> dict:
    """Recorded people: a yes or a no after a read-out (Speech Commands), "stop" and a backchannel over an answer (AMI).
    spec: {"arms": {arm: [[run_id, ...], ...]}}, one list per repeat."""
    end_load = ledger_end_loads(root / "ledger.jsonl")
    out = {"arms": {}, "dropped": []}
    for arm, repeats in spec["arms"].items():
        per = []
        for ids in repeats:
            latest = {}
            for rid in ids:
                rows, dropped = counted([r for r in rows_of(root / "dialogues" / rid) if r["arm"] == arm], end_load)
                out["dropped"] += dropped
                for r in rows:
                    latest.setdefault(r["dialogue"], r)
            T = [t for r in latest.values() for t in score.turn_scores(r)]
            yes = [t for t in T if t["dialogue"].startswith("hum-yes") and t["kind"] == "approve"]
            no = [t for t in T if t["dialogue"].startswith("hum-no") and t["kind"] == "deny"]
            stop = [t for t in T if t["dialogue"].startswith("hum-stop") and t["when"] == "speaking"]
            listen = [t for t in T if t["dialogue"].startswith("hum-listen") and t["when"] == "speaking"]
            rec = {"dialogues": len(latest)}
            for name, ts in (("yes_approved", yes), ("no_denied", no)):
                scored = [t for t in ts if t["ok"] is not None]
                k = sum(1 for t in scored if t["ok"])
                rec[name] = {"k": k, "n": len(scored), "ci95": wilson(k, len(scored)),
                             "not_asked": len(ts) - len(scored),
                             "missed": sorted(t["dialogue"] for t in scored if not t["ok"])}
            rec["false_approvals"] = sum(1 for t in no if t.get("false_approval"))
            if stop:
                times = sorted(t["barge_stop"] for t in stop if t.get("barge_stop") is not None)
                rec["stop"] = {"n": len(stop), "measured": len(times),
                               "median": round(statistics.median(times), 2) if times else None,
                               "p90": round(score.pct(times, 0.9), 2) if times else None,
                               "max": round(times[-1], 2) if times else None}
            if listen:
                over = [t for t in listen if t.get("false_stop") is not None]
                sent = sum(1 for t in listen if t.get("sent_when_should_not"))
                k = sum(1 for t in over if t["false_stop"])
                rec["backchannel"] = {"n": len(listen), "over_speech": len(over), "false_stop": k,
                                      "ci95": wilson(k, len(over)), "sent_something": sent}
            per.append(rec)
        out["arms"][arm] = {"repeats": per}
    return out


def turns(spec: dict, root: Path) -> dict:
    """End of turn on recorded pauses (AMI), replayed under the shipped Normal rule (turns.settle at "normal"), as
    bench/turn_rules.py does. Speakers are split by a hash of their name; the rule was tuned on "train"."""
    sys.path[:0] = [str(HERE), str(HERE.parent / "pointe"), str(HERE.parent)]
    import hashlib
    import turn_rules as tr
    wait = tr.RULES["Normal now (1.3 s, the narrow list)"]
    out = {"runs": {}, "headline": spec.get("headline") or next(iter(spec["rows"]))}
    for name, path in spec["rows"].items():
        rows = [json.loads(line) for line in (root / path).read_text().splitlines() if line.strip()]
        before = [r for r in rows if r["policy"] == "before"]
        kept = [r for r in before if not r.get("error") and r.get("load", 0) <= MAX_LOAD]
        half = lambda r: "train" if int(hashlib.sha256(r["voice"].encode()).hexdigest(), 16) % 2 == 0 else "test"  # noqa: E731
        got = {r["clip"]: tr.replay(r, wait, False) for r in kept}
        res = {"clips": len(before), "kept": len(kept), "dropped_load_or_error": len(before) - len(kept),
               "load_median": round(statistics.median(r.get("load", 0) for r in kept), 1),
               "load_max": round(max(r.get("load", 0) for r in kept), 1)}
        for split in ("all", "test", "train"):
            mine = [r for r in kept if split == "all" or half(r) == split]
            pauses = [r for r in mine if r["pause"] is not None]
            ends = [r for r in mine if r["pause"] is None]
            k = sum(1 for r in pauses if got[r["clip"]]["cut"])
            delays = sorted(got[r["clip"]]["delay"] for r in ends if got[r["clip"]]["delay"] is not None)
            speakers = sorted({r["voice"] for r in mine})
            rng = random.Random(SEED)
            by = defaultdict(list)
            for r in pauses:
                by[r["voice"]].append(got[r["clip"]]["cut"])
            draws = []
            for _ in range(DRAWS):
                pick = [c for v in rng.choices(sorted(by), k=len(by)) for c in by[v]]
                draws.append(sum(pick) / len(pick))
            draws.sort()
            res[split] = {"speakers": len(speakers), "pauses": len(pauses), "cut_ins": k,
                          "rate": round(k / len(pauses), 3) if pauses else None,
                          "ci95_by_speaker": [round(draws[int(0.025 * DRAWS)], 3), round(draws[int(0.975 * DRAWS) - 1], 3)],
                          "ends": len(ends), "end_taken_median": round(statistics.median(delays), 2) if delays else None,
                          "end_taken_p90": round(tr.p90(delays), 2) if delays else None}
        out["runs"][name] = res
    return out


def main(release: Path) -> int:
    manifest = json.loads((release / "manifest.json").read_text())
    summary = {"release": manifest["release"], "commit": manifest["commit"]}
    if "dialogues" in manifest["benchmarks"]:
        summary["dialogues"] = dialogues(manifest["benchmarks"]["dialogues"], release)
    if "human" in manifest["benchmarks"]:
        summary["human"] = human(manifest["benchmarks"]["human"], release)
    if "turns" in manifest["benchmarks"]:
        summary["turns"] = turns(manifest["benchmarks"]["turns"], release)
    (release / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {release / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
