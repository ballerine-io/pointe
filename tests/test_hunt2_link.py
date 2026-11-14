"""Second bug hunt, link/hub/node protocol: each test here is written to FAIL on 8b7dba0 and names the defect."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import harnesses  # noqa: E402
import hub_nodes  # noqa: E402
import nodelink  # noqa: E402
import sessions  # noqa: E402
from sessions import Session  # noqa: E402
from test_hub_nodes import FakeNode, _request, entry, paired, real, run, settle  # noqa: E402,F401  (real is a fixture)
from test_hub_nodes import world  # noqa: E402,F401
import test_node  # noqa: E402
from test_node import FakeHub, _body  # noqa: E402
from test_orchestrator import d, fake_conn  # noqa: E402,F401


# ---------- 3. the node never gets past a transcript line longer than READ_MAX ----------

def test_a_line_longer_than_one_read_does_not_stall_shipping_for_good(tmp_path, monkeypatch):
    monkeypatch.setattr(test_node.node, "READ_MAX", 4096)  # the real cap is 4 MB: a pasted screenshot is bigger
    big = json.dumps({"type": "user", "image": "x" * 5000}) + "\n"  # one line over READ_MAX
    small = json.dumps({"type": "assistant", "message": {"content": "done"}}) + "\n"

    async def scenario(hub, n):
        body = _body(tmp_path)
        Path(body["transcript"]).write_text(big + small)
        await n.register(body)
        await hub.next("transcript.repointed")
        try:
            frame = await hub.next("transcript", timeout=2)
        except asyncio.TimeoutError:
            pytest.fail("nothing shipped: the node re-reads the same READ_MAX bytes every poll and never advances")
        assert frame["next_offset"] == len((big + small).encode())
        assert frame["entries"] == [small]  # the oversize line is skipped, its bytes counted, the rest ships

    test_node.run(scenario, tmp_path)


# ---------- 1. hub restart, then the page connects: the one held prompt is asked twice ----------

def _restored_remote(d, hub, node, request_id="p1"):
    """A remote session as Registry.load brings it back after a hub restart: machine set, its prompt still pending
    (PERSISTED carries permission_id, permission_text, permission_spoken)."""
    sid = nodelink.hub_session_id(node["id"], "s1")
    s = Session(id=sid, name="shop", cwd="/home/u/shop", machine="devbox", harness="claude-code",
                harness_data={"remote_id": "s1", "node_id": node["id"], "files": []},
                permission_id=request_id, permission_text="[permission request] Bash: List files\n{\"command\": \"ls\"}",
                permission_full="Bash: List files\n{\"command\": \"ls\"}", permission_spoken="run: ls", permission_cut=False)
    s.transcript = harnesses.of(s).transcript_path(s)
    d.REGISTRY.add(s)
    d.REGISTRY.active_id = sid
    return s


def test_after_a_hub_restart_the_held_prompt_is_asked_once_when_the_page_connects(real, monkeypatch):
    d, hub, mono = real
    node = paired(hub)
    session = _restored_remote(d, hub, node)
    asked: list[str] = []
    original = d._ask_permission

    async def counting(s):
        asked.append(s.permission_id)
        return await original(s)

    async def no_worker(_s):
        pass

    monkeypatch.setattr(d, "_ask_permission", counting)
    monkeypatch.setattr(d, "_add_worker", no_worker)
    monkeypatch.setattr(harnesses.HOST, "on_call", hub.on_call, raising=False)  # as hub_nodes.install wires it
    d.state.conn, d.state.call_sent = None, None
    pending = {k: v for k, v in _request().items() if k != "id"}

    async def go():
        fake = FakeNode(hub, node)
        welcome = await fake.connect()
        assert welcome["call_up"] is False
        await fake.send_sessions(entry(pending=pending))  # the node still holds it (within its grace window)
        assert asked == []  # no call yet: not put
        await d._on_connect(fake_conn())  # the page reconnects; _notify_call sends `call {up: true}`
        call = await fake.recv("call")
        assert call["up"] is True
        await fake.send("permission.request", **_request())  # node._reoffer: the same request_id again
        await fake.recv("permission.holding")
        await settle()
        await fake.drop()

    run(go())
    assert asked == ["p1"], f"the one held prompt was asked {len(asked)} times: {asked}"


# ---------- 2. a snapshot that lands while the answer is in flight resurrects the prompt ----------

def test_a_snapshot_during_delivery_of_an_answer_does_not_bring_the_prompt_back(real, monkeypatch):
    d, hub, mono = real
    node = paired(hub)
    put: list[str] = []
    original = d._put_permission

    async def recording(session, request_id, *a, **k):
        put.append(request_id)
        return await original(session, request_id, *a, **k)

    async def no_worker(_s):
        pass

    monkeypatch.setattr(d, "_put_permission", recording)
    monkeypatch.setattr(d, "_add_worker", no_worker)
    d.state.conn = fake_conn()
    pending = {k: v for k, v in _request().items() if k != "id"}

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry(pending=pending))
        await fake.send("permission.request", **_request())
        await fake.recv("permission.holding")
        await settle()
        session = d.REGISTRY.sessions[nodelink.hub_session_id(node["id"], "s1")]
        assert put == ["p1"] and session.permission_id == "p1"
        answering = asyncio.create_task(d._apply_answer(session, "p1", "allow", "tapped"))
        answer = await fake.recv("permission.answer")
        assert answer["request_id"] == "p1"
        # The node's liveness tick sends a snapshot (a title changed) before its permission.answered goes out; the
        # prompt is still listed as pending there because the node has not released the hook yet.
        await fake.send_sessions(entry(pending=pending, title="New title"))
        await fake.send("permission.answered", request_id="p1", ok=True)
        assert await answering is True
        await settle()
        await fake.drop()
        return session

    session = run(go())
    assert put == ["p1"], f"the answered prompt was put to the user again: {put}"
    assert session.permission_id is None, "a prompt the node released is pending again on the hub (a ghost card)"


# ---------- 4. a /resume on the node ships an old conversation as live news ----------

def test_a_move_to_a_file_that_already_holds_a_conversation_is_shipped_as_history(tmp_path):
    home = tmp_path / "claude-home"
    (home / "sessions").mkdir(parents=True)
    (home / "projects" / "p").mkdir(parents=True)
    old = "".join(json.dumps({"type": "assistant", "message": {"content": f"turn {i} finished"}}) + "\n" for i in range(50))

    async def scenario(hub, n):
        body = _body(tmp_path)
        Path(body["transcript"]).write_text('{"n": 0}\n')
        await n.register(body)
        await hub.next("transcript")
        resumed = home / "projects" / "p" / "old-id.jsonl"
        resumed.write_text(old)  # /resume: Claude Code moves the session onto a file that already happened
        (home / "sessions" / f"{os.getpid()}.json").write_text(json.dumps({"sessionId": "old-id"}))
        repointed = await hub.next("transcript.repointed")
        assert repointed.get("history") is True, (
            "a repoint onto a file that already holds a conversation is sent as a live move: the hub writes it "
            "straight into the mirror and the follower feeds whatever lands after its reopen as news")

    test_node.run(scenario, tmp_path)
