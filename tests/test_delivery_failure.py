"""A send that cannot be delivered fails cleanly. From a live run: a session registered without an inbox socket made
post_inbox raise ValueError inside the brain's send tool; the call had no result, the vendor refused the history
("tool_use ids were found without tool_result blocks"), and the user heard "I lost my connection to the model"."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import vendors  # noqa: E402
from sessions import Session, post_inbox  # noqa: E402
from test_orchestrator import _brain, _say, add, d, fake_conn, open_gates  # noqa: E402,F401


def _valid(messages: list[dict]) -> bool:
    """Every tool call has its result right after it: what the vendors require."""
    for i, m in enumerate(messages):
        if m["role"] == "assistant" and m.get("calls"):
            nxt = messages[i + 1] if i + 1 < len(messages) else None
            if not nxt or nxt["role"] != "tool" or {r["id"] for r in nxt["results"]} != {c["id"] for c in m["calls"]}:
                return False
    return True


def test_an_inbox_post_without_a_socket_is_a_failed_delivery_not_an_exception():
    s = Session(id="x", name="lantern", cwd="/tmp", inbox_socket=None)
    assert asyncio.run(post_inbox(s, "hello")) is False


def test_a_tool_that_raises_gets_an_error_result_and_the_next_turn_works(monkeypatch):
    async def broken(params):
        raise ValueError("no path and sock were specified")

    tool = SimpleNamespace(name="send_to_claude_code", description="d", properties={}, required=[], handler=broken)
    b, spoken = _brain([], [tool])
    seen = []
    steps = [vendors.Step([{"id": "a", "name": "send_to_claude_code", "args": {"message": "check it"}}]),
             _say("It did not reach lantern.", "t"), _say("Hello again.", "u")]

    async def step(_choice, _system, messages, _tools):
        seen.append([dict(m) for m in messages])
        if not _valid(messages):
            raise RuntimeError("400 tool_use ids were found without tool_result blocks")
        return steps.pop(0)

    monkeypatch.setattr(vendors, "step", step)
    asyncio.run(b.turn("ask lantern to check it"))
    result = next(r for m in b.messages if m["role"] == "tool" for r in m["results"] if r["id"] == "a")
    assert "error" in result["result"] and "not delivered" in result["result"]["error"].lower()
    assert _valid(b.messages)
    asyncio.run(b.turn("hello"))
    assert spoken == ["It did not reach lantern.", "Hello again."]


def test_a_send_to_a_session_with_no_inbox_tells_the_brain_it_was_not_delivered(d, monkeypatch):
    lantern = add(d, "cc1", "lantern")  # no inbox socket, no channel
    d.REGISTRY.active_id = lantern.id
    d.state.conn = fake_conn()
    open_gates(d, monkeypatch, "tell lantern to check the migration")
    results = []
    params = SimpleNamespace(arguments={"message": "Check the migration.", "session": "lantern"},
                             result_callback=lambda r, **_: asyncio.sleep(0, results.append(r)))
    asyncio.run(d.send_to_claude_code(params))
    assert results and "Not delivered to lantern" in results[0]["error"]
    assert d.state.dispatches[-1]["how"] == "failed: delivery error"
