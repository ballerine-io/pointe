"""The barge-in and backchannel set (bargein.toml): how fast the voice reacts to a voice over it, and what it decides.

  uv run --locked --extra local python bench/conversational/dialogues/bargein_report.py <run-id> [<run-id> ...]

Per run, from the rows and the isolated daemon's own log (no model, no spend):

- interruptions (`bi-int-*`): the voice's audible stop after the user began (the suite's `barge_stop`, from the
  recorder), the new question answered (`ok`), and the daemon's first reaction after the user began: the duck where the
  build has one ("voice ducked"), else the cut ("barge-in:").
- backchannels (`bi-back-*`): the daemon cut the voice ("barge-in:" in the window), it went on with the same reply
  afterwards ("reply resumed"), and anything sent to a session (never right).

Medians and p90 with a 95% interval from resampling the dialogues; rates with a Wilson interval. Synthetic voices: the
numbers say what the code does with these clips, not how people would rate it.
"""

import json
import random
import re
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]
from dialogues import score  # noqa: E402

LOG_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.(\d{3})")


def _when(line: str) -> float | None:
    m = LOG_TIME.match(line)
    return time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")) + int(m.group(2)) / 1000 if m else None


def _first(log: list, pattern: str, a: float, b: float) -> float | None:
    for line in log:
        if re.search(pattern, line) and (t := _when(line)) is not None and a <= t < b:
            return t
    return None


def row_result(row: dict) -> dict | None:
    if not row["dialogue"].startswith("bi-") or row.get("error") or len(row["turns"]) < 2:
        return None
    t = row["turns"][1]
    a, b = t["start"], score.window_end(row, 1)
    scored = score.turn_scores(row)[1]
    log = row.get("log") or []
    ducked = _first(log, r"voice ducked", a - 0.05, b)
    cut = _first(log, r"(?<!no )barge-in: ", a - 0.05, b)  # "no barge-in: a backchannel ..." is the voice going on
    first = min(x for x in (ducked, cut) if x is not None) if (ducked or cut) else None
    return {"dialogue": row["dialogue"], "kind": "interrupt" if row["dialogue"].startswith("bi-int") else "backchannel",
            "voice_over": t.get("speaking_at_start", True), "stop": scored.get("barge_stop"), "ok": bool(scored.get("ok")),
            "react": None if first is None else round(first - a, 3), "ducked": ducked is not None,
            "cut": cut is not None, "resumed": _first(log, r"reply resumed", a, b) is not None,
            "sent": bool(scored.get("delivered_to"))}


def wilson(k: int, n: int) -> str:
    if not n:
        return "n=0"
    p, z = k / n, 1.96
    centre, half = (p + z * z / (2 * n)) / (1 + z * z / n), z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5 / (1 + z * z / n)
    return f"{k}/{n} = {p:.0%} ({max(0, centre - half):.0%} to {min(1, centre + half):.0%})"


def spread(values: list, q: float) -> str:
    values = sorted(v for v in values if v is not None)
    if not values:
        return "n=0"
    pick = (lambda v: statistics.median(v)) if q == 0.5 else (lambda v: sorted(v)[min(len(v) - 1, int(round(q * (len(v) - 1))))])
    rnd = random.Random(7)
    boots = sorted(pick([rnd.choice(values) for _ in values]) for _ in range(2000))
    return f"{pick(values):.2f} s ({boots[50]:.2f} to {boots[1949]:.2f}), n={len(values)}"


def report(run_ids: list[str]) -> str:
    out = []
    for run_id in run_ids:
        rows = [json.loads(line) for line in (HERE / "results" / run_id / "rows.jsonl").read_text().splitlines() if line.strip()]
        got = [r for r in map(row_result, rows) if r]
        over = [r for r in got if r["voice_over"]]  # a clip that landed while the voice was quiet tests nothing here
        ints, backs = [r for r in over if r["kind"] == "interrupt"], [r for r in over if r["kind"] == "backchannel"]
        out += [f"## {run_id}: {len(got)} rows, {len(got) - len(over)} landed while the voice was quiet (left out)", "",
                "Interruptions",
                f"- first reaction after the user began (duck, or cut): median {spread([r['react'] for r in ints], 0.5)}; "
                f"p90 {spread([r['react'] for r in ints], 0.9)}",
                f"- audible stop (recorder): median {spread([r['stop'] for r in ints], 0.5)}; p90 {spread([r['stop'] for r in ints], 0.9)}",
                f"- cut by the daemon: {wilson(sum(r['cut'] for r in ints), len(ints))}",
                f"- the new question answered: {wilson(sum(r['ok'] for r in ints), len(ints))}",
                "", "Backchannels",
                f"- voice cut by the daemon (false stop): {wilson(sum(r['cut'] for r in backs), len(backs))}",
                f"- ducked: {wilson(sum(r['ducked'] for r in backs), len(backs))}",
                f"- cut and then resumed: {wilson(sum(r['cut'] and r['resumed'] for r in backs), sum(r['cut'] for r in backs))}",
                f"- the suite's own false stop (its span ended within 1.2 s): {wilson(sum((r['stop'] or 9) < 1.2 for r in backs), len(backs))}",
                f"- sent to a session: {wilson(sum(r['sent'] for r in backs), len(backs))}", ""]
    return "\n".join(out)


if __name__ == "__main__":
    print(report(sys.argv[1:]))
