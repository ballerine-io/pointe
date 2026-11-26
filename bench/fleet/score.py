"""The fleet benchmark's scorer: what each raw row counts as, the counts and intervals over a set of rows, and the
plan's bars beside them. Pure functions over rows; no file, clock or model here. Standard library only.

A row is one line of results/<run-id>/rows.jsonl (bench/fleet/run.py writes them):

  kind "turn"     one scripted user turn: `turn_kind`, `expect`, `deliveries` (every request that reached a stand-in's
                  inbox while the turn was watched: the only evidence of where a send went), `said` (what the voice
                  showed), the model steps, and `error` when the turn could not be driven.
  kind "burst"    many sessions ending their turn within a minute: what was said, what was held, what was lost.
  kind "readers"  reader calls over a window with every session active, or with 80% of them quiet.
  kind "crash"    a run that ended early, with its reason.

Outcomes are by rule:
  a clear turn      right: at least one delivery and every one to the expected session; wrong: any delivery to another
                    session; asked: nothing delivered and the voice's reply has a question mark; nothing: neither.
  an ambiguous turn asked: nothing delivered and a question mark in the reply; sent: anything delivered; neither.
  a question turn   sent: anything delivered (a question is not a request); otherwise the expected sessions the reply
                    names, and the other sessions it names.
A turn with `error`, or one whose own brain steps all failed with nothing sent, is "crashed" and stays in every
denominator it belongs to; nothing is dropped here.
"""

import math
import random
import re

CLEAR = ("clear_name", "clear_machine_name", "clear_description")
AMBIGUOUS = ("ambiguous_name", "ambiguous_description", "ambiguous_none")
QUESTIONS = ("needs_me", "on_machine")
BARS = {"needs_tokens_max": 1800, "brain_input_within": 0.10, "first_token_within_secs": 0.150,
        "wrong_session_max_5x20": 0.05, "asked_of_14": 10, "quiet_reader_share_max": 0.30, "burst_spoken_max": 4}
LOAD_MAX = 20.0  # a row that began or ended above this 1-minute load keeps its routing outcome and loses its timings


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """95% Wilson score interval for k of n. With n = 0 the interval is the whole range."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def quantile(values: list[float], q: float) -> float | None:
    """The q-quantile by nearest rank (the smallest value with at least q of the values at or below it)."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def median(values: list[float]) -> float | None:
    return quantile(values, 0.5)


def bootstrap(values: list[float], q: float = 0.5, iters: int = 2000, seed: int = 20261126) -> tuple[float, float] | None:
    """95% percentile interval of a quantile, resampling the values."""
    if not values:
        return None
    rng = random.Random(seed)
    stats = sorted(quantile([values[rng.randrange(len(values))] for _ in values], q) for _ in range(iters))
    return stats[int(0.025 * iters)], stats[min(iters - 1, int(0.975 * iters))]


def asked(said: list[str]) -> bool:
    return any("?" in line or "？" in line for line in said)


def names(text: str, name: str) -> bool:
    """The text says this session's name as a word of its own."""
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text, re.I) is not None


def no_brain(row: dict) -> bool:
    """The turn's own brain steps were tried and none completed (the vendor could not be reached, or timed out), and
    nothing was sent: what was shown is the daemon's "say that again?", not an answer. Counted as crashed, never as
    asked."""
    own = [s for s in row.get("steps") or [] if s.get("own")]
    return bool(own) and all(s.get("error") for s in own) and not row.get("deliveries")


def outcome(row: dict) -> str:
    """What a turn row counts as (see the module's first lines)."""
    if row.get("error") or no_brain(row):
        return "crashed"
    kind, landed = row["turn_kind"], [d["session"] for d in row.get("deliveries") or []]
    if kind in CLEAR:
        want = row["expect"]["session"]
        if any(s != want for s in landed):
            return "wrong"
        if landed:
            return "right"
        return "asked" if asked(row.get("said") or []) else "nothing"
    if kind in AMBIGUOUS:
        if landed:
            return "sent"
        return "asked" if asked(row.get("said") or []) else "neither"
    return "sent" if landed else "answered"


def mentions(row: dict, fleet: dict) -> dict:
    """For a question turn: how many of the expected sessions the reply names, and how many others it names. A name
    several sessions have ("shop") counts for the expected one and is never an "other"."""
    reply = " ".join(row.get("said") or [])
    by_id = {s["id"]: s for s in fleet["sessions"]}
    want = {by_id[i]["name"] for i in row["expect"]["sessions"]}
    others = {s["name"] for s in fleet["sessions"]} - want
    return {"expected": len(want), "named": sum(names(reply, n) for n in want),
            "others_named": sorted(n for n in others if names(reply, n))}


def timed(row: dict) -> bool:
    return max(row.get("load_start") or 0.0, row.get("load_end") or 0.0) <= LOAD_MAX


def _rate(k: int, n: int) -> dict:
    low, high = wilson(k, n)
    return {"k": k, "n": n, "rate": (k / n if n else None), "low": low, "high": high}


def _spread(values: list[float]) -> dict:
    return {"n": len(values), "median": median(values), "p90": quantile(values, 0.9), "max": max(values) if values else None,
            "median_interval": bootstrap(values, 0.5), "p90_interval": bootstrap(values, 0.9)}


def summarize(rows: list[dict], fleet: dict | None = None) -> dict:
    """The counts and spreads of one set of rows (one run, or the runs of one size and arm together)."""
    turns = [r for r in rows if r["kind"] == "turn"]
    results = [(r, outcome(r)) for r in turns]
    clear = [(r, o) for r, o in results if r["turn_kind"] in CLEAR]
    ambiguous = [(r, o) for r, o in results if r["turn_kind"] in AMBIGUOUS]
    questions = [(r, o) for r, o in results if r["turn_kind"] in QUESTIONS]
    count = lambda pairs, what: sum(o == what for _, o in pairs)  # noqa: E731
    by_kind = {}
    for kind in (*CLEAR, *AMBIGUOUS, *QUESTIONS):
        pairs = [(r, o) for r, o in results if r["turn_kind"] == kind]
        if pairs:
            by_kind[kind] = {what: count(pairs, what) for what in sorted({o for _, o in pairs})} | {"n": len(pairs)}
    ok = [r for r, o in results if o != "crashed"]
    quiet = [r for r in ok if timed(r)]
    out = {
        "turns": len(turns), "crashed": count(results, "crashed"),
        "untimed_for_load": len(ok) - len(quiet),
        "clear": {"right": _rate(count(clear, "right"), len(clear)), "wrong": _rate(count(clear, "wrong"), len(clear)),
                  "asked": _rate(count(clear, "asked"), len(clear)), "nothing": _rate(count(clear, "nothing"), len(clear)),
                  "crashed": count(clear, "crashed")},
        "ambiguous": {"asked": _rate(count(ambiguous, "asked"), len(ambiguous)),
                      "sent": _rate(count(ambiguous, "sent"), len(ambiguous)),
                      "neither": _rate(count(ambiguous, "neither"), len(ambiguous)), "crashed": count(ambiguous, "crashed")},
        "questions": {"sent": _rate(count(questions, "sent"), len(questions)), "crashed": count(questions, "crashed")},
        "by_kind": by_kind,
        "needs_tokens": _spread([r["needs_tokens"] for r in ok if r.get("needs_tokens") is not None]),
        "needs_tokens_missing": sum(r.get("needs_tokens") is None for r in ok),
        "brain_input": _spread([r["brain_input_tokens"] for r in ok if r.get("brain_input_tokens")]),
        "brain_input_first_step": _spread([r["brain_input_first_step"] for r in ok if r.get("brain_input_first_step")]),
        "first_token": _spread([r["first_token_secs"] for r in quiet if r.get("first_token_secs") is not None]),
        "first_send": _spread([r["first_send_secs"] for r in quiet if r.get("first_send_secs") is not None]),
        "reader_calls": sum(r.get("reader_calls") or 0 for r in ok),
        "checker_calls": sum(r.get("checker_calls") or 0 for r in ok),
    }
    if fleet is not None:
        for kind in QUESTIONS:
            got = [mentions(r, fleet) for r, o in questions if r["turn_kind"] == kind and o == "answered"]
            out[f"{kind}_named"] = {"turns": len(got), "expected": sum(g["expected"] for g in got),
                                    "named": sum(g["named"] for g in got),
                                    "turns_naming_others": sum(bool(g["others_named"]) for g in got)}
    return out


def burst(rows: list[dict]) -> list[dict]:
    return [{"run": r["run"], "finished": len(r["finished"]), "spoken": len(r["spoken"]), "held": len(r["held"]),
             "lost": len(r["lost"]), "reader_calls": r.get("reader_calls"), "error": r.get("error")}
            for r in rows if r["kind"] == "burst"]


def readers(rows: list[dict]) -> dict:
    """Reader calls an hour with every session active and with 80% quiet, and the second as a share of the first."""
    by = {r["scenario"]: r for r in rows if r["kind"] == "readers" and not r.get("error")}
    active, quiet = by.get("all_active"), by.get("quiet_80")
    share = (quiet["per_hour"] / active["per_hour"]) if active and quiet and active["per_hour"] else None
    return {"all_active": active and active["per_hour"], "quiet_80": quiet and quiet["per_hour"], "share": share,
            "models": (active or quiet or {}).get("models")}


def verdict(ok: bool | None) -> str:
    return "not measured" if ok is None else "pass" if ok else "FAIL"


def bars(at: dict, base: dict | None, size: str, bursts: list[dict], reader: dict) -> list[dict]:
    """The plan's bars for one size and arm. `at`: summarize() of that size's rows; `base`: of the 1x4 rows of the
    same arm (None when 1x4 was not run). Each bar: its name, the bar, the measured value and pass, FAIL or not
    measured. No rounding here: the comparison is on the values as computed."""
    out = []

    def bar(name: str, limit: str, measured: str, ok: bool | None, note: str = "") -> None:
        out.append({"bar": name, "limit": limit, "measured": measured, "verdict": verdict(ok), "note": note})

    worst = at["needs_tokens"]["max"]
    bar("tokens of \"what needs me\"", f"at most {BARS['needs_tokens_max']:,}",
        "not measured" if worst is None else f"max {worst:,} (median {at['needs_tokens']['median']:,}), {at['needs_tokens']['n']} turns",
        None if worst is None else worst <= BARS["needs_tokens_max"],
        f"{at['needs_tokens_missing']} turns without a count" if at["needs_tokens_missing"] else "")
    mine, ref = at["brain_input"]["median"], base and base["brain_input"]["median"]
    if size == "1x4":
        bar("brain input tokens per turn", "the reference for the other sizes",
            "not measured" if mine is None else f"median {mine:,}", None if mine is None else True)
    else:
        bar("brain input tokens per turn", f"within {BARS['brain_input_within']:.0%} of 1x4",
            "not measured" if None in (mine, ref) else f"median {mine:,} against {ref:,} ({mine / ref - 1:+.0%})",
            None if None in (mine, ref) else mine <= ref * (1 + BARS["brain_input_within"]))
    for q, label in ((0.5, "median"), (0.9, "p90")):
        mine = at["first_token"]["median" if q == 0.5 else "p90"]
        ref = base and base["first_token"]["median" if q == 0.5 else "p90"]
        if size == "1x4":
            bar(f"first token, {label}", "the reference for the other sizes",
                "not measured" if mine is None else f"{mine:.3f} s", None if mine is None else True)
        else:
            bar(f"first token, {label}", f"at most {BARS['first_token_within_secs'] * 1000:.0f} ms above 1x4",
                "not measured" if None in (mine, ref) else f"{mine:.3f} s against {ref:.3f} s ({(mine - ref) * 1000:+.0f} ms)",
                None if None in (mine, ref) else mine - ref <= BARS["first_token_within_secs"])
    wrong = at["clear"]["wrong"]
    said = f"{wrong['k']} of {wrong['n']} ({wrong['low']:.0%} to {wrong['high']:.0%})" if wrong["n"] else "not measured"
    if size != "1x4":
        ref_wrong = base and base["clear"]["wrong"]
        known = bool(wrong["n"] and ref_wrong and ref_wrong["n"])
        bar("wrong session on clear turns", "not above the 1x4 rate",
            said + (f" against {ref_wrong['k']} of {ref_wrong['n']}" if known else ""),
            (wrong["rate"] <= ref_wrong["rate"]) if known else None)
    if size == "5x20":
        bar("wrong session on clear turns", f"at most {BARS['wrong_session_max_5x20']:.0%}", said,
            (wrong["rate"] <= BARS["wrong_session_max_5x20"]) if wrong["n"] else None,
            "the interval does not rule out a rate above the bar" if wrong["n"] and wrong["high"] > BARS["wrong_session_max_5x20"]
            and wrong["rate"] <= BARS["wrong_session_max_5x20"] else "")
    if size == "1x4":
        bar("wrong session on clear turns", "the reference for the other sizes", said, True if wrong["n"] else None)
    ask = at["ambiguous"]["asked"]
    need = math.ceil(ask["n"] * BARS["asked_of_14"] / 14)
    bar("asked first on ambiguous turns", f"at least {need} of {ask['n']} (10 of 14, scaled to n)",
        f"{ask['k']} of {ask['n']} ({ask['low']:.0%} to {ask['high']:.0%})" if ask["n"] else "not measured",
        (ask["k"] >= need) if ask["n"] else None)
    share = reader.get("share")
    bar("reader calls an hour with 80% of sessions quiet", f"at most {BARS['quiet_reader_share_max']:.0%} of all active",
        "not measured" if share is None else f"{reader['quiet_80']:.0f} against {reader['all_active']:.0f} ({share:.0%})",
        None if share is None else share <= BARS["quiet_reader_share_max"],
        f"models: {reader['models']}" if reader.get("models") else "")
    good = [b for b in bursts if not b["error"]]
    if not good:
        bar("30 sessions finish within a minute", f"at most {BARS['burst_spoken_max']} spoken lines, nothing lost", "not measured", None)
    for b in good:
        bar("30 sessions finish within a minute", f"at most {BARS['burst_spoken_max']} spoken lines, nothing lost",
            f"{b['spoken']} spoken, {b['held']} held, {b['lost']} lost, of {b['finished']} ({b['run']})",
            b["spoken"] <= BARS["burst_spoken_max"] and b["lost"] == 0)
    return out
