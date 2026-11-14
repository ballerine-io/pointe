"""Bug hunt 2: what a node (or a stolen node key) can make the hub say or do through the strings it controls.
Each test is a scenario that should hold per docs/design/multi-machine.md; a failure proves the finding."""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import alerts  # noqa: E402
import sessions  # noqa: E402
from test_mixed_harnesses import _join, node  # noqa: E402,F401  (node is a fixture)
from test_orchestrator import _consent_setup, add, client_for, d, fake_conn, verdicts  # noqa: E402,F401


def _names(d):
    return list(d.REGISTRY.sessions.values())


# ---------- Q3: a node-chosen name shadows a hub-local session ----------

def test_a_remote_session_that_joined_first_does_not_keep_the_plain_name_from_a_later_local_one(d, node):
    """Design, failure modes: "Two sessions named shop on two machines: the hub suffixes the later one with the machine".
    The later one here is local, which can never carry this Mac's name, so it gets "-2" and the plain "shop" stays the
    node's: "tell shop to run the tests" goes to the node."""
    remote = _join(d, "devbox", "r1", "shop")
    joined = client_for(d).post("/voice/register", headers={"authorization": "Bearer secret"},
                                json={"id": "cc1", "name": "shop", "cwd": "/repos/shop", "pid": os.getpid(),
                                      "transcript": "/tmp/none.jsonl"}).json()
    local = d.REGISTRY.sessions["cc1"]
    picked = sessions.match_session("tell shop to run the tests", _names(d))
    assert picked is not remote, f"local joined as {joined['name']!r}, remote kept {remote.name!r}: plain 'shop' routes to the node"


def test_a_remote_session_named_yes_does_not_swallow_the_users_yes_to_a_local_prompt(d, node, monkeypatch):
    """_answer_permission: "others = named_sessions(text) ... if others: return" treats "yes" as aimed at the session
    called "yes". Control: test_o13_control_a_plain_yes_answers_the_active_session."""
    active, posts = _consent_setup(d, monkeypatch)
    trap = _join(d, "devbox", "r1", "yes")
    assert trap.name != "yes", trap.name  # refused: a yes or no word never names a session
    asyncio.run(d.on_user_utterance("yes"))
    assert [v["behavior"] for v in verdicts(posts)] == ["allow"], f"the yes went nowhere; pending={active.permission_id}"


def test_a_remote_session_named_no_does_not_swallow_the_users_no_to_a_local_prompt(d, node, monkeypatch):
    """Design: "A no from anywhere denies"."""
    active, posts = _consent_setup(d, monkeypatch)
    trap = _join(d, "devbox", "r1", "no")
    assert trap.name != "no", trap.name
    asyncio.run(d.on_user_utterance("no"))
    assert [v["behavior"] for v in verdicts(posts)] == ["deny"], f"the no went nowhere; pending={active.permission_id}"


def test_a_local_session_named_yes_does_not_swallow_the_users_yes_to_the_active_prompt(d, node, monkeypatch):
    active, posts = _consent_setup(d, monkeypatch)
    joined = client_for(d).post("/voice/register", headers={"authorization": "Bearer secret"},
                                json={"id": "cc9", "name": "yes", "cwd": "/repos/yes", "pid": os.getpid(),
                                      "transcript": "/tmp/none.jsonl", "name_given": True}).json()
    assert joined["name"] != "yes"
    asyncio.run(d.on_user_utterance("yes"))
    assert [v["behavior"] for v in verdicts(posts)] == ["allow"]


def test_a_session_cannot_be_renamed_or_titled_with_a_consent_word(d, node):
    add(d, "cc1", "shop", "/repos/shop")
    renamed = client_for(d).post("/voice/rename", json={"name": "shop", "new_name": "ok deploy"})
    assert renamed.status_code == 409 and "yes or no" in renamed.json()["detail"]
    remote = _join(d, "devbox", "r1", "api")
    _join(d, "devbox", "r1", "api", title="don't stop")  # a later snapshot: the node's title
    assert remote.name == "api"


def test_a_node_title_that_extends_a_local_sessions_name_does_not_capture_its_requests(d, node):
    """rename() refuses an exact clash and a name that is *part of* another's, not one that *contains* another's.
    A node titles its session "shop deploy" next to the local "shop"; "ask shop about the deploy" now picks the node."""
    local = add(d, "cc1", "shop", "/repos/shop")
    remote = _join(d, "devbox", "r1", "api")
    _join(d, "devbox", "r1", "api", title="shop deploy")  # a later snapshot: the node's title
    assert remote.name == "api", remote.name  # refused: it shares "shop" with a session on another machine
    said = "what is shop doing with the deploy"  # ("ask shop about the deploy" survives: strip_tasks drops the task words)
    picked = sessions.match_session(said, _names(d))
    assert picked is local, f"{said!r} -> {getattr(picked, 'name', None)!r}"


def test_a_node_name_sharing_a_word_with_a_local_session_is_refused_at_join(d, node):
    add(d, "cc1", "shop", "/repos/shop")
    s = _join(d, "devbox", "r1", "shop deploy", cwd="/srv/storefront")
    assert "shop" not in s.name.split(), s.name
    assert sessions.match_session("what is shop doing with the deploy", _names(d)).id == "cc1"


def test_the_machine_suffix_and_unrelated_names_still_pass_across_machines(d, node):
    add(d, "cc1", "shop", "/repos/shop")
    assert _join(d, "devbox", "s1", "shop").name == "shop devbox"
    assert _join(d, "devbox", "a1", "api").name == "api"


def test_a_node_title_one_letter_off_a_local_name_does_not_make_every_request_to_it_a_tie(d, node):
    """"shops" hears "shop" (SequenceMatcher 0.89 >= 0.8) with the same score as "shop": every "tell shop ..." becomes
    "which one?"."""
    local = add(d, "cc1", "shop", "/repos/shop")
    _join(d, "devbox", "r1", "api")
    _join(d, "devbox", "r1", "api", title="shops")
    assert d.REGISTRY.sessions["n3f2a1-r1"].name == "api"  # refused: one letter off a session on another machine
    assert sessions.match_session("tell shop to run the tests", _names(d)) is local


def test_a_remote_session_cannot_be_named_after_this_mac(d, node):
    """_tell_apart: this Mac's name is never an alias ("go to studio" must mean the machine). The node side has no check:
    a node names its session "studio" and "go to studio" picks it."""
    add(d, "cc1", "api", "/repos/api")
    s = _join(d, "devbox", "r1", "studio")
    assert "studio" not in s.name.lower().split(), s.name
    assert sessions.name_groups("go to studio", _names(d)) == []


# ---------- Q5: file names ----------

def test_a_nodes_file_names_are_bounded_before_the_routing_prompt(d, node):
    """40 names of 4096 chars pass hub_nodes._bounded and register_remote's [:40]; _tracked_files joins them whole into
    the _classify_target prompt, per session, on every routed send."""
    s = _join(d, "devbox", "r1", "api", files=["x" * 4095 + str(i) for i in range(40)])
    files = d._tracked_files(s)
    assert len(files) <= 4_000, f"{len(files)} chars of file names go into the routing prompt for one session"


# ---------- Q4: cwd as a string ----------

def test_a_remote_session_does_not_inherit_a_departed_local_sessions_briefing_group_by_folder_string(d, node):
    """_briefing_groups joins a departed session to a live one on cwd equality, without the machine: a node's "/repos/shop"
    adopts the notes of the local shop that just closed."""
    gone = add(d, "cc1", "shop", "/repos/shop")
    d.REGISTRY.remove("cc1")
    remote = _join(d, "devbox", "r1", "api", cwd="/repos/shop")
    groups = d._briefing_groups("all")
    assert [gone, remote] not in groups, [[s.name for s in g] for g in groups]


# ---------- Q2: request ids share one keyspace across machines ----------

def test_a_flood_of_remote_requests_does_not_forget_a_local_requests_read_out(d, node, monkeypatch):
    """alerts._REQUESTS keeps the last 64 ids of any session on any machine. A node that sends 64 requests evicts the
    local request's record: its notification Approve is then refused (approvable() False)."""
    async def quiet(*a, **k):
        return None

    monkeypatch.setattr(d, "say", quiet)
    monkeypatch.setattr(d, "_ask_permission", quiet)
    local = add(d, "cc1", "shop", "/repos/shop")
    remote = _join(d, "devbox", "r1", "api")
    d.state.conn = fake_conn()
    asyncio.run(d._put_permission(local, "ab12cd34", "Bash", "status", json.dumps({"command": "git status"})))
    assert alerts.approvable(local.id, "ab12cd34")
    for i in range(alerts.KEEP):
        asyncio.run(d.remote_permission(remote, f"r{i}", "Bash", "status", "{}", "run: git status"))
    assert local.permission_id == "ab12cd34"
    assert alerts.approvable(local.id, "ab12cd34"), "the local request's read-out was evicted by the node's requests"


def test_a_remote_request_id_cannot_rewrite_what_a_local_requests_notification_shows(d, node, monkeypatch):
    """alerts.note_request is keyed by request id alone, and a node picks its own ids. One equal to a local pending id
    (8 hex chars: a guess, or a hub that ever reveals them) replaces the local record: the local request, unreadable
    (WebFetch), becomes approvable from a notification that shows the node's words."""
    async def quiet(*a, **k):
        return None

    monkeypatch.setattr(d, "say", quiet)
    monkeypatch.setattr(d, "_ask_permission", quiet)
    local = add(d, "cc1", "shop", "/repos/shop")
    remote = _join(d, "devbox", "r1", "api")
    d.state.conn = fake_conn()
    asyncio.run(d._put_permission(local, "ab12cd34", "WebFetch", "fetch", json.dumps({"url": "https://x"})))
    assert not alerts.approvable(local.id, "ab12cd34")
    asyncio.run(d.remote_permission(remote, "ab12cd34", "Bash", "list", json.dumps({"command": "ls"}), "run: ls"))
    shown = alerts.permission_alert(local.name, local.id, local.permission_id, 0.0)
    assert not shown["approvable"] and "ls" not in shown["body"], shown


def test_an_empty_remote_request_id_is_not_put_to_the_user(d, node, monkeypatch):
    """nodelink's schema takes any string. An empty id is read out and shown, but no yes or tap can ever answer it
    (`if not session.permission_id` everywhere)."""
    async def quiet(*a, **k):
        return None

    monkeypatch.setattr(d, "say", quiet)
    monkeypatch.setattr(d, "_ask_permission", quiet)
    remote = _join(d, "devbox", "r1", "api")
    d.state.conn = fake_conn()
    held = asyncio.run(d.remote_permission(remote, "", "Bash", "status", "{}", "run: git status"))
    assert held is False and not remote.permission_text, (held, remote.permission_text)


def test_an_odd_remote_request_id_is_not_put_to_the_user(d, node, monkeypatch):
    async def quiet(*a, **k):
        return None

    monkeypatch.setattr(d, "say", quiet)
    monkeypatch.setattr(d, "_ask_permission", quiet)
    remote = _join(d, "devbox", "r1", "api")
    d.state.conn = fake_conn()
    for bad in ("a b", "x" * 65, "../p1", "p1\n"):
        assert asyncio.run(d.remote_permission(remote, bad, "Bash", "status", "{}", "run: git status")) is False
    assert remote.permission_id is None
    assert asyncio.run(d.remote_permission(remote, "req-1_a", "Bash", "status", "{}", "run: git status")) is True
