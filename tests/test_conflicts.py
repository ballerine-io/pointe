"""Conflict alarm (docs/features/conflict-alarm.md): two sessions that disagree about the same work.

Offline: a fake reading model, temp git repositories, transcripts in each harness's own shape. What it must never do is
tested as hard as what it does: send to a session, answer or hold a permission, talk into a meeting, talk over a
push-to-talk press, or raise an alarm because two sessions read the same file."""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import conflicts  # noqa: E402
import harnesses  # noqa: E402
from brief import FINAL_MARK  # noqa: E402
from harnesses import codex as codex_harness  # noqa: E402
from harnesses import opencode as opencode_harness  # noqa: E402
from harnesses.base import finished_tag  # noqa: E402
from sessions import Session  # noqa: E402
from test_orchestrator import Params, client_for, d, fake_conn, record_dispatch, verdicts  # noqa: E402,F401

MIGRATION_PASSED = "The migration for the refund_reason column ran on staging and passed. Nothing else changed."
TEST_FAILED = "The refunds test that reads the new refund_reason column failed on staging: column does not exist."

CONFLICT = {"conflict": True, "still_current": True, "claim_a": "the migration for the refund_reason column passed",
            "claim_b": "the refunds test that reads the new refund_reason column failed: column does not exist",
            "why": "The column cannot both exist and be missing.", "severity": "high",
            "question_for_a": "Which database did the migration run against?",
            "question_for_b": "Which database did the test connect to?"}


# ---------- fixtures ----------

def git_repo(path: Path, branch: str = "main") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True)
    return path


def transcript(path: Path, entries: list[dict]) -> str:
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return str(path)


def tool(name: str, **tool_input) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": name, "input": tool_input}]}}


def session(d, sid, name, cwd, entries=(), harness="claude-code", tmp=None) -> Session:
    path = transcript(Path(tmp or cwd) / f"{sid}.jsonl", list(entries))
    s = Session(id=sid, name=name, cwd=str(cwd), pid=os.getpid(), transcript=path, harness=harness)
    d.REGISTRY.add(s)
    return s


def fake_reader(d, monkeypatch, check=None):
    """The reading model: writes each report from the final message itself (so nothing is unsupported), answers the
    conflict check with `check` (a dict, a function of the prompt, or an exception), and writes no notes."""
    calls = []

    async def read(system, prompt, thinking=None):
        if system == conflicts.CHECK_SYSTEM:
            calls.append(prompt)
            if isinstance(check, Exception):
                raise check
            return check(prompt) if callable(check) else dict(check or {"conflict": False})
        if "ended its turn" in system:
            final = prompt.split("final message, complete:\n", 1)[-1]
            return {"status": "done", "urgency": "normal", "verdict": "see message", "limits": [], "say": final,
                    "line": final, "speak": True, "waiting": False}
        return {}

    async def no_brief(session):
        return None

    monkeypatch.setattr(d, "_read_model", read)
    monkeypatch.setattr(d, "_refresh_brief", no_brief)
    monkeypatch.setattr(d, "ALARM", conflicts.Alarm())
    monkeypatch.setattr(d, "NOTES", d.Notes())
    monkeypatch.setattr(d, "PREFS", d.Prefs(Path(os.environ["CLAUDE_VOICE_STATE"]) / "prefs-conflicts.json"))
    d.PREFS.values.clear()
    monkeypatch.setattr(d, "CONFLICT_POLL_SECS", 0.02)
    d.state.conn = fake_conn()
    return calls


async def report(d, s: Session, final: str) -> None:
    """A session ends its turn with `final`, as its harness's follower says it; then the conflict check finishes."""
    await d.feed(s, f"{finished_tag(harnesses.get(s.harness).label)} {FINAL_MARK}{final}", True)
    await settle(d)


async def settle(d) -> None:
    while d._CONFLICT_SCANS:
        await asyncio.gather(*list(d._CONFLICT_SCANS))


def alarms(d) -> list[str]:
    return [t for t, respond in d.state.conn.injector.fed if "two sessions disagree" in t]


def lantern_and_billing(d, tmp_path, branch_b="main"):
    """Two sessions in one repository, each in its own subfolder (the same git root)."""
    repo = git_repo(tmp_path / "shop")
    (repo / "db").mkdir()
    (repo / "api").mkdir()
    lantern = session(d, "cc-lantern", "lantern", repo / "db", tmp=tmp_path)
    billing = session(d, "cx-billing", "billing", repo / "api", harness="codex", tmp=tmp_path)
    if branch_b != "main":
        other = git_repo(tmp_path / "shop-wt", branch_b)
        billing.cwd = str(other)
    return lantern, billing


# ---------- prefilter, in code ----------

def test_only_edits_count_as_touching_a_file_reads_never_do(tmp_path):
    path = transcript(tmp_path / "t.jsonl", [
        tool("Read", file_path="/repo/ledger.py"), tool("Grep", pattern="refund", path="/repo/refunds.py"),
        tool("Edit", file_path="/repo/billing/charge.py"), tool("Write", file_path="/repo/notes/plan.md"),
        tool("MultiEdit", file_path="/repo/main.py"),  # too common a name to mean anything
    ])
    assert conflicts.edited_stems(path) == {"charge", "plan"}


def test_edited_files_are_read_from_each_harness_mirror():
    oc = opencode_harness.mirror_lines({"id": "m1", "type": "assistant", "time": {"created": 1}, "finish": "stop", "content": [
        {"type": "tool", "name": "edit", "state": {"input": {"filePath": "/repo/src/refunds.ts"}}},
        {"type": "tool", "name": "read", "state": {"input": {"filePath": "/repo/src/ledger.ts"}}}]})
    cx = codex_harness.mirror_lines({"status": "completed", "items": [
        {"id": "i1", "type": "fileChange", "changes": [{"path": "/repo/db/migrate_refund_reason.sql", "kind": "add"},
                                                        {"path": "/repo/db/schema.sql", "kind": "update"}]}]})
    lines = [json.dumps(e) for e in oc + cx]
    tmp = Path(os.environ["CLAUDE_VOICE_STATE"]) / "mirror.jsonl"
    tmp.write_text("\n".join(lines) + "\n")
    assert conflicts.edited_stems(str(tmp)) == {"refunds", "migrate_refund_reason", "schema"}


def _report(sid, name, cwd="", root="", final="", names=(), edited=(), at=None, branch=""):
    return conflicts.Report(session_id=sid, name=name, agent="Claude", cwd=cwd, root=root, branch=branch,
                            at=time.time() if at is None else at, final=final, names=set(names), edited=set(edited))


def test_the_prefilter_picks_pairs_that_share_a_repository_names_or_a_mention(tmp_path):
    repo = git_repo(tmp_path / "shop")
    (repo / "a").mkdir()
    (repo / "b").mkdir()
    root_a, branch = conflicts.git_place(str(repo / "a"))
    assert root_a == str(repo.resolve()) and branch == "main"
    assert conflicts.git_place(str(tmp_path / "nowhere")) == ("", "")
    now = time.time()
    new = _report("1", "billing", root=root_a, final="done")
    assert conflicts.candidate(new, _report("2", "lantern", root=root_a), now) == "same repository"
    assert conflicts.candidate(new, _report("2", "lantern", root="/other"), now) is None
    assert conflicts.candidate(_report("1", "billing", names={"stripe", "refund_reason"}),
                               _report("2", "lantern", edited={"refund_reason", "stripe"}), now) == "shared names"
    assert conflicts.candidate(_report("1", "billing", names={"stripe"}), _report("2", "lantern", names={"stripe"}), now) is None
    assert conflicts.candidate(_report("1", "billing", final="lantern said the migration passed"),
                               _report("2", "lantern"), now) == "named"
    assert conflicts.candidate(_report("1", "billing", final="the lanterns are on"), _report("2", "lantern"), now) is None


def test_one_session_contradicting_itself_and_a_stale_report_are_never_pairs():
    now = time.time()
    assert conflicts.candidate(_report("1", "billing", root="/r"), _report("1", "billing", root="/r"), now) is None
    assert conflicts.candidate(_report("1", "billing", root="/r"), _report("2", "lantern", root="/r", at=now - 5 * 3600), now) is None


def test_a_claim_its_session_never_made_is_dropped():
    assert conflicts.verified("the migration for the refund_reason column passed", MIGRATION_PASSED)
    assert not conflicts.verified("the migration failed", MIGRATION_PASSED)  # "failed" is not in the message
    assert not conflicts.verified("the deploy to production is live", MIGRATION_PASSED)
    assert not conflicts.verified("the cache warmer crashed overnight", MIGRATION_PASSED)  # invented content
    assert not conflicts.verified("", MIGRATION_PASSED)


def test_accept_checks_everything_the_reader_proposes():
    alarm = conflicts.Alarm()
    a = _report("a", "lantern", final=MIGRATION_PASSED, branch="main")
    b = _report("b", "billing", final=TEST_FAILED, branch="main")
    now = time.time()
    assert alarm.accept(a, b, {**CONFLICT, "conflict": False}, now, 1) is None
    assert alarm.accept(a, b, {**CONFLICT, "still_current": False}, now, 1) is None  # the earlier claim is stale
    assert alarm.accept(a, b, {**CONFLICT, "claim_b": CONFLICT["claim_a"]}, now, 1) is None  # agreement
    assert alarm.accept(a, b, "not json", now, 1) is None
    c = alarm.accept(a, b, CONFLICT, now, 1)
    assert c and c.severity == "high" and c.a_name == "lantern" and c.b_name == "billing"
    assert alarm.accept(a, b, CONFLICT, now + 31 * 60, 1) is None  # the same claims, never twice
    assert alarm.accept(a, b, {**CONFLICT, "claim_a": "Nothing else changed"}, now + 60, 1) is None  # one per pair per 30 min


def test_rate_limit_and_a_snooze_that_lasts_for_the_call():
    alarm = conflicts.Alarm()
    now = time.time()
    a, b = _report("a", "lantern", final=MIGRATION_PASSED), _report("b", "billing", final=TEST_FAILED)
    c = alarm.accept(a, b, CONFLICT, now, "call-1")
    assert not alarm.allowed("a", "b", now + 60, "call-1")  # 30 minutes per pair
    assert alarm.allowed("a", "b", now + 31 * 60, "call-1")
    alarm.dismiss(c, "call-1")
    assert alarm.open() == []
    assert not alarm.allowed("b", "a", now + 31 * 60, "call-1")  # snoozed for this call, whichever order
    assert alarm.allowed("a", "b", now + 31 * 60, "call-2")  # a new call: it may come back


def test_across_branches_a_conflict_is_normal_and_says_the_branches():
    alarm = conflicts.Alarm()
    c = alarm.accept(_report("a", "lantern", final=MIGRATION_PASSED, branch="dev"),
                     _report("b", "billing", final=TEST_FAILED, branch="main"), CONFLICT, time.time(), 1)
    assert c.severity == "normal" and c.public()["branches"] == {"a": "dev", "b": "main"}


# ---------- in the daemon ----------

def test_two_reports_that_disagree_give_one_urgent_line_one_card_and_one_note(d, monkeypatch, tmp_path):
    calls = fake_reader(d, monkeypatch, CONFLICT)
    sent = record_dispatch(d, monkeypatch)
    lantern, billing = lantern_and_billing(d, tmp_path)

    async def go():
        await report(d, lantern, MIGRATION_PASSED)
        assert calls == []  # nothing to compare with yet
        await report(d, billing, TEST_FAILED)

    asyncio.run(go())
    assert len(calls) == 1 and "lantern (Claude)" in calls[0] and "billing (Codex)" in calls[0]
    [line] = alarms(d)
    assert d._feed_priority(line) == -1  # the urgent lane
    assert "lantern" in line and "billing" in line and "Send nothing unless the user says so" in line
    assert CONFLICT["claim_a"] in line and CONFLICT["claim_b"] in line
    status = client_for(d).get("/voice/status").json()
    [card] = status["conflicts"]
    assert card["a"] == "lantern" and card["b"] == "billing" and card["agent_b"] == "Codex"
    assert card["questions"] == {"a": CONFLICT["question_for_a"], "b": CONFLICT["question_for_b"]}
    [alert] = [a for a in status["attention"] if a["kind"] == "conflict"]
    assert alert["id"] == f"conflict:{card['id']}" and alert["title"] == "Two sessions disagree"
    assert "lantern" in alert["body"] and "migration" not in alert["body"]  # names only: claims stay on the screen
    assert alert["approvable"] is False
    assert [n.kind for n in d.NOTES.items] == ["conflict"]
    assert sent == []  # an alarm never asks a session on its own


def test_an_alarm_never_answers_or_holds_a_permission(d, monkeypatch, tmp_path):
    """A read-out window is open on the active session when the alarm comes: the alarm waits for it to close, and the
    request, its window and its answer are untouched."""
    fake_reader(d, monkeypatch, CONFLICT)
    monkeypatch.setattr(d, "PERMISSION_ANSWER_SECS", 120.0)
    posts = []

    async def deliver(session, request_id, verdict):
        posts.append((session.name, request_id, verdict))
        return True

    monkeypatch.setattr(d, "_deliver_verdict", deliver)
    lantern, billing = lantern_and_billing(d, tmp_path)
    d.REGISTRY.active_id = lantern.id
    lantern.permission_id, lantern.permission_text = "p1", "[permission request] Bash: rm -rf build"
    opened = time.time()
    lantern.permission_delivered_at = lantern.permission_read_at = opened

    async def go():
        await report(d, lantern, MIGRATION_PASSED)
        scan = asyncio.create_task(report(d, billing, TEST_FAILED))
        for _ in range(30):
            await asyncio.sleep(0.02)
        assert alarms(d) == [] and client_for(d).get("/voice/status").json()["conflicts"]  # shown, not said
        assert lantern.permission_id == "p1" and lantern.permission_delivered_at == opened and posts == []
        await d._apply_answer(lantern, "p1", "allow", "tapped")  # the user's own tap
        await scan

    asyncio.run(go())
    assert posts == [("lantern", "p1", "allow")]  # only the tap answered it
    assert len(alarms(d)) == 1  # said once the window closed


def test_asking_sends_the_cards_question_to_that_session_and_never_as_the_users_words(d, monkeypatch, tmp_path):
    """Mythos review AV-6. The question is a model's, written over two sessions' reports: one tap sends it, word for word
    as the card shows it, to the session it names, under a header saying it is a conflict check. It never becomes the
    user's words (state.last_utterance), which the send check and the start, close and add parsers read as speech."""
    fake_reader(d, monkeypatch, CONFLICT)
    sent = record_dispatch(d, monkeypatch)
    lantern, billing = lantern_and_billing(d, tmp_path)
    asyncio.run(report(d, lantern, MIGRATION_PASSED))
    asyncio.run(report(d, billing, TEST_FAILED))
    assert sent == []
    pushed = []

    async def push(frame, *a):
        pushed.append(frame)

    d.state.conn.injector.push_frame = push
    d.state.last_utterance = "what is billing doing?"
    talk = list(d.state.conversation)
    client = client_for(d)
    card = client.get("/voice/status").json()["conflicts"][0]
    assert client.post("/voice/conflicts", json={"action": "ask", "id": card["id"], "side": "c"}).status_code == 400
    assert client.post("/voice/conflicts", json={"action": "ask", "id": "nope", "side": "a"}).status_code == 404
    r = client.post("/voice/conflicts", json={"action": "ask", "id": card["id"], "side": "a"})
    assert r.status_code == 200, r.text
    assert len(sent) == 1 and sent[0][0] == "lantern", sent
    assert sent[0][1].startswith("A conflict check, sent by the user from Pointe's conflict card")
    assert sent[0][1].endswith(CONFLICT["question_for_a"])
    assert pushed == [], "the brain was handed the model's question as the user's words"
    assert d.state.last_utterance == "what is billing doing?"
    assert [t for t in d.state.conversation if t[0] == "user"] == [t for t in talk if t[0] == "user"]
    assert client.get("/voice/status").json()["conflicts"][0]["asked"] == ["a"]


def test_a_typed_ask_cannot_approve_a_waiting_permission(d, monkeypatch, tmp_path):
    fake_reader(d, monkeypatch, {**CONFLICT, "question_for_a": "yes"})
    sent = record_dispatch(d, monkeypatch)
    posts = []

    async def deliver(session, request_id, verdict):
        posts.append(verdict)
        return True

    monkeypatch.setattr(d, "_deliver_verdict", deliver)
    lantern, billing = lantern_and_billing(d, tmp_path)
    asyncio.run(report(d, lantern, MIGRATION_PASSED))
    asyncio.run(report(d, billing, TEST_FAILED))
    d.REGISTRY.active_id = lantern.id
    lantern.permission_id, lantern.permission_delivered_at, lantern.permission_read_at = "p9", 1.0, time.time()
    d.state.conn.injector.bot_started_at = 2.0  # the request was read out
    d.state.conn.injector.push_frame = lambda *a: asyncio.sleep(0)
    card = client_for(d).get("/voice/status").json()["conflicts"][0]
    assert client_for(d).post("/voice/conflicts", json={"action": "ask", "id": card["id"], "side": "a"}).status_code == 200
    assert posts == [] and lantern.permission_id == "p9"
    assert len(sent) == 1 and d.state.last_utterance != "yes"  # sent to lantern, never taken as the user's yes


def test_dismissing_by_tap_or_by_voice_snoozes_the_pair_for_the_call(d, monkeypatch, tmp_path):
    calls = fake_reader(d, monkeypatch, CONFLICT)
    lantern, billing = lantern_and_billing(d, tmp_path)
    asyncio.run(report(d, lantern, MIGRATION_PASSED))
    asyncio.run(report(d, billing, TEST_FAILED))
    client = client_for(d)
    card = client.get("/voice/status").json()["conflicts"][0]
    assert client.post("/voice/conflicts", json={"action": "dismiss", "id": card["id"]}).json() == {"conflicts": []}
    assert not [n for n in d.NOTES.items if n.state == "open"]  # its note is dismissed with it
    d.ALARM.last_raised.clear()  # past the 30 minutes: only the snooze is left
    asyncio.run(report(d, lantern, MIGRATION_PASSED + " Checked twice."))
    assert len(calls) == 1  # snoozed: not even a reader call

    # by voice: "I know" right after the alarm was said
    d.ALARM.snoozed.clear()
    d.ALARM.raised.clear()
    asyncio.run(report(d, billing, TEST_FAILED))
    assert client.get("/voice/status").json()["conflicts"]
    asyncio.run(d.on_user_utterance("I know, later"))
    assert client.get("/voice/status").json()["conflicts"] == []


def test_in_a_meeting_an_alarm_is_a_card_and_a_note_never_speech(d, monkeypatch, tmp_path):
    from test_meeting_daemon import _meeting_ready, _start

    fake_reader(d, monkeypatch, CONFLICT)
    lantern, billing = lantern_and_billing(d, tmp_path)
    asyncio.run(report(d, lantern, MIGRATION_PASSED))
    _meeting_ready(d, monkeypatch)
    monkeypatch.setattr(d, "NOTES", d.Notes())
    _start(d, "participating")
    asyncio.run(report(d, billing, TEST_FAILED))
    assert alarms(d) == [] and not [t for t, _ in d.state.monologue_held if "disagree" in t]  # not even after the meeting
    assert client_for(d).get("/voice/status").json()["conflicts"]
    assert [n.kind for n in d.NOTES.items if n.kind == "conflict"] == ["conflict"]
    card = client_for(d).get("/voice/status").json()["conflicts"][0]
    r = client_for(d).post("/voice/conflicts", json={"action": "ask", "id": card["id"], "side": "a"})
    assert r.status_code == 409  # nothing goes to a session during a meeting


def test_a_push_to_talk_press_holds_the_alarm_until_it_is_released(d, monkeypatch, tmp_path):
    fake_reader(d, monkeypatch, CONFLICT)
    d.PREFS.update({"microphone": "ptt"})
    lantern, billing = lantern_and_billing(d, tmp_path)

    async def go():
        await report(d, lantern, MIGRATION_PASSED)
        d.state.ptt.press(time.time())
        scan = asyncio.create_task(report(d, billing, TEST_FAILED))
        for _ in range(20):
            await asyncio.sleep(0.02)
        assert alarms(d) == []  # never over the user's press
        d.state.ptt.release(time.time())
        await scan

    asyncio.run(go())
    assert len(alarms(d)) == 1


def test_card_only_and_off(d, monkeypatch, tmp_path):
    calls = fake_reader(d, monkeypatch, CONFLICT)
    lantern, billing = lantern_and_billing(d, tmp_path)
    d.PREFS.update({"conflicts.spoken": False})
    asyncio.run(report(d, lantern, MIGRATION_PASSED))
    asyncio.run(report(d, billing, TEST_FAILED))
    assert alarms(d) == [] and len(client_for(d).get("/voice/status").json()["conflicts"]) == 1
    d.PREFS.update({"conflicts.on": False})
    d.ALARM = conflicts.Alarm()
    asyncio.run(report(d, lantern, MIGRATION_PASSED))
    asyncio.run(report(d, billing, TEST_FAILED))
    assert len(calls) == 1  # off: no reader call at all
    assert client_for(d).get("/voice/prefs").json()["conflicts.on"] is False
    assert client_for(d).post("/voice/prefs", json={"conflicts.spoken": "loud"}).status_code == 400


def test_reader_unavailable_means_no_alarm_and_a_journal_line(d, monkeypatch, tmp_path):
    from loguru import logger

    fake_reader(d, monkeypatch, TimeoutError())
    lines = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="INFO")
    lantern, billing = lantern_and_billing(d, tmp_path)
    try:
        asyncio.run(report(d, lantern, MIGRATION_PASSED))
        asyncio.run(report(d, billing, TEST_FAILED))
    finally:
        logger.remove(sink)
    assert alarms(d) == [] and client_for(d).get("/voice/status").json()["conflicts"] == []
    assert any(line.startswith("conflict check skipped") for line in lines)


def test_a_stale_earlier_claim_is_no_alarm(d, monkeypatch, tmp_path):
    fake_reader(d, monkeypatch, {**CONFLICT, "still_current": False})
    lantern, billing = lantern_and_billing(d, tmp_path)
    asyncio.run(report(d, lantern, MIGRATION_PASSED))
    asyncio.run(report(d, billing, TEST_FAILED))
    assert alarms(d) == []


def test_across_branches_the_alarm_says_the_branches(d, monkeypatch, tmp_path):
    calls = fake_reader(d, monkeypatch, CONFLICT)
    lantern, billing = lantern_and_billing(d, tmp_path, branch_b="release")  # billing in another clone, on release
    lantern.brief = {"people_and_names": ["refund_reason", "staging"]}
    billing.brief = {"people_and_names": ["refund_reason", "staging"]}
    asyncio.run(report(d, lantern, MIGRATION_PASSED))
    asyncio.run(report(d, billing, TEST_FAILED))
    assert "git branch main" in calls[0] and "git branch release" in calls[0]
    card = client_for(d).get("/voice/status").json()["conflicts"][0]
    assert card["severity"] == "normal" and card["branches"] == {"a": "main", "b": "release"}
    assert "main" in alarms(d)[0] and "release" in alarms(d)[0]


def test_hebrew_the_alarm_is_said_in_hebrew_with_claims_as_written(d, monkeypatch, tmp_path):
    fake_reader(d, monkeypatch, CONFLICT)
    d.state.last_utterance = "מה המצב עם המיגרציה"
    lantern, billing = lantern_and_billing(d, tmp_path)
    asyncio.run(report(d, lantern, MIGRATION_PASSED))
    asyncio.run(report(d, billing, TEST_FAILED))
    assert "In Hebrew" in alarms(d)[0] and "in the language it was written in" in alarms(d)[0]


# ---------- no false alarms: two sessions reading the same file ----------

def test_two_sessions_reading_the_same_file_in_different_repositories_never_reach_the_reader(d, monkeypatch, tmp_path):
    """Both read ledger.py and talk about it; one passed, one failed. Reads are not edits and the repositories differ:
    no pair, no reader call, no alarm, even with a reader that would call anything a conflict."""
    calls = fake_reader(d, monkeypatch, CONFLICT)
    one, two = git_repo(tmp_path / "shop"), git_repo(tmp_path / "warehouse")
    reads = [tool("Read", file_path="ledger.py"), tool("Grep", pattern="refund_reason", path="ledger.py")]
    a = session(d, "cc1", "shop", one, reads, tmp=tmp_path)
    b = session(d, "oc1", "warehouse", two, reads, harness="opencode", tmp=tmp_path)
    asyncio.run(report(d, a, "Read ledger.py: the refund_reason column passed review."))
    asyncio.run(report(d, b, "Read ledger.py: the refund_reason test failed here."))
    assert calls == [] and alarms(d) == []


def test_two_sessions_reading_the_same_file_in_one_repository_are_no_alarm(d, monkeypatch, tmp_path):
    """Same repository, so the reader is asked. A reader that answers well says no; a careless one that calls the shared
    read a conflict is caught in code: the same claim twice is agreement, and an invented failure is not in the
    message."""
    repo = git_repo(tmp_path / "shop")
    reads = [tool("Read", file_path=str(repo / "ledger.py"))]
    lantern = session(d, "cc1", "lantern", repo, reads, tmp=tmp_path)
    billing = session(d, "cx1", "billing", repo, reads, harness="codex", tmp=tmp_path)
    a_final = "I read ledger.py. It rounds refunds half up. No changes made."
    b_final = "I read ledger.py too. It rounds refunds half up, which matches the spec. No changes made."
    for answer in ({"conflict": False},
                   {**CONFLICT, "claim_a": "ledger.py rounds refunds half up", "claim_b": "ledger.py rounds refunds half up"},
                   {**CONFLICT, "claim_a": "I read ledger.py", "claim_b": "the ledger test failed"}):
        calls = fake_reader(d, monkeypatch, answer)
        asyncio.run(report(d, lantern, a_final))
        asyncio.run(report(d, billing, b_final))
        assert len(calls) == 1, answer
        assert alarms(d) == [] and client_for(d).get("/voice/status").json()["conflicts"] == [], answer


# ---------- mixed harnesses ----------

def test_codex_and_opencode_editing_the_same_files_in_different_folders_raise_one_alarm(d, monkeypatch, tmp_path):
    """Claude Code, OpenCode and Codex on one call. OpenCode and Codex edit the same two files in separate clones (no
    shared git root): the shared edits make them a pair. Claude Code, which only read one of the files, is not paired."""
    calls = fake_reader(d, monkeypatch, CONFLICT)
    oc_lines = opencode_harness.mirror_lines({"id": "m1", "type": "assistant", "time": {"created": 1}, "content": [
        {"type": "tool", "name": "edit", "state": {"input": {"filePath": "/clone-a/db/migrate_refund_reason.sql"}}},
        {"type": "tool", "name": "write", "state": {"input": {"filePath": "/clone-a/db/refund_schema.sql"}}}]})
    cx_lines = codex_harness.mirror_lines({"status": "completed", "items": [
        {"id": "i1", "type": "fileChange", "changes": [{"path": "/clone-b/db/migrate_refund_reason.sql"},
                                                        {"path": "/clone-b/db/refund_schema.sql"}]}]})
    claude = session(d, "cc1", "docs", git_repo(tmp_path / "docs"), [tool("Read", file_path="/docs/refund_schema.sql")], tmp=tmp_path)
    shop = session(d, "ses_shop", "shop", git_repo(tmp_path / "clone-a"), oc_lines, harness="opencode", tmp=tmp_path)
    harbor = session(d, "th_harbor", "harbor", git_repo(tmp_path / "clone-b"), cx_lines, harness="codex", tmp=tmp_path)
    asyncio.run(report(d, claude, "Docs updated for the refund_reason column. Nothing else changed."))
    asyncio.run(report(d, shop, MIGRATION_PASSED))
    assert calls == []  # docs only read a file: no pair
    asyncio.run(report(d, harbor, TEST_FAILED))
    assert len(calls) == 1 and "shop (OpenCode)" in calls[0] and "harbor (Codex)" in calls[0]
    [line] = alarms(d)
    assert "shop" in line and "harbor" in line and "docs" not in line
    card = client_for(d).get("/voice/status").json()["conflicts"][0]
    assert (card["a"], card["agent_a"], card["b"], card["agent_b"]) == ("shop", "OpenCode", "harbor", "Codex")


def test_a_departed_sessions_report_is_never_compared(d, monkeypatch, tmp_path):
    calls = fake_reader(d, monkeypatch, CONFLICT)
    lantern, billing = lantern_and_billing(d, tmp_path)
    asyncio.run(report(d, lantern, MIGRATION_PASSED))
    d.REGISTRY.sessions.pop(lantern.id)
    asyncio.run(report(d, billing, TEST_FAILED))
    assert calls == []


def test_the_phone_key_reaches_the_conflicts_route():
    import guards

    assert "/voice/conflicts" in guards._PHONE_PATHS


def test_no_call_and_no_meeting_needed_for_the_card_but_asking_needs_a_call(d, monkeypatch, tmp_path):
    fake_reader(d, monkeypatch, CONFLICT)
    lantern, billing = lantern_and_billing(d, tmp_path)
    d.state.conn = None

    async def go():
        for s, final in ((lantern, MIGRATION_PASSED), (billing, TEST_FAILED)):
            await d._digest_turn(s, f"[x] {FINAL_MARK}{final}")
            await settle(d)

    asyncio.run(go())
    card = client_for(d).get("/voice/status").json()["conflicts"][0]
    assert client_for(d).post("/voice/conflicts", json={"action": "ask", "id": card["id"], "side": "b"}).status_code == 409
    assert client_for(d).post("/voice/conflicts", json={"action": "shout"}).status_code == 400
    assert client_for(d).post("/voice/conflicts", content=b"[]", headers={"content-type": "application/json"}).status_code == 400


@pytest.fixture(autouse=True)
def _no_leftover_scans():
    yield
    import daemon

    if hasattr(daemon, "_CONFLICT_SCANS"):
        daemon._CONFLICT_SCANS.clear()


def test_the_page_and_the_app_use_the_same_words():
    """Parity: every fixed string of the app's ConflictCopy is on the page, word for word."""
    import re

    root = Path(__file__).resolve().parents[1]
    swift = (root / "apple" / "PointeKit" / "Sources" / "PointeUI" / "Conflicts.swift").read_text()
    page = " ".join((root / "ui.html").read_text().split())
    copy = swift[swift.index("enum ConflictCopy"):swift.index("struct ConflictCard")]
    fixed = re.findall(r'static let \w+ = "([^"]+)"', copy)
    assert len(fixed) >= 10
    built = ["Ask ", "Asked ", "On different branches: ", " more disagreement", "That conflict is gone.", "Not done."]
    missing = [s for s in fixed + built if s not in page]
    assert missing == []
