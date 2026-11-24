"""A send that Claude Code holds or refuses is not called delivered.

Claude Code holds an inbox message to a session that bypasses permission prompts (unless that session sets
`crossSessionInbound: accept`), and refuses one under `refuse`. It writes nothing back on the inbox connection: a
`peer_message_status` line goes to the reply address in the message's `from`, about 0.2 s later, and only for a held,
refused or dropped message; the user's answer in the terminal sends a second one (`delivered`, `denied`, `expired`).
Seen against Claude Code 2.1.325. The fake inbox here answers the same way.

uv run --locked pytest -q tests/test_held_send.py
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harnesses.claude_code as cc_module  # noqa: E402
import nodelink  # noqa: E402
import sessions  # noqa: E402
from harnesses.claude_code import ClaudeCode, may_hold, permission_mode  # noqa: E402
from sessions import Session, post_inbox  # noqa: E402
from test_orchestrator import add, client_for, d, open_gates  # noqa: E402,F401


@pytest.fixture
def sockdir():
    path = Path(tempfile.mkdtemp(prefix="cvh-", dir="/tmp"))  # a Unix socket path must stay short
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(sessions, "RECEIPT_SECS", 0.4)


class FakeInbox:
    """Claude Code's inbox socket: takes the lines, and answers a message that carries a reply address with the
    statuses in `answers` (none: accepted), each sent as Claude Code sends it, on a new connection to that address."""

    def __init__(self, path: Path, answers=(), later=()):
        self.path, self.answers, self.later = path, list(answers), list(later)
        self.lines: list[dict] = []
        self.back_on_connection = False

    async def __aenter__(self):
        self.server = await asyncio.start_unix_server(self._take, str(self.path))
        return self

    async def __aexit__(self, *exc):
        self.server.close()

    async def _take(self, reader, writer):
        lines = [json.loads(line) for line in (await reader.read()).decode().splitlines()]
        self.lines += lines
        writer.close()
        message = lines[-1]
        if message.get("from", "").startswith("uds:"):
            asyncio.create_task(self._answer(message["from"][4:], message["msg_id"]))

    async def _answer(self, reply: str, msg_id: str):
        await asyncio.sleep(0.05)
        for status in self.answers:
            await self._status(reply, msg_id, status)
        for wait, status in self.later:
            await asyncio.sleep(wait)
            await self._status(reply, msg_id, status)

    async def _status(self, reply: str, msg_id: str, status: str):
        frame = {"type": "control", "action": "peer_message_status", "status": status, "reason": "…",
                 "from": f"uds:{self.path}", "orig_msg_id": msg_id, "msgV": 1, "msg_id": "6cefe8fb-0000-4000-8000-87bc1e5f7d88"}
        if status == "refused":  # how Claude Code words a refusal on the wire
            frame.update(status="expired", status_detail="refused")
        _, w = await asyncio.open_unix_connection(reply)
        w.write((json.dumps(frame) + "\n").encode())
        await w.drain()
        w.close()


def session(sockdir: Path, **kw) -> Session:
    return Session(id="cc1", name="bluebell", cwd=str(sockdir), inbox_socket=str(sockdir / "123.sock"), **kw)


# ---------- the wire ----------

def test_a_held_message_is_not_delivered_and_the_session_shows_it_held(sockdir):
    async def go():
        s = session(sockdir)
        async with FakeInbox(sockdir / "123.sock", answers=["held"]) as inbox:
            ok = await post_inbox(s, "run the tests", receipt=True)
        return s, ok, inbox

    s, ok, inbox = asyncio.run(go())
    assert ok is False and s.held_at is not None
    line = inbox.lines[-1]
    assert line["from"].startswith(f"uds:{sockdir}/") and line["from"].endswith(".sock")  # beside its socket
    assert len(line["msg_id"]) == 36
    assert sessions.terminal_wait(s) == "a message from the voice, held for approval in its terminal"
    assert "crossSessionInbound to accept" in sessions.inbox_need(s, time.time())


def test_a_refused_message_is_not_delivered_and_says_which_setting(sockdir):
    async def go():
        s = session(sockdir)
        async with FakeInbox(sockdir / "123.sock", answers=["refused"]):
            return s, await post_inbox(s, "run the tests", receipt=True)

    s, ok = asyncio.run(go())
    assert ok is False and s.refused_at is not None and s.held_at is None
    assert sessions.terminal_wait(s) == ""  # nothing to answer in the terminal
    need = sessions.inbox_need(s, time.time())
    assert "refuses messages from other sessions" in need and "crossSessionInbound to accept" in need
    assert sessions.inbox_need(s, time.time() + sessions.REFUSED_SHOW_SECS + 1) == ""


def test_no_answer_is_an_accepted_message_and_the_reply_address_is_gone_after(sockdir):
    async def go():
        s = session(sockdir)
        async with FakeInbox(sockdir / "123.sock") as inbox:
            return s, await post_inbox(s, "run the tests", receipt=True), inbox

    s, ok, inbox = asyncio.run(go())
    assert ok is True and s.held_at is None and s.refused_at is None
    assert [p.name for p in sockdir.iterdir()] == ["123.sock"]  # the reply socket was removed


def test_without_a_receipt_the_message_carries_no_reply_address(sockdir):
    """A session given a reply address tries to answer through it (Opus did, live): offered only where it is needed."""
    async def go():
        s = session(sockdir, inbox_token="tok")
        async with FakeInbox(sockdir / "123.sock", answers=["held"]) as inbox:
            ok = await post_inbox(s, "run the tests")
            await asyncio.sleep(0.1)
            return ok, inbox

    ok, inbox = asyncio.run(go())
    assert ok is True
    assert inbox.lines[0] == {"type": "auth", "token": "tok"}
    assert set(inbox.lines[1]) == {"type", "message"}


@pytest.mark.parametrize("answer", ["delivered", "denied", "expired"])
def test_the_users_answer_in_the_terminal_ends_the_hold(sockdir, answer):
    async def go():
        s = session(sockdir)
        async with FakeInbox(sockdir / "123.sock", answers=["held"], later=[(0.2, answer)]):
            assert await post_inbox(s, "run the tests", receipt=True) is False
            assert s.held_at is not None
            for _ in range(40):
                await asyncio.sleep(0.05)
                if s.held_at is None:
                    break
        return s

    s = asyncio.run(go())
    assert s.held_at is None and sessions.terminal_wait(s) == ""
    assert [p.name for p in sockdir.iterdir()] == ["123.sock"]


def test_a_hold_nobody_reports_on_is_not_claimed_forever(sockdir):
    s = session(sockdir)
    s.held_at = time.time() - sessions.HELD_WATCH_SECS - 1
    assert not sessions.message_held(s) and sessions.terminal_wait(s) == "" and sessions.inbox_need(s, time.time()) == ""


def test_a_receipt_for_another_message_or_a_reply_sent_to_the_address_is_ignored(sockdir):
    async def go():
        s = session(sockdir)
        receipts = await sessions._Receipts.open(s.inbox_socket)
        try:
            _, w = await asyncio.open_unix_connection(receipts.path)
            w.write((json.dumps({"type": "control", "action": "peer_message_status", "status": "held",
                                 "orig_msg_id": "00000000-0000-4000-8000-000000000000"}) + "\n").encode())
            w.write((json.dumps({"type": "user", "message": {"role": "user", "content": "pong"}}) + "\n").encode())
            await w.drain()
            w.close()
            return await receipts.next(0.3)
        finally:
            receipts.close()

    assert asyncio.run(go()) is None


# ---------- when to ask for one ----------

def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def _transcript(tmp: Path, mode: str) -> str:
    path = tmp / "t.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in [
        {"type": "permission-mode", "permissionMode": "auto", "sessionId": "s"},
        {"type": "user", "permissionMode": mode, "message": {"role": "user", "content": "hi"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}},
    ]) + "\n")
    return str(path)


@pytest.mark.parametrize("user,repo,mode,expected", [
    (None, None, "bypassPermissions", True),  # the default holds: the voice asserts no permission mode
    (None, None, "plan", True),
    (None, None, "auto", False),
    (None, None, "", False),  # unknown: no reply address
    ("accept", None, "bypassPermissions", False),  # the fix
    ("hold", None, "auto", True),
    ("refuse", None, "auto", True),
    ("accept", "refuse", "auto", True),  # the repository may tighten
    ("hold", "accept", "auto", True),  # and not loosen
    (None, "accept", "bypassPermissions", True),  # a repository accept alone sets nothing
    (None, "hold", "auto", True),
])
def test_a_receipt_is_asked_for_exactly_where_claude_code_could_hold(tmp_path, user, repo, mode, expected):
    home, cwd = tmp_path / "home", tmp_path / "repo"
    cwd.mkdir()
    if user:
        _write(home / "settings.json", {"crossSessionInbound": user, "model": "x"})
    if repo:
        _write(cwd / ".claude" / "settings.local.json", {"crossSessionInbound": repo})
    s = Session(id="x", name="x", cwd=str(cwd), home=str(home), transcript=_transcript(tmp_path, mode) if mode else "")
    assert may_hold(s) is expected


def test_managed_settings_win_over_the_users(tmp_path, monkeypatch):
    managed = tmp_path / "managed.json"
    _write(managed, {"crossSessionInbound": "accept"})
    monkeypatch.setattr(cc_module, "MANAGED_SETTINGS", managed)
    home = tmp_path / "home"
    _write(home / "settings.json", {"crossSessionInbound": "hold"})
    assert may_hold(Session(id="x", name="x", cwd=str(tmp_path), home=str(home))) is False


def test_the_permission_mode_is_the_transcripts_last(tmp_path):
    assert permission_mode(_transcript(tmp_path, "bypassPermissions")) == "bypassPermissions"
    assert permission_mode(str(tmp_path / "none.jsonl")) == ""


def test_the_adapter_asks_for_a_receipt_only_from_a_session_that_could_hold(sockdir, tmp_path):
    async def go(mode):
        s = session(sockdir, transcript=_transcript(tmp_path, mode))
        async with FakeInbox(sockdir / "123.sock", answers=["held"]) as inbox:
            ok = await ClaudeCode().send(s, "run the tests")
            await asyncio.sleep(0.1)
            return ok, inbox.lines[-1]

    ok, line = asyncio.run(go("bypassPermissions"))
    assert ok is False and "from" in line
    ok, line = asyncio.run(go("default"))
    assert ok is True and "from" not in line


# ---------- what the user is told ----------

def _send(d, text: str = "Run the tests.") -> dict:
    results = []
    params = SimpleNamespace(arguments={"message": text, "session": "bluebell"},
                             result_callback=lambda r, **_: asyncio.sleep(0, results.append(r)))
    asyncio.run(d.send_to_claude_code(params))
    return results[0]


def _deliver_as(d, monkeypatch, outcome: str):
    async def deliver(session, text):
        if outcome == "held":
            session.held_at = time.time()
        elif outcome == "refused":
            session.refused_at = time.time()
        return outcome == "ok"

    monkeypatch.setattr(d, "deliver", deliver)


def test_the_brain_is_told_it_was_held_and_the_setting_and_the_screens_show_it(d, monkeypatch):
    bluebell = add(d, "cc1", "bluebell")
    d.REGISTRY.active_id = bluebell.id
    _deliver_as(d, monkeypatch, "held")
    open_gates(d, monkeypatch, "tell bluebell to run the tests")
    result = _send(d)
    assert "held the message for approval in its terminal" in result["error"]
    assert "crossSessionInbound to accept" in result["error"] and "sent_to" not in result
    assert d.state.dispatches[-1]["how"] == "failed: held or refused by Claude Code"
    shown = next(s for s in client_for(d).get("/voice/status").json()["sessions"] if s["name"] == "bluebell")
    assert shown["needs"] == sessions.HELD_NEED and shown["blocked_on"] == "held message" and not shown["working"]


def test_the_brain_is_told_it_was_refused(d, monkeypatch):
    bluebell = add(d, "cc1", "bluebell")
    d.REGISTRY.active_id = bluebell.id
    _deliver_as(d, monkeypatch, "refused")
    open_gates(d, monkeypatch, "tell bluebell to run the tests")
    result = _send(d)
    assert "refuses messages from other sessions" in result["error"] and "crossSessionInbound" in result["error"]
    shown = next(s for s in client_for(d).get("/voice/status").json()["sessions"] if s["name"] == "bluebell")
    assert shown["needs"] == sessions.REFUSED_NEED


def test_an_old_hold_does_not_explain_a_new_failure(d, monkeypatch):
    bluebell = add(d, "cc1", "bluebell")
    bluebell.held_at = time.time() - 30
    d.REGISTRY.active_id = bluebell.id
    _deliver_as(d, monkeypatch, "fail")
    open_gates(d, monkeypatch, "tell bluebell to run the tests")
    assert "Not delivered to bluebell. Tell the user it did not reach the session." == _send(d)["error"]


def test_a_held_session_alerts_like_a_prompt_in_its_terminal(d):
    bluebell = add(d, "cc1", "bluebell")
    bluebell.held_at = time.time() - sessions.TERMINAL_NEWS_AFTER_SECS - 1
    item = next(a for a in d._attention() if a["session"] == "bluebell")
    assert item["kind"] == "terminal" and item["body"].startswith("A message from the voice, held for approval")


# ---------- another machine ----------

def test_the_send_result_frame_carries_why_and_an_old_one_still_reads():
    frame = nodelink.decode(nodelink.encode("send.result", req="r", ok=False, held="held"), nodelink.NODE_FRAMES)
    assert frame["held"] == "held"
    assert nodelink.decode(json.dumps({"t": "send.result", "req": "r", "ok": True}), nodelink.NODE_FRAMES)["ok"] is True
    assert nodelink.decode(json.dumps({"t": "send.result", "req": "r", "ok": False, "held": "lost"}), nodelink.NODE_FRAMES) is None


def test_a_node_says_why_its_session_did_not_take_the_send(tmp_path):
    from test_node import _body, run

    sock = Path(tempfile.mkdtemp(prefix="cvn-", dir="/tmp")) / "77.sock"
    _write(tmp_path / "claude-home" / "settings.json", {"crossSessionInbound": "hold"})

    async def scenario(hub, n):
        async with FakeInbox(sock, answers=["held"]):
            await n.register(_body(tmp_path, inbox_socket=str(sock)))
            await hub.send("send", req="r1", id=hub.hub_id("sess-1"), text="run the tests")
            assert await hub.next("send.result", req="r1") == {"t": "send.result", "req": "r1", "ok": False, "held": "held"}

    try:
        run(scenario, tmp_path)
    finally:
        shutil.rmtree(sock.parent, ignore_errors=True)


def test_a_send_to_two_where_one_held_says_both(d, monkeypatch):
    add(d, "a", "alpha/main"), add(d, "b", "beta/main")

    async def deliver(session, text):
        if session.name == "beta/main":
            session.held_at = time.time()
            return False
        return True

    monkeypatch.setattr(d, "deliver", deliver)
    open_gates(d, monkeypatch, "tell alpha and beta to pull dev")
    from test_orchestrator import send
    result = asyncio.run(send(d, "Pull dev."))
    assert result["sent_to"] == ["alpha/main"] and result["failed"] == ["beta/main"]
    assert "beta/main's Claude Code held the message" in result["say"]
