"""The OpenCode adapter against a fake OpenCode v2 service: the same routes and event stream, no real OpenCode."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from aiohttp import web

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harnesses  # noqa: E402
from harnesses.opencode import OpenCode, Service, finished, mirror_lines, tool_request  # noqa: E402
from sessions import VOICE_PREFIX, Session  # noqa: E402
from test_orchestrator import client_for, d  # noqa: E402,F401  (d is a fixture)


def _assistant(mid, text, finish="stop", completed=True, tool=None, created=1):
    content = ([{"type": "tool", "id": "t1", "name": tool, "state": {"input": {"command": "ls"}}, "time": {"created": 1}}]
               if tool else []) + ([{"type": "text", "text": text}] if text else [])
    t = {"created": created, **({"completed": created + 1} if completed else {})}
    return {"id": mid, "type": "assistant", "content": content, "time": t, **({"finish": finish} if completed else {})}


class FakeOpenCode:
    """Routes the adapter uses, with the state a test can change."""

    def __init__(self):
        self.messages = [{"id": "msg_1", "type": "user", "text": "earlier question", "time": {"created": 1}},
                         _assistant("msg_2", "earlier answer", created=2)]
        self.permissions: list[dict] = []
        self.replies: list[tuple[str, dict]] = []
        self.prompts: list[tuple[str, dict]] = []
        self.deleted: list[str] = []
        self.interrupts: list[str] = []
        self.events: asyncio.Queue = asyncio.Queue()
        self.connections = 0
        self.drop_first = False

    async def get_session(self, request):
        sid = request.match_info["sid"]
        if sid != "ses_live" or sid in self.deleted:
            return web.json_response({"error": "not found"}, status=404)
        return web.json_response({"data": {"id": sid, "title": "Shop checkout"}})

    def app(self) -> web.Application:
        app = web.Application()
        r = app.router
        r.add_get("/api/session/{sid}/message", self.list_messages)
        r.add_get("/api/session/{sid}/permission", self.list_permissions)
        r.add_post("/api/session/{sid}/permission/{rid}/reply", self.reply)
        r.add_post("/api/session/{sid}/prompt", self.prompt)
        r.add_post("/api/session/{sid}/fork", self.fork)
        r.add_post("/api/session/{sid}/interrupt", self.interrupt)
        r.add_delete("/api/session/{sid}", self.delete)
        r.add_get("/api/session/{sid}", self.get_session)
        r.add_get("/api/event", self.event_stream)
        return app

    async def list_messages(self, request):
        if request.match_info["sid"] == "ses_fork":
            return web.json_response({"data": [_assistant("msg_f", "The fork says hello.", created=99)], "cursor": {}})
        if request.match_info["sid"] != "ses_live":
            return web.json_response({"error": "not found"}, status=404)
        return web.json_response({"data": list(reversed(self.messages)), "cursor": {}})  # newest first, like the service

    async def list_permissions(self, request):
        return web.json_response({"data": self.permissions})

    async def fork(self, request):
        return web.json_response({"data": {"id": "ses_fork"}})

    async def reply(self, request):
        self.replies.append((request.match_info["rid"], await request.json()))
        return web.json_response({})

    async def prompt(self, request):
        self.prompts.append((request.match_info["sid"], await request.json()))
        return web.json_response({"data": {}})

    async def interrupt(self, request):
        self.interrupts.append(request.match_info["sid"])
        return web.json_response({"data": {"interrupted": True}})

    async def delete(self, request):
        self.deleted.append(request.match_info["sid"])
        return web.json_response({})

    async def event_stream(self, request):
        self.connections += 1
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(b'data: {"type": "server.connected", "data": {}}\n\n')
        if self.drop_first and self.connections == 1:
            return response  # the connection ends at once: the adapter must reconnect and read again
        while True:
            event = await self.events.get()
            await response.write(f"data: {json.dumps(event)}\n\n".encode())


@pytest.fixture
def fake(tmp_path, monkeypatch):
    monkeypatch.setattr(harnesses.HOST, "state_dir", tmp_path)
    monkeypatch.setattr("harnesses.opencode.RESYNC_SECS", 0.2)
    return FakeOpenCode()


async def _serve(fake):
    runner = web.AppRunner(fake.app(), shutdown_timeout=0.2)  # an open event stream must not hold the shutdown
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, OpenCode(Service(url=f"http://127.0.0.1:{port}", password="test-only"))


def _session(tmp_path):
    return Session(id="ses_live", name="shop", cwd=str(tmp_path), pid=0,
                   transcript=str(OpenCode.mirror_path("ses_live")), harness="opencode")


def test_permission_requests_become_the_daemons_tool_requests():
    assert tool_request({"action": "bash", "resources": ["git push --force"], "message": "Push"}) == \
        ("Bash", {"command": "git push --force", "description": "Push"})
    assert tool_request({"action": "edit", "resources": ["/repo/a.py"], "metadata": {"filePath": "/repo/a.py"}})[1][
        "file_path"] == "/repo/a.py"
    assert tool_request({"action": "websearch", "resources": [], "message": "Search"})[0] == "websearch"


def test_messages_mirror_as_claude_code_entries_and_streaming_ones_wait():
    lines = mirror_lines(_assistant("m", "Done: tests pass.", tool="bash"))
    assert lines[0]["message"]["content"][0]["type"] == "tool_use"
    assert lines[1]["message"]["stop_reason"] == "end_turn" and lines[1]["message"]["content"][0]["text"] == "Done: tests pass."
    assert "stop_reason" not in mirror_lines(_assistant("m", "Let me check.", finish="tool-calls"))[0]["message"]
    assert not finished(_assistant("m", "partial", completed=False)) and finished({"type": "user"})


def test_a_finished_turn_reaches_the_feed_once_and_history_does_not(fake, tmp_path):
    fed = []

    async def feed(session, text, respond):
        fed.append((text, respond))

    async def scenario():
        runner, oc = await _serve(fake)
        session = _session(tmp_path)
        task = asyncio.create_task(oc.watch(session, feed)[0])
        await asyncio.sleep(0.6)
        fake.messages.append({"id": "msg_3", "type": "user", "text": f"{VOICE_PREFIX} #ab12] run the tests", "time": {"created": 3}})
        fake.messages.append(_assistant("msg_4", "Tests pass, 12 of 12.", created=4))
        await fake.events.put({"type": "session.idle", "data": {"sessionID": "ses_live"}})
        await asyncio.sleep(1.2)
        task.cancel()
        await oc.service.close()
        await runner.cleanup()

    asyncio.run(scenario())
    reports = [t for t, respond in fed if respond]
    assert len(reports) == 1 and "finished its turn" in reports[0] and "12 of 12" in reports[0]
    assert not any("earlier answer" in t for t, _ in fed)  # history is in the record, not news
    assert "earlier answer" in OpenCode.mirror_path("ses_live").read_text()


@pytest.mark.parametrize("verdict,decision", [("allow", "once"), ("deny", "reject")])
def test_a_permission_goes_through_the_daemons_flow_and_the_answer_goes_back(fake, tmp_path, monkeypatch, verdict, decision):
    asked = []

    async def hold(session, tool_name, tool_input, gone, run_in=None):
        asked.append((tool_name, tool_input["command"]))
        return verdict

    monkeypatch.setattr(harnesses.HOST, "hold_permission", hold)

    async def scenario():
        runner, oc = await _serve(fake)
        task = asyncio.create_task(oc.watch(_session(tmp_path), lambda *a: asyncio.sleep(0))[0])
        await asyncio.sleep(0.4)
        await fake.events.put({"type": "permission.asked", "data": {
            "id": "per_1", "sessionID": "ses_live", "action": "bash", "resources": ["rm -rf build"]}})
        await asyncio.sleep(0.6)
        task.cancel()
        await oc.service.close()
        await runner.cleanup()

    asyncio.run(scenario())
    assert asked == [("Bash", "rm -rf build")]
    assert fake.replies[0][0] == "per_1" and fake.replies[0][1]["decision"] == decision


def test_an_approval_answered_in_opencode_first_is_let_go(fake, tmp_path, monkeypatch):
    async def hold(session, tool_name, tool_input, gone, run_in=None):
        for _ in range(30):
            if await gone():
                return None
            await asyncio.sleep(0.05)
        return "allow"

    monkeypatch.setattr(harnesses.HOST, "hold_permission", hold)

    async def scenario():
        runner, oc = await _serve(fake)
        task = asyncio.create_task(oc.watch(_session(tmp_path), lambda *a: asyncio.sleep(0))[0])
        await asyncio.sleep(0.4)
        await fake.events.put({"type": "permission.asked", "data": {"id": "per_2", "sessionID": "ses_live", "action": "bash",
                                                                    "resources": ["ls"]}})
        await asyncio.sleep(0.2)
        await fake.events.put({"type": "permission.replied", "data": {"sessionID": "ses_live", "requestID": "per_2", "reply": "once"}})
        await asyncio.sleep(1.0)
        task.cancel()
        await oc.service.close()
        await runner.cleanup()

    asyncio.run(scenario())
    assert fake.replies == []


def test_the_stream_reconnects_and_reads_again_what_it_missed(fake, tmp_path):
    fake.drop_first = True
    fed = []

    async def feed(session, text, respond):
        fed.append(text)

    async def scenario():
        runner, oc = await _serve(fake)
        task = asyncio.create_task(oc.watch(_session(tmp_path), feed)[0])
        await asyncio.sleep(0.3)
        fake.messages.append(_assistant("msg_5", "Deployed to staging.", created=5))  # while the stream was down
        await asyncio.sleep(2.0)
        task.cancel()
        await oc.service.close()
        await runner.cleanup()

    asyncio.run(scenario())
    assert fake.connections >= 2
    assert any("Deployed to staging" in t for t in fed)


def test_a_request_is_sent_as_a_steer_with_the_voice_tag(fake, tmp_path):
    async def scenario():
        runner, oc = await _serve(fake)
        ok = await oc.send(_session(tmp_path), "run the tests")
        await oc.service.close()
        await runner.cleanup()
        return ok

    assert asyncio.run(scenario()) is True
    sid, body = fake.prompts[0]
    assert sid == "ses_live" and body["delivery"] == "steer" and body["text"].startswith(VOICE_PREFIX)


def test_a_stop_interrupts_the_sessions_execution(fake, tmp_path):
    async def scenario():
        runner, oc = await _serve(fake)
        ok = await oc.interrupt(_session(tmp_path))
        await oc.service.close()
        await runner.cleanup()
        return ok

    assert asyncio.run(scenario()) is True
    assert fake.interrupts == ["ses_live"]


def test_a_side_question_is_answered_by_a_fork_that_is_then_deleted(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    async def scenario():
        runner, oc = await _serve(fake)
        answer = await oc.side_question(_session(tmp_path), "who owns the rollout?")
        await oc.service.close()
        await runner.cleanup()
        return answer

    assert asyncio.run(scenario()) == "The fork says hello."
    assert fake.prompts[0][0] == "ses_fork" and fake.deleted == ["ses_fork"]


_real_sleep = asyncio.sleep


async def _fast_sleep(seconds):
    await _real_sleep(0)


def test_a_deleted_opencode_session_drops_off(fake, tmp_path):
    session = Session(id="ses_gone", name="old", cwd=str(tmp_path), pid=0, transcript=str(tmp_path / "x.jsonl"),
                      harness="opencode")

    async def scenario():
        runner, oc = await _serve(fake)
        await oc.sync(session)
        await oc.service.close()
        await runner.cleanup()
        return oc.alive(session)

    assert asyncio.run(scenario()) is False


def test_the_daemon_registers_an_opencode_session_and_shows_its_harness(d):
    client = client_for(d)
    auth = {"authorization": "Bearer secret"}
    body = {"id": "ses_abc", "name": "shop", "cwd": "/tmp", "pid": 0, "transcript": "/tmp/none.jsonl", "harness": "opencode"}
    assert client.post("/voice/register", headers=auth, json=body).status_code == 200
    assert d.REGISTRY.sessions["ses_abc"].harness == "opencode" and not d.REGISTRY.sessions["ses_abc"].joining
    assert client.get("/voice/status").json()["sessions"][0]["harness"] == "opencode"
    assert client.post("/voice/register", headers=auth, json={**body, "id": "x1", "harness": "nope"}).status_code == 400


def test_a_send_to_an_opencode_session_goes_through_its_harness(d, monkeypatch):
    sent = []

    async def send(self, session, text):
        sent.append((session.id, text))
        return True

    monkeypatch.setattr(OpenCode, "send", send)
    s = Session(id="ses_abc", name="shop", cwd="/tmp", pid=0, transcript="/tmp/none.jsonl", harness="opencode")
    assert asyncio.run(d.deliver(s, "run the tests")) is True and sent == [("ses_abc", "run the tests")]


def test_a_v2_shell_request_is_read_out_like_a_bash_one():
    """From a live run: OpenCode v2 names its shell tool "shell", and the adapter only knew "bash", so a plain command
    could not be read out and needed a tap."""
    from guards import readable_request
    from harnesses.opencode import tool_request

    tool, tool_input = tool_request({"action": "shell", "resources": ["touch created.txt"],
                                     "metadata": {"command": "touch created.txt"}})
    assert tool == "Bash" and readable_request(tool, tool_input, "/repo") == "run: touch created.txt"
