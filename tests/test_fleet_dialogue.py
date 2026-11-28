"""The fleet dialogues' own pieces (bench/fleet/dialogue.py, vendors.py): the fleet each size builds, the overview's
scorer, and the several-session Codex daemon and OpenCode service against Pointe's real adapters for them."""

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harnesses  # noqa: E402
import scale  # noqa: E402
from bench_fleet import load  # noqa: E402
from harnesses.codex import Codex, Connection  # noqa: E402
from harnesses.opencode import OpenCode, Service  # noqa: E402
from sessions import Session  # noqa: E402

dialogue, vendors, gen = load("dialogue", "vendors", "gen")


@pytest.mark.parametrize("n", dialogue.SIZES)
def test_each_size_is_two_machines_each_running_all_three_harnesses_with_every_role_placed(n):
    d = dialogue.fleet(n)
    assert d == dialogue.fleet(n) and len(d["sessions"]) == n
    by = lambda role: [s for s in d["sessions"] if role in s["roles"]]  # noqa: E731
    for m in dialogue.MACHINES:
        assert {s["harness"] for s in d["sessions"] if s["machine"] == m} == set(dialogue.HARNESSES)
    for role in ("approves", "name", "topic"):
        assert sorted(s["harness"] for s in by(role)) == sorted(dialogue.HARNESSES), role
    assert {s["machine"] for s in by("approves")} == set(dialogue.MACHINES)
    assert any(s["machine"] == "avi-box" for s in by("name")) and any(s["machine"] == "avi-box" for s in by("topic"))
    asks = by("asks")
    assert {s["machine"] for s in asks} == set(dialogue.MACHINES) and all(s["state"] == "asks" and s["question"] for s in asks)
    assert all(s["roles"] == ["asks"] for s in asks)  # one that waits is never sent anything
    assert not {s["id"] for s in by("name")} & {s["id"] for s in by("topic")}
    names = [s["name"] for s in d["sessions"]]
    assert all(dialogue._apart(a, b) for i, a in enumerate(names) for b in names[i + 1:])  # none renamed at join
    firsts = [s["topic"].split()[0] for s in d["sessions"]]
    assert len(set(firsts)) == n  # "the session working on the <topic>" fits one session
    flood = [s for s in d["sessions"] if s["finish_at"] is not None]
    assert len(flood) == n - 5 and all(0 <= s["finish_at"] <= dialogue.FLOOD_SECS for s in flood)
    steps = dialogue.steps(d)
    assert [s["kind"] for s in steps] == ["overview", "name", "name", "name", "topic", "topic", "topic"]


def test_the_overview_passes_on_the_counts_and_both_waiting_names_and_fails_without_them():
    d = dialogue.fleet(15)
    waiting = [s for s in d["sessions"] if "asks" in s["roles"]]
    rows = [(m if m != "studio" else "", sum(s["machine"] == m for s in d["sessions"]), 0,
             [s["name"] for s in waiting if s["machine"] == m]) for m in dialogue.MACHINES]
    line = scale.overview(rows)
    assert dialogue.overview_ok([line], d, {}) == (True, "")
    ok, why = dialogue.overview_ok([line.replace(waiting[0]["name"], "someone")], d, {})
    assert not ok and waiting[0]["name"] in why
    ok, why = dialogue.overview_ok(["Eight sessions here and seven sessions on avi-box; " + " and ".join(s["name"] for s in waiting)], d, {})
    assert ok, why  # counts said in words count too


def _session(sid, harness, name):
    path = (Codex if harness == "codex" else OpenCode).mirror_path(sid)
    return Session(id=sid, name=name, cwd="/repo", pid=0, transcript=str(path), harness=harness)


def test_the_codex_daemon_keeps_each_thread_apart_through_pointes_adapter(tmp_path, monkeypatch):
    monkeypatch.setattr(harnesses.HOST, "state_dir", tmp_path)
    asked = []

    async def hold(session, tool_name, tool_input, gone, run_in=None):
        asked.append((session.name, tool_input["command"], run_in))
        return "allow"

    monkeypatch.setattr(harnesses.HOST, "hold_permission", hold)
    short = Path(tempfile.mkdtemp(prefix="cx", dir="/tmp"))
    fake = vendors.CodexMachine(short / "s.sock")
    a, b = "00000000-0000-4000-8000-0000000000aa", "00000000-0000-4000-8000-0000000000bb"
    fake.add(a, "/repo/a", "tide", "Fix the coupon ledger.", "Done, 14 tests pass.")
    fake.add(b, "/repo/b", "harbor", "Fix the refund cache.", "Should I drop the old rows?")
    fed = []

    async def feed(session, text, respond):
        fed.append((session.name, text, respond))

    async def scenario():
        await fake.start()
        cx = Codex(Connection(fake.path))
        sa, sb = _session(a, "codex", "tide"), _session(b, "codex", "harbor")
        tasks = [asyncio.create_task(cx.watch(s, feed)[0]) for s in (sa, sb)]
        await asyncio.sleep(0.6)
        assert await cx.send(sb, "add a test")
        await fake.finish(a, "The coupon ledger work is finished.")
        rid = await fake.ask(b, "git status --short", "List changed files")
        await asyncio.sleep(1.2)
        for t in tasks:
            t.cancel()
        await cx.link.close()
        await fake.stop()
        return rid

    try:
        rid = asyncio.run(scenario())
    finally:
        import shutil

        shutil.rmtree(short, ignore_errors=True)
    assert [x["session"] for x in fake.sent] == [b] and "add a test" in fake.sent[0]["text"]
    reports = [(name, text) for name, text, respond in fed if respond]
    assert len(reports) == 1 and reports[0][0] == "tide" and "coupon ledger work is finished" in reports[0][1]
    assert asked == [("harbor", "git status --short", "/repo/b")] and fake.answers == {rid: {"decision": "accept"}}
    assert "Should I drop the old rows?" in Codex.mirror_path(b).read_text()  # history: in the record, not news


def test_the_opencode_service_keeps_each_session_apart_through_pointes_adapter(tmp_path, monkeypatch):
    monkeypatch.setattr(harnesses.HOST, "state_dir", tmp_path)
    monkeypatch.setattr("harnesses.opencode.RESYNC_SECS", 0.2)
    asked = []

    async def hold(session, tool_name, tool_input, gone, run_in=None):
        asked.append((session.name, tool_name, tool_input["command"]))
        return "allow"

    monkeypatch.setattr(harnesses.HOST, "hold_permission", hold)
    fake = vendors.OpenCodeMachine()
    a, b = "ses_" + "a" * 32, "ses_" + "b" * 32
    fake.add(a, "zeppelin", "Fix the payroll queue.", "Done, all tests pass.")
    fake.add(b, "gondolier", "Fix the audit parser.", "Done, all tests pass.")
    fed = []

    async def feed(session, text, respond):
        fed.append((session.name, text, respond))

    async def scenario():
        await fake.start()
        oc = OpenCode(Service(url=fake.url, password="test-only"))
        sa, sb = _session(a, "opencode", "zeppelin"), _session(b, "opencode", "gondolier")
        tasks = [asyncio.create_task(oc.watch(s, feed)[0]) for s in (sa, sb)]
        await asyncio.sleep(0.6)
        assert await oc.send(sa, "run the linter")
        await fake.finish(b, "The audit parser work is finished.")
        rid = await fake.ask(a, "git status --short", "List changed files")
        await asyncio.sleep(1.2)
        for t in tasks:
            t.cancel()
        await oc.service.close()
        await fake.stop()
        return rid

    rid = asyncio.run(scenario())
    assert [x["session"] for x in fake.sent] == [a] and "run the linter" in fake.sent[0]["text"]
    reports = [(name, text) for name, text, respond in fed if respond]
    assert len(reports) == 1 and reports[0][0] == "gondolier" and "audit parser work is finished" in reports[0][1]
    assert asked == [("zeppelin", "Bash", "git status --short")] and fake.answers[rid]["decision"] == "once"
    assert fake.sessions[a]["permissions"] == []


def test_the_opencode_on_the_path_answers_service_status_with_the_url(tmp_path):
    vendors.opencode_cli(tmp_path, "http://127.0.0.1:4567")
    env = {**os.environ, "PATH": f"{tmp_path}:/usr/bin:/bin"}
    got = subprocess.run(["opencode", "service", "status"], capture_output=True, text=True, env=env, timeout=10)
    assert got.returncode == 0 and got.stdout.split()[0] == "http://127.0.0.1:4567"
    assert subprocess.run(["opencode", "run"], capture_output=True, env=env, timeout=10).returncode == 1


def test_the_report_counts_a_paid_dialogue_and_says_each_step_and_what_failed():
    (report,) = load("report")
    steps = [{"kind": "dialogue_step", "step": "overview", "passed": True, "why": ""}]
    steps += [{"kind": "dialogue_step", "step": "name", "passed": True, "why": ""} for _ in range(3)]
    steps += [{"kind": "dialogue_step", "step": "topic", "passed": i != 1, "why": ""} for i in range(3)]
    steps += [{"kind": "dialogue_step", "step": "approvals", "passed": True, "verdicts": {"a": "allow", "b": "allow", "c": "allow"},
               "pending_at_once": 3, "read_out": ["a", "b", "c"], "taps": 3, "stray_answers": 0},
              {"kind": "dialogue_step", "step": "flood", "passed": False, "finished": list("abcdefghij"), "report_lines": 3,
               "named_in_held": 6, "lost": ["j"], "answers": 3, "answers_not_said": []},
              {"kind": "dialogue", "sessions": 15, "passed": False}]
    run = {"manifest": {"run": "fleet-x-dialogue-2m15-fleet-on", "what": "dialogue", "models": "real", "arm": "fleet-on",
                        "started": "2026-11-28T09:00:00+0200", "pointe": {"pointe_tree": "abcdef0123456"}},
           "rows": steps, "calls": [], "not_counted": ""}
    assert report.counted(run) and not report.counted({**run, "manifest": {**run["manifest"], "models": "stub"}})
    text = "\n".join(report.dialogue_section([run], lambda r: r["manifest"]["pointe"]["pointe_tree"][:10]))
    row = next(line for line in text.splitlines() if line.startswith("| fleet-x"))
    assert "`abcdef0123`" in row and "| 15 |" in row
    assert "pass: 3 of 3 to the one session named" in row and "**FAIL**: 2 of 3 to the one session named" in row
    assert "pass: 3 pending at once, 3 read out, 3 of 3 allowed in 3 taps, 0 stray" in row
    assert "**FAIL**: 10 finished, 3 report lines, 6 held, 1 lost, 3 of 3 answers said" in row and row.endswith("| **FAIL** |")
