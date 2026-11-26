"""Writes bench/fleet/RESULTS.md from the raw rows in bench/fleet/results/: nothing in it is typed by hand.

    uv run --locked python -I bench/fleet/report.py

It refuses to write when the dataset on disk is not the frozen one (FROZEN.json), or when a run it would count was
made on another dataset. Counted: every paid run of the whole turn list (`turns`, real models, no --limit), every
burst, every reader count, every simulator measurement. Not counted, and listed with their counts: smoke runs (a
--limit) and dry runs with stubbed models. A counted run's crashed rows stay in its denominators.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import score  # noqa: E402

SIZES = ("1x4", "5x20", "10x30")
ARMS = ("baseline", "fleet-off", "fleet-on")
ARM_WORDS = {"baseline": "main before the fleet work", "fleet-off": "the fleet build, POINTE_FLEET=off",
             "fleet-on": "the fleet build, POINTE_FLEET=on"}


class Refused(RuntimeError):
    pass


def load(results: Path) -> list[dict]:
    """Every run folder: its manifest and its rows."""
    runs = []
    for folder in sorted(p for p in results.iterdir() if p.is_dir()) if results.exists() else []:
        manifest, rows = folder / "manifest.json", folder / "rows.jsonl"
        if not manifest.exists():
            continue
        skip = folder / "NOT_COUNTED"
        calls = [json.loads(line) for line in (folder / "calls.jsonl").read_text().splitlines() if line.strip()] if (folder / "calls.jsonl").exists() else []
        runs.append({"manifest": json.loads(manifest.read_text()), "calls": calls, "not_counted": skip.read_text().strip() if skip.exists() else "",
                     "rows": [json.loads(line) for line in rows.read_text().splitlines() if line.strip()] if rows.exists() else []})
    return runs


def counted(run: dict) -> bool:
    m = run["manifest"]
    if run.get("not_counted"):
        return False
    if m["what"] == "turns":
        return m["models"] == "real" and not m.get("limit")
    if m["what"] == "burst":
        return m["models"] == "real"
    return m["what"] in ("readers", "up")


def model_calls(calls: list[dict]) -> tuple[int, int, int]:
    """Reader, checker and brain calls of a run, from its calls.jsonl: the reader's model is the one `_read_model`
    called; every other text call is the checker's."""
    reader = next((c["choice"] for c in calls if c["kind"] == "text" and c.get("caller") == "_read_model"), None)
    texts = [c for c in calls if c["kind"] == "text"]
    return (sum(c["choice"] == reader for c in texts), sum(c["choice"] != reader for c in texts), sum(c["kind"] == "step" for c in calls))


def _pct(rate: dict) -> str:
    if not rate["n"]:
        return "none"
    return f"{rate['k']} of {rate['n']} ({rate['low']:.0%} to {rate['high']:.0%})"


def _num(value, unit: str = "", digits: int = 0) -> str:
    return "n/a" if value is None else f"{value:,.{digits}f}{unit}"


def _span(spread: dict, key: str, unit: str = "", digits: int = 0) -> str:
    value, interval = spread[key], spread.get(f"{key}_interval")
    if value is None:
        return "n/a"
    return f"{value:,.{digits}f}{unit}" + (f" ({interval[0]:,.{digits}f} to {interval[1]:,.{digits}f})" if interval else "")


def render(runs: list[dict], frozen: dict, dataset_sha: str, fleets: dict[str, dict], ledger: list[dict],
           trees: dict[str, str] | None = None) -> str:
    trees = trees or {}
    if not frozen or frozen.get("dataset_sha256") != dataset_sha:
        raise Refused("the dataset on disk is not the one in FROZEN.json: no report")
    used = [r for r in runs if counted(r)]
    for r in used:
        if r["manifest"]["what"] in ("turns", "burst") and r["manifest"]["dataset_sha256"] != dataset_sha:
            raise Refused(f"{r['manifest']['run']} was made on another dataset: no report")
    left = [r for r in runs if not counted(r)]
    out = ["<!-- Written by bench/fleet/report.py from bench/fleet/results/. Do not edit by hand. -->", "",
           "# Fleet benchmark: one voice, many machines and sessions", "",
           "A self-evaluation: Pointe's team wrote the simulator, the turns, the labels and the scorer. Typed text, "
           "scripted stand-in sessions, synthetic names. Every number below is computed from the rows in "
           "`bench/fleet/results/`; intervals are 95% (Wilson for counts, a bootstrap over turns for medians and p90).", "",
           f"Dataset `{frozen.get('dataset_version')}`, frozen {frozen.get('frozen_at')}, sha256 `{dataset_sha[:16]}`. "
           "60 turns a size; expected outcomes labelled by rule from the fleet's description (`bench/fleet/turns.py`).", ""]
    by: dict[tuple[str, str], list[dict]] = {}
    for r in used:
        by.setdefault((r["manifest"]["arm"], r["manifest"]["size"]), []).append(r)

    def rows_of(arm: str, size: str, what: str) -> list[dict]:
        return [row for r in by.get((arm, size), []) if r["manifest"]["what"] == what for row in r["rows"]]

    out += ["## Bars", ""]
    measured_any = False
    for arm in ARMS:
        base_rows = [x for x in rows_of(arm, "1x4", "turns") if x["kind"] == "turn"]
        base = score.summarize(base_rows, fleets.get("1x4")) if base_rows else None
        for size in SIZES:
            turn_rows = [x for x in rows_of(arm, size, "turns") if x["kind"] == "turn"]
            bursts, readers = score.burst(rows_of(arm, size, "burst")), score.readers(rows_of(arm, size, "readers"))
            if not turn_rows and not bursts and readers["share"] is None:
                continue
            measured_any = True
            at = score.summarize(turn_rows, fleets.get(size))
            n_runs = len([r for r in by.get((arm, size), []) if r["manifest"]["what"] == "turns"])
            out += [f"### {size}, {ARM_WORDS[arm]}", "",
                    f"{n_runs} runs of the turn list: {at['driven']} turns driven, {at['crashed']} crashed, {at['not_run']} not run (their run stopped first)"
                    + ("; no 1x4 run of this arm, so nothing to compare with" if size != "1x4" and base is None else "") + ".", "",
                    "| Bar | The plan's bar | Measured | |", "|---|---|---|---|"]
            for b in score.bars(at, base, size, bursts, readers):
                out.append(f"| {b['bar']} | {b['limit']} | {b['measured']}{'; ' + b['note'] if b['note'] else ''} | **{b['verdict']}** |")
            out.append("")
    if not measured_any:
        out += ["Nothing measured yet.", ""]

    want = {"fleet-on": True, "fleet-off": False, "baseline": None}
    checked = [x for r in used for x in r["rows"] if x["kind"] in ("turn", "burst", "readers") and not x.get("error")]
    off_arm = [x for x in checked if x.get("fleet_on") is not want[x["arm"]]]
    builds = sorted({(r["manifest"]["arm"], trees.get(r["manifest"]["pointe"]["commit"], r["manifest"]["pointe"].get("pointe_tree") or "unknown")[:12])
                     for r in used if "pointe" in r["manifest"]})
    out += ["## The arms, as the daemon states them", "",
            f"{len(checked) - len(off_arm)} of {len(checked)} rows carry the daemon's own `fleet.on` (`/voice/context`) equal to their arm's"
            + (f"; **{len(off_arm)} do not**" if off_arm else "") + ". The `pointe/` folder each arm ran (its git tree): " + ", ".join(f"{a} `{c}`" for a, c in builds) + ".", ""]
    out += ["## Every run", "",
            "| Arm | Size | Run | Clear: right | Clear: wrong session | Clear: asked instead | Clear: nothing | Ambiguous: asked | "
            "Ambiguous: sent | Ambiguous: neither | Driven / crashed / not run | Needs tokens, median / max | Brain input per turn, median | "
            "First token, median / p90 | First send, median | Reader / checker / brain calls in the run |", "|" + "---|" * 16]
    for (arm, size), group in sorted(by.items(), key=lambda kv: (ARMS.index(kv[0][0]), SIZES.index(kv[0][1]) if kv[0][1] in SIZES else 9)):
        turn_runs = [r for r in group if r["manifest"]["what"] == "turns"]
        sets = [(r["manifest"]["run"], [x for x in r["rows"] if x["kind"] == "turn"], model_calls(r.get("calls") or [])) for r in turn_runs]
        if len(sets) > 1:
            sets.append(("all runs", [x for _, rows, _ in sets for x in rows], tuple(sum(c[i] for _, _, c in sets) for i in range(3))))
        for name, rows, made in sets:
            s = score.summarize(rows, fleets.get(size))
            c, a = s["clear"], s["ambiguous"]
            out.append(f"| {arm} | {size} | {name} | {_pct(c['right'])} | {_pct(c['wrong'])} | {_pct(c['asked'])} | {_pct(c['nothing'])} | "
                       f"{_pct(a['asked'])} | {_pct(a['sent'])} | {_pct(a['neither'])} | {s['driven']} / {s['crashed']} / {s['not_run']} | "
                       f"{_span(s['needs_tokens'], 'median')} / {_num(s['needs_tokens']['max'])} | {_span(s['brain_input'], 'median')} | "
                       f"{_span(s['first_token'], 'median', ' s', 2)} / {_span(s['first_token'], 'p90', ' s', 2)} | "
                       f"{_span(s['first_send'], 'median', ' s', 2)} | {made[0]} / {made[1]} / {made[2]} |")
    out += ["", "Needs tokens: the \"what each session needs\" block of the turn's first brain step, counted by the brain "
            "vendor's own token counter as one message. Brain input: the vendor's count of the whole prompt, summed over the "
            "turn's own brain steps. First token and first send: from the typed line; a send's time is exact to 20 ms. "
            "Timings leave out rows that began or ended with the load over 20.", ""]

    out += ["## By kind of turn (all runs of a size and arm together)", "",
            "| Arm | Size | Kind | n | Outcomes |", "|---|---|---|---|---|"]
    for (arm, size), group in sorted(by.items(), key=lambda kv: (ARMS.index(kv[0][0]), kv[0][1])):
        rows = [x for r in group if r["manifest"]["what"] == "turns" for x in r["rows"] if x["kind"] == "turn"]
        if not rows:
            continue
        s = score.summarize(rows, fleets.get(size))
        for kind, counts in s["by_kind"].items():
            out.append(f"| {arm} | {size} | {kind} | {counts['n']} | " + ", ".join(f"{k} {v}" for k, v in counts.items() if k != "n") + " |")
        held = [x for x in rows if x["turn_kind"] == "ambiguous_name"]
        for flag, words in ((True, "this Mac has a session of the name"), (False, "only other machines have one")):
            part = [x for x in held if x.get("this_mac_holds") is flag]
            if part:
                tally: dict[str, int] = {}
                for x in part:
                    tally[score.outcome(x)] = tally.get(score.outcome(x), 0) + 1
                out.append(f"| {arm} | {size} | ambiguous_name, {words} | {len(part)} | " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())) + " |")
        for kind in score.QUESTIONS:
            q = s.get(f"{kind}_named")
            if q and q["turns"]:
                out.append(f"| {arm} | {size} | {kind}: expected sessions named in the reply | {q['turns']} | "
                           f"{q['named']} of {q['expected']} names; {q['turns_naming_others']} replies name a session not expected |")
    out.append("")

    bursts = [(r["manifest"], row) for r in used for row in r["rows"] if row["kind"] == "burst"]
    out += ["## 30 sessions end their turn within a minute", ""]
    if bursts:
        out += ["| Arm | Size | Run | Finished | Spoken lines | Held items | Named in speech | Named in the held list | Lost | Reader calls | Error |",
                "|" + "---|" * 11]
        for m, b in bursts:
            out.append(f"| {m['arm']} | {m['size']} | {m['run']} | {len(b['finished'])} | {len(b['spoken'])} | {len(b['held'])} | "
                       f"{b.get('named_in_speech', 'n/a')} | {b.get('named_in_held', 'n/a')} | {len(b['lost'])} | {b.get('reader_calls', 'n/a')} | {b.get('error') or ''} |")
        out += ["", "Lost: a session that ended its turn and is named neither in a spoken line nor in the held list when the "
                "fleet went quiet. One run each: n = 1.", ""]
    else:
        out += ["Not run.", ""]

    readers = [(r["manifest"], row) for r in used for row in r["rows"] if row["kind"] == "readers"]
    out += ["## Reader calls", ""]
    if readers:
        out += ["| Arm | Size | Scenario | Sessions active | Turns ended | Reader calls in the window | An hour | Error |", "|" + "---|" * 8]
        for m, x in readers:
            out.append(f"| {m['arm']} | {m['size']} | {x.get('scenario')} | {x.get('active_sessions', 'n/a')} of {x.get('sessions', 'n/a')} | "
                       f"{x.get('turns_ended', 'n/a')} | {x.get('reader_calls', 'n/a')} | {_num(x.get('per_hour'))} | {x.get('error') or ''} |")
        out += ["", "Counted with stubbed models: the count is the daemon's own decisions to call the reader, not what a "
                "model wrote. Each active session ends a turn once a minute for two minutes; the hourly figure is the "
                "window's count times 30. One run each: n = 1.", ""]
    else:
        out += ["Not run.", ""]

    sims = [(r["manifest"], row) for r in used for row in r["rows"] if row["kind"] == "sim"]
    out += ["## The simulator on this machine", ""]
    if sims:
        out += ["| Size | Arm | Processes | Sessions on their machine | Up in | Voice memory | Nodes' memory, together | "
                "Voice CPU | Nodes' CPU, together | Runner CPU | Load |", "|" + "---|" * 11]
        for m, x in sims:
            out.append(f"| {x['size']} | {x['arm']} | {x['processes']} | {x['on_their_machine']} of {x['sessions']} | {x['up_secs']} s | "
                       f"{x['voice_rss_mb']} MB | {x['nodes_rss_mb']} MB | {x['voice_cpu_share']:.0%} of a core | "
                       f"{x['nodes_cpu_share']:.0%} | {x['runner_cpu_share']:.0%} | {x['load']:.1f} |")
        out += ["", "Stubbed models, a call held for a minute with nothing typed. Processes: one voice daemon, one node a "
                "machine beyond the first, and the runner, which holds every stand-in session as a thread.", ""]
    else:
        out += ["Not measured.", ""]

    out += ["## Spend", "", "| Launch | What | Model calls | USD |", "|---|---|---|---|"]
    for row in ledger:
        out.append(f"| {row['launch']} | {row['what']} | {row['calls']} | {row['usd']:.4f} |")
    out += [f"| all {len(ledger)} paid launches | | {sum(r['calls'] for r in ledger)} | {sum(r['usd'] for r in ledger):.4f} |", "",
            "Computed from each call's token counts at list price (`prices.json`), not metered; smoke runs included. "
            "Each run's `manifest.json` has the split by model and says which calls were estimated from sizes.", ""]

    out += ["## Not counted above", ""]
    if left:
        out += ["| Run | Why | Rows |", "|---|---|---|"]
        for r in left:
            m = r["manifest"]
            why = r.get("not_counted") or ("stubbed models (a dry run)" if m["models"] == "stub" else f"a smoke run of {m.get('limit')} turns")
            out.append(f"| {m['run']} | {why} | {len(r['rows'])} |")
        out.append("")
    else:
        out += ["Nothing: every run folder is counted.", ""]
    crashes = [(r["manifest"]["run"], row["error"]) for r in used for row in r["rows"] if row["kind"] == "crash"]
    if crashes:
        out += ["Runs that ended early (the turns they drove are counted; the turns they did not reach are \"not run\", in no rate):", ""]
        out += [f"- {run}: {why}" for run, why in crashes] + [""]

    missing = [f"{size}, {ARM_WORDS[arm]}" for arm in ARMS for size in SIZES
               if not [r for r in by.get((arm, size), []) if r["manifest"]["what"] == "turns"]]
    out += ["## What this does not show", "",
            "- **Typed text, not speech.** Every turn is a line typed into the call. No recognizer, no voice, no turn-taking, "
            "no misheard names. The call has no ears and is in reading mode: replies are shown, not spoken, and the brain is told so.",
            "- **Stand-ins, not agents.** A session is a scripted record and an inbox. It never answers a request, so every "
            "request sent stays listed as unanswered for the rest of its run, and no report comes back during the turns.",
            "- **One voice, one person.** No second voice on a machine, no shared machine, no link that drops.",
            "- **Synthetic names and work.** One-word session names chosen to be unlike each other, except the shared ones; "
            "invented goals of two words. Real fleets have names that sound alike.",
            "- **One fleet a size.** The same generated fleet in every run; runs differ in turn order and in what the models do.",
            "- **Turns in one call.** The 60 turns of a run share a call, so later turns carry earlier ones in the brain's history.",
            "- **The reader's notes are read once.** A size's first paid run pays the reader to read every session; later "
            "runs of that arm reuse those notes (each manifest has the notes' hash).",
            "- **A self-evaluation.** Nobody outside the team has run it. The \"ask\" label for a shared name follows the "
            "plan, not the daemon's design for a name this Mac holds; those turns are shown apart above.",
            "- **\"Asked\" is a question mark.** A reply with a question mark and no send counts as asking; what it asked is not judged.",
            "- **Reader calls are counted with stubbed models**, over two minutes, and scaled to an hour.",
            "- **The machine was shared** with other work; each row has the load at its start and end."]
    out += ["- **Two scorer rules were written after the first rows were read**, and say so here: a turn whose brain steps "
            "all failed is crashed, not \"asked\" (the daemon's \"say that again?\" has a question mark); and rates are over the "
            "turns that were driven, with the crashed and not-run counts beside them, because a turn never reached lowered "
            "the wrong-session rate when it sat in the denominator.",
            "- **A run that stopped early drove fewer turns.** Each run types the 60 turns in its own shuffled order (the "
            "seed and the order are in its manifest), so a run that stopped at its launch's spend limit covers the first "
            "part of its own order: not the same turns as a whole run. The run list above has each stop; a stopped run "
            "that was made again whole is listed as superseded and not counted."]
    if missing:
        out.append("- **Not run:** the turn list at " + "; ".join(missing) + ".")
    if not bursts:
        out.append("- **Not run:** 30 sessions ending their turn within a minute (a paid run), at any size or arm.")
    return "\n".join(out) + "\n"


def write(results: Path, out: Path, frozen_path: Path, dataset_sha: str, fleets: dict[str, dict]) -> str:
    """RESULTS.md from the rows, or Refused with nothing written."""
    frozen = json.loads(frozen_path.read_text()) if frozen_path.exists() else {}
    ledger_path = results / "ledger.jsonl"
    ledger = [json.loads(line) for line in ledger_path.read_text().splitlines() if line.strip()] if ledger_path.exists() else []
    trees_path = results / "pointe-trees.json"
    text = render(load(results), frozen, dataset_sha, fleets, ledger, json.loads(trees_path.read_text()) if trees_path.exists() else {})
    out.write_text(text)
    return text


if __name__ == "__main__":
    import turns as dataset

    fleets = {size: dataset.load(size)[0] for size in SIZES}
    if "--trees" in sys.argv:  # for runs made before a manifest had `pointe_tree`: the tree of pointe/ at each run's commit
        import subprocess

        known = {}
        for r in load(HERE / "results"):
            commit = r["manifest"].get("pointe", {}).get("commit")
            tree = subprocess.run(["git", "-C", str(HERE), "rev-parse", f"{commit}:pointe"], capture_output=True, text=True).stdout.strip()
            if commit and tree:
                known[commit] = tree
        (HERE / "results" / "pointe-trees.json").write_text(json.dumps(known, indent=1, sort_keys=True) + "\n")
    try:
        write(HERE / "results", HERE / "RESULTS.md", dataset.FROZEN, dataset.dataset_sha(), fleets)
    except Refused as e:
        raise SystemExit(str(e))
    print("wrote bench/fleet/RESULTS.md")
