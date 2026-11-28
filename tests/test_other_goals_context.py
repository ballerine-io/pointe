"""The brain is told what each other session works on once its notes arrive, so "the session working on X" finds it.

uv run --locked --group test-tools pytest -q tests/test_other_goals_context.py
"""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_orchestrator import add, d  # noqa: E402,F401  (d is a fixture)


@pytest.fixture
def fleet(d):  # noqa: F811
    for i, name in enumerate(("heron", "pelican-web", "fennel", "orchard")):
        add(d, f"s{i}", name)
    return d



def test_the_brain_is_told_what_each_other_session_works_on_once_its_notes_arrive(fleet):
    """The routing miss in the same dialogue: the call opened with "orchid (no notes yet)", orchid's notes ("Add
    retries with backoff to the ticket migration") arrived 44 s before the request, and nothing told the brain, which
    said none of its sessions was about it. Each [right now] block now carries the other sessions' goals."""
    d = fleet
    orchard = d.REGISTRY.sessions["s3"]
    orchard.brief = {"goal": "Add retries with backoff to the lantern import and cover them with tests.", "state": "done"}
    d.REGISTRY.active_id = "s0"
    context = d._brain_context()
    assert "orchard: Add retries with backoff to the lantern import" in context
    assert "fennel: no notes yet" in context


def test_a_large_fleet_points_to_list_sessions_instead_of_listing_every_goal(d, monkeypatch):  # noqa: F811
    for i in range(d.OTHER_GOALS_MAX + 2):
        add(d, f"s{i}", f"bay{i}").brief = {"goal": f"Goal number {i} of a long list."}
    d.REGISTRY.active_id = "s0"
    context = d._brain_context()
    assert "Goal number 5" not in context and "list_sessions" in context
