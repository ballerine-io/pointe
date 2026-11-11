"""One call over sessions of different harnesses: two Claude Code sessions and an OpenCode one, routed, briefed,
reported and approved the way several Claude Code sessions are."""

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harnesses  # noqa: E402
from harnesses.base import finished_tag  # noqa: E402
from sessions import Session  # noqa: E402
from test_opencode import FakeOpenCode, _serve  # noqa: E402
from test_orchestrator import _async, client_for, d, fake_conn  # noqa: E402,F401  (d is a fixture)


def _three(d):
    billing = Session(id="cc1", name="billing/main", cwd="/repos/billing", pid=os.getpid(), transcript="/tmp/none.jsonl")
    docs = Session(id="cc2", name="docs/main", cwd="/repos/docs", pid=os.getpid(), transcript="/tmp/none.jsonl",
                   home="/Users/me/.claude-personal")  # a second Claude account
    shop = Session(id="ses_shop", name="shop", cwd="/repos/shop", transcript="/tmp/shop.jsonl", harness="opencode")
    for s in (billing, docs, shop):
        d.REGISTRY.add(s)
    d.REGISTRY.active_id = billing.id
    return billing, docs, shop


def test_requests_route_across_harnesses_by_name_alias_and_broadcast(d):
    billing, docs, shop = _three(d)
    d.state.last_utterance = "tell shop to run the tests"
    assert asyncio.run(d._route("Run the tests.", "tell shop to run the tests")) == ([shop], "named")
    assert asyncio.run(d._route("Run the tests.", "ask the opencode one to run the tests"))[0] == [shop]
    targets, how = asyncio.run(d._route("Pull main.", "tell everyone to pull main"))
    assert how == "all" and {t.id for t in targets} == {"cc1", "cc2", "ses_shop"}
    assert asyncio.run(d._route("Fix the docs.", "tell docs to fix the docs")) == ([docs], "named")


def test_an_unnamed_request_is_auto_routed_to_the_opencode_session_it_is_about(d, monkeypatch):
    billing, docs, shop = _three(d)
    seen = {}

    async def classify(message, sessions):
        seen["sessions"] = [s.harness for s in sessions]
        return shop

    monkeypatch.setattr(d, "_classify_target", classify)
    assert asyncio.run(d._route("Add a coupon field.", "add a coupon field to checkout")) == ([shop], "auto")
    assert sorted(seen["sessions"]) == ["claude-code", "claude-code", "opencode"]


def test_what_each_session_needs_covers_every_harness_and_names_the_mode(d):
    _three(d)
    needs = d._needs_now()
    assert "orchestrator mode" in needs and all(name in needs for name in ("billing/main", "docs/main", "shop"))


def test_a_report_from_each_harness_is_read_with_its_own_label(d):
    billing, _, shop = _three(d)
    assert d._report_of(f"[billing/main: {finished_tag('claude-code')[1:]} done") == "billing/main"
    assert d._report_of(f"[shop: {finished_tag('opencode')[1:]} done") == "shop"
    assert d._report_of(finished_tag("opencode") + " done") == "opencode"
    from brief import REPORT_SYSTEM, for_agent

    assert "Claude" not in for_agent(REPORT_SYSTEM, harnesses.get("opencode").agent)
    assert for_agent(REPORT_SYSTEM, harnesses.get("claude-code").agent) == REPORT_SYSTEM


def test_two_approvals_from_two_harnesses_at_once(d):
    """The active Claude Code session's prompt is put to the user and answered; OpenCode's, in the background, is only
    announced and waits for its own answer."""
    billing, _, shop = _three(d)
    d.state.conn = fake_conn(bot_started_at=2.0)
    hook = {"session_id": "cc1", "tool_name": "Bash", "tool_input": {"command": "touch x", "description": "make x"}}

    async def scenario():
        held_cc = asyncio.create_task(d.permission_hook(
            SimpleNamespace(json=_async(hook), is_disconnected=_async(False)), "Bearer secret"))
        held_oc = asyncio.create_task(d._harness_permission(shop, "Bash", {"command": "rm -rf dist", "description": "clean"}))
        while not (billing.permission_id and shop.permission_id):
            await asyncio.sleep(0.01)
        assert billing.permission_id != shop.permission_id
        await d._apply_answer(billing, billing.permission_id, "allow", "user said: 'yes'")
        reply = await held_cc
        assert not held_oc.done()  # one answer never answers the other harness's prompt
        await d._apply_answer(shop, shop.permission_id, "deny", "tapped")
        return reply, await held_oc

    reply, oc = asyncio.run(scenario())
    assert reply["hookSpecificOutput"]["decision"]["behavior"] == "allow" and oc == "deny"


def test_a_deleted_opencode_session_is_reaped_with_no_call_up(d, tmp_path, monkeypatch):
    monkeypatch.setattr(harnesses.HOST, "state_dir", tmp_path)
    fake = FakeOpenCode()

    async def scenario():
        runner, oc = await _serve(fake)
        session = Session(id="ses_gone", name="old", cwd=str(tmp_path), transcript=str(tmp_path / "x.jsonl"),
                          harness="opencode")
        d.REGISTRY.add(session)
        monkeypatch.setitem(harnesses._HARNESSES, "opencode", oc)
        assert d.state.conn is None
        await oc.probe(session)  # what the liveness loop does every few seconds
        await d._reap_dead()
        await oc.service.close()
        await runner.cleanup()

    asyncio.run(scenario())
    assert "ses_gone" not in d.REGISTRY.sessions


def test_an_unknown_harness_is_never_driven_as_claude_code():
    unknown = harnesses.get("some-future-agent")
    assert unknown.name == "some-future-agent" and not unknown.attach
    assert unknown.alive(Session(id="x", name="x", cwd="/tmp", harness="some-future-agent")) is False


def test_status_shows_each_sessions_harness_and_what_it_can_do(d):
    _three(d)
    sessions = {s["name"]: s for s in client_for(d).get("/voice/status").json()["sessions"]}
    assert sessions["shop"]["harness"] == "opencode" and sessions["shop"]["capabilities"]["approvals"] is True
    assert sessions["billing/main"]["capabilities"]["attach"] is True


@pytest.mark.parametrize("clash", ["shop", "shop/main"])
def test_the_same_folder_in_two_harnesses_gets_the_harness_in_its_name(d, clash):
    client = client_for(d)
    auth = {"authorization": "Bearer secret"}
    client.post("/voice/register", headers=auth, json={"id": "cc1", "name": clash, "cwd": "/repos/shop", "pid": os.getpid(),
                                                         "transcript": "/tmp/none.jsonl", "name_given": True})
    joined = client.post("/voice/register", headers=auth, json={"id": "ses_shop", "name": "shop", "cwd": "/repos/shop",
                                                                 "transcript": "/tmp/s.jsonl", "harness": "opencode"}).json()
    assert joined["name"] == "shop opencode"


def test_the_probe_takes_opencodes_own_title(tmp_path, monkeypatch):
    monkeypatch.setattr(harnesses.HOST, "state_dir", tmp_path)
    fake = FakeOpenCode()
    session = Session(id="ses_live", name="shop", cwd=str(tmp_path), transcript=str(tmp_path / "x.jsonl"), harness="opencode")

    async def scenario():
        runner, oc = await _serve(fake)
        await oc.probe(session)
        await oc.service.close()
        await runner.cleanup()
        return oc

    oc = asyncio.run(scenario())
    assert oc.title(session) == "Shop checkout" and oc.alive(session)


def test_pointe_join_asks_the_harness_for_its_session_and_registers_it(monkeypatch, tmp_path):
    from harnesses import join, opencode

    monkeypatch.setattr(opencode, "pick_session", lambda cwd, wanted: {
        "id": "ses_abc", "title": "Shop checkout", "location": {"directory": "/repos/shop"}})
    sent = []
    monkeypatch.setattr(join, "daemon", lambda path, body: sent.append((path, body)) or {"name": "shop"})
    monkeypatch.setattr(join.subprocess, "run", lambda *a, **k: None)
    join.main(["opencode"])
    path, body = sent[0]
    assert path == "/voice/register" and body["harness"] == "opencode" and body["id"] == "ses_abc"
    assert body["harness_data"] == {"title": "Shop checkout"} and body["cwd"] == "/repos/shop"
    join.main(["opencode"], leave=True)
    assert sent[-1] == ("/voice/disconnect", {"id": "ses_abc"})
    with pytest.raises(SystemExit):
        join.main(["claude-code"])  # Claude Code joins from inside the session: /pointe:voice


def test_the_brain_is_told_which_agent_runs_each_session(d):
    """From a live run: "tell the codex one to ..." got "I don't know which session is Codex": the needs list the brain
    reads every turn named the sessions but not their agents."""
    _three(d)
    d.REGISTRY.add(Session(id="cx1", name="harbor", cwd="/repos/harbor", transcript="/tmp/harbor.jsonl", harness="codex"))
    needs = d._needs_now()
    assert "- harbor (Codex," in needs and "- shop (OpenCode," in needs and "- billing/main (Claude," in needs


def test_two_approval_requests_at_once_are_asked_in_turn_and_none_is_dropped(d, monkeypatch):
    """From a live run: OpenCode asked for "touch created.txt" and "echo ..." at once; the second handed the first "back
    to the terminal", where no OpenCode prompt was in view, and it never ran."""
    _three(d)
    shop = d.REGISTRY.sessions["ses_shop"]
    put = []

    async def fake_put(session, request_id, tool_name, description, preview):
        put.append(preview)
        session.permission_id = request_id
        return {}

    monkeypatch.setattr(d, "_put_permission", fake_put)

    async def scenario():
        first = asyncio.create_task(d.hold_permission(shop, "Bash", {"command": "touch created.txt"}, deadline_secs=5))
        second = asyncio.create_task(d.hold_permission(shop, "Bash", {"command": "echo hi > where.txt"}, deadline_secs=5))
        await asyncio.sleep(0.3)
        assert len(put) == 1  # one at a time
        shop.permission_answer.set_result("allow")
        assert await first == "allow"
        await asyncio.sleep(0.3)
        assert len(put) == 2  # then the next is asked, not dropped
        shop.permission_answer.set_result("deny")
        assert await second == "deny"

    asyncio.run(scenario())
