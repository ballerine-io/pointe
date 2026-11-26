"""The fleet benchmark's scorer and report (bench/fleet/score.py, report.py), on hand-built rows with known answers.
No daemon, no model, no key."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bench" / "fleet"))
import report  # noqa: E402
import score  # noqa: E402

FLEET = {"sessions": [{"id": "a", "name": "tide", "machine": "studio"}, {"id": "b", "name": "quarry", "machine": "studio"},
                      {"id": "c", "name": "shop", "machine": "studio"}, {"id": "d", "name": "shop", "machine": "avi-box"}]}


def turn(kind: str, expect: dict, landed=(), said=(), **more) -> dict:
    return {"kind": "turn", "run": "r1", "arm": "fleet-on", "size": "5x20", "turn": f"{kind}-00", "turn_kind": kind,
            "expect": expect, "deliveries": [{"session": s, "secs": 1.0} for s in landed], "said": list(said), "error": None,
            "load_start": 3.0, "load_end": 3.0, **more}


def rows() -> list[dict]:
    send = {"action": "send", "session": "a"}
    return [
        turn("clear_name", send, ["a"], ["Sent to tide."], first_token_secs=1.0, brain_input_tokens=1000, needs_tokens=500),
        turn("clear_name", send, ["b"], ["Sent."], first_token_secs=2.0, brain_input_tokens=2000, needs_tokens=700),  # wrong session
        turn("clear_name", send, ["a", "b"], ["Sent."], first_token_secs=3.0, brain_input_tokens=3000, needs_tokens=900),  # right and wrong: wrong
        turn("clear_description", send, [], ["Which session do you mean?"], first_token_secs=4.0),  # asked instead
        turn("clear_description", send, [], ["I can't do that."], first_token_secs=9.0, load_end=25.0),  # nothing; too loaded to time
        turn("ambiguous_name", {"action": "ask", "fits": ["c", "d"]}, [], ["Which shop, studio or avi-box?"]),  # asked
        turn("ambiguous_name", {"action": "ask", "fits": ["c", "d"]}, ["c"], ["Sent to shop."]),  # sent
        turn("ambiguous_none", {"action": "ask", "fits": []}, [], ["There is no such session."]),  # neither
        {**turn("ambiguous_none", {"action": "ask", "fits": []}), "error": "the line could not be typed"},  # crashed
        turn("needs_me", {"action": "answer", "sessions": ["a", "b"]}, [], ["Tide needs an answer. Shop is fine."]),
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
    assert (a["asked"]["k"], a["sent"]["k"], a["neither"]["k"], a["crashed"], a["asked"]["n"]) == (1, 1, 1, 1, 4)  # the crashed row stays in n
    assert s["first_token"]["n"] == 4 and s["first_token"]["median"] == 2.0 and s["first_token"]["p90"] == 4.0  # the loaded row is not timed
    assert s["needs_tokens"]["max"] == 900 and s["needs_tokens"]["median"] == 700 and s["brain_input"]["median"] == 2000
    assert s["needs_me_named"] == {"turns": 1, "expected": 2, "named": 1, "turns_naming_others": 1}  # tide named, quarry not; shop is another


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
                        "asked first on ambiguous turns": "FAIL",  # 1 of 4, the bar scaled to 3 of 4
                        "reader calls an hour with 80% of sessions quiet": "pass",
                        "30 sessions finish within a minute": "FAIL"}  # 5 spoken lines
    assert bars[("asked first on ambiguous turns", "at least 3 of 4 (10 of 14, scaled to n)")]["measured"].startswith("1 of 4")
    assert bars[("wrong session on clear turns", "not above the 1x4 rate")]["verdict"] == "FAIL"  # 2 of 5 against 0 of 1
    assert bars[("wrong session on clear turns", "at most 5%")]["verdict"] == "FAIL"
    nothing = score.bars(score.summarize([], FLEET), None, "10x30", [], {"share": None})
    assert {b["verdict"] for b in nothing} == {"not measured"}


def _results(tmp_path: Path, dataset_sha: str = "abc") -> Path:
    run = tmp_path / "results" / "fleet-1-turns-5x20-fleet-on-r1"
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({"run": run.name, "what": "turns", "size": "5x20", "arm": "fleet-on", "models": "real",
                                                   "limit": 0, "dataset_sha256": dataset_sha}))
    crash = {"kind": "crash", "run": run.name, "arm": "fleet-on", "size": "5x20", "error": "TimeoutError: the voice stopped answering"}
    (run / "rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [*rows(), crash]))
    smoke = tmp_path / "results" / "fleet-0-turns-5x20-fleet-on-r1"
    smoke.mkdir()
    (smoke / "manifest.json").write_text(json.dumps({"run": smoke.name, "what": "turns", "size": "5x20", "arm": "fleet-on",
                                                     "models": "real", "limit": 6, "dataset_sha256": dataset_sha}))
    (smoke / "rows.jsonl").write_text(json.dumps(rows()[0]) + "\n")
    (tmp_path / "results" / "ledger.jsonl").write_text(json.dumps({"launch": run.name, "what": "turns", "usd": 1.25, "calls": 40}) + "\n")
    (tmp_path / "FROZEN.json").write_text(json.dumps({"dataset_sha256": "abc", "dataset_version": "fleet-test", "frozen_at": "then"}))
    return tmp_path


def test_the_report_is_written_from_the_rows_with_failures_and_exclusions_said(tmp_path):
    at = _results(tmp_path)
    text = report.write(at / "results", at / "RESULTS.md", at / "FROZEN.json", "abc", {"5x20": FLEET})
    assert (at / "RESULTS.md").read_text() == text
    assert "| wrong session on clear turns | at most 5% | 2 of 5 (12% to 77%) | **FAIL** |" in text
    assert "1 runs of the turn list, 10 turn rows, 1 crashed; no 1x4 run of this arm" in text
    assert "a smoke run of 6 turns | 1 |" in text and "TimeoutError: the voice stopped answering" in text
    assert "| all 1 paid launches | | 40 | 1.2500 |" in text
    assert "**Not run:** the turn list at 1x4, main before the fleet work" in text


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
    import turns

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
