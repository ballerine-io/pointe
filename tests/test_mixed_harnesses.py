"""One call over sessions of different harnesses: two Claude Code sessions and an OpenCode one, routed, briefed,
reported and approved the way several Claude Code sessions are."""

import asyncio
import json
import time
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harnesses  # noqa: E402
import nodelink  # noqa: E402
from harnesses.base import finished_tag  # noqa: E402
from sessions import Session  # noqa: E402
from test_opencode import FakeOpenCode, _serve  # noqa: E402
from test_orchestrator import _async, add, client_for, d, fake_conn, send  # noqa: E402,F401  (d is a fixture)


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

    async def classify(message, sessions, tie=False):
        seen["sessions"] = [s.harness for s in sessions]
        return shop

    monkeypatch.setattr(d, "_classify_target", classify)
    assert asyncio.run(d._route("Add a coupon field.", "add a coupon field to checkout")) == ([shop], "auto")
    assert sorted(seen["sessions"]) == ["claude-code", "claude-code", "opencode"]


def test_ask_claude_code_never_goes_to_another_harness_in_the_thread(d, monkeypatch):
    """From the harness matrix on 1.13.2: with lighthouse the only Claude Code session and the conversation last with
    harbor (Codex), "Ask Claude Code to check the release codename in the FACT file again" went to harbor: the router's
    classifier found it unclear and the thread decided. "Claude Code" is no session's name, but it does say which agent."""
    lighthouse = add(d, "cc1", "lighthouse/main")
    harbor = Session(id="cx1", name="harbor", cwd="/repos/harbor", transcript="/tmp/harbor.jsonl", harness="codex")
    orchard = Session(id="ses_o", name="orchard", cwd="/repos/orchard", transcript="/tmp/orchard.jsonl", harness="opencode")
    d.REGISTRY.add(harbor), d.REGISTRY.add(orchard)
    d.REGISTRY.active_id, d.state.thread = harbor.id, (harbor.id, time.time())

    async def unclear(message, sessions):
        return None

    monkeypatch.setattr(d, "_classify_target", unclear)
    said = "Ask Claude Code to check the release codename in the FACT file again."
    assert asyncio.run(d._route("Check the release codename again.", said)) == ([lighthouse], "harness")

    async def lighthouse_it_is(message, sessions):  # the next run: the classifier saw it, and the thread made it "which?"
        return lighthouse

    monkeypatch.setattr(d, "_classify_target", lighthouse_it_is)
    assert asyncio.run(d._route("Check the release codename again.", said)) == ([lighthouse], "harness")
    monkeypatch.setattr(d, "_classify_target", unclear)
    assert asyncio.run(d._route("Check it again.", "ask it to check again"))[0] == [harbor]  # no agent named: the thread


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

    async def fake_put(session, request_id, tool_name, description, preview, run_in=None):
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


# ---------- harnesses.of: one place picks a session's adapter (docs/design/multi-machine.md) ----------

class FakeRemote(harnesses.Harness):
    """Stands in for harnesses/remote.py's RemoteHarness until it lands."""

    def __init__(self, session, inner):
        self.inner, self.label, self.agent = inner, "remote-label", inner.agent
        self.watched = []

    def alive(self, session):
        return True  # from node state, never a pid

    def transcript_path(self, session):
        return "/mirror/s1.0.jsonl"

    def watch(self, session, feed):
        self.watched.append(session.id)
        return []


@pytest.fixture
def remote(monkeypatch):
    made = []

    def wrap(session, inner):
        made.append(FakeRemote(session, inner))
        return made[-1]

    harnesses.set_remote(wrap)
    yield made
    harnesses.set_remote(None)


def _on_devbox(harness="claude-code"):
    return Session(id="n3f2a1-s1", name="shop", cwd="/srv/shop", pid=0, transcript="", harness=harness, machine="devbox")


def test_a_local_session_gets_its_harness_adapter_unchanged(remote):
    for name in ("claude-code", "opencode", "codex"):
        assert harnesses.of(Session(id="x", name="x", cwd="/tmp", harness=name)) is harnesses.get(name)
    assert not remote


def test_a_session_on_another_machine_goes_through_the_remote_adapter(remote):
    adapter = harnesses.of(_on_devbox("opencode"))
    assert adapter is remote[-1] and adapter.inner is harnesses.get("opencode")


def test_a_remote_session_with_no_remote_adapter_is_never_driven_locally():
    """Before harnesses/remote.py is wired, a session with a machine must not be typed into this machine's agent."""
    s = _on_devbox()
    assert harnesses.of(s) is not harnesses.get("claude-code")
    assert harnesses.of(s).alive(s) is False
    assert asyncio.run(harnesses.of(s).send(s, "pull")) is False
    assert (harnesses.of(s).agent, harnesses.of(s).label) == ("Claude", "claude-code")  # still named as its agent


def test_the_sessions_module_sites_go_through_of(remote):
    import sessions

    s = _on_devbox("opencode")
    assert s.alive()  # the local Claude Code check would be a pid check, and pid 0 is never alive
    assert sessions.current_transcript(s) == "/mirror/s1.0.jsonl"
    assert ("remote-label", 0) in sessions._aliases(s)


def test_the_session_worker_watches_through_of(d, remote, monkeypatch):
    async def started(self):
        pass

    monkeypatch.setattr(d.ClaudeSessionWorker.__mro__[1], "start", started)
    s = _on_devbox()
    asyncio.run(d.ClaudeSessionWorker(s, d.feed).start())
    assert remote[-1].watched == [s.id]


def test_no_session_picks_its_adapter_by_name_alone():
    """Every adapter call for a session goes through harnesses.of, or a remote session would be driven as local."""
    import re

    root = Path(__file__).resolve().parents[1]
    modules = [*root.glob("pointe/*.py"), *root.glob("pointe/harnesses/*.py")]
    assert len(modules) > 20
    for module in modules:
        assert not re.search(r"harnesses\.get\([^)]*\.harness\)", module.read_text()), module.name


# ---------- sessions on other machines: the daemon side (docs/design/multi-machine.md, Track C) ----------

from test_orchestrator import Params, open_gates, record_dispatch, spoken  # noqa: E402


class FakeNode(harnesses.Harness):
    """harnesses/remote.py's RemoteHarness as the design specifies it, until it lands: alive and online from node state,
    send and verdicts over the link, label and agent from the inner adapter. It does NOT turn side questions off, so the
    daemon's own refusal is what the tests see."""

    def __init__(self, link, inner):
        self.link, self.inner = link, inner
        self.name, self.label, self.agent = inner.name, inner.label, inner.agent
        self.side_questions = inner.side_questions

    def capabilities(self):
        return self.inner.capabilities()

    def alive(self, session):
        return session.id not in self.link.left

    def transcript_path(self, session):
        return session.transcript

    async def send(self, session, text):
        self.link.sent.append((session.id, text))
        return True

    async def answer(self, session, request_id, verdict, how, spoken):
        self.link.answers.append((session.id, request_id, verdict, how, spoken))
        return self.link.ok

    async def leave(self, session):
        self.link.left.add(session.id)


@pytest.fixture
def node(d, monkeypatch, tmp_path):
    import sessions

    link = SimpleNamespace(sent=[], answers=[], left=set(), ok=True, calls=[])
    harnesses.set_remote(lambda session, inner: FakeNode(link, inner))
    table = {"devbox": sessions.Machine(name="devbox", id="n3f2a1aa", os="linux", online=True, rtt_ms=23, key_fp="3f2a9c"),
             "laptop": sessions.Machine(name="laptop", id="n9c0deff", os="macos", online=True, rtt_ms=40)}
    monkeypatch.setattr(sessions, "MACHINES", table)
    (tmp_path / "config.json").write_text(json.dumps({"machine": "studio"}))
    monkeypatch.setattr(harnesses.HOST, "on_call", lambda call: link.calls.append(call), raising=False)
    monkeypatch.setattr(harnesses.HOST, "invite", None, raising=False)
    link.machines = table
    yield link
    harnesses.set_remote(None)


def _join(d, machine, sid, name, **entry):
    node_id = {"devbox": "n3f2a1aa", "laptop": "n9c0deff"}[machine]
    body = {"id": sid, "name": name, "cwd": f"/srv/{name}", "pid": 4242, "harness": "claude-code", **entry}
    return asyncio.run(d.register_remote(node_id, machine, body))


def test_a_remote_session_joins_with_its_machine_and_a_hub_side_id(d, node):
    shop = add(d, "cc1", "shop", "/repos/shop")
    api = _join(d, "devbox", "abc", "api", files=["main.py", "api/routes.py"])
    assert api.id == "n3f2a1-abc" and api.machine == "devbox" and api.harness_data["remote_id"] == "abc"
    assert d.REGISTRY.sessions[api.id] is api and shop.machine == ""
    status = client_for(d).get("/voice/status").json()
    rows = {s["name"]: s for s in status["sessions"]}
    assert rows["api"]["machine"] == "devbox" and rows["api"]["online"] is True
    assert rows["shop"]["machine"] == "studio" and rows["shop"]["online"] is True
    assert rows["api"]["capabilities"]["side_questions"] is False  # no forked copy on the node
    here, devbox, laptop = status["machines"]
    assert here == {"id": "hub", "name": "studio", "here": True, "os": here["os"], "online": True, "sessions": 1, "need": 0}
    assert devbox["name"] == "devbox" and devbox["here"] is False and devbox["sessions"] == 1 and devbox["rtt_ms"] == 23
    assert devbox["os"] == "linux" and devbox["key_fp"] == "3f2a9c" and devbox["online"] is True
    assert laptop["sessions"] == 0
    assert status["invite"] is None


def test_with_one_machine_the_status_has_one_machine_entry(d, node):
    node.machines.clear()
    add(d, "cc1", "shop", "/repos/shop")
    status = client_for(d).get("/voice/status").json()
    assert [m["name"] for m in status["machines"]] == ["studio"] and status["machines"][0]["here"] is True


def test_a_name_another_machine_uses_gets_the_machine_suffix(d, node):
    add(d, "cc1", "shop", "/repos/shop")
    assert _join(d, "devbox", "s1", "shop").name == "shop devbox"
    client = client_for(d)
    remote = _join(d, "laptop", "w1", "web")
    joined = client.post("/voice/register", headers={"authorization": "Bearer secret"},
                         json={"id": "cc2", "name": "web", "cwd": "/repos/web", "pid": os.getpid(),
                               "transcript": "/tmp/none.jsonl", "name_given": True}).json()
    assert joined["name"] == "web"  # a session on this Mac keeps the plain name; this Mac's name is never a suffix
    assert remote.name == "web laptop"


def test_a_session_is_never_named_after_a_machine(d, node):
    joined = client_for(d).post("/voice/register", headers={"authorization": "Bearer secret"},
                                json={"id": "cc1", "cwd": "/repos/devbox", "pid": os.getpid(),
                                      "transcript": "/tmp/none.jsonl"}).json()
    assert joined["name"] != "devbox"
    renamed = client_for(d).post("/voice/rename", json={"name": joined["name"], "new_name": "laptop"})
    assert renamed.status_code == 409 and "machine" in renamed.json()["detail"]


def test_the_invite_goes_only_to_the_page_on_this_mac_and_the_phone_key(d, node, monkeypatch):
    import remote

    invite = {"code": "K7PQ-2MXD", "expires_in": 540}
    monkeypatch.setattr(harnesses.HOST, "invite", lambda: invite)
    assert client_for(d).get("/voice/status").json()["invite"] == invite
    tls_page = SimpleNamespace(scope={"server": ("studio", remote.TLS_PORT), "state": {}})
    phone_app = SimpleNamespace(scope={"server": ("studio", remote.TLS_PORT), "state": {"pointe_phone": True}})
    assert d._shows_invite(tls_page) is False and d._shows_invite(phone_app) is True


def test_the_page_over_tls_is_told_it_cannot_invite_and_hides_the_button(d, node, monkeypatch):
    import remote

    monkeypatch.setattr(harnesses.HOST, "invite", lambda: None, raising=False)
    assert client_for(d).get("/voice/status").json()["can_invite"] is True
    tls_page = SimpleNamespace(scope={"server": ("studio", remote.TLS_PORT), "state": {}})
    phone_app = SimpleNamespace(scope={"server": ("studio", remote.TLS_PORT), "state": {"pointe_phone": True}})
    assert d._can_invite(tls_page) is False and d._can_invite(phone_app) is True
    monkeypatch.delattr(harnesses.HOST, "invite")
    assert d._can_invite(phone_app) is False  # no node link: nothing to invite to
    page = (Path(__file__).resolve().parents[1] / "pointe" / "ui.html").read_text()
    assert "$('mach-invitebtn').hidden = live || !canInvite;" in page and "s.can_invite !== false" in page


def test_list_sessions_tells_the_brain_each_sessions_machine_and_whether_it_is_online(d, node):
    add(d, "cc1", "shop", "/repos/shop")
    _join(d, "devbox", "abc", "api")
    node.machines["devbox"].online = False
    p = Params()
    asyncio.run(d.list_sessions(p))
    rows = {s["name"]: s for s in p.results[0]["sessions"]}
    assert rows["api"]["machine"] == "devbox" and rows["api"]["online"] is False
    assert rows["shop"]["machine"] == "studio" and rows["shop"]["online"] is True
    tool = next(t for t in d.TOOLS.standard_tools if t.name == "list_sessions")
    assert "machine" in tool.description and "everywhere" in tool.description


def test_the_brain_hears_of_machines_only_when_sessions_are_on_more_than_one(d, node):
    add(d, "cc1", "shop", "/repos/shop")
    assert "Machines:" not in d._brain_context() and "(Claude, not working)" in d._needs_now()
    _join(d, "devbox", "abc", "api")
    _join(d, "laptop", "w1", "web")
    node.machines["laptop"].online, node.machines["laptop"].since = False, 1731590520.0
    context = d._brain_context()
    line = next(x for x in context.splitlines() if x.startswith("Machines:"))
    assert "studio (this Mac, 1 session)" in line and "devbox (Linux, 1 session, 23 ms)" in line
    assert "laptop (offline since " in line and ", 1 session)" in line


def test_what_each_session_needs_names_its_machine_groups_by_machine_and_marks_offline(d, node):
    add(d, "cc1", "shop", "/repos/shop")
    api = _join(d, "devbox", "abc", "api")
    api.busy = True
    _join(d, "laptop", "w1", "web")
    node.machines["laptop"].online = False
    needs = d._needs_now()
    assert "- api (Claude on devbox, working)" in needs and "- shop (Claude on studio, not working)" in needs
    assert "OFFLINE: cannot be sent to" in needs.split("- web")[1] and "OFFLINE" not in needs.split("- web")[0]
    lines = needs.splitlines()
    assert lines.index(next(x for x in lines if x.startswith("On devbox"))) == lines.index("- api (Claude on devbox, working). "
                                                                                             "No notes on it yet. Waits on the user for: nothing.") - 1


def test_the_routing_classifier_sees_the_machine_next_to_the_folder(d, node, monkeypatch):
    shop = add(d, "cc1", "shop", "/repos/shop")
    api = _join(d, "devbox", "abc", "api")
    prompts = []

    async def text(model, prompt, *a, **k):
        prompts.append(prompt)
        return "api"

    monkeypatch.setattr(d.vendors, "text", text)
    assert asyncio.run(d._classify_target("Restart the VM service.", [shop, api])) is api
    assert "folder /srv/api, on devbox" in prompts[0] and "folder /repos/shop, on studio" in prompts[0]


def test_a_machine_suffix_is_spoken_as_where_it_runs(d, node):
    add(d, "cc1", "shop", "/repos/shop")
    _join(d, "devbox", "s1", "shop/main")
    assert d._spoken_names("shop/main devbox finished") == "shop on devbox finished"
    _join(d, "devbox", "a1", "api")
    assert d._spoken_names("api finished") == "api finished"  # said only when it tells sessions apart


def test_a_remote_sessions_file_names_come_from_its_node(d, node, monkeypatch):
    api = _join(d, "devbox", "abc", "api", files=["billing.py", "README.md"])

    def no_git(*a, **k):
        raise AssertionError("git ran on the hub for a session on another machine")

    monkeypatch.setattr(d, "_git_files", no_git)
    assert d._tracked_files(api) == "billing.py README.md"


def test_a_send_to_an_offline_machine_is_refused_with_a_clear_line(d, node, monkeypatch):
    add(d, "cc1", "shop", "/repos/shop")
    _join(d, "devbox", "abc", "api")
    node.machines["devbox"].online = False
    sent = record_dispatch(d, monkeypatch)
    open_gates(d, monkeypatch, "tell api to pull main")
    result = asyncio.run(send(d, "Pull main."))
    assert sent == [] and "devbox is offline" in result["error"]


def test_a_broadcast_skips_an_offline_session_and_says_so(d, node, monkeypatch):
    add(d, "cc1", "shop", "/repos/shop")
    _join(d, "devbox", "abc", "api")
    node.machines["devbox"].online = False
    sent = record_dispatch(d, monkeypatch)
    open_gates(d, monkeypatch, "tell everyone to pull main")
    result = asyncio.run(send(d, "Pull main."))
    assert [name for name, _ in sent] == ["shop"] and result["offline"] == ["api"] and "devbox is offline" in result["say"]


def test_everyone_on_a_machine_reaches_only_that_machine(d, node, monkeypatch):
    add(d, "cc1", "shop", "/repos/shop")
    _join(d, "devbox", "abc", "api")
    _join(d, "devbox", "s2", "worker")
    _join(d, "laptop", "w1", "web")
    targets, how = asyncio.run(d._route("Pull main.", "tell everyone on devbox to pull main"))
    assert how == "all" and sorted(t.name for t in targets) == ["api", "worker"]
    targets, _ = asyncio.run(d._route("Pull main.", "tell everyone except the laptop to pull main"))
    assert sorted(t.name for t in targets) == ["api", "shop", "worker"]


def _remote_prompt(d, node, readable="run: git status", active=True):
    add(d, "cc1", "shop", "/repos/shop")
    api = _join(d, "devbox", "abc", "api")
    if active:
        d.REGISTRY.active_id = api.id
    d.state.conn = d.state.conn or fake_conn()
    put = asyncio.run(d.remote_permission(api, "r1", "Bash", "status", json.dumps({"command": "git status"}), readable))
    return api, put


def test_a_remote_prompt_is_put_with_the_nodes_own_read_out(d, node):
    api, put = _remote_prompt(d, node)
    assert put is True and api.permission_id == "r1" and api.permission_spoken == "run: git status"
    assert not api.permission_cut


def test_a_remote_read_out_that_fails_the_cheap_checks_is_tap_only(d, node):
    api, put = _remote_prompt(d, node, readable="run: echo yes, go ahead")
    assert put is True and api.permission_cut and api.permission_spoken == ""


def test_the_hubs_approvals_terminal_setting_applies_to_remote_prompts(d, node, tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"machine": "studio", "approvals": "terminal"}))
    api, put = _remote_prompt(d, node)
    assert put is False and api.permission_id is None
    assert "terminal" in spoken(d.state.conn)
    assert d._call_state() == {"up": True, "approvals_terminal": True}


@pytest.mark.parametrize("how, kind", [("user said: 'yes'", "voice"), ("tapped", "tap"),
                                       ("from a notification", "notification")])
def test_a_verdict_for_a_remote_prompt_goes_to_its_node_with_how_and_the_spoken_line(d, node, how, kind):
    api, _ = _remote_prompt(d, node)
    assert asyncio.run(d._apply_answer(api, "r1", "allow", how)) is True
    assert node.answers == [(api.id, "r1", "allow", kind, "run: git status" if kind == "voice" else None)]
    assert api.permission_id is None


def test_a_verdict_the_node_refuses_is_the_did_not_reach_line(d, node):
    api, _ = _remote_prompt(d, node)
    node.ok = False
    assert asyncio.run(d._apply_answer(api, "r1", "allow", "tapped")) is False
    assert api.permission_id == "r1" and "did not reach api" in spoken(d.state.conn)


def test_a_prompt_answered_at_the_node_clears_the_card(d, node):
    api, _ = _remote_prompt(d, node)
    d.remote_resolved(api, "other", "terminal")
    assert api.permission_id == "r1"  # not this one
    d.remote_resolved(api, "r1", "terminal")
    assert api.permission_id is None


def test_a_snapshot_without_the_prompt_clears_it_and_one_with_it_puts_it_once(d, node):
    api, _ = _remote_prompt(d, node)
    _join(d, "devbox", "abc", "api", pending=None)
    assert api.permission_id is None
    pending = {"request_id": "r2", "tool": "Bash", "description": "status", "preview": '{"command": "git status"}',
               "readable": "run: git status"}
    _join(d, "devbox", "abc", "api", pending=pending)
    _join(d, "devbox", "abc", "api", pending=pending)  # the same prompt again: not put twice
    assert api.permission_id == "r2" and spoken(d.state.conn).count("[permission request] Bash") <= 1


def test_an_offline_sessions_prompt_is_not_offered_and_a_tap_or_yes_is_refused(d, node):
    api, _ = _remote_prompt(d, node)
    node.machines["devbox"].online = False
    d.state.conn = fake_conn()
    asyncio.run(d._ask_permission(api))
    assert d.state.conn.injector.fed == []
    row = next(s for s in client_for(d).get("/voice/status").json()["sessions"] if s["name"] == "api")
    assert row["voice_can_approve"] is False and row["online"] is False and row["request_id"] == "r1"
    tap = client_for(d).post("/voice/approve", json={"session": "api", "request_id": "r1", "decision": "allow"})
    assert tap.status_code == 409 and "offline" in tap.json()["detail"]
    d.state.last_utterance = "yes"
    asyncio.run(d._answer_permission("yes"))
    assert node.answers == [] and "offline" in spoken(d.state.conn)


def test_a_machine_dropping_mid_approval_is_said_once(d, node):
    api, _ = _remote_prompt(d, node)
    asyncio.run(d._watch_machines())
    d.state.conn = fake_conn()
    node.machines["devbox"].online = False
    asyncio.run(d._watch_machines())
    asyncio.run(d._watch_machines())
    said = spoken(d.state.conn)
    assert said.count("devbox dropped") == 1 and "api" in said and "terminal" in said
    # the node still holds it for its grace window: not "went back to its terminal" yet (a re-offer is read out again)
    assert "went back" not in said and f"{nodelink.HOLD_GRACE_SECS:.0f} seconds" in said


def test_the_node_link_hears_when_the_call_or_the_approvals_setting_changes(d, node, tmp_path):
    d._notify_call()
    d.state.conn = fake_conn()
    d._notify_call()
    d._notify_call()
    (tmp_path / "config.json").write_text(json.dumps({"approvals": "terminal"}))
    d._notify_call()
    assert node.calls == [{"up": False, "approvals_terminal": False}, {"up": True, "approvals_terminal": False},
                          {"up": True, "approvals_terminal": True}]


def test_a_by_the_way_question_about_a_remote_session_is_answered_from_its_record(d, node, monkeypatch):
    api = _join(d, "devbox", "abc", "api")
    monkeypatch.setattr(d, "COPY_SESSIONS", True)
    monkeypatch.setattr(__import__("harnesses.claude_code").claude_code.ClaudeCode, "side_questions", True)  # no claude binary needed
    assert harnesses.of(api).side_questions  # the inner adapter could fork; the node cannot

    async def from_record(target, question):
        return {"session": target.name, "answer": "from the mirror"}

    async def no_copy(*a):
        raise AssertionError("a copy was forked for a session on another machine")

    monkeypatch.setattr(d, "_from_record", from_record)
    monkeypatch.setattr(d, "_ask_copy", no_copy)
    p = Params(question="why did it pick Redis?", session="api")
    asyncio.run(d.ask_about_session(p))
    assert p.results[0]["answer"] == "from the mirror"


def test_challenge_evidence_skips_remote_diffs_and_says_so(d, node, monkeypatch):
    api = _join(d, "devbox", "abc", "api")

    def no_diffs(session):
        raise AssertionError("diffs were read on the hub for a session on another machine")

    monkeypatch.setattr(d, "_challenge_diffs", no_diffs)
    lines = asyncio.run(d._challenge_evidence([api]))
    assert any("api" in x and "devbox" in x and "diff" in x for x in lines)


@pytest.mark.parametrize("machine", ["", "devbox"])
def test_show_while_it_says_skips_a_remote_sessions_report(d, node, monkeypatch, machine):
    s = _join(d, "devbox", "abc", "api") if machine else add(d, "cc1", "api", "/repos/api")
    d.REGISTRY.active_id = s.id
    d.state.conn = fake_conn()
    s.artifacts = [{"kind": "edit", "path": f"{s.cwd}/x.py"}]
    offered = []
    monkeypatch.setattr(d.SHOWS, "offer", lambda *a: offered.append(a))

    async def digest(session, text):
        return {"say": "Done: x.py fixed.", "final": "Done: x.py fixed.", "line": "fixed x.py", "excerpt": "fixed"}

    monkeypatch.setattr(d, "_digest_turn", digest)
    asyncio.run(d.feed(s, f"{finished_tag('claude-code')} Done: x.py fixed.", True))
    assert bool(offered) is (not machine)


def test_a_switch_across_machines_names_the_machine(d, node):
    shop = add(d, "cc1", "shop", "/repos/shop")
    api = _join(d, "devbox", "abc", "api")
    worker = _join(d, "devbox", "w2", "worker")
    d.REGISTRY.active_id = shop.id
    note = asyncio.run(d.activate(api))
    assert "devbox" in note.get("say", "")
    assert "say" not in asyncio.run(d.activate(worker))  # same machine: nothing to add


def test_go_to_a_machine_with_two_sessions_asks_which_on_it(d, node):
    add(d, "cc1", "shop", "/repos/shop")
    _join(d, "devbox", "abc", "api")
    _join(d, "devbox", "w2", "worker")
    now = time.time()
    d.state.last_utterance, d.state.last_user_speech_at, d.state.last_switch_at = "go to devbox", now, now - 30
    p = Params(name="devbox")
    asyncio.run(d.switch_session(p))
    assert "which on devbox: api or worker" in p.results[0]["error"]
    d.state.last_utterance, d.state.last_switch_at = "go to the laptop one", now - 30
    _join(d, "laptop", "w1", "web")
    p = Params(name="laptop")
    asyncio.run(d.switch_session(p))
    assert p.results[0]["active"] == "web"


def test_taking_a_remote_session_off_the_voice_tells_its_node(d, node):
    api = _join(d, "devbox", "abc", "api")
    asyncio.run(d.disconnect(api, "by voice"))
    assert api.id in node.left and api.id not in d.REGISTRY.sessions


def test_a_remote_session_beside_a_local_one_each_with_its_own_prompt(d, node):
    """A remote OpenCode session beside a local Claude Code one: one answer never answers the other."""
    billing = add(d, "cc1", "billing/main", "/repos/billing")
    shop = _join(d, "devbox", "ses_shop", "shop", harness="opencode")
    d.state.conn = fake_conn(bot_started_at=2.0)
    hook = {"session_id": "cc1", "tool_name": "Bash", "tool_input": {"command": "touch x", "description": "make x"}}

    async def scenario():
        held = asyncio.create_task(d.permission_hook(
            SimpleNamespace(json=_async(hook), is_disconnected=_async(False)), "Bearer secret"))
        await d.remote_permission(shop, "r9", "Bash", "clean", '{"command": "rm -rf dist"}', "run: rm -rf dist")
        while not billing.permission_id:
            await asyncio.sleep(0.01)
        await d._apply_answer(shop, "r9", "deny", "tapped")
        assert not held.done() and billing.permission_id
        await d._apply_answer(billing, billing.permission_id, "allow", "user said: 'yes'")
        return await held

    reply = asyncio.run(scenario())
    assert reply["hookSpecificOutput"]["decision"]["behavior"] == "allow"
    assert node.answers == [(shop.id, "r9", "deny", "tap", None)] and shop.harness == "opencode"


def test_an_approval_alert_names_the_machine_only_when_sessions_span_machines(d, node):
    shop = add(d, "cc1", "shop", "/repos/shop")
    shop.permission_id = "p1"

    def titles():
        return {a["session"]: a["title"] for a in client_for(d).get("/voice/status").json()["attention"]
                if a["kind"] == "permission"}

    assert titles() == {"shop": "shop needs approval"}  # one machine: as today
    twin = _join(d, "devbox", "s1", "shop")  # named "shop devbox": the title says the machine once, as the card does
    api = _join(d, "devbox", "abc", "api")
    twin.permission_id, api.permission_id = "p2", "p3"
    assert titles() == {"shop": "shop · studio needs approval", "shop devbox": "shop · devbox needs approval",
                        "api": "api · devbox needs approval"}


def test_a_hub_shutting_down_does_not_tell_its_nodes_the_call_ended(d, node, monkeypatch):
    """From the two-machine run: on `voice-daemon stop` the call socket closed first and the nodes were sent
    `call {up: false}`, so each handed its held prompt back to the terminal 2 s before the link dropped, and the
    restarted hub could never ask it again. Going down, the hub says nothing: the link drops with it."""
    d.state.conn = fake_conn()
    d._notify_call()
    assert node.calls[-1]["up"] is True
    monkeypatch.setattr(d, "SERVER", SimpleNamespace(should_exit=True))
    d.state.conn = None
    d._call_ended()
    assert node.calls[-1]["up"] is True  # nothing sent
    monkeypatch.setattr(d, "SERVER", SimpleNamespace(should_exit=False))
    d._notify_call()
    assert node.calls[-1]["up"] is False  # a real hang-up still tells them
