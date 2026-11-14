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
