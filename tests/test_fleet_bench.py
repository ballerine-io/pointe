"""The fleet benchmark's scorer and report (bench/fleet/score.py, report.py), on hand-built rows with known answers.
No daemon, no model, no key."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_fleet import load  # noqa: E402

report, score, turns = load("report", "score", "turns")

FLEET = {"sessions": [{"id": "a", "name": "pinwheel", "machine": "studio"}, {"id": "b", "name": "gable", "machine": "studio"},
                      {"id": "c", "name": "shop", "machine": "studio"}, {"id": "d", "name": "shop", "machine": "avi-box"}]}


def turn(kind: str, expect: dict, landed=(), said=(), **more) -> dict:
    return {"kind": "turn", "run": "r1", "arm": "fleet-on", "size": "5x20", "turn": f"{kind}-00", "turn_kind": kind,
            "expect": expect, "deliveries": [{"session": s, "secs": 1.0} for s in landed], "said": list(said), "error": None,
            "load_start": 3.0, "load_end": 3.0, **more}


def rows() -> list[dict]:
    send = {"action": "send", "session": "a"}
    return [
        turn("clear_name", send, ["a"], ["Sent to pinwheel."], first_token_secs=1.0, brain_input_tokens=1000, needs_tokens=500),
        turn("clear_name", send, ["b"], ["Sent."], first_token_secs=2.0, brain_input_tokens=2000, needs_tokens=700),  # wrong session
        turn("clear_name", send, ["a", "b"], ["Sent."], first_token_secs=3.0, brain_input_tokens=3000, needs_tokens=900),  # right and wrong: wrong
        turn("clear_description", send, [], ["Which session do you mean?"], first_token_secs=4.0),  # asked instead
        turn("clear_description", send, [], ["I can't do that."], first_token_secs=9.0, load_end=25.0),  # nothing; too loaded to time
        turn("ambiguous_name", {"action": "ask", "fits": ["c", "d"]}, [], ["Which shop, studio or avi-box?"]),  # asked
        turn("ambiguous_name", {"action": "ask", "fits": ["c", "d"]}, ["c"], ["Sent to shop."]),  # sent
        turn("ambiguous_none", {"action": "ask", "fits": []}, [], ["There is no such session."]),  # neither
        {**turn("ambiguous_none", {"action": "ask", "fits": []}), "error": "the line could not be typed"},  # crashed
        turn("needs_me", {"action": "answer", "sessions": ["a", "b"]}, [], ["Pinwheel needs an answer. Shop is fine."]),
    ]


def test_each_row_counts_as_what_the_rule_says():
    assert [score.outcome(r) for r in rows()] == ["right", "wrong", "wrong", "asked", "nothing", "asked", "sent", "neither",
                                                 "crashed", "answered"]


def test_counts_and_intervals_are_exact():
    s = score.summarize(rows(), FLEET)
    assert (s["turns"], s["crashed"], s["untimed_for_load"]) == (10, 1, 1)
    assert (s["clear"]["right"]["k"], s["clear"]["wrong"]["k"], s["clear"]["asked"]["k"], s["clear"]["nothing"]["k"]) == (1, 2, 1, 1)
    assert s["clear"]["wrong"]["n"] == 5 and s["clear"]["wrong"]["rate"] == 0.4
    assert (round(s["clear"]["wrong"]["low"], 4), round(s["clear"]["wrong"]["high"], 4)) == (0.1176, 0.7693)  # Wilson, 2 of 5
    a = s["ambiguous"]
    assert (a["asked"]["k"], a["sent"]["k"], a["neither"]["k"], a["crashed"], a["asked"]["n"]) == (1, 1, 1, 1, 3)  # crashed: counted apart, not in n
    assert s["first_token"]["n"] == 4 and s["first_token"]["median"] == 2.0 and s["first_token"]["p90"] == 4.0  # the loaded row is not timed
    assert s["needs_tokens"]["max"] == 900 and s["needs_tokens"]["median"] == 700 and s["brain_input"]["median"] == 2000
    assert s["needs_me_named"] == {"turns": 1, "expected": 2, "named": 1, "turns_naming_others": 1}  # pinwheel named, gable not; shop is another


def test_wilson_and_quantiles():
    assert score.wilson(0, 0) == (0.0, 1.0)
    assert tuple(round(x, 4) for x in score.wilson(0, 36)) == (0.0, 0.0964)
    assert tuple(round(x, 4) for x in score.wilson(30, 42)) == (0.5643, 0.8283)
    assert score.quantile([5, 1, 3, 2, 4], 0.5) == 3 and score.quantile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9) == 9
    assert score.quantile([], 0.5) is None and score.bootstrap([], 0.5) is None
    assert score.bootstrap([7.0] * 5) == (7.0, 7.0)


def test_the_bars_say_fail_plainly_and_scale_the_ask_bar():
    at = score.summarize(rows(), FLEET)
    base = score.summarize([turn("clear_name", {"action": "send", "session": "a"}, ["a"], ["Sent."], first_token_secs=1.9,
                                 brain_input_tokens=1900, needs_tokens=400)], FLEET)
    bars = {(b["bar"], b["limit"]): b for b in score.bars(at, base, "5x20", [{"run": "b1", "finished": 30, "spoken": 5, "held": 25,
                                                                           "lost": 0, "error": None}],
                                                         {"all_active": 3000.0, "quiet_80": 600.0, "share": 0.2, "models": "stubbed"})}
    verdicts = {name: b["verdict"] for (name, _), b in bars.items() if name != "wrong session on clear turns"}
    assert verdicts == {'tokens of "what needs me"': "pass", "brain input tokens per turn": "pass",  # 2000 against 1900: +5%
                        "first token, median": "pass", "first token, p90": "FAIL",  # 2.0 against 1.9; 4.0 against 1.9
                        "asked first on ambiguous turns": "FAIL",  # 1 of 3 driven, the bar scaled to 3 of 3
                        "reader calls an hour with 80% of sessions quiet": "pass",
                        "30 sessions finish within a minute": "FAIL"}  # 5 spoken lines
    assert bars[("asked first on ambiguous turns", "at least 3 of 3 (10 of 14, scaled to n)")]["measured"].startswith("1 of 3")
    assert bars[("wrong session on clear turns", "not above the 1x4 rate")]["verdict"] == "FAIL"  # 2 of 5 against 0 of 1
    assert bars[("wrong session on clear turns", "at most 5%")]["verdict"] == "FAIL"
    # one 1x4 turn: every resample of it is 1900 / 1.9 s, so the interval is the spread of the size's own turns
    assert bars[("brain input tokens per turn", "within 10% of 1x4")]["measured"] == "median 2,000 against 1,900 (+5.3%; 95% interval -47.4% to +57.9%)"
    assert bars[("first token, median", "at most 150 ms above 1x4")]["measured"].endswith("(+100 ms; 95% interval -900 ms to +2100 ms)")
    nothing = score.bars(score.summarize([], FLEET), None, "10x30", [], {"share": None})
    assert {b["verdict"] for b in nothing} == {"not measured"}


def _results(tmp_path: Path, dataset_sha: str = "abc") -> Path:
    run = tmp_path / "results" / "fleet-1-turns-5x20-fleet-on-r1"
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({"run": run.name, "what": "turns", "size": "5x20", "arm": "fleet-on", "models": "real",
                                                   "limit": 0, "dataset_sha256": dataset_sha,
                                                   "started": "2026-11-26T10:00:00", "pointe": {"commit": "c1", "pointe_tree": "aaaaaaaaaaaabbbb"}}))
    crash = {"kind": "crash", "run": run.name, "arm": "fleet-on", "size": "5x20", "error": "TimeoutError: the voice stopped answering"}
    (run / "rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [*rows(), crash]))
    smoke = tmp_path / "results" / "fleet-0-turns-5x20-fleet-on-r1"
    smoke.mkdir()
    (smoke / "manifest.json").write_text(json.dumps({"run": smoke.name, "what": "turns", "size": "5x20", "arm": "fleet-on",
                                                     "models": "real", "limit": 6, "dataset_sha256": dataset_sha,
                                                     "started": "2026-11-26T09:00:00", "pointe": {"commit": "c1", "pointe_tree": "aaaaaaaaaaaabbbb"}}))
    (smoke / "rows.jsonl").write_text(json.dumps(rows()[0]) + "\n")
    (tmp_path / "results" / "ledger.jsonl").write_text(json.dumps({"launch": run.name, "what": "turns", "usd": 1.25, "calls": 40}) + "\n")
    (tmp_path / "FROZEN.json").write_text(json.dumps({"dataset_sha256": "abc", "dataset_version": "fleet-test", "frozen_at": "then"}))
    return tmp_path


def test_the_report_is_written_from_the_rows_with_failures_and_exclusions_said(tmp_path):
    at = _results(tmp_path)
    text = report.write(at / "results", at / "RESULTS.md", at / "FROZEN.json", "abc", {"5x20": FLEET})
    assert (at / "RESULTS.md").read_text() == text
    assert "| wrong session on clear turns | at most 5% | 2 of 5 (12% to 77%) | **FAIL** |" in text
    assert "1 runs of the turn list: 9 turns driven, 1 crashed, 0 not run (their run stopped first); no 1x4 run of this arm on this build" in text
    assert "### 5x20, the fleet build, POINTE_FLEET=on, build `aaaaaaaaaa`" in text
    assert "a smoke run of 6 turns | 1 |" in text and "TimeoutError: the voice stopped answering" in text
    assert "| all 1 paid launches | | 40 | 1.2500 |" in text
    assert "**Not run on the newest build (`aaaaaaaaaa`):** the turn list at 1x4, main before the fleet work" in text


def test_the_report_refuses_when_the_dataset_is_not_the_frozen_one(tmp_path):
    at = _results(tmp_path)
    with pytest.raises(report.Refused, match="not the one in FROZEN.json"):
        report.write(at / "results", at / "RESULTS.md", at / "FROZEN.json", "changed", {"5x20": FLEET})
    assert not (at / "RESULTS.md").exists()
    other = _results(tmp_path / "other", dataset_sha="older")
    with pytest.raises(report.Refused, match="made on another dataset"):
        report.write(other / "results", other / "RESULTS.md", other / "FROZEN.json", "abc", {"5x20": FLEET})
    assert not (other / "RESULTS.md").exists()


def test_the_dataset_on_disk_is_the_generators_and_the_frozen_one():
    assert turns.check() == []
    for size in turns.SIZES:
        fleet, listed = turns.load(size)
        kinds = [t["kind"] for t in listed]
        assert len(listed) >= 60 and sum(k in turns.AMBIGUOUS for k in kinds) == 14
        ids = {s["id"] for s in fleet["sessions"]}
        assert all(t["expect"].get("session", next(iter(ids))) in ids for t in listed)


def test_a_turn_whose_brain_never_answered_is_crashed_not_asked():
    lost = turn("clear_name", {"action": "send", "session": "a"}, [], ["I lost my connection to the model for a moment. Say that again?"],
                steps=[{"own": True, "error": "APIConnectionError"}, {"own": True, "error": "APIConnectionError"}])
    assert score.outcome(lost) == "crashed"
    assert score.outcome({**lost, "steps": [{"own": True, "error": "TimeoutError"}, {"own": True, "error": None}]}) == "asked"


def test_a_turn_its_run_never_reached_is_not_run_not_crashed_and_in_no_rate():
    unreached = {"kind": "turn", "run": "r1", "arm": "fleet-off", "size": "5x20", "turn": "clear_name-05", "turn_kind": "clear_name",
                 "expect": {"action": "send", "session": "a"},
                 "error": "not run: stopped after 41 turns: this launch reached its spend limit of $2.00"}
    assert score.outcome(unreached) == "not_run"
    s = score.summarize([*rows(), unreached, {**unreached, "turn_kind": "ambiguous_name"}], FLEET)
    assert (s["turns"], s["driven"], s["crashed"], s["not_run"]) == (12, 9, 1, 2)
    assert s["clear"]["wrong"]["n"] == 5 and s["ambiguous"]["asked"]["n"] == 3  # as without the two rows
    assert s["clear"]["crashed"] == 0 and s["ambiguous"]["crashed"] == 1  # a real crash keeps its count


def test_a_request_taken_for_a_correction_is_listed_with_whether_it_came_right_after_the_send(tmp_path):
    at = _results(tmp_path)
    run = at / "results" / "fleet-1-turns-5x20-fleet-on-r1"
    send = {"action": "send", "session": "a"}
    drop = {"session": "b", "secs": 1.0, "text": "[Voice request] Drop my last request (\"x\"): it was meant for another session."}
    later = [turn("clear_name", send, ["b"], order=0), turn("clear_name", send, ["a"], order=1),
             {**turn("clear_name", send, ["a"], order=2), "turn": "clear_name-07", "deliveries": [drop, {"session": "a", "secs": 1.0, "text": "x"}]}]
    (run / "rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in later))
    text = report.write(at / "results", at / "RESULTS.md", at / "FROZEN.json", "abc", {"5x20": FLEET})
    assert "| fleet-on, build `aaaaaaaaaa` | 5x20 | r1 | clear_name-07 | 2 | no |" in text
    assert "fleet-on `aaaaaaaaaa` 1 of 3." in text


def test_a_burst_finds_a_session_by_the_name_the_voice_gave_it_at_join():
    called = {"a": {"pinwheel"}, "b": {"riddle", "session 0c2a71"}, "c": {"gable"}}
    told, kept, lost = score.burst_named(["a", "b", "c"], ["Pinwheel finished."], ["{'session': 'session 0c2a71', 'kind': 'report'}"], called)
    assert (told, kept, lost) == (["a"], ["b"], ["c"])


def test_the_burst_bar_counts_report_lines_and_not_approvals_or_their_reminders():
    """The owner's reading of "at most 4 spoken lines": lines about finished turns. A line naming no session that
    finished (an approval prompt, its "still waiting" reminder) is not a report line."""
    called = {"a": {"galaxy"}, "b": {"acorn"}, "c": {"wasabi"}, "d": {"ultra"}, "e": {"jupiter"}}
    spoken = ["shrike wants to run: git status. Should it?", "Two updates: galaxy is done. Acorn changed the queue.",
              "Four on dana-rig finished: wasabi, ultra and 2 more.", "shrike's still waiting on your yes or no.",
              "Nutmeg, on omer-lab, is waiting on a permission.", "Jupiter finished the parser."]
    assert score.report_lines(spoken, called) == 3
    row = {"kind": "burst", "run": "b1", "finished": list(called), "spoken": spoken, "held": [], "lost": [], "error": None,
           "report_lines": 3}
    assert score.burst([row])[0]["report_lines"] == 3
    assert score.burst([{k: v for k, v in row.items() if k != "report_lines"}])[0]["report_lines"] == 6  # written before: every line
    out = {b["bar"]: b for b in score.bars(score.summarize([], FLEET), None, "5x20", score.burst([row]), {"share": None})}
    burst = out["30 sessions finish within a minute"]
    assert burst["verdict"] == "pass" and burst["limit"] == "at most 4 spoken report lines, nothing lost", burst
    assert burst["measured"].startswith("3 report lines (6 spoken), 0 held, 0 lost, of 5"), burst
    five = {**row, "spoken": spoken + ["Galaxy again.", "Acorn again."]}
    five["report_lines"] = score.report_lines(five["spoken"], called)
    assert score.bars(score.summarize([], FLEET), None, "5x20", score.burst([five]), {"share": None})[-1]["verdict"] == "FAIL"


def test_the_reader_scenario_has_every_session_end_turns_and_the_user_keep_eighty_percent_quiet():
    """The reader bar at 58af2eb7 measured 20% because 80% of the sessions did nothing (reader_skipped 0): it did not
    exercise the quiet tier. Now both scenarios have every session end its turns on the same schedule, and in
    quiet_80 the user's own words ("keep tide harbor quiet") mark 80% of them quiet first."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("fleet_rules", Path(__file__).resolve().parents[1] / "pointe" / "scale.py")
    scale_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scale_mod)
    (run,) = load("run")
    names = {f"s{i:02d}": n for i, n in enumerate("tide harbor skiff lantern gully pelican orchard pasture cinder alder".split())}
    names["s10"] = "session 0c2a71"  # renamed at join: two words, and not a name anyone says
    due_all, marked_all = run.readers_plan(sorted(names), names, "all_active", seed=7)
    due_quiet, marked = run.readers_plan(sorted(names), names, "quiet_80", seed=7)
    assert due_all == due_quiet and sorted(sid for _, sid in due_all) == sorted(list(names) * 2)
    assert marked_all == [] and len(marked) == 8 and "s10" not in marked  # 80% of 11, rounded down; plain names only
    lines = run.quiet_lines([names[sid] for sid in marked])
    assert all(len(line.split()) <= 9 for line in lines)
    told = [scale_mod.quiet_intent(line) for line in lines]
    assert all(t and t[0] for t in told) and sorted(" ".join(t[1] for t in told).split()) == sorted(names[sid] for sid in marked)


def test_the_reader_bar_compares_with_the_all_followed_figure_and_refuses_a_run_that_marked_nothing():
    followed = {"kind": "readers", "scenario": "all_active", "per_hour": 1000.0, "models": "stubbed", "sessions": 100}
    quiet = {"kind": "readers", "scenario": "quiet_80", "per_hour": 250.0, "models": "stubbed", "sessions": 100,
             "marked_quiet": 80, "tiers_after_marking": {"focus": 2, "background": 18, "quiet": 80}}
    got = score.readers([quiet], [followed])
    assert (got["all_active"], got["quiet_80"], got["share"]) == (1000.0, 250.0, 0.25)
    old = {k: v for k, v in quiet.items() if k not in ("marked_quiet", "tiers_after_marking")}
    refused = score.readers([old], [followed])  # written before: 80% idle, none quiet
    assert refused["share"] is None and "none quiet" in refused["why"]
    assert "2 of 100" in score.readers([{**quiet, "marked_quiet": 2}], [followed])["why"]
    bar = next(b for b in score.bars(score.summarize([], FLEET), None, "5x20", [], got) if b["bar"].startswith("reader calls"))
    assert bar["verdict"] == "pass" and bar["limit"] == "at most 30% of all followed (rules off, every turn read)", bar
    assert "80 of 100 marked quiet, 80 quiet in the tiers" in bar["note"], bar
