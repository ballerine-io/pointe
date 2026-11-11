"""The Codex adapter against a fake Codex app-server daemon: JSON-RPC over a WebSocket on a Unix socket, as Codex 0.160
speaks it, with no real Codex."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harnesses  # noqa: E402
from harnesses.codex import Codex, Connection, command_text, decision, mirror_lines, pick_thread, tool_request  # noqa: E402
from sessions import VOICE_PREFIX, Session  # noqa: E402

THREAD = "00000000-0000-4000-8000-00000000c0de"


def _turn(tid, user, answer, status="completed", command=None):
    items = [{"type": "userMessage", "id": f"{tid}-u", "content": [{"type": "text", "text": user}]}]
    if command:
        items.append({"type": "commandExecution", "id": f"{tid}-c", "command": f"/bin/zsh -lc '{command}'"})
    if answer:
        items.append({"type": "agentMessage", "id": f"{tid}-a", "text": answer, "phase": "final_answer"})
    return {"id": tid, "items": items, "status": status, "startedAt": int(tid[-1]), "completedAt": int(tid[-1]) + 1}


class FakeCodex:
    """The daemon's methods the adapter uses, with state a test can change."""

    def __init__(self, path: Path):
        self.path = path
        self.turns = [_turn("turn1", "earlier question", "earlier answer")]
        self.loaded = {THREAD}
        self.plain_tui = False  # the thread runs inside a plain `codex`: resume fails with "active writer"
        self.calls: list[tuple[str, dict]] = []
        self.replies: list[tuple[object, dict]] = []
        self.clients: list = []
        self.server = None

    async def start(self):
        from websockets.asyncio.server import unix_serve

        self.server = await unix_serve(self.handle, str(self.path))

    async def stop(self):
        for ws in list(self.clients):
            await ws.close()
        self.server.close()
        await self.server.wait_closed()

    async def push(self, method, params, request_id=None):
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            message["id"] = request_id
        for ws in list(self.clients):
            await ws.send(json.dumps(message))

    async def handle(self, ws):
        self.clients.append(ws)
        try:
            async for raw in ws:
                m = json.loads(raw)
                if "method" not in m:
                    self.replies.append((m.get("id"), m.get("result")))
                    continue
                self.calls.append((m["method"], m.get("params") or {}))
                if "id" not in m:
                    continue
                result, error = self.answer(m["method"], m.get("params") or {})
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": m["id"], **({"error": {"message": error}} if error else {"result": result})}))
        finally:
            self.clients.remove(ws)

    def answer(self, method, params):
        thread = {"id": THREAD, "name": "Fix checkout", "preview": "fix it", "cwd": "/repo", "recencyAt": 5,
                  "status": {"type": "idle" if THREAD in self.loaded else "notLoaded"}}
        if method == "initialize":
            return {"userAgent": "fake"}, None
        if method == "thread/resume":
            return ({}, f"thread {THREAD} already has an active writer") if self.plain_tui else ({"thread": thread}, None)
        if method == "thread/turns/list":
            return {"data": self.turns, "nextCursor": None}, None
        if method == "thread/loaded/list":
            return {"data": sorted(self.loaded)}, None
        if method == "thread/list":
            return {"data": [thread]}, None
        if method == "thread/read":
            return {"thread": thread}, None
        if method in ("turn/start", "turn/steer"):
            return {"turn": {"id": "turn9"}}, None
        if method == "thread/fork":
            return {"thread": {"id": "fork1"}}, None
        return {}, None


@pytest.fixture
def fake(tmp_path, monkeypatch):
    import tempfile

    monkeypatch.setattr(harnesses.HOST, "state_dir", tmp_path)
    short = Path(tempfile.mkdtemp(prefix="cx", dir="/tmp"))  # a Unix socket path must stay under ~100 characters
    yield FakeCodex(short / "s.sock")
    import shutil

    shutil.rmtree(short, ignore_errors=True)


def _session(tmp_path):
    return Session(id=THREAD, name="shop", cwd="/repo", pid=0, transcript=str(Codex.mirror_path(THREAD)), harness="codex")


def test_codex_requests_and_turns_become_what_the_daemon_already_reads():
    assert command_text("/bin/zsh -lc 'touch x'") == "touch x"
    assert command_text("/bin/bash -c 'echo '\\''hi'\\'''") == "echo 'hi'"
    assert tool_request("item/commandExecution/requestApproval", {"command": "/bin/zsh -lc 'git push'", "reason": "Push"}) == \
        ("Bash", {"command": "git push", "description": "Push"})
    assert tool_request("item/permissions/requestApproval", {}) is None  # permission grants stay with the TUI
    lines = mirror_lines(_turn("turn2", "run the tests", "Tests pass.", command="pytest -q"))
    assert [line["type"] for line in lines] == ["user", "assistant", "assistant"]
    assert lines[1]["message"]["content"][0]["input"]["command"] == "pytest -q"
    assert lines[2]["message"]["stop_reason"] == "end_turn"


def test_decisions_are_only_what_codex_offered():
    assert decision("allow", ["accept", {"acceptWithExecpolicyAmendment": {}}, "cancel"]) == "accept"
    assert decision("deny", ["accept", "cancel"]) == "cancel"  # no decline offered: cancel
    assert decision("deny", ["accept", "decline", "cancel"]) == "decline"  # decline keeps the turn going


def test_a_finished_turn_reaches_the_feed_once_and_history_does_not(fake, tmp_path):
    fed = []

    async def feed(session, text, respond):
        fed.append((text, respond))

    async def scenario():
        await fake.start()
        cx = Codex(Connection(fake.path))
        task = asyncio.create_task(cx.watch(_session(tmp_path), feed)[0])
        await asyncio.sleep(0.6)
        fake.turns.append(_turn("turn2", f"{VOICE_PREFIX} #ab12] run the tests", "Tests pass, 12 of 12."))
        await fake.push("turn/completed", {"threadId": THREAD, "turn": {"id": "turn2", "status": "completed"}})
        await asyncio.sleep(1.2)
        await fake.push("turn/completed", {"threadId": THREAD, "turn": {"id": "turn2", "status": "completed"}})  # again
        await asyncio.sleep(0.8)
        task.cancel()
        await cx.link.close()
        await fake.stop()

    asyncio.run(scenario())
    reports = [t for t, respond in fed if respond]
    assert len(reports) == 1 and "codex finished its turn" in reports[0] and "12 of 12" in reports[0]
    assert not any("earlier answer" in t for t, _ in fed)  # history is in the record, not news
    assert "earlier answer" in Codex.mirror_path(THREAD).read_text()


def test_a_message_starts_a_turn_when_idle_and_steers_a_running_one(fake, tmp_path):
    async def scenario():
        await fake.start()
        cx = Codex(Connection(fake.path))
        session = _session(tmp_path)
        task = asyncio.create_task(cx.watch(session, lambda *a: asyncio.sleep(0))[0])
        await asyncio.sleep(0.4)
        assert await cx.send(session, "run the tests")
        await fake.push("turn/started", {"threadId": THREAD, "turn": {"id": "turn5"}})
        await asyncio.sleep(0.2)
        assert await cx.send(session, "and the lint")
        task.cancel()
        await cx.link.close()
        await fake.stop()

    asyncio.run(scenario())
    sends = [(m, p) for m, p in fake.calls if m in ("turn/start", "turn/steer")]
    assert sends[0][0] == "turn/start" and sends[0][1]["input"][0]["text"].startswith(VOICE_PREFIX)
    assert sends[1][0] == "turn/steer" and sends[1][1]["expectedTurnId"] == "turn5"


@pytest.mark.parametrize("verdict,expected", [("allow", "accept"), ("deny", "cancel")])
def test_an_approval_goes_through_the_daemons_flow_and_the_answer_goes_back(fake, tmp_path, monkeypatch, verdict, expected):
    asked = []

    async def hold(session, tool_name, tool_input, gone):
        asked.append((tool_name, tool_input["command"]))
        return verdict

    monkeypatch.setattr(harnesses.HOST, "hold_permission", hold)

    async def scenario():
        await fake.start()
        cx = Codex(Connection(fake.path))
        task = asyncio.create_task(cx.watch(_session(tmp_path), lambda *a: asyncio.sleep(0))[0])
        await asyncio.sleep(0.4)
        await fake.push("item/commandExecution/requestApproval", {
            "threadId": THREAD, "command": "/bin/zsh -lc 'touch x'", "availableDecisions": ["accept", "cancel"]}, request_id=0)
        await asyncio.sleep(0.4)
        task.cancel()
        await cx.link.close()
        await fake.stop()

    asyncio.run(scenario())
    assert asked == [("Bash", "touch x")] and fake.replies == [(0, {"decision": expected})]


def test_an_approval_answered_in_the_tui_first_is_let_go(fake, tmp_path, monkeypatch):
    async def hold(session, tool_name, tool_input, gone):
        while not await gone():
            await asyncio.sleep(0.05)
        return "allow"  # what the voice would have said: too late, the TUI answered

    monkeypatch.setattr(harnesses.HOST, "hold_permission", hold)

    async def scenario():
        await fake.start()
        cx = Codex(Connection(fake.path))
        task = asyncio.create_task(cx.watch(_session(tmp_path), lambda *a: asyncio.sleep(0))[0])
        await asyncio.sleep(0.4)
        await fake.push("item/commandExecution/requestApproval", {
            "threadId": THREAD, "command": "rm -rf build", "availableDecisions": ["accept", "cancel"]}, request_id=3)
        await asyncio.sleep(0.2)
        await fake.push("serverRequest/resolved", {"threadId": THREAD, "requestId": 3})
        await asyncio.sleep(0.4)
        task.cancel()
        await cx.link.close()
        await fake.stop()

    asyncio.run(scenario())
    assert fake.replies == []  # nothing sent after the TUI answered


def test_the_link_comes_back_after_the_daemon_restarts_and_reads_what_it_missed(fake, tmp_path):
    fed = []

    async def feed(session, text, respond):
        fed.append(text)

    async def scenario():
        await fake.start()
        cx = Codex(Connection(fake.path))
        task = asyncio.create_task(cx.watch(_session(tmp_path), feed)[0])
        await asyncio.sleep(0.5)
        await fake.stop()  # the daemon updates itself and restarts
        fake.turns.append(_turn("turn3", "deploy it", "Deployed to staging."))  # done while the link was down
        await fake.start()
        await asyncio.sleep(12)  # the next check finds the link down, connects again and reads the turns
        task.cancel()
        await cx.link.close()
        await fake.stop()

    asyncio.run(scenario())
    assert any("Deployed to staging" in t for t in fed)
    assert sum(1 for m, _ in fake.calls if m == "thread/resume") >= 2  # resumed again on the new link


def test_a_plain_codex_tui_cannot_be_joined_and_says_how_to_start_it(fake, tmp_path):
    fake.plain_tui = True
    fed = []

    async def feed(session, text, respond):
        fed.append(text)

    async def scenario():
        await fake.start()
        cx = Codex(Connection(fake.path))
        session = _session(tmp_path)
        await asyncio.wait_for(cx.watch(session, feed)[0], 5)
        alive = cx.alive(session)
        await cx.link.close()
        await fake.stop()
        return alive

    assert asyncio.run(scenario()) is False
    assert any("--remote unix://" in t for t in fed)


def test_joining_picks_the_loaded_thread_here_or_explains_why_not(fake, tmp_path):
    async def scenario():
        await fake.start()
        found = await pick_thread("/repo", None, fake.path)
        fake.loaded = set()  # a plain codex: listed, not loaded by the daemon
        try:
            await pick_thread("/repo", None, fake.path)
            refused = None
        except SystemExit as e:
            refused = str(e)
        await fake.stop()
        return found, refused

    found, refused = asyncio.run(scenario())
    assert found["id"] == THREAD and "--remote unix://" in refused


def test_a_side_question_goes_to_an_ephemeral_read_only_fork(fake, tmp_path):
    async def scenario():
        await fake.start()
        cx = Codex(Connection(fake.path))

        async def answer_later():
            await asyncio.sleep(0.3)
            await fake.push("turn/completed", {"threadId": "fork1", "turn": {"id": "t", "items": [
                {"type": "agentMessage", "text": "The fork says hello."}]}})

        asyncio.create_task(answer_later())
        got = await cx.side_question(_session(tmp_path), "what changed?")
        await cx.link.close()
        await fake.stop()
        return got

    assert asyncio.run(scenario()) == "The fork says hello."
    fork = next(p for m, p in fake.calls if m == "thread/fork")
    assert fork["ephemeral"] is True and fork["sandbox"] == "read-only" and fork["approvalPolicy"] == "never"


def test_a_thread_is_found_however_its_folder_is_spelled(tmp_path):
    """From a live run: Codex kept /tmp/mx/harbor, `pointe join` looked for /private/tmp/mx/harbor, and found nothing."""
    import os as _os

    from harnesses.codex import _aliases_of, _same_folder

    real = tmp_path / "harbor"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    assert _same_folder(str(link), str(real)) and not _same_folder(str(real), str(tmp_path))
    assert _aliases_of("/tmp") == ["/tmp"] if _os.path.realpath("/tmp").startswith("/private") else True
