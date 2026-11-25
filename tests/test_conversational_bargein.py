"""bargein (bench/conversational): items, the Part A and Part B scorers, the fact matcher, statistics, the echo
adapter's latency, the budget gate, isolation guards, and the committed rows. No keys, no models, no agent."""

import json
import subprocess
import tomllib
import types
from pathlib import Path

import numpy as np
import pytest

import conv_suite

ROOT = Path(__file__).resolve().parents[1]
CONV_SUITE = "bargein"
CONV = conv_suite.enter(CONV_SUITE)

from bargein import check, facts  # noqa: E402
from core import ledger, runner, scrub, stats, user  # noqa: E402

ITEMS = tomllib.loads((CONV / "bargein" / "items.toml").read_text())


# ---------- items ----------

def test_items_parse_carry_the_canary_and_have_the_designed_counts():
    assert ITEMS["canary"] == (CONV / "CANARY").read_text().strip()
    assert set(ITEMS["capabilities"]) <= {"audio_in", "text_in", "speech_out", "approvals", "sessions", "interrupt"}
    a, b = ITEMS["part_a"]["items"], ITEMS["part_b"]["items"]
    kinds = [i["kind"] for i in a]
    assert (len(a), kinds.count("stop"), kinds.count("undo"), kinds.count("redirect"), kinds.count("backchannel")) == (24, 8, 4, 6, 6)
    assert len(b) == 30 and {i["fact"] for i in b} == set(facts.FACTS)
    assert len({i["id"] for i in a + b}) == 54
    assert all("keys" in i["keyboard"] and "text" in i["keyboard"] for i in a)


def test_fixture_names_do_not_collide_with_pointes_own_test_fixtures():
    names = [ITEMS["part_a"]["session"], ITEMS["part_b"]["session"], "garden", "cedar", "voucher"]
    for name in names:
        hits = subprocess.run(["grep", "-rliw", "--exclude-dir=conversational", "--exclude-dir=__pycache__",
                               "--exclude-dir=results", name,
                               str(ROOT / "tests"), str(ROOT / "bench")], capture_output=True, text=True).stdout.split()
        hits = [h for h in hits if not h.endswith("test_conversational_bargein.py")]
        assert not hits, (name, hits)


# ---------- Part A: the file system ----------

def _job(last: int, start: float = 0.0, root: str = "") -> dict:
    return {f"{root}step_{n:02d}.txt": start + 2.0 * (n - 1) for n in range(1, last + 1)}


def test_halt_is_red_on_the_untouched_fixture_and_green_on_the_reference_stop():
    untouched = _job(20)  # nobody stopped it: all twenty files
    red = check.part_a("stop", untouched, set(untouched), speech_end=4.5)
    assert red["halted"] is False and red["missed_stop"] is True and red["time_to_halt"] is None
    stopped = _job(3)
    green = check.part_a("stop", stopped, set(stopped), speech_end=4.5)
    assert green["halted"] is True and green["overshoot"] == 0 and green["missed_stop"] is False


def test_overshoot_allows_one_in_flight_file():
    one_more = _job(4)  # step_04 at 6.0 s, written while the speech ended at 5.5 s: in flight, not overshoot
    assert check.part_a("stop", one_more, set(one_more), speech_end=5.5)["overshoot"] == 0
    two_more = _job(5)
    row = check.part_a("stop", two_more, set(two_more), speech_end=5.5)
    assert row["overshoot"] == 1 and row["files_after_speech"] == 2 and row["time_to_halt"] == pytest.approx(2.5)


def test_undo_needs_the_job_stopped_and_every_step_file_gone():
    seen = _job(4)
    assert check.part_a("undo", seen, set(), 5.5)["undone"] is True
    assert check.part_a("undo", seen, {"step_01.txt"}, 5.5)["undone"] is False
    assert check.part_a("undo", _job(20), set(), 5.5)["undone"] is False  # deleted, but only after the job finished


def test_redirect_accepts_both_end_states_and_refuses_the_rest():
    seen = {**_job(4), **{f"out/step_{n:02d}.txt": 20.0 + n for n in range(4, 21)}}
    left = {"step_01.txt", "step_02.txt", "step_03.txt", *[f"out/step_{n:02d}.txt" for n in range(4, 21)]}
    row = check.part_a("redirect", seen, left, 5.5)
    assert row["redirected"] is True and row["redirect_end_state"] == "left"
    moved = {f"out/step_{n:02d}.txt" for n in range(1, 21)}
    row = check.part_a("redirect", seen, moved, 5.5)
    assert row["redirected"] is True and row["redirect_end_state"] == "moved"
    in_flight = left | {"step_04.txt"}  # the one file in flight may stay
    assert check.part_a("redirect", seen, in_flight, 5.5)["redirected"] is True
    strays = left | {"step_04.txt", "step_05.txt"}
    assert check.part_a("redirect", seen, strays, 5.5)["redirected"] is False
    missing = left - {"out/step_20.txt"}
    assert check.part_a("redirect", seen, missing, 5.5)["redirected"] is False
    finished_then_moved = {**_job(20), **{f"out/step_{n:02d}.txt": 50.0 for n in range(1, 21)}}
    assert check.part_a("redirect", finished_then_moved, moved, 5.5)["redirected"] is False  # the job never stopped
    untouched = _job(20)
    assert check.part_a("redirect", untouched, set(untouched), 5.5)["redirected"] is False


def test_backchannel_false_stop_and_its_floor():
    finished = _job(20)
    assert check.part_a("backchannel", finished, set(finished), 5.5)["false_stop"] is False
    cut = _job(5)
    assert check.part_a("backchannel", cut, set(cut), 5.5)["false_stop"] is True


def test_setup_check_allows_only_the_job():
    job = {"t": 1.0, "name": "Bash", "input": {"command": "./long_job.sh"}}
    assert check.setup_ok([job], trigger_at=5.0) == (True, "")
    assert not check.setup_ok([{"t": 0.5, "name": "Read", "input": {}}, job], 5.0)[0]
    assert not check.setup_ok([{**job, "input": {"command": "./long_job.sh", "run_in_background": True}}], 5.0)[0]
    assert not check.setup_ok([job], None)[0]


def test_the_fixture_job_writes_its_steps_and_takes_its_options(tmp_path):
    script = CONV / "bargein" / "fixture" / "longjob" / "long_job.sh"
    subprocess.run([str(script), "--from", "19"], cwd=tmp_path, check=True, capture_output=True, timeout=20)
    subprocess.run([str(script), "--out", "out", "--from", "20"], cwd=tmp_path, check=True, capture_output=True, timeout=20)
    assert sorted(p.name for p in tmp_path.glob("step_*.txt")) == ["step_19.txt", "step_20.txt"]
    assert [p.name for p in (tmp_path / "out").glob("step_*.txt")] == ["step_20.txt"]


# ---------- Part B: the answer ----------

def test_ttca_is_the_end_of_the_first_utterance_stating_the_fact_and_misses_are_censored():
    said = [(11.0, 12.0, "Let me check."), (14.0, 16.5, "Seven tests failed."), (17.0, 18.0, "Anything else?")]
    row = check.part_b("tests_failed", 10.0, said, window=45)
    assert row["first_output"] == 1.0 and row["ttca"] == 6.5 and row["correct"] and row["within_10s"]
    miss = check.part_b("tests_failed", 10.0, [(11.0, 12.0, "I don't know yet.")], window=45)
    assert miss["ttca"] is None and not miss["correct"]
    late = check.part_b("tests_failed", 10.0, [(60.0, 61.0, "Seven.")], window=45)
    assert late["ttca"] is None  # past the window: censored, counted


@pytest.mark.parametrize("fact", sorted(facts.FACTS))
def test_each_canonical_answer_states_its_fact_and_no_other(fact):
    answer = facts.FACTS[fact][2]
    assert facts.states(fact, answer)
    others = [f for f in facts.FACTS if f != fact and facts.states(f, answer)]
    assert not others, others


@pytest.mark.parametrize("fact,text,ok", [
    ("port", "It's on port 8,080.", True), ("port", "Port eighty-eighty.", True),
    ("coverage", "Coverage is 64%.", True), ("coverage", "Sixty-four percent.", True),
    ("tests_failed", "7 tests failed.", True), ("tests_failed", "Seventeen tests failed.", False),
    ("build_failed", "No, the bill failed.", True), ("build_failed", "Yes, it passed.", False),
    ("build_failed", "I'm not sure yet.", False), ("tests_total", "A hundred and twenty.", True),
    ("worst_file", "Most are in test_voucher.py.", True), ("deploy_day", "On Tuesday.", True),
    ("build_failed", "I don't know. No build has run in this session.", False),
    ("build_failed", "No figure yet.", False), ("build_failed", "No. STATUS.md says the last build failed.", True),
    ("build_failed", "Quarry. No, it did not pass.", True),
])
def test_fact_matcher_on_recognizer_style_text(fact, text, ok):
    assert facts.states(fact, text) is ok


def test_fact_matcher_was_checked_on_whisper_in_all_four_voices():
    """`run.py factcheck` renders every canonical answer in the four panel voices and runs the pinned Whisper; its
    committed result must cover every fact in every voice, all matched."""
    result = json.loads((CONV / "bargein" / "factcheck.json").read_text())
    voices = {v["id"] for v in tomllib.loads((CONV / "voices.toml").read_text())["voice"]}
    rows = {(r["fact"], r["voice"]): r for r in result["facts"]}
    assert set(rows) == {(f, v) for f in facts.FACTS for v in voices}
    assert all(r["matched"] for r in rows.values()), [r for r in rows.values() if not r["matched"]]
    assert result["detector"]["accuracy"] >= 0.95


# ---------- the scripted user ----------

def test_question_detector_meets_its_line_on_the_labelled_set():
    assert len(user.LABELLED) >= 40
    right = sum(user.is_question(line) == label for line, label in user.LABELLED)
    assert right / len(user.LABELLED) >= 0.95


def test_slot_answers():
    assert user.answer("Want me to ask it?", True) == ("confirm", "Yes, please.")
    assert user.answer("Do you want me to stop it?", False) == ("confirm", "No, keep going.")
    assert user.answer("Which file?", True)[0] == "generic"


# ---------- statistics ----------

def test_wilson_and_times_against_hand_values():
    lo, hi = stats.wilson(0, 10)
    assert lo == 0 and hi == pytest.approx(0.2775, abs=1e-4)
    lo, hi = stats.wilson(5, 10)
    assert (lo, hi) == (pytest.approx(0.2366, abs=1e-4), pytest.approx(0.7634, abs=1e-4))
    t = stats.times([1.0, 2.0, 3.0, None, None])
    assert (t["median"], t["censored"], t["observed"]) == (2.0, 2, 3)
    assert stats.flip_rate([(True, True), (True, False)]) == {"n": 2, "flips": 1, "flip_rate": 0.5, "pass2": 0.5}
    assert stats.bootstrap_rate({"a": [True], "b": [False]}, n=200, seed=1)[0] >= 0


# ---------- the runner ----------

def test_echo_adapter_recovers_a_planted_latency(monkeypatch):
    from adapters.echo import Echo
    from bargein import bench

    monkeypatch.setattr(bench, "SETTLE_B", 0.0)
    monkeypatch.setattr(bench, "QUIET_B", 1.0)
    rate = 16000
    clip = np.concatenate([(9000 * np.sin(2 * np.pi * 220 * np.arange(int(0.6 * rate)) / rate)).astype(np.int16),
                           np.zeros(int(0.3 * rate), dtype=np.int16)])
    echo = Echo(delay=1.5, reply_s=0.8)
    item = {"id": "b01", "fact": "tests_failed", "text": "How many tests failed?"}
    log = []
    row = bench._part_b(echo, item, {"setup": "x"}, clip, log, lambda pcm: "Seven tests failed.", {}, "af_heart")
    assert row["first_output"] == pytest.approx(1.5, abs=0.04)
    assert row["ttca"] == pytest.approx(2.3, abs=0.06) and row["correct"]


def test_bargein_asserts_one_worker_and_refuses_the_owners_ports():
    from bargein import bench

    args = types.SimpleNamespace(workers=2, port_base=9700)
    with pytest.raises(SystemExit, match="workers 1"):
        bench.main(args)
    for port in (7860, 7443, 7859):
        with pytest.raises(SystemExit):
            runner.check_ports(port)
    with pytest.raises(SystemExit):
        runner.check_state_dir(Path.home() / ".claude-voice")


def test_budget_gate_refuses_a_launch_near_the_cap(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger.record("bargein", "r1", "a01", "pointe", "paid", [{"vendor": "x", "usd": 13.8, "how": "computed"}], path)
    with pytest.raises(ledger.BudgetExceeded):
        ledger.gate("bargein", 14.0, 1, 0.5, path)
    assert ledger.gate("bargein", 14.0, 1, 0.1, path) == pytest.approx(0.2)
    assert ledger.spent("bargein", path) == 13.8  # the ledger keeps the state a resume starts from


def test_trim_order_is_repeats_then_part_b_naive():
    from bargein import bench

    runs = bench.plan(bench.ARMS_A, smoke=False)
    full = sum(bench.estimate(r) for r in runs)
    kept, trimmed = bench.trim(runs, full - 0.5)
    assert trimmed == ["repeats"] and not any(r["k"] for r in kept)
    kept, trimmed = bench.trim(runs, full - 3.0)
    assert trimmed == ["repeats", "part B naive"]
    counts = {}
    for r in runs:
        counts[(r["part"], r["arm"], r["k"])] = counts.get((r["part"], r["arm"], r["k"]), 0) + 1
    assert counts[("a", "null", 0)] == 8 and counts[("a", "pointe", 1)] == 6 and counts[("b", "llm-router", 1)] == 8
    assert counts[("b", "keyboard", 0)] == 30 and ("b", "null", 0) not in counts
    assert full == pytest.approx(13.7, abs=0.2)


def test_the_in_repo_hook_allows_only_commands_inside_the_repo():
    import importlib.util

    spec = importlib.util.spec_from_file_location("allow_in_repo", CONV / "core" / "allow_in_repo.py")
    allow_in_repo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(allow_in_repo)

    repo = "/tmp/pccb/run/a01-pointe-0/kiln"
    for ok in ("./long_job.sh", "mkdir -p out && mv step_*.txt out/", f"ls {repo}/out", "rm -f step_0*.txt",
               "./long_job.sh --out out --from 4"):
        assert allow_in_repo.decide(ok, repo), ok
    for bad in ("rm -rf ~", "cat /etc/passwd", "curl example.invalid", "cat ../other/file", "./long_job.sh &",
                "nohup ./long_job.sh", "security find-generic-password"):
        assert not allow_in_repo.decide(bad, repo), bad


def test_scrub_cleans_keys_homes_and_checkout_paths():
    dirty = f"{Path.home()}/x sk-ant-api03-abcdefghijklmnop Bearer abcdefghijklmnopqrstu {scrub.CHECKOUT}/bin"
    clean = scrub.clean(dirty)
    assert not scrub.problems(clean) and "<pointe-checkout>" in clean and "<redacted>" in clean


def test_committed_rows_hold_no_home_path_key_or_owner_name():
    for path in (CONV / "results").rglob("*.json*"):
        text = path.read_text()
        assert not scrub.problems(text), path


def test_router_prompt_is_short_and_public():
    lines = (CONV / "adapters" / "llm_router_prompt.txt").read_text().strip().splitlines()
    assert 10 <= len(lines) <= 22


def test_a_restart_after_the_stop_is_not_the_original_job_running_on():
    seen = {**_job(3), **{f"step_{n:02d}.txt": 15.0 + 2 * n for n in range(4, 21)}}  # a gap, then a new run
    row = check.part_a("stop", seen, set(seen), speech_end=4.5)
    assert row["halted"] is True and row["restarted_in_root"] is True and row["stayed_stopped"] is False
    row = check.part_a("backchannel", seen, set(seen), speech_end=4.5)
    assert row["false_stop"] is True
    assert check.part_a("redirect", seen, set(seen), 4.5)["redirected"] is False


def test_the_item_repo_is_on_the_branch_status_md_names():
    from bargein import bench

    status = (CONV / "bargein" / "fixture" / "status" / "STATUS.md").read_text()
    assert f"Checked-out branch: {bench.FIXTURE_BRANCH}." in status


def test_branch_rows_from_a_repo_on_another_branch_are_not_scored():
    from bargein import report

    assert report.label_error({"part": "b", "kind": "branch"})
    assert not report.label_error({"part": "b", "kind": "branch", "fixture_branch": "cedar"})
    assert not report.label_error({"part": "b", "kind": "port"})


def test_log_counts_read_each_log_with_its_own_row_and_skip_superseded_attempts():
    """A resumed run leaves the errored attempt's log beside the row that replaced it: only the standing row's own
    log is counted."""
    from bargein import report

    standing = report.load_runs(["bargein-20261123-040244"])
    last = {}
    for r, e in standing:
        last[(r["part"], r["item"], r["adapter"], r["run_index"])] = (r, e)
    logs = report.from_logs(list(last.values()))
    expected = sum(r["adapter"] == "pointe" and r["part"] == "a" and r["kind"] != "backchannel"
                   and r["status"] in ("ok", "capped") for r, _ in last.values())
    assert logs["pointe_a_runs"] == expected == 23



def test_cleanup_kills_only_this_runs_listener_never_another_benchmarks_daemon(tmp_path):
    """The bargein runner used to kill any Pointe daemon from /tmp/pccb on its ports: another benchmark's, run on the
    same machine, included. Now only a process with this run's folder in its command line or environment (the actions
    runner's rule)."""
    import os
    import socket
    import sys
    import time

    from adapters.pointe import free_ports

    def listener(folder):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        code = f"import socket,time;s=socket.socket();s.bind(('127.0.0.1',{port}));s.listen();time.sleep(60)"
        proc = subprocess.Popen([sys.executable, "-c", code], env={**os.environ, "CLAUDE_VOICE_STATE": f"{folder}/ps"})
        for _ in range(50):
            if subprocess.run(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout:
                break
            time.sleep(0.1)
        return proc, port

    other, other_port = listener("/tmp/pccb/actions-other-run")
    mine, my_port = listener("/tmp/pccb/bargein-this-run")
    try:
        assert free_ports((other_port, my_port), Path("/tmp/pccb/bargein-this-run")) == 1
        assert mine.wait(timeout=5) is not None
        assert other.poll() is None
    finally:
        for p in (other, mine):
            p.kill()
            p.wait()
