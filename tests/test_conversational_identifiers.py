"""Offline checks of the Spoken Identifiers benchmark (bench/conversational, design revision 2, 5.2): no keys, no agent.

The scorer is red on the untouched fixture and green for each reference edit; a decoy edit scores wrong_symbol; every
target has a decoy within edit distance 2 of its spoken form; the null policy scores 0 right and all no-action; the
statistics, the budget gate, the audit, the scrubber and the port guard do what they say.
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "bench" / "conversational"
sys.path.insert(0, str(BENCH))

from adapters.echo import Echo  # noqa: E402
from core import audit, ledger, runner, scrub, stats, user  # noqa: E402
from core.adapter import SpendRow  # noqa: E402
from identifiers import bench, check  # noqa: E402

ITEMS = check.load_items()


@pytest.fixture
def repo(tmp_path):
    def make():
        d = tmp_path / f"r{len(list(tmp_path.iterdir()))}"
        shutil.copytree(check.FIXTURE, d)
        return d
    return make


def test_items_parse_carry_the_canary_and_name_capabilities():
    canary = (BENCH / "CANARY").read_text().strip()
    assert ITEMS["canary"] == canary and canary in (BENCH / "identifiers" / "items.toml").read_text()
    assert ITEMS["capabilities"] == ["text_in"]
    assert len(ITEMS["targets"]) == 24
    classes = [t["class"] for t in ITEMS["targets"].values()]
    assert {c: classes.count(c) for c in set(classes)} == {
        "camel_snake": 6, "homophone": 4, "digits": 4, "dunder_caps": 4, "flag": 4, "nested_path": 2}
    check.anchor_index(ITEMS)  # every anchor is one line, once in its file


@pytest.mark.parametrize("tid", sorted(ITEMS["targets"]))
def test_check_is_red_on_the_fixture_and_green_with_the_reference_edit(repo, tid):
    r = repo()
    assert check.score(r, tid, ITEMS)["outcome"] == "no_action"
    check.reference_edit(r, tid, ITEMS)
    s = check.score(r, tid, ITEMS)
    assert s["outcome"] == "right_symbol" and s["marker_exact"] and not s["others_touched"]


def _mark(r: Path, sid: str, text: str = "marked") -> None:
    s = ITEMS["symbols"][sid]
    p = r / s["file"]
    lines = p.read_text().splitlines(keepends=True)
    i = next(i for i, line in enumerate(lines) if line.strip() == s["anchor"])
    lines.insert(i, f"{check.COMMENT[p.suffix]} {text}\n")
    p.write_text("".join(lines))


@pytest.mark.parametrize("tid", sorted(ITEMS["targets"]))
def test_a_decoy_edit_scores_wrong_symbol(repo, tid):
    t = ITEMS["targets"][tid]
    r = repo()
    _mark(r, t["decoys"][0])
    s = check.score(r, tid, ITEMS)
    assert s["outcome"] == "wrong_symbol" and s["decoys_touched"] == [t["decoys"][0]]
    r2 = repo()  # the target and a decoy together are still harmful
    check.reference_edit(r2, tid, ITEMS)
    _mark(r2, t["decoys"][0])
    assert check.score(r2, tid, ITEMS)["outcome"] == "wrong_symbol"


def test_changing_a_decoys_own_line_is_wrong_symbol_and_an_unrelated_edit_is_other_change(repo):
    r = repo()
    p = r / "almanac" / "lunar.py"
    p.write_text(p.read_text().replace("def parse_moon_phases(lines):", "def parse_moon_phases(lines):  # marked"))
    assert check.score(r, "t01", ITEMS)["outcome"] == "wrong_symbol"
    r2 = repo()
    (r2 / "NOTES.md").write_text("marked\n")
    assert check.score(r2, "t01", ITEMS)["outcome"] == "other_change"


def test_a_marker_with_an_aside_counts_but_is_not_exact(repo):
    r = repo()
    _mark(r, "py.cache.flush", "marked: cache as in a memory cache")
    s = check.score(r, "t07", ITEMS)
    assert s["outcome"] == "right_symbol" and not s["marker_exact"]


@pytest.mark.parametrize("tid", sorted(ITEMS["targets"]))
def test_every_target_has_a_decoy_within_edit_distance_two_of_its_spoken_form(tid):
    assert check.qualifying_decoys(ITEMS, tid), tid


def test_spoken_form_normalization():
    n = check.normalize
    assert n("parse_moon_phase") == n("parseMoonPhase") == "parse moon phase"
    assert n("__version__") == n("VERSION") == "version"
    assert n("checksum_sha256") == "checksum sha 256" and n("renderV2") == "render v 2"
    assert n("--dry-run") == "dry run" and n("--dryrun") == "dryrun"
    assert check.edit_distance("cache flush", "cash flush") == 2


def test_the_clip_plan_draws_two_voices_per_target_one_with_babble():
    clips = [c for c in bench.clip_plan() if not c.get("answer")]
    assert len(clips) == 48
    for tid in ITEMS["targets"]:
        mine = [c for c in clips if c["target"] == tid]
        assert len({c["voice"] for c in mine}) == 2 and sorted(str(c["noise_db"]) for c in mine) == ["12", "None"]
    assert bench.clip_plan() == bench.clip_plan()  # seeded


def test_the_run_plan_has_the_designed_counts():
    runs = bench.run_plan()
    count = {a: sum(r["arm"] == a and r["run_index"] == 0 for r in runs) for a in bench.ARMS}
    assert count == {"keyboard-canonical": 24, "keyboard-transcript": 24, "null": 48, "naive": 48, "llm-router": 48,
                     "pointe": 48, "pointe-text": 24}
    repeats = [r for r in runs if r["run_index"] == 1]
    assert sorted({r["arm"] for r in repeats}) == ["llm-router", "pointe"] and len(repeats) == 24
    assert len({r["key"] for r in runs}) == len(runs)
    assert runs[-1]["run_index"] == 1  # the repeat is last: the first thing a short budget trims


def _ctx():
    return {"items": ITEMS, "model": "m", "mode": "acceptEdits", "deny_read": [], "secrets": {"anthropic": "x"},
            "run_id": "offline", "repo_commit": "c", "pointe_commit": "p", "claude_code": "0", "smoke": True,
            "audio_matches_lock": True}


def test_echo_through_the_runner_and_the_scorer(tmp_path):
    run = next(r for r in bench.run_plan() if r["arm"] == "keyboard-canonical")
    row, spend, log = bench.one(run, 9401, tmp_path / "a", _ctx(),
                                Echo(edit=lambda r: check.reference_edit(r, run["target"], ITEMS)))
    assert row["outcome"] == "right_symbol" and row["delivered"] == [run["text"]]
    decoy = ITEMS["targets"][run["target"]]["decoys"][0]
    row, _, _ = bench.one(run, 9401, tmp_path / "b", _ctx(), Echo(edit=lambda r: _mark(r, decoy)))
    assert row["outcome"] == "wrong_symbol"
    scrub.check(json.dumps(row))


def test_the_null_policy_scores_zero_right_and_all_no_action(tmp_path, monkeypatch):
    monkeypatch.setattr(bench.time, "sleep", lambda s: None)
    from adapters.null import Null

    class OfflineNull(Null):
        def start(self, sessions, env):  # the floor's no-ops, without starting an agent
            self.env = env

    outcomes = []
    for i, run in enumerate(r for r in bench.run_plan() if r["arm"] == "null"):
        run = {**run, "clip": None}  # no audio needed: null ignores it
        row, _, _ = bench.one(run, 9401, tmp_path / str(i), _ctx(), OfflineNull())
        outcomes.append(row["outcome"])
    assert len(outcomes) == 48 and set(outcomes) == {"no_action"}


def test_stats_against_hand_computed_values():
    lo, hi = stats.wilson(0, 24)
    assert lo == 0 and abs(hi - 0.1380) < 1e-3
    lo, hi = stats.wilson(12, 24)
    assert abs(lo - 0.3143) < 1e-3 and abs(hi - 0.6857) < 1e-3  # p 0.5, z 1.96: 0.5 -+ 0.1857
    assert stats.flip_rate([(True, True), (True, False), (False, False), (False, True)]) == 0.5
    assert stats.pass_k([[True, True], [True, False]]) == 0.5
    rows = [{"t": i // 2, "v": i % 3 == 0} for i in range(48)]
    a = stats.cluster_bootstrap(rows, lambda r: r["t"], lambda r: r["v"], seed=3)
    assert a == stats.cluster_bootstrap(rows, lambda r: r["t"], lambda r: r["v"], seed=3) and a[0] < 0.34 < a[1]
    d, lo, hi = stats.paired_bootstrap({1: [1], 2: [1]}, {1: [0], 2: [1]})
    assert d == 0.5 and lo <= d <= hi


def test_the_budget_gate_refuses_a_launch_near_the_cap(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger.add("identifiers", "r", "i", "run", [SpendRow("x", 11.9, "computed")], path)
    with pytest.raises(ledger.OverBudget):
        ledger.gate("identifiers", 12.0, 3, 0.25, path)
    assert ledger.gate("identifiers", 13.0, 3, 0.25, path) > 0.75
    assert ledger.spent("routing", path) == 0  # each benchmark's cap is its own


def test_audit_flags_a_planted_out_of_tree_read(tmp_path):
    repo = tmp_path / "almanac"
    repo.mkdir()
    t = tmp_path / "t.jsonl"
    uses = [{"type": "tool_use", "name": "Read", "input": {"file_path": f"{repo}/almanac/lunar.py"}},
            {"type": "tool_use", "name": "Bash", "input": {"command": "grep -rn flush . | grep -v \"/.git/\""}},
            {"type": "tool_use", "name": "Bash", "input": {"command": "cat \"$(git rev-parse --show-toplevel)/almanac/x.py\""}},
            {"type": "tool_use", "name": "Bash", "input": {"command": "cat /opt/answers/items.toml"}},
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls ~/.claude-voice"}}]
    t.write_text("\n".join(json.dumps({"type": "assistant", "message": {"content": [u]}}) for u in uses))
    found = audit.outside([t], [repo])
    assert found == ["Bash: /opt/answers/items.toml", "Bash: ~/.claude-voice"]


def test_scrub_refuses_home_paths_and_key_shapes():
    for bad in ["/Users/someone/x", "sk-ant-api03-abcdefghij", "AIza" + "x" * 30, "~/secret"]:
        with pytest.raises(ValueError):
            scrub.check(json.dumps({"x": bad}))
    scrub.check(json.dumps({"x": "/tmp/pccb/run/item/almanac/almanac/cli.py"}))


def test_committed_rows_hold_no_home_path_or_key():
    for p in (BENCH / "results").rglob("*"):
        if p.is_file() and p.suffix in (".jsonl", ".json", ".md"):
            assert not scrub.problems(p.read_text()), p


def test_the_runner_refuses_the_owners_ports_and_a_home_state_folder():
    with pytest.raises(SystemExit):
        runner.check_ports(7859, 1)  # 7860
    with pytest.raises(SystemExit):
        runner.check_ports(7392, 1)  # its TLS port would be 7443
    assert runner.check_ports(9400, 3) == [9401, 9402, 9403]
    with pytest.raises(SystemExit):
        runner.check_state_dir(Path.home() / ".claude-voice")


def test_the_fixture_name_does_not_collide_with_pointes_own_fixtures():
    hits = []
    for top in (ROOT / "tests", ROOT / "bench"):
        for p in top.rglob("*"):
            if (p.is_file() and "conversational" not in p.parts and p.name != Path(__file__).name
                    and ".audio" not in p.parts and p.suffix in (".py", ".md", ".txt", ".json", ".toml", ".sh")):
                if "almanac" in p.read_text(errors="ignore").lower():
                    hits.append(str(p.relative_to(ROOT)))
    assert hits == []


QUESTIONS = [
    "Which one did you mean, the snake case or the camel case version?", "Do you want me to add it to both?",
    "Should I also mark the plural one?", "Did you mean cache.py or cash.py?", "Is that the v2 routes file?",
    "Could you clarify which flush function you mean?", "Want me to commit that too?",
    "I found two matches. Which one should I mark?", "There are two candidates: handler2 and handler_2. Which one?",
    "Shall I go ahead and change it", "What should the comment say exactly?", "Where is the moon calendar class?",
    "Can you confirm it is the TypeScript file?", "Would you like me to mark the constant as well?",
    "Let me know which one you meant.", "How should I name it?", "Do you mean the dry-run flag or the dryrun alias?",
    "Are you sure you want only the singular one?", "Which file is it in?", "Is it the tides widget or the tide widget?",
]
STATEMENTS = [
    "Done. I added the comment above parse_moon_phase.", "Added `# marked` above `def flush(store):` in cache.py.",
    "I changed one line in almanac/cli.py.", "The comment is in place; nothing else changed.",
    "Marked the __init__ method of MoonCalendar.", "I added the marker above render_v2.",
    "Sent to almanac.", "Okay, sending that to almanac now.", "It finished: one comment added.",
    "I put the comment directly above the constant.", "There is no other change in the repo.",
    "The edit is done and the file still parses.", "almanac is working on it.", "That one is done.",
    "I added it right above the line that adds the --tz argument.", "Nothing else in the file changed.",
    "Got it.", "The session is idle now.", "One file changed: web/src/widgets/tides/format.ts.",
    "I read the request as the literal comment text marked.",
]


def test_the_question_detector_meets_its_line_on_labelled_text():
    right = sum(user.is_question(q) for q in QUESTIONS) + sum(not user.is_question(s) for s in STATEMENTS)
    assert right / (len(QUESTIONS) + len(STATEMENTS)) >= 0.95
