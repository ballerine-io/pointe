"""In orchestrator mode a permission request from a session not in focus is read out, not "say switch to it".

From the conversation suite: "granary is waiting on a permission approval for the logging work. Say 'switch to granary'
and I'll read it out." A voice-only user had to say a command before they could hear what they were approving. When no
other request waits, the requesting session takes the focus and its request is read out as any other, its name first
("granary wants to run ... Should it?"); a spoken yes then binds to it exactly as for the active session. With another
request already waiting, or in session mode, the old behaviour stays.

uv run pytest -q tests/test_permission_focus.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import add, d, fake_conn  # noqa: E402,F401  (d is the daemon fixture)

PREVIEW = json.dumps({"command": "python3 -m unittest"})


def _setup(d, monkeypatch):  # noqa: F811
    a, b = add(d, "a", "ledgerline"), add(d, "b", "skyway")
    d.REGISTRY.active_id = "a"
    d.REGISTRY.mode = "orchestrator"
    d.state.conn = fake_conn()
    asked = []

    async def ask(session):
        asked.append(session.name)
    monkeypatch.setattr(d, "_ask_permission", ask)
    return a, b, asked


def test_a_request_from_a_session_not_in_focus_is_read_out(d, monkeypatch):  # noqa: F811
    a, b, asked = _setup(d, monkeypatch)
    asyncio.run(d._put_permission(b, "p1", "Bash", "run the tests", PREVIEW))
    assert asked == ["skyway"] and d.REGISTRY.active is b


def test_with_another_request_waiting_it_is_announced_only(d, monkeypatch):  # noqa: F811
    a, b, asked = _setup(d, monkeypatch)
    a.permission_id = "p0"
    asyncio.run(d._put_permission(b, "p1", "Bash", "run the tests", PREVIEW))
    assert asked == [] and d.REGISTRY.active is a
