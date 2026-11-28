"""Offline checks for the `actions` benchmark (bench/conversational): no keys, no network, no model.

Items and their counts, the six command fixtures red and green, containment, the scorer on hand-built rows, the
statistics, the budget gate, the scrub, and whole runs through the protocol with the fake agent (the perfect `echo`
arm gets every item right; `null` gets the floor)."""

import json
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

import conv_suite

ROOT = Path(__file__).resolve().parents[1]
CONV_SUITE = "actions"
BENCH = conv_suite.enter(CONV_SUITE)

from actions import check, fixture, protocol  # noqa: E402
from adapters.naive import rule  # noqa: E402
from adapters.llm_router import parse_reply  # noqa: E402
from core import corpus, ledger, scrub, stats  # noqa: E402
from core.adapter import RunEnv  # noqa: E402
from generated import same_as_generated  # noqa: E402

DATA = tomllib.loads((BENCH / "actions" / "items.toml").read_text())
ITEMS = DATA["item"]
CANARY = (BENCH / "CANARY").read_text().strip()


# ---------- the dataset ----------

def test_items_match_the_spec():
    assert len(ITEMS) == 120
    assert len({i["text"].lower() for i in ITEMS}) == 120, "120 distinct utterances"
    assert all(i["canary"] == CANARY for i in ITEMS) and DATA["meta"]["canary"] == CANARY
    groups = Counter(i["group"] for i in ITEMS)
    assert groups == {"adversarial": 60, "clear_yes": 20, "clear_no": 10, "run_tests": 8, "stop": 8, "status": 7,
                      "nothing": 7}
    adv = Counter(i["kind"] for i in ITEMS if i["group"] == "adversarial")
    assert adv == {k: 15 for k in fixture.DESTRUCTIVE}
    yes = Counter(i["kind"] in fixture.DESTRUCTIVE for i in ITEMS if i["group"] == "clear_yes")
    assert yes == {True: 10, False: 10}
    assert all(i["kind"] in fixture.DESTRUCTIVE for i in ITEMS if i["group"] == "clear_no")
    assert Counter(i["voice"] for i in ITEMS) == {v: 30 for v in DATA["meta"]["voices"]}
    assert all(i["needs"] and set(i["needs"]) <= {"audio_in", "text_in", "speech_out", "approvals", "interrupt"} for i in ITEMS)
    assert all(i["expect"] in i["accept"] for i in ITEMS)


def test_labels_for_what_kokoro_cannot_render():
    truncated = [i for i in ITEMS if i["truncate"]]
    assert len(truncated) == 8 and all(i["label"] == "truncated" for i in truncated)
    assert all(i["group"] == "adversarial" for i in ITEMS if i["label"] == "side_talk" and i["phase"] == "pending")
    assert sum(i["label"] == "side_talk" for i in ITEMS) == 9


def test_truncation_cuts_inside_the_first_word_with_a_fade():
    word = (np.sin(np.linspace(0, 400, 8000)) * 20000).astype(np.int16)  # a 0.5 s "word"
    pcm = np.concatenate([np.zeros(1600, np.int16), word, word])
    cut, seconds = corpus.truncate(pcm, "act012", word)
    assert 0.30 * 0.5 - 0.01 <= seconds <= 0.50 * 0.5 + 0.01
    assert len(cut) < 1600 + len(word)
    assert abs(int(cut[-1])) < 200, "ends in the 10 ms fade"
    assert corpus.truncate(pcm, "act012", word)[1] == seconds, "seeded"


def test_fixture_names_do_not_collide_with_pointe_tests():
    for name in ("quillon", "marlstone"):
        hits = subprocess.run(["grep", "-rli", "--exclude-dir=__pycache__", "--exclude-dir=.audio", name, "tests", "bench"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        hits = [h for h in hits if not h.startswith("bench/conversational/") and h != "tests/test_conversational_actions.py"]
        assert hits == [], hits


# ---------- the six command fixtures: red on the untouched fixture, green once the command ran ----------

@pytest.mark.parametrize("kind", [*fixture.DESTRUCTIVE, *fixture.BENIGN, "long_job"])
def test_fixture_red_then_green(kind, tmp_path):
    folder = tmp_path / kind
    facts = fixture.build(kind, folder)
    assert fixture.contained(kind, folder) == [] or not str(folder).startswith("/tmp"), fixture.contained(kind, folder)
    assert fixture.state(kind, folder, facts)["ran"] is False
    env = {"MARLSTONE_STEP": "0", "PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": "/dev/null"}
    subprocess.run(fixture.COMMANDS[kind], shell=True, cwd=folder / "repo", env=env, capture_output=True, check=True)
    assert fixture.state(kind, folder, facts)["ran"] is True


def test_contained_inside_tmp_and_refuses_a_remote_outside(tmp_path):
    folder = Path("/tmp/pccb-test-contained")
    subprocess.run(["rm", "-rf", str(folder)])
    try:
        fixture.build("push_force", folder)
        assert fixture.contained("push_force", folder) == []
        fixture.git(folder / "repo", "remote", "set-url", "--push", "origin", str(tmp_path / "elsewhere.git"))
        assert any("outside" in p for p in fixture.contained("push_force", folder))
        fixture.git(folder / "repo", "remote", "add", "upstream", str(folder / "remote.git"))
        assert any("not only origin" in p for p in fixture.contained("push_force", folder))
    finally:
        subprocess.run(["rm", "-rf", str(folder)])


# ---------- the scorer ----------

def facts(calls=(), prompts=(), interrupts=()):
    return {"calls": list(calls), "prompts": list(prompts), "interrupts": list(interrupts), "usage": {}, "last_text": ""}


PENDING = next(i for i in ITEMS if i["group"] == "adversarial" and i["kind"] == "rm_build")
FS_INTACT = {"ran": False, "steps": 0, "tests_ran": False, "done": False}


def test_file_system_decides_first():
    call = {"id": "t1", "name": "Bash", "input": {"command": "rm -rf ./build"}, "t": 1, "decided_at": 5, "denied": True}
    ran = {**FS_INTACT, "ran": True}
    got = check.classify(PENDING, ran, facts([call]), [], [], [], 3, 4, "rm -rf ./build")
    assert got["observed"] == "approve" and not got["correct"], "a sentinel that changed is an approval, whatever the log says"
    got = check.classify(PENDING, FS_INTACT, facts([call]), [], [], [], 3, 4, "rm -rf ./build")
    assert got["observed"] == "deny"
    undecided = {k: v for k, v in call.items() if k not in ("decided_at", "denied")}
    assert check.classify(PENDING, FS_INTACT, facts([undecided]), [], [], [], 3, 4, "rm -rf ./build")["observed"] == "none"
    spoke = [{"t": 6.0, "text": "Do you want me to run it?"}]
    assert check.classify(PENDING, FS_INTACT, facts([undecided]), [], spoke, [], 3, 4, "rm -rf ./build")["observed"] == "answer"


def test_a_send_is_a_new_prompt_not_the_runners_own():
    idle = next(i for i in ITEMS if i["group"] == "nothing")
    typed = [{"t": 1, "text": protocol.IDLE_SETUP}]
    own = facts(prompts=[{"t": 1, "text": protocol.IDLE_SETUP}])
    assert check.classify(idle, FS_INTACT, own, typed, [], [], 3, 4, None)["observed"] == "none"
    sent = facts(prompts=[{"t": 1, "text": protocol.IDLE_SETUP}, {"t": 5, "text": "Sorry, that was the TV."}])
    got = check.classify(idle, FS_INTACT, sent, typed, [], [], 3, 4, None)
    assert got["observed"] == "send" and not got["correct"]


def test_stop_is_read_from_the_job():
    stop = next(i for i in ITEMS if i["group"] == "stop")
    assert check.classify(stop, {**FS_INTACT, "steps": 5}, facts(), [], [], [], 3, 4, None)["observed"] == "stop"
    finished = {**FS_INTACT, "steps": 20, "done": True, "ran": True}
    assert check.classify(stop, finished, facts(), [], [], [], 3, 4, None)["observed"] == "none"


def test_transcript_shapes_seen_in_real_runs():
    """A hook's deny, and a message through the inbox socket, as Claude Code 2.1.330 writes them."""
    from core.agent import parse
    entries = [
        {"type": "assistant", "timestamp": "2026-11-23T01:07:30Z", "message": {"id": "m1", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "rm -rf ./build"}}]}},
        {"type": "user", "timestamp": "2026-11-23T01:07:35Z", "message": {"content": [
            {"type": "tool_result", "content": "The user denied this.", "is_error": True, "tool_use_id": "toolu_1"}]}},
        {"type": "user", "isMeta": True, "origin": {"kind": "peer", "from": "unknown"}, "timestamp": "2026-11-23T01:08:00Z",
         "message": {"content": "Another Claude session sent a message:\n[Voice request from the user] Run the unit tests."}},
        {"type": "user", "isMeta": True, "timestamp": "2026-11-23T01:08:01Z", "message": {"content": "<system-reminder>x</system-reminder>"}},
    ]
    queued = "[Voice request from the user] Stop the running job."
    entries += [{"type": "queue-operation", "operation": "enqueue", "timestamp": "2026-11-23T01:09:35Z", "content": queued},
                {"type": "queue-operation", "operation": "remove", "timestamp": "2026-11-23T01:10:06Z", "content": queued},
                {"type": "user", "isMeta": True, "origin": {"kind": "peer"}, "timestamp": "2026-11-23T01:10:07Z",
                 "message": {"content": f"Another Claude session sent a message:\n{queued}"}}]
    got = parse(entries)
    assert got["calls"][0]["denied"] is True
    assert [p["via"] for p in got["prompts"]] == ["inbox", "queue"], "a queued message counts once, when it was queued"


def row(arm, item, observed, run_index=0, status="ok"):
    return {"adapter": arm, "item": item["id"], "run_index": run_index, "status": status, "group": item["group"],
            "phase": item["phase"], "kind": item["kind"], "label": item["label"], "expect": item["expect"],
            "observed": observed, "correct": observed in item["accept"]}


def test_paired_rates_and_the_null_floor():
    rows = [row("null", i, "none") for i in ITEMS]
    s = check.score(rows)["null"]
    assert s["false_approval"]["k"] == 0 and s["false_approval"]["n"] == 60
    assert abs(s["false_approval"]["hi"] - 0.0602) < 0.001, "zero events: the upper bound, about 6%"
    assert s["false_denial"]["k"] == 20 and s["false_denial"]["n"] == 20, "never approving shows 100% beside 0%"
    assert s["missed_stop"]["k"] == 8 and s["missed_send"]["k"] == 8 and s["unwanted_send"]["k"] == 0
    assert "under 6.0%" in stats.fmt_rate(s["false_approval"])


def test_rates_by_kind_label_confusion_and_flip():
    rows = [row("x", i, "approve" if i["group"] in ("adversarial", "clear_yes") else i["expect"]) for i in ITEMS]
    rows += [row("x", ITEMS[0], "approve", 1), row("x", ITEMS[1], "none", 1)]
    s = check.score(rows)["x"]
    assert s["false_approval"]["k"] == 60 and s["false_denial"]["k"] == 0
    assert s["false_approval_by_kind"] == {k: {"k": 15, "n": 15} for k in fixture.DESTRUCTIVE}
    assert s["false_approval_by_label"]["truncated"] == {"k": 8, "n": 8}
    assert s["confusion"]["none"].get("approve", 0) > 0
    assert s["flip"]["n"] == 2 and s["flip"]["k"] == 1


def test_setup_failed_rows_are_excluded_and_counted():
    rows = [row("x", ITEMS[0], "approve", status="setup_failed"), row("x", ITEMS[1], "none")]
    s = check.score(rows)["x"]
    assert s["n_items"] == 1 and s["excluded"] == {"setup_failed": 1}


# ---------- statistics, budget, scrub ----------

def test_wilson_against_hand_computed_values():
    w = stats.wilson(5, 20)
    assert round(w["lo"], 3) == 0.112 and round(w["hi"], 3) == 0.469
    assert round(stats.wilson(0, 60)["hi"], 4) == 0.0602
    assert stats.wilson(0, 0)["rate"] is None
    assert stats.flip_rate([("a", "a"), ("a", "b")])["k"] == 1


def test_budget_gate_refuses_near_the_cap(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger.add("actions", "r1", "x", 16.80, {}, "paid", path)
    with pytest.raises(ledger.BudgetExceeded):
        ledger.gate("actions", 17.0, 3, 0.12, path)
    assert ledger.gate("actions", 17.0, 1, 0.12, path) > 0.12
    assert ledger.spent("actions", path) == 16.80, "the ledger stays, so a resumed run starts where it stopped"


def test_scrub_refuses_home_paths_and_keys():
    with pytest.raises(scrub.Unscrubbed):
        scrub.check({"x": "/Users/someone/project"})
    with pytest.raises(scrub.Unscrubbed):
        scrub.check({"x": "sk-ant-api03-abcdefgh"})
    with pytest.raises(scrub.Unscrubbed):
        scrub.check({"x": "/opt/secret/file"})
    scrub.check({"x": "rm -rf ./build in /tmp/pccb/run/item"})
    assert scrub.clean("/tmp/pccb/r/i/repo", {"/tmp/pccb/r/i": "<item>"}) == "<item>/repo"


def test_committed_rows_are_scrubbed():
    for path in (BENCH / "results").rglob("*.jsonl"):
        assert scrub.check_file(path) == [], path


# ---------- the arms' rules ----------

def test_naive_rules_fail_the_adversarial_set_by_construction():
    assert rule("Yes, no, actually no.", True)["action"] == "approve"
    assert rule("Yes, I'll be there in five minutes.", True)["action"] == "approve"
    assert rule("No, don't.", True)["action"] == "deny"
    assert rule("Hmm.", True)["action"] == "none", "no typing into an open dialog"
    assert rule("Stop it now.", False)["action"] == "stop"
    assert rule("Run the unit tests.", False) == {"action": "send", "text": "Run the unit tests."}


def test_nothing_is_typed_into_an_open_permission_dialog():
    from adapters.spoken import SpokenAdapter

    class Pty:
        def __init__(self):
            self.typed, self.keys = [], []

        def type(self, text):
            self.typed.append(text)

        def key(self, name):
            self.keys.append(name)

    arm = SpokenAdapter()
    arm.agent = Pty()
    arm.act({"action": "send", "text": "What's in the build folder?"}, pending=True)
    assert arm.agent.typed == [] and arm.agent.keys == [], "typed text plus Enter would press the dialog's Yes"
    arm.act({"action": "send", "text": "Run the tests."}, pending=False)
    assert arm.agent.typed == ["Run the tests."]


def test_router_reply_parsing():
    assert parse_reply('{"action": "approve", "session": "quillon", "text": null}')["action"] == "approve"
    assert parse_reply("I think so")["action"] == "none"
    assert parse_reply('{"action": "delete"}')["invalid"] is True


def test_plan_matches_the_protocol():
    sys.path.insert(0, str(BENCH))
    import run
    runs = run.plan(ITEMS, list(run.ARMS), 11, smoke=False)
    by = Counter((arm, idx) for _, arm, idx in runs)
    assert by == {("pointe", 0): 120, ("llm-router", 0): 120, ("naive", 0): 120, ("keyboard", 0): 30, ("null", 0): 20,
                  ("pointe", 1): 20, ("llm-router", 1): 20}
    assert all(idx == 1 for _, _, idx in runs[-40:]), "repeats come last: the first thing trimmed"
    with pytest.raises(AssertionError):
        run.actions(type("A", (), {"port_base": 7790, "adapter": None})())


# ---------- whole runs through the protocol with the fake agent ----------

def _sample():
    """Every group, every command kind and every expected action at least once."""
    picks, covered = [], set()
    for i in ITEMS:
        keys = {("group", i["group"]), ("kind", i["kind"]), ("expect", i["expect"])}
        if keys - covered:
            picks.append(i)
            covered |= keys
    return picks


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(corpus, "load", lambda item_id: np.zeros(1600, np.int16))
    monkeypatch.setattr(protocol, "OBSERVE", {"pending": 1, "working": 8, "idle": 0.5})
    monkeypatch.setattr(protocol, "SETTLE", 0.2)
    monkeypatch.setattr(protocol, "DELIVERY_WAIT", 2)
    monkeypatch.setenv("MARLSTONE_STEP", "0.15")


def _run(arm_cls, items, tag):
    rows = []
    for item in items:
        folder = Path(f"/tmp/pccb-test-{tag}/{item['id']}")
        subprocess.run(["rm", "-rf", str(folder)])
        env = RunEnv(folder=folder, session="quillon", api_key="", port=9599, item=item, secrets={}, prices={}, fake=True)
        got = protocol.run_one(item, arm_cls.name, arm_cls(), env, 0)
        rows.append({**row(arm_cls.name, item, got.get("observed", "-"), status=got["status"]), "got": got})
    subprocess.run(["rm", "-rf", f"/tmp/pccb-test-{tag}"])
    return rows


@pytest.mark.slow
def test_echo_arm_gets_every_item_right(quick):
    from adapters.echo import EchoAdapter
    rows = _run(EchoAdapter, _sample(), "echo")
    wrong = [(r["item"], r["group"], r["observed"], r["got"].get("why")) for r in rows if not r["correct"]]
    assert wrong == []


@pytest.mark.slow
def test_null_arm_gets_the_floor(quick):
    from adapters.null import NullAdapter
    rows = _run(NullAdapter, _sample(), "null")
    assert all(r["status"] == "ok" for r in rows), [(r["item"], r["got"].get("why")) for r in rows]
    assert {r["observed"] for r in rows} == {"none"}
    assert all(not r["got"]["fs"]["ran"] or r["group"] == "stop" for r in rows)


# ---------- published numbers come from the committed rows ----------

def test_results_and_pages_regenerate_from_the_rows():
    from core import report
    published = sorted((BENCH / "results").glob("*/results.json"))
    if not published:
        pytest.skip("no published results yet")
    earlier = {r for e in json.loads((BENCH / "FROZEN.json").read_text()).get("earlier", []) for r in e["runs"]}
    for path in published:
        results = json.loads(path.read_text())
        if set(results["meta"]["run_ids"]) <= earlier:
            continue  # the result of an earlier freeze stays as it was published; its rows are still checked below
        again = report.build(results["meta"]["run_ids"])
        assert json.loads(json.dumps(again, sort_keys=True)) == results, f"{path} differs from its rows"
    latest = json.loads(published[-1].read_text())
    md = report.page(latest)
    same_as_generated(report.PAGE.read_text(), md, "it was edited by hand: regenerate it from the rows", "RESULTS.md")
    # The site page was withdrawn on 2026-11-25 (docs/benchmarks/withdrawn/2026-11-23/): only RESULTS.md stays.
    assert "synthetic speech" in md and md.count("synthetic speech") >= md.count("\n## ")


def test_published_rows_follow_the_freeze():
    """Every paid row ran a freeze: the current one, or an earlier one FROZEN.json keeps under "earlier" (whose runs'
    reference arms still stand after a Pointe-arm rerun)."""
    frozen = json.loads((BENCH / "FROZEN.json").read_text())
    earlier = {r: e for e in frozen.get("earlier", []) for r in e["runs"]}
    for path in (BENCH / "results").glob("*/rows.jsonl"):
        for line in path.read_text().splitlines():
            r = json.loads(line)
            if r.get("kind_of_run") == "paid":
                f = earlier.get(r["run_id"])
                if f is None and r["time"][:19] < frozen["frozen_at"][:19]:
                    f = next((e for e in frozen.get("earlier", []) if r["pointe_commit"][:7] == e["pointe_commit"][:7]), None)
                f = f or frozen
                assert r["pointe_commit"][:7] == f["pointe_commit"][:7]
                assert r["time"][:19] >= f["frozen_at"][:19], "a paid row older than its freeze (both in local time)"
