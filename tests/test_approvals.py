"""The approvals record (pointe/approvals.py, docs/features/approvals-record.md): every answer to a permission request
that went through Pointe, with when, how (voice, tap, a notification's action), the exact request and the voice lock's
score, read back from the daemon's own journal by GET /voice/approvals. Offline: no model, no network. The journal
here is a fixture of invented sessions (tests/fixtures/approvals_journal.jsonl).
"""

import asyncio
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
import approvals  # noqa: E402
from test_orchestrator import _consent_setup, client_for, d, verdicts  # noqa: E402,F401  (d is the daemon fixture)

FIXTURE = ROOT / "tests" / "fixtures" / "approvals_journal.jsonl"
AUTH = {"authorization": "Bearer secret"}
IN_FIXTURE = ["p1", "p2", "p3", "p4", "p5"]  # every well-formed approval line of the fixture, oldest first


# ---------- the record, read from a journal ----------

def test_every_approval_in_the_journal_is_in_the_record_newest_first():
    got = approvals.read([FIXTURE])
    assert [a["request_id"] for a in got] == IN_FIXTURE[::-1]
    lines = [json.loads(line)["event"] for line in FIXTURE.read_text().splitlines()]
    assert len(got) == sum(1 for e in lines if e.startswith(approvals.MARK)) - 1  # one line is not JSON: skipped, not fatal
    first = got[-1]
    assert first == {"at": "2026-11-20 09:14:02.121", "session": "bluebell/dev", "machine": None, "request_id": "p1", "decision": "allow",
                     "by": "voice", "request": "Bash\ngit push --force-with-lease origin retry-fix", "cut": False, "lock": "approvals", "score": 0.71}


def test_a_line_that_only_mentions_approval_is_not_a_record():
    assert all(a["request_id"] in IN_FIXTURE for a in approvals.read([FIXTURE]))
    assert approvals.parse({"at": "x", "event": "approval of the plan is done"}) is None
    assert approvals.parse({"at": "x", "event": 'approval {"decision": "maybe", "session": "a", "request_id": "r"}'}) is None


def test_the_older_journal_file_is_read_too_and_the_newest_are_kept(tmp_path):
    lines = FIXTURE.read_text().splitlines(keepends=True)
    (tmp_path / "journal.jsonl.1").write_text("".join(lines[:4]))
    (tmp_path / "journal.jsonl").write_text("".join(lines[4:]))
    paths = [tmp_path / "journal.jsonl.1", tmp_path / "journal.jsonl", tmp_path / "missing.jsonl"]
    assert [a["request_id"] for a in approvals.read(paths)] == IN_FIXTURE[::-1]
    assert [a["request_id"] for a in approvals.read(paths, limit=2)] == ["p5", "p4"]


def test_how_it_was_answered_is_one_of_three_words():
    assert approvals.by("user said: 'yes'") == "voice"
    assert approvals.by("tapped") == "tap"
    assert approvals.by("from a notification") == "notification"
    assert approvals.by("night shift: its own rule") == "other"


def test_a_long_request_is_cut_and_says_so_and_a_secret_is_masked():
    event = approvals.event(session="docs", machine=None, request_id="r9", decision="allow", how="tapped", lock="off", score=None,
                            request="Bash\n" + "echo token=sk-ant-abcdefghijklmnopqrstuvwxyz0123456789 " + "x" * 5000)
    got = approvals.parse({"at": "2026-11-21 10:00:00.000", "event": event})
    assert got["cut"] and len(got["request"]) == approvals.MAX_REQUEST_CHARS
    assert "sk-ant-abcdefghijklmnopqrstuvwxyz0123456789" not in event


# ---------- the daemon writes it ----------

def _journal_to(d, monkeypatch, tmp_path):
    """The daemon's own journal sink, on a file of this test's."""
    path = tmp_path / "journal.jsonl"
    monkeypatch.setattr(d, "JOURNAL", path)
    return path, d.logger.add(d._journal, level="INFO", diagnose=False, backtrace=False)


@pytest.mark.parametrize("decision", ["allow", "deny"])
def test_a_tap_is_written_with_the_exact_request_and_no_score(d, monkeypatch, tmp_path, decision):
    active, posts = _consent_setup(d, monkeypatch)
    active.permission_full = "Bash\nrm -rf build"
    path, sink = _journal_to(d, monkeypatch, tmp_path)
    try:
        r = client_for(d).post("/voice/approve", headers=AUTH, json={"session": active.name, "request_id": "p1", "decision": decision})
    finally:
        d.logger.remove(sink)
    assert r.status_code == 200
    got = approvals.read([path])
    assert len(got) == 1 and got[0] | {"at": ""} == {
        "at": "", "session": "bluebell/dev", "machine": None, "request_id": "p1", "decision": decision, "by": "tap",
        "request": "Bash\nrm -rf build", "cut": False, "lock": d.lock_level(), "score": None}


def test_a_spoken_yes_is_written_with_the_voice_locks_score(d, monkeypatch, tmp_path):
    active, posts = _consent_setup(d, monkeypatch)
    active.permission_full = "Bash\nrm -rf build"
    d.state.last_speaker = d.speaker.Verdict(0.73, 1.4, "mac", 5.0)
    monkeypatch.setattr(d, "lock_level", lambda: "approvals")
    path, sink = _journal_to(d, monkeypatch, tmp_path)
    try:
        assert asyncio.run(d._apply_answer(active, "p1", "allow", "user said: 'yes'"))
    finally:
        d.logger.remove(sink)
    got = approvals.read([path])
    assert [(a["by"], a["decision"], a["score"], a["lock"], a["request"]) for a in got] == [("voice", "allow", 0.73, "approvals", "Bash\nrm -rf build")]


def test_a_tap_never_carries_a_score_left_from_an_earlier_utterance(d, monkeypatch, tmp_path):
    active, posts = _consent_setup(d, monkeypatch)
    d.state.last_speaker = d.speaker.Verdict(0.9, 2.0, "mac", 5.0)
    path, sink = _journal_to(d, monkeypatch, tmp_path)
    try:
        asyncio.run(d._apply_answer(active, "p1", "allow", "tapped"))
    finally:
        d.logger.remove(sink)
    assert approvals.read([path])[0]["score"] is None


def test_an_answer_that_did_not_reach_the_session_is_not_in_the_record(d, monkeypatch, tmp_path):
    active, _ = _consent_setup(d, monkeypatch)

    async def lost(*_a, **_k):
        return False

    monkeypatch.setattr(d, "post_channel", lost)
    path, sink = _journal_to(d, monkeypatch, tmp_path)
    try:
        assert not asyncio.run(d._apply_answer(active, "p1", "allow", "tapped"))
    finally:
        d.logger.remove(sink)
    assert approvals.read([path]) == []


# ---------- the endpoint ----------

def test_the_endpoint_returns_every_approval_in_the_journal(d, monkeypatch, tmp_path):
    shutil.copy(FIXTURE, tmp_path / "journal.jsonl")
    monkeypatch.setattr(d, "JOURNAL", tmp_path / "journal.jsonl")
    r = client_for(d).get("/voice/approvals", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert [a["request_id"] for a in body["approvals"]] == IN_FIXTURE[::-1]
    assert body["approvals"][0]["cut"] is True and body["approvals"][2]["machine"] == "devbox"
    assert set(body["approvals"][0]) == {"at", "session", "machine", "request_id", "decision", "by", "request", "cut", "lock", "score"}


def test_the_endpoint_is_behind_the_same_lock_as_the_rest(d, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    shutil.copy(FIXTURE, tmp_path / "journal.jsonl")
    monkeypatch.setattr(d, "JOURNAL", tmp_path / "journal.jsonl")
    stranger = TestClient(d.app, base_url="http://127.0.0.1:7860")
    assert stranger.get("/voice/approvals").status_code == stranger.get("/voice/status").status_code == 403
    assert stranger.get("/voice/approvals", headers={"authorization": "Bearer nope"}).status_code == 403
    assert stranger.get("/voice/approvals", headers={"Origin": "http://localhost:3000", **AUTH}).status_code == \
        stranger.get("/voice/status", headers={"Origin": "http://localhost:3000", **AUTH}).status_code


def test_no_journal_yet_is_an_empty_record(d, monkeypatch, tmp_path):
    monkeypatch.setattr(d, "JOURNAL", tmp_path / "none.jsonl")
    assert client_for(d).get("/voice/approvals", headers=AUTH).json() == {"approvals": []}


# ---------- the apps and the page read the same answer ----------

def test_the_apps_fixture_is_the_endpoints_answer_to_the_fixture_journal(d, monkeypatch, tmp_path):
    """ApprovalsTests.swift decodes Fixtures/approvals.json: it is what the daemon sends for this journal, so a field
    renamed on one side fails on the other."""
    shutil.copy(FIXTURE, tmp_path / "journal.jsonl")
    monkeypatch.setattr(d, "JOURNAL", tmp_path / "journal.jsonl")
    sent = client_for(d).get("/voice/approvals", headers=AUTH).json()
    kept = json.loads((ROOT / "apps" / "PointeKit" / "Tests" / "PointeUIUnitTests" / "Fixtures" / "approvals.json").read_text())
    assert sent == kept


def test_the_words_are_the_same_on_the_page_and_in_the_apps():
    page = (ROOT / "pointe" / "ui_approvals.html").read_text()
    swift = (ROOT / "apps" / "PointeKit" / "Sources" / "PointeUI" / "Approvals.swift").read_text()
    for key, words in approvals.COPY.items():
        plain = words.replace("{lock}", "").replace("{score}", "")
        for part in [p for p in (words.split("{")[0], words.rsplit("}", 1)[-1]) if p.strip()] if "{" in words else [plain]:
            assert part in page, f"{key}: the page does not say {part!r}"
            assert part in swift, f"{key}: the apps do not say {part!r}"
