"""A session on another machine stopped at a prompt in its terminal is shown as one, like a session on this Mac.

The node reads `claude agents --json` for its own sessions (1.10.0) and now ships the result in its `sessions` snapshot
(`blocked_on`, `blocked_since`, `held_at`, in the node's clock); the hub applies it shifted by the clock skew, so the
page, the app, the brain and the alerts treat it as they treat a local one. A node older than 1.12.0 sends none of it.

uv run --locked pytest -q tests/test_remote_prompt_state.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import node  # noqa: E402
import sessions  # noqa: E402
from sessions import Session, apply_wait_state, wait_state  # noqa: E402
from test_mixed_harnesses import _join, node as linked  # noqa: E402,F401  (linked is a fixture)
from test_orchestrator import client_for, d  # noqa: E402,F401


def test_the_wait_state_is_what_the_node_knows_and_nothing_when_there_is_none():
    s = Session(id="s", name="api", cwd="/srv/api")
    assert wait_state(s) == {"blocked_on": "", "blocked_since": None, "held_at": None}
    s.blocked_on, s.blocked_since = "permission prompt", 1000.0
    assert wait_state(s) == {"blocked_on": "permission prompt", "blocked_since": 1000.0, "held_at": None}
    s.held_at = time.time() - sessions.HELD_WATCH_SECS - 1  # past the cap: not claimed on the hub either
    assert wait_state(s)["held_at"] is None


def test_the_hub_applies_it_in_its_own_clock_and_keeps_the_time_of_an_unchanged_wait():
    s = Session(id="n-s", name="api", cwd="/srv/api", machine="devbox")
    apply_wait_state(s, {"blocked_on": "permission prompt", "blocked_since": 1000.0, "held_at": None}, skew=30.0)
    assert (s.blocked_on, s.blocked_since) == ("permission prompt", 1030.0)
    apply_wait_state(s, {"blocked_on": "permission prompt", "blocked_since": 1001.5, "held_at": None}, skew=30.0)
    assert s.blocked_since == 1030.0  # the same wait: the alert's id stays
    apply_wait_state(s, {"blocked_on": "", "blocked_since": None, "held_at": None}, skew=30.0)
    assert (s.blocked_on, s.blocked_since) == ("", None)


def test_a_held_message_there_is_held_here_until_the_node_says_it_is_not():
    s = Session(id="n-s", name="api", cwd="/srv/api", machine="devbox")
    now = time.time()
    apply_wait_state(s, {"blocked_on": "", "held_at": now - 40}, skew=0.0)
    assert s.held_at == now - 40 and sessions.message_held(s)
    s.held_at = here = now - 5  # the hub's own time from `send.result`: kept
    apply_wait_state(s, {"blocked_on": "", "held_at": now - 40}, skew=0.0)
    assert s.held_at == here
    apply_wait_state(s, {"blocked_on": "", "held_at": None}, skew=0.0)
    assert s.held_at is None


def test_an_older_node_changes_nothing_and_bad_values_are_not_trusted():
    s = Session(id="n-s", name="api", cwd="/srv/api", machine="devbox", blocked_on="input needed", blocked_since=5.0)
    apply_wait_state(s, {"id": "s", "name": "api"}, skew=0.0)  # a 1.11 node's entry
    assert (s.blocked_on, s.blocked_since) == ("input needed", 5.0)
    apply_wait_state(s, {"blocked_on": "x" * 500, "blocked_since": float("nan"), "held_at": "soon"}, skew=0.0)
    assert len(s.blocked_on) == 64 and s.blocked_since is not None and s.held_at is None


def test_a_remote_session_at_a_prompt_shows_as_a_local_one_does(d, linked):
    api = _join(d, "devbox", "abc", "api", blocked_on="permission prompt", blocked_since=time.time() - 3, held_at=None)
    api.busy = True  # its mirrored transcript shows a tool call
    row = next(s for s in client_for(d).get("/voice/status").json()["sessions"] if s["name"] == "api")
    assert row["working"] is False and row["blocked_on"] == "permission prompt"
    assert row["needs"] == "A permission prompt in its terminal."
    assert "stopped at a prompt in its terminal" in d._needs_now()


def test_a_remote_wait_alerts_after_the_same_quiet_time(d, linked):
    _join(d, "devbox", "abc", "api", blocked_on="input needed",
          blocked_since=time.time() - sessions.TERMINAL_NEWS_AFTER_SECS - 2, held_at=None)
    item = next(a for a in d._attention() if a["session"] == "api")
    assert item["kind"] == "terminal" and item["body"] == "A question in its terminal. Answer it there."
    assert "devbox" in item["title"]


def test_the_next_snapshot_clears_it(d, linked):
    api = _join(d, "devbox", "abc", "api", blocked_on="permission prompt", blocked_since=time.time(), held_at=None)
    _join(d, "devbox", "abc", "api", blocked_on="", blocked_since=None, held_at=None)
    assert api.blocked_on == "" and client_for(d).get("/voice/status").json()["sessions"][-1]["needs"] is None


def test_a_session_joined_from_an_older_node_is_never_called_blocked(d, linked):
    api = _join(d, "devbox", "abc", "api")
    api.busy = True
    row = next(s for s in client_for(d).get("/voice/status").json()["sessions"] if s["name"] == "api")
    assert row["working"] is True and row["blocked_on"] is None and row["needs"] is None


# ---------- the node ----------

def test_the_node_ships_the_wait_and_sends_a_snapshot_when_it_changes(tmp_path, monkeypatch):
    from test_node import _body, run

    monkeypatch.setattr(node, "LIVENESS_SECS", 0.1)

    async def scenario(hub, n):
        await n.register(_body(tmp_path))
        snap = await hub.next("sessions")
        while not snap["sessions"]:  # the one sent on the welcome, before it joined
            snap = await hub.next("sessions")
        assert snap["sessions"][0]["blocked_on"] == "" and snap["sessions"][0]["held_at"] is None
        session = n.registry.sessions["sess-1"]
        session.blocked_on, session.blocked_since = "permission prompt", 1234.5
        snap = await hub.next("sessions")
        while snap["sessions"][0]["blocked_on"] != "permission prompt":
            snap = await hub.next("sessions")
        assert snap["sessions"][0]["blocked_since"] == 1234.5
        session.blocked_on, session.blocked_since = "", None
        snap = await hub.next("sessions")
        while snap["sessions"][0]["blocked_on"]:
            snap = await hub.next("sessions")
        assert await hub.quiet("sessions", 0.5)  # nothing changed: no more snapshots

    run(scenario, tmp_path)
