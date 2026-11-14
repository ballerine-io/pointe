"""Hunt 2, feature interactions: a remote prompt that times out while news is held (meeting, brainstorm).

daemon._hold_one (local): when the prompt waits out its deadline under a holds_news mode, a line is queued in
state.monologue_held so the user hears, at the hand-off, that the approval went back to its terminal. The remote path
ends in daemon.remote_resolved(how="timeout") and queues nothing: the design says meeting mode "changes nothing", but
the user is told about a local prompt and not about a remote one."""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_mixed_harnesses import _join, node  # noqa: E402,F401  (node is a fixture)
from test_orchestrator import add, d  # noqa: E402,F401  (d is a fixture)


def _held_lines(d):
    return [text for text, _ in d.state.monologue_held]


def test_a_remote_prompt_that_times_out_during_held_news_is_reported_at_the_handoff_like_a_local_one(d, node, monkeypatch):
    async def quiet(*a, **k):
        return None

    monkeypatch.setattr(d, "say", quiet)
    monkeypatch.setattr(d, "_ask_permission", quiet)
    remote = _join(d, "devbox", "s1", "api")  # before the call: register_remote starts no worker then
    d.state.conn = object()  # a call is up
    d.state.monologue = []  # brainstorm: current_mode().holds_news

    local = add(d, "cc1", "shop", "/w/shop")
    preview = json.dumps({"command": "git status"})
    asyncio.run(d._hold_one(local, "Bash", {"command": "git status"}, preview, None, deadline=time.time() - 1))
    local_lines = _held_lines(d)
    assert local_lines and "went back to its terminal" in local_lines[-1]  # the local path says so

    asyncio.run(d.remote_permission(remote, "req1", "Bash", "git status", preview, "run: git status"))
    assert remote.permission_id == "req1"
    d.remote_resolved(remote, "req1", "timeout")  # the node's deadline passed: it handed the prompt to its terminal
    assert remote.permission_id is None
    remote_lines = [t for t in _held_lines(d) if "api" in t]
    assert remote_lines and "went back to its terminal" in remote_lines[-1], \
        f"the remote prompt's return to the terminal is never told at the hand-off: {_held_lines(d)}"
