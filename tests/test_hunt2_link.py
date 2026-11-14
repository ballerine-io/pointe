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
