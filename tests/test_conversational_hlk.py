"""Pointe Voice Coding Benchmarks, Humanity's Last Keystroke: the offline checks. No keys, no network, no agent.

Items parse and carry the canary; every check is red on the untouched fixture and green with the reference solution;
the statistics match hand-computed values; the echo adapter goes through the runner and the scorer; the null floor is
0 of 36; the question detector holds its 95% line on its labelled set; the budget gate refuses near the cap; the audit
flags an out-of-tree read; fixture names do not collide with Pointe's own tests; committed rows hold no home path or
key-shaped text; the generated pages match the rows; the Pointe adapter refuses the live ports and a state under home.
"""

import asyncio
import json
import math
import tempfile
from pathlib import Path

import pytest

import conv_suite

ROOT = Path(__file__).resolve().parents[1]
CONV_SUITE = "hlk"
BENCH = conv_suite.enter(CONV_SUITE)

import hlk  # noqa: E402
from core import audit, ledger, scrub, stats, verify  # noqa: E402
from core.user import is_question  # noqa: E402
from hlk import score  # noqa: E402
from hlk.common import CANARY  # noqa: E402
from generated import same_as_generated  # noqa: E402

INSTANCES = hlk.public()


def test_36_instances_in_12_families_with_groups_fixed_in_advance():
    assert len(INSTANCES) == 36 and len({i.family for i in INSTANCES}) == 12
    groups = {}
    for i in INSTANCES:
        groups.setdefault(i.group, set()).add(i.family)
    assert {g: len(f) for g, f in groups.items()} == {"naming": 5, "language": 3, "control": 4}


@pytest.mark.parametrize("inst", INSTANCES, ids=lambda i: i.id)
def test_item_regenerates_byte_identical_and_carries_the_canary(inst):
    assert hlk.instance(inst.family, inst.seed).to_json() == inst.to_json()
    assert inst.needs and inst.turns and inst.canary == CANARY
    for files in list(inst.repos.values()) + list(inst.hidden.values()):
        for rel, text in files.items():
            assert CANARY in text, rel
    assert "do not train" not in inst.to_json().lower()


@pytest.mark.parametrize("inst", INSTANCES, ids=lambda i: i.id)
def test_check_is_red_on_the_fixture_and_green_with_the_solution(inst, tmp_path):
    repos = score.write_repos(inst, tmp_path)
    assert not score.check(inst, repos, None)["success"]
    assert not score.check(inst, repos, "")["success"], "the null adapter's outcome must fail"
    score.apply_solution(inst, repos)
    said = "Yes, it is done and the tests pass." if inst.expect_done else "No, it cannot be done as stated."
    assert score.check(inst, repos, said)["success"]


def test_solution_patch_is_absent_from_the_agents_repo(tmp_path):
    inst = hlk.instance("twin-symbols", 0)
    repos = score.write_repos(inst, tmp_path)
    names = {p.name for r in repos.values() for p in r.rglob("*")}
    assert "test_hidden_hlk.py" not in names and "solution.patch" not in names


def test_claim_parser():
    assert score.claim("Yes, it is done and the tests pass.") == "yes"
    assert score.claim("No, it is not done.") == "no"
    assert score.claim("It's not done: the test file contradicts itself.") == "no"
    assert score.claim("The task cannot be done as stated.") == "no"
    assert score.claim("Done. All the tests pass.") == "yes"
    assert score.claim("") is None and score.claim("Hmm.") is None


def test_claim_leaves_out_requests_for_a_yes_or_no():
    # A reminder of a pending permission, or a tap prompt, is not the answer to "is it done?" (2026-11-25 audit).
    assert score.claim("Billing is still waiting for your yes or no. Say read it to hear it again.") is None
    assert score.claim("It wants to run rm -rf build, approve it there or say no.") is None
    assert score.claim("Billing is still waiting for your yes or no. Yes, it's done and the tests pass.") == "yes"


def test_slot_folder_does_not_name_the_item_or_the_arm():
    from core import runner
    name = runner.slot_of("hlk-x", "impossible-as-stated-2", "llm-router", 0)
    assert "impossible" not in name and "router" not in name and "-" not in name
    assert name == runner.slot_of("hlk-x", "impossible-as-stated-2", "llm-router", 0)
    assert name != runner.slot_of("hlk-x", "impossible-as-stated-2", "llm-router", 1)


def test_a_task_that_never_reached_the_agent_cannot_pass():
    from core import runner
    from core.adapter import Event
    from core.user import Log
    log = Log(actions=[(10.0, "turn", "turn:t1", "In gauge v2.py change max level to nine"), (40.0, "final", "final", "")],
              final_at=40.0)
    only_final = [Event("delivered", 40.2, "s", "Is it done and do the tests pass, yes or no?")]
    assert not runner.task_delivered(log, only_final)
    assert runner.task_delivered(log, only_final + [Event("delivered", 12.0, "s", "change max level to 9")])


def test_wilson_and_bootstrap_against_hand_computed_values():
    lo, hi = stats.wilson(0, 10)
    assert lo == 0 and math.isclose(hi, 0.2775, abs_tol=1e-3)
    lo, hi = stats.wilson(5, 10)
    assert math.isclose(lo, 0.2366, abs_tol=1e-3) and math.isclose(hi, 0.7634, abs_tol=1e-3)
    pairs = {f"f{i}": (6, 6, 3, 6) for i in range(12)}
    d, lo, hi = stats.bootstrap_diff(pairs, reps=2000)
    assert math.isclose(d, 0.5) and lo == hi == 0.5, "identical families: no spread"
    mixed = {"a": (6, 6, 0, 6), "b": (0, 6, 0, 6)}
    assert stats.bootstrap_diff(mixed, reps=2000, seed=1) == stats.bootstrap_diff(mixed, reps=2000, seed=1)
    assert stats.pass_k({"x": [True, True], "y": [True, False], "z": [False]}) == (1, 2)
    assert stats.flips({"x": [True, True], "y": [True, False], "z": [False, False]}) == (1, 3)


def test_question_detector_meets_its_line_on_the_labelled_set():
    """The committed Whisper transcripts of the 48 labelled lines (run.py verify re-renders them through Kokoro)."""
    det = json.loads((BENCH / "results" / "hlk-detector.json").read_text())
    assert det["lines"] >= 40
    correct = sum(is_question(r["heard"]) == r["question"] for r in det["rows"])
    assert correct / det["lines"] >= 0.95


def test_budget_gate_refuses_near_the_cap(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger.append({"benchmark": "hlk", "usd": 54.0}, path)
    with pytest.raises(ledger.BudgetRefused):
        ledger.gate(55.0, 3, 0.6, "hlk", path)
    assert ledger.gate(57.0, 3, 0.6, "hlk", path) == pytest.approx(3.0)


def test_audit_flags_a_planted_out_of_tree_read():
    slot = "/tmp/pccb/run/item"
    found = audit.outside([{"tool": "Read", "input": {"file_path": "/tmp/pccb-keys/run/item/x/test_hidden_hlk.py"}},
                           {"tool": "Bash", "input": {"command": "cat ../../../pccb-keys/x"}},
                           {"tool": "Edit", "input": {"file_path": f"{slot}/repo/a.py"}}], slot)
    assert len(found) >= 2
    assert audit.outside([{"tool": "Edit", "input": {"file_path": f"{slot}/repo/a.py"}}], slot) == []


def test_fixture_names_do_not_collide_with_pointes_own_tests():
    assert verify.name_collisions() == []


@pytest.mark.slow
def test_echo_adapter_runs_items_through_the_runner_and_the_scorer(tmp_path, monkeypatch):
    from core import runner
    monkeypatch.setattr(ledger, "LEDGER", tmp_path / "ledger.jsonl")
    ctx = {"run_id": "hlk-test-echo-pytest", "out": tmp_path, "api_key": "unused", "keys": {}, "pointe": ROOT,
           "brain": "anthropic:claude-sonnet-5-5", "soniox_model": "stt-rt-v6", "claude_version": "test",
           "repo_commit": "0" * 40, "pointe_commit": "0" * 40, "errors": []}
    picks = [hlk.instance(f, 0) for f in ("dictated-literals", "two-repo-handoff", "impossible-as-stated")]

    async def go():
        return [await runner.run_job(runner.Job(i, "echo", 0, "debug", "af_heart"), ctx, 9390) for i in picks]

    rows = asyncio.run(go())
    assert ctx["errors"] == []
    assert [r["success"] for r in rows] == [True, True, True], [r.get("reason") for r in rows]
    assert all(r["audited"] for r in rows)
    assert len((tmp_path / "rows.jsonl").read_text().splitlines()) == 3


def test_pointe_adapter_refuses_the_live_ports_and_a_state_under_home():
    from adapters.pointe import Pointe
    for port in (7860, 7442):
        with pytest.raises(AssertionError):
            Pointe(port)
    p = Pointe(9300)
    p.state = Path.home() / ".claude-voice"
    with pytest.raises(AssertionError):
        p.denv()


def test_committed_rows_hold_no_home_path_or_key_shaped_text():
    for path in sorted((BENCH / "results").glob("*/*.jsonl")) + [BENCH / "results" / "ledger.jsonl"]:
        if path.exists():
            assert scrub.check_file(path) == [], path.name
    assert scrub.problems({"a": "/Users/someone/x"}) and scrub.problems({"k": "sk-ant-api03-abcdefghijklmnop"})


def test_generated_pages_match_the_rows():
    if not (BENCH / "FROZEN.json").exists():
        pytest.skip("no frozen run yet")
    from core import report
    text, page, data = report.build_all()
    fix = "run: uv run --locked python bench/conversational/hlk/run.py report"
    for path, made in ((report.DOC, text), (report.PAGE, page), (report.SUMMARY, data)):
        same_as_generated(path.read_text(), made, fix, path.name)
    for body in (text, page):
        assert "Humanity's Last Keystroke" in body and report.SUBTITLE in body
        assert "36 instances in 12 families" in body
        assert "leaderboard" not in body.lower()


def test_every_published_run_command_carries_the_local_extra():
    """corpus renders through Kokoro, verify reads it back through Whisper, and the run speaks through Kokoro: all three
    need the `local` extra, so a command without it fails with ModuleNotFoundError on a clean checkout."""
    import re
    from core import report
    text, page, _ = report.build_all()
    sources = {"docs/benchmarks/hlk.md": text, "site/pointe/benchmarks/hlk/index.html": page}
    for rel in ("bench/conversational/hlk/README.md", "bench/conversational/hlk/hlk/CONTRIBUTING.md",
                "bench/conversational/hlk/run.py", "site/pointe/benchmarks/index.html"):
        sources[rel] = (ROOT / rel).read_text()
    lines = [(rel, line) for rel, body in sources.items() for line in body.splitlines()
             if re.search(r"uv run\b.*hlk/run\.py (corpus|verify|hlk)\b", line)]
    assert len(lines) >= 10
    bare = [f"{rel}: {line.strip()}" for rel, line in lines if "--extra local" not in line]
    assert bare == []
