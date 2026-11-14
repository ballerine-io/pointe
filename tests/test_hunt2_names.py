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
