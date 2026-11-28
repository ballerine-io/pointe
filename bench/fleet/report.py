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
    if m["what"] in ("burst", "dialogue"):
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
           trees: dict[str, str] | None = None, carried: list[dict] | None = None) -> str:
    trees, carried = trees or {}, carried or []
    if not frozen or frozen.get("dataset_sha256") != dataset_sha:
        raise Refused("the dataset on disk is not the one in FROZEN.json: no report")
    used = [r for r in runs if counted(r)]
    for r in used:
        if r["manifest"]["what"] in ("turns", "burst") and r["manifest"]["dataset_sha256"] != dataset_sha:
            raise Refused(f"{r['manifest']['run']} was made on another dataset: no report")
    left = [r for r in runs if not counted(r)]
    # Bursts written before a session was looked for by the name the voice gave it at join too: counted again here.
    for r in used:
        names = r["manifest"].get("names") or {}
        for x in r["rows"]:
            if x["kind"] == "burst" and not x.get("error") and r["manifest"]["size"] in fleets:
                dataset = {s["id"]: s["name"] for s in fleets[r["manifest"]["size"]]["sessions"]}
                called = {sid: {dataset[sid], *([names[sid]] if names.get(sid) else [])} for sid in x["finished"]}
                told, kept, lost = score.burst_named(x["finished"], x["spoken"], x["held"], called)
                if lost != x["lost"]:
                    x["lost_as_written"] = len(x["lost"])
                x.update(named_in_speech=len(told), named_in_held=len(kept), lost=lost,
                         report_lines=score.report_lines(x["spoken"], called))
    out = ["<!-- Written by bench/fleet/report.py from bench/fleet/results/. Do not edit by hand. -->", "",
           "# Fleet benchmark: one voice, many machines and sessions", "",
           "A self-evaluation: Pointe's team wrote the simulator, the turns, the labels and the scorer. Typed text, "
           "scripted stand-in sessions, synthetic names. Every number below is computed from the rows in "
           "`bench/fleet/results/`; intervals are 95% (Wilson for counts, a bootstrap over turns for medians and p90).", "",
           f"Dataset `{frozen.get('dataset_version')}`, frozen {frozen.get('frozen_at')}, sha256 `{dataset_sha[:16]}`. "
           "60 turns a size; expected outcomes labelled by rule from the fleet's description (`bench/fleet/turns.py`).", ""]
    def build(r: dict) -> str:
        p = r["manifest"].get("pointe") or {}
        return (trees.get(p.get("commit"), p.get("pointe_tree")) or "unknown")[:10]

    # One section a build: both arms of a comparison ran the same pointe/ folder. Builds in the order they were run.
    order: list[str] = []
    for r in sorted(used, key=lambda r: r["manifest"]["started"]):
        if r["manifest"]["what"] in ("turns", "burst") and build(r) not in order:
            order.append(build(r))
    by: dict[tuple[str, str], list[dict]] = {}
    held_apart: list[dict] = []  # turns about a session the voice renamed at join: a group of their own
    for r in used:
        apart = [x for x in r["rows"] if x.get("renamed_at_join") or x.get("near_name")]
        held_apart += [{**x, "build": build(r)} for x in apart]
        r = {**r, "rows": [x for x in r["rows"] if not (x.get("renamed_at_join") or x.get("near_name"))]}
        tag = build(r) if r["manifest"]["what"] in ("turns", "burst") else "any"
        by.setdefault((f"{r['manifest']['arm']}@{tag}", r["manifest"]["size"]), []).append(r)
        for c in carried:  # an arm whose code path is the same in a later build: its runs stand for that build too
            if tag == c["from"][:10] and r["manifest"]["arm"] == c["arm"] and c["to"][:10] in order:
                by.setdefault((f"{c['arm']}@{c['to'][:10]}", r["manifest"]["size"]), []).append(r)

    def rows_of(arm: str, size: str, what: str) -> list[dict]:
        return [row for r in by.get((arm, size), []) if r["manifest"]["what"] == what for row in r["rows"]]

    def words(arm_at: str) -> str:
        arm, tag = arm_at.split("@")
        came = next((c for c in carried if c["arm"] == arm and c["to"][:10] == tag), None)
        return ARM_WORDS[arm] + (f", build `{tag}`" if tag != "any" else "") + (f" (rows of build `{came['from'][:10]}`, carried)" if came else "")

    arms_at = [f"{arm}@{tag}" for tag in order for arm in ARMS]

    out += ["## Bars", ""]
    measured_any = False
    for arm in arms_at:
        plain = arm.split("@")[0] + "@any"  # reader counts are made with stubbed models, on the newest build only
        base_rows = [x for x in rows_of(arm, "1x4", "turns") if x["kind"] == "turn"]
        base = score.summarize(base_rows, fleets.get("1x4")) if base_rows else None
        for size in SIZES:
            turn_rows = [x for x in rows_of(arm, size, "turns") if x["kind"] == "turn"]
            bursts = score.burst(rows_of(arm, size, "burst"))
            readers = score.readers(rows_of(plain, size, "readers"), rows_of("fleet-off@any", size, "readers"))
            if not turn_rows and not bursts:
                continue
            measured_any = True
            at = score.summarize(turn_rows, fleets.get(size))
            n_runs = len([r for r in by.get((arm, size), []) if r["manifest"]["what"] == "turns"])
            out += [f"### {size}, {words(arm)}", "",
                    f"{n_runs} runs of the turn list: {at['driven']} turns driven, {at['crashed']} crashed, {at['not_run']} not run (their run stopped first)"
                    + ("; no 1x4 run of this arm on this build, so nothing to compare with" if size != "1x4" and base is None else "") + ".", "",
                    "| Bar | The plan's bar | Measured | |", "|---|---|---|---|"]
            for b in score.bars(at, base, size, bursts, readers):
                out.append(f"| {b['bar']} | {b['limit']} | {b['measured']}{'; ' + b['note'] if b['note'] else ''} | **{b['verdict']}** |")
            out.append("")
    if not measured_any:
        out += ["Nothing measured yet.", ""]

    want = {"fleet-on": True, "fleet-off": False, "baseline": None}
    checked = [x for r in used for x in r["rows"] if x["kind"] in ("turn", "burst", "readers") and not x.get("error")]
    off_arm = [x for x in checked if x.get("fleet_on") is not want[x["arm"]]]
    builds = sorted({(r["manifest"]["arm"], build(r)) for r in used if r["manifest"]["what"] in ("turns", "burst")})
    out += ["## The arms, as the daemon states them", "",
            f"{len(checked) - len(off_arm)} of {len(checked)} rows carry the daemon's own `fleet.on` (`/voice/context`) equal to their arm's"
            + (f"; **{len(off_arm)} do not**" if off_arm else "") + ". The `pointe/` folder each arm ran (its git tree): " + ", ".join(f"{a} `{c}`" for a, c in builds) + ".", ""]
    for c in carried:
        out += [f"Carried: the {c['arm']} rows of build `{c['from'][:10]}` are shown again under build `{c['to'][:10]}`, not run again. {c['why']}", ""]
    out += ["## Every run", "",
            "| Arm | Size | Run | Clear: right | Clear: wrong session | Clear: asked instead | Clear: nothing | Ambiguous: asked | "
            "Ambiguous: sent | Ambiguous: neither | Driven / crashed / not run | Needs tokens, median / max | Brain input per turn, median | "
            "First token, median / p90 | First send, median | Reader / checker / brain calls in the run |", "|" + "---|" * 16]
    def key_order(kv):
        (arm, size), _ = kv
        return (arms_at.index(arm) if arm in arms_at else 99, SIZES.index(size) if size in SIZES else 9)

    for (arm, size), group in sorted(by.items(), key=key_order):
        turn_runs = [r for r in group if r["manifest"]["what"] == "turns"]
        sets = [(r["manifest"]["run"], [x for x in r["rows"] if x["kind"] == "turn"], model_calls(r.get("calls") or [])) for r in turn_runs]
        if len(sets) > 1:
            sets.append(("all runs", [x for _, rows, _ in sets for x in rows], tuple(sum(c[i] for _, _, c in sets) for i in range(3))))
        for name, rows, made in sets:
            s = score.summarize(rows, fleets.get(size))
            c, a = s["clear"], s["ambiguous"]
            out.append(f"| {words(arm)} | {size} | {name} | {_pct(c['right'])} | {_pct(c['wrong'])} | {_pct(c['asked'])} | {_pct(c['nothing'])} | "
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
    for (arm, size), group in sorted(by.items(), key=key_order):
        rows = [x for r in group if r["manifest"]["what"] == "turns" for x in r["rows"] if x["kind"] == "turn"]
        if not rows:
            continue
        arm = words(arm)
        s = score.summarize(rows, fleets.get(size))
        for kind, counts in s["by_kind"].items():
            out.append(f"| {arm} | {size} | {kind} | {counts['n']} | " + ", ".join(f"{k} {v}" for k, v in counts.items() if k != "n") + " |")
        held = [x for x in rows if x["turn_kind"] == "ambiguous_name"]
        for flag, held_by in ((True, "this Mac has a session of the name"), (False, "only other machines have one")):
            part = [x for x in held if x.get("this_mac_holds") is flag]
            if part:
                tally: dict[str, int] = {}
                for x in part:
                    tally[score.outcome(x)] = tally.get(score.outcome(x), 0) + 1
                out.append(f"| {arm} | {size} | ambiguous_name, {held_by} | {len(part)} | " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())) + " |")
        for kind in score.QUESTIONS:
            q = s.get(f"{kind}_named")
            if q and q["turns"]:
                out.append(f"| {arm} | {size} | {kind}: expected sessions named in the reply | {q['turns']} | "
                           f"{q['named']} of {q['expected']} names; {q['turns_naming_others']} replies name a session not expected |")
    out.append("")

    out += ["## Turns about a session the voice renamed when it joined, or whose name is one letter from another's", ""]
    if held_apart:
        tally: dict[tuple, dict[str, int]] = {}
        for x in held_apart:
            if x["kind"] == "turn":
                cell = tally.setdefault((f"{x['arm']}, build `{x['build']}`", x["size"],
                                         x["turn_kind"] + (", renamed session" if x.get("renamed_at_join") else ", a name one letter from another's")), {})
                cell[score.outcome(x)] = cell.get(score.outcome(x), 0) + 1
        out += ["The voice's own naming rules refused some dataset names at join and gave those sessions a name of its own "
                "(\"session 1a2b3c\"; each run's manifest lists them under `renamed_at_join`). A turn that expects, fits or "
                "lists such a session has a label the fleet no longer matches. A turn that says a name one letter from another "
                "session's (\"fennel\", \"funnel\") is marked from the first runs that record it. Those turns are in no rate above, and are here.", "",
                "| Arm | Size | Kind | Outcomes |", "|---|---|---|---|"]
        for (arm, size, kind), cell in sorted(tally.items()):
            out.append(f"| {arm} | {size} | {kind} | " + ", ".join(f"{k} {v}" for k, v in sorted(cell.items())) + " |")
        out.append("")
    else:
        out += ["None in the runs counted.", ""]

    # The frozen turns hold no correction, so a "Drop my last request" delivery is always a request the voice took for one.
    out += ["## Requests taken for a correction (\"Drop my last request\" sent)", ""]
    taken = []
    for r in used:
        turns = sorted((x for x in r["rows"] if x["kind"] == "turn"), key=lambda x: x.get("order", 0))
        for before, x in zip([None, *turns], turns):
            dropped = [d["session"] for d in x.get("deliveries") or [] if "Drop my last request" in d.get("text", "")]
            if dropped:
                last = {d["session"] for d in (before or {}).get("deliveries") or []}
                taken.append((r, x, all(s in last for s in dropped)))
    if taken:
        out += ["The frozen turns have no correction in them: each row here is a new request the voice took for a correction of "
                "an earlier send, and told that earlier session to drop its work. Counted as a wrong session above. \"Right after "
                "the send\": the session told to drop got the turn just before.", "",
                "| Arm | Size | Run | Turn | Order | Right after the send |", "|---|---|---|---|---|---|"]
        for r, x, after in taken:
            out.append(f"| {r['manifest']['arm']}, build `{build(r)}` | {x['size']} | {x['run']} | {x['turn']} | {x.get('order')} | {'yes' if after else 'no'} |")
        out.append("")
    else:
        out += ["None in the runs counted.", ""]
    out += ["By build and arm, rows with such a send, of the turns driven: " + ", ".join(
        f"{arm} `{tag}` {sum(1 for r, _, _ in taken if r['manifest']['arm'] == arm and build(r) == tag)} of "
        f"{sum(1 for r in used if r['manifest']['what'] == 'turns' and r['manifest']['arm'] == arm and build(r) == tag for x in r['rows'] if x['kind'] == 'turn' and score.outcome(x) not in ('crashed', 'not_run'))}"
        for tag in order for arm in ARMS if any(r["manifest"]["what"] == "turns" and r["manifest"]["arm"] == arm and build(r) == tag for r in used)) + ".", ""]

    probes = [(r, row) for r in used for row in r["rows"] if row["kind"] == "probe"]
    if probes:
        out += ["## Probe: \"What did I send to <session>?\" after the 60 turns", "",
                "Not part of the frozen dataset and in no bar (`bench/fleet/probes.json`, its hash in each row). Asked about "
                "the session that got the run's first delivery. Recalled: the reply has a word of five letters or more from "
                "that request, and nothing was sent.", "", "| Arm | Size | Run | Recalled | The reply |", "|---|---|---|---|---|"]
        for r, x in probes:
            said = " ".join(x.get("said") or [])[:160].replace("|", "/")
            out.append(f"| {r['manifest']['arm']}, build `{build(r)}` | {x['size']} | {x['run']} | {'yes' if x.get('recalled') else 'no'} | {said} |")
        out.append("")

    bursts = [(r["manifest"], row) for r in used for row in r["rows"] if row["kind"] == "burst"]
    out += ["## 30 sessions end their turn within a minute", ""]
    if bursts:
        out += ["| Arm | Size | Run | Finished | Spoken lines | Report lines spoken | Held items | Named in speech | Named in the held list | Lost | "
                "Report lines (daemon's count) | Not read (quiet) | Reader calls | Error |", "|" + "---|" * 14]
        for m, b in bursts:
            out.append(f"| {m['arm']} | {m['size']} | {m['run']} | {len(b['finished'])} | {len(b['spoken'])} | {b.get('report_lines', 'n/a')} | {len(b['held'])} | "
                       f"{b.get('named_in_speech', 'n/a')} | {b.get('named_in_held', 'n/a')} | {len(b['lost'])}"
                       + (f" (written {b['lost_as_written']})" if "lost_as_written" in b else "")
                       + f" | {(b.get('fleet_stats') or {}).get('report_lines_spoken', 'n/a')} | {(b.get('fleet_stats') or {}).get('reader_skipped', 'n/a')} | "
                       f"{b.get('reader_calls', 'n/a')} | {b.get('error') or ''} |")
        out += ["", "Lost: a session that ended its turn and is named neither in a spoken line nor in the held list when the "
                "fleet went quiet, by its dataset name or the name the voice gave it at join (a run written before that is "
                "counted again, with the count it wrote beside it). Spoken lines: every line said in the window, approvals and "
                "their reminders included. Report lines spoken: the spoken lines that name a session that finished; the bar "
                "counts these (the owner's reading: an approval prompt and its reminder are not reports). Report lines "
                "(daemon's count): the daemon's own count of lines about finished turns. Not read (quiet): finished turns of quiet sessions the daemon did not read.", ""]
    else:
        out += ["Not run.", ""]

    readers = [(r["manifest"], row) for r in used for row in r["rows"] if row["kind"] == "readers"]
    out += ["## Reader calls", ""]
    if readers:
        out += ["| Arm | Size | Scenario | Sessions active | Marked quiet | Quiet in the tiers | Turns ended | Reader calls in the window | "
                "Not read (quiet) | An hour | Error |", "|" + "---|" * 11]
        for m, x in readers:
            out.append(f"| {m['arm']} | {m['size']} | {x.get('scenario')} | {x.get('active_sessions', 'n/a')} of {x.get('sessions', 'n/a')} | "
                       f"{x.get('marked_quiet', 'n/a')} | {(x.get('tiers_after_marking') or {}).get('quiet', 'n/a')} | "
                       f"{x.get('turns_ended', 'n/a')} | {x.get('reader_calls', 'n/a')} | {(x.get('fleet_stats') or {}).get('reader_skipped', 'n/a')} | "
                       f"{_num(x.get('per_hour'))} | {x.get('error') or ''} |")
        out += ["", "Counted with stubbed models: the count is the daemon's own decisions to call the reader, not what a "
                "model wrote. Every session ends a turn once a minute for two minutes; the hourly figure is the window's "
                "count times 30. In quiet_80 the user first types \"keep tide harbor … quiet\" for 80% of the sessions. "
                "The bar compares it with the rules-off arm's all_active, which reads every finished turn (all followed). "
                "Rows written before that (80% of the sessions idle, none marked, \"Marked quiet\" n/a) are listed and "
                "not counted. One run each: n = 1.", ""]
    else:
        out += ["Not run.", ""]

    out += dialogue_section([r for r in sorted(used, key=lambda r: r["manifest"]["started"]) if r["manifest"]["what"] == "dialogue"], build)

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
        out += ["| Run | Build | Why | Rows |", "|---|---|---|---|"]
        for r in left:
            m = r["manifest"]
            why = r.get("not_counted") or ("stubbed models (a dry run)" if m["models"] == "stub" else f"a smoke run of {m.get('limit')} turns")
            out.append(f"| {m['run']} | `{build(r)}` | {why} | {len(r['rows'])} |")
        out.append("")
    else:
        out += ["Nothing: every run folder is counted.", ""]
    crashes = [(r["manifest"]["run"], row["error"]) for r in used for row in r["rows"] if row["kind"] == "crash"]
    if crashes:
        out += ["Runs that ended early (the turns they drove are counted; the turns they did not reach are \"not run\", in no rate):", ""]
        out += [f"- {run}: {why}" for run, why in crashes] + [""]

    newest = order[-1] if order else "any"
    missing = [f"{size}, {ARM_WORDS[arm]}" for arm in ARMS for size in SIZES
               if not [r for r in by.get((f"{arm}@{newest}", size), []) if r["manifest"]["what"] == "turns"]]
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
        out.append(f"- **Not run on the newest build (`{newest}`):** the turn list at " + "; ".join(missing) + ".")
    if not bursts:
        out.append("- **Not run:** 30 sessions ending their turn within a minute (a paid run), at any size or arm.")
    return "\n".join(out) + "\n"


def dialogue_section(runs: list[dict], build) -> list[str]:
    """The fleet dialogues (bench/fleet/dialogue.py): one row a run, each step pass or FAIL with what decided it."""
    out = ["## Fleet dialogues: 8, 15 and 30 sessions, two machines, three harnesses", ""]
    if not runs:
        return out + ["Not run.", ""]
    out += ["| Run | Build | Arm | Sessions | Overview | By name | By topic | Three approvals at once | Flood of reports | Dialogue |",
            "|" + "---|" * 10]
    for r in runs:
        steps = [x for x in r["rows"] if x["kind"] == "dialogue_step"]
        summary = next((x for x in r["rows"] if x["kind"] == "dialogue"), {})

        def cell(kind: str) -> str:
            xs = [x for x in steps if x["step"] == kind]
            if not xs:
                return "not run"
            verdict = "pass" if all(x["passed"] for x in xs) else "**FAIL**"
            x = xs[-1]
            if kind in ("name", "topic"):
                return f"{verdict}: {sum(x['passed'] for x in xs)} of {len(xs)} to the one session named"
            if kind == "approvals":
                allowed = sum(v == "allow" for v in x["verdicts"].values())
                return (f"{verdict}: {x['pending_at_once']} pending at once, {len(x['read_out'])} read out, {allowed} of "
                        f"{len(x['verdicts'])} allowed in {x['taps']} taps, {x['stray_answers']} stray")
            if kind == "flood":
                return (f"{verdict}: {len(x['finished'])} finished, {x['report_lines']} report lines, {x['named_in_held']} held, "
                        f"{len(x['lost'])} lost")
            return verdict + (f": missing {x['why']}" if x.get("why") else "")

        result = "pass" if summary.get("passed") else f"**FAIL**{': ' + summary['error'] if summary.get('error') else ''}"
        out.append(f"| {r['manifest']['run']} | `{build(r)}` | {r['manifest']['arm']} | {summary.get('sessions', 'n/a')} | "
                   f"{cell('overview')} | {cell('name')} | {cell('topic')} | {cell('approvals')} | {cell('flood')} | {result} |")
    out += ["", "Each machine runs sessions of all three harnesses: Claude Code stand-ins, and Codex and OpenCode sessions held "
            "by a fake Codex daemon and a fake OpenCode service on each machine, reached through Pointe's own adapters. "
            "The rules, written before any paid row (`bench/fleet/dialogue.py`): the overview gives each machine's number of "
            "sessions and names both sessions waiting on a question; a request by name or by topic reaches that session and "
            "no other; three approvals asked at once (one per harness, on both machines) are all pending on the page together, "
            "each is read out, each is allowed by a tap on the page (a typed yes never answers an approval), and no other "
            "approval is answered; in the flood every finished turn is said or held and at most "
            "four spoken lines are reports. One dialogue a size: each step is n = 1, pass or fail, with no interval.", ""]
    return out


def write(results: Path, out: Path, frozen_path: Path, dataset_sha: str, fleets: dict[str, dict]) -> str:
    """RESULTS.md from the rows, or Refused with nothing written."""
    frozen = json.loads(frozen_path.read_text()) if frozen_path.exists() else {}
    ledger_path = results / "ledger.jsonl"
    ledger = [json.loads(line) for line in ledger_path.read_text().splitlines() if line.strip()] if ledger_path.exists() else []
    trees_path = results / "pointe-trees.json"
    carried_path = results / "carried.json"
    text = render(load(results), frozen, dataset_sha, fleets, ledger, json.loads(trees_path.read_text()) if trees_path.exists() else {},
                  json.loads(carried_path.read_text()) if carried_path.exists() else [])
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
