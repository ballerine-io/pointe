"""Hunt 2, feature interactions: briefing groups join a departed session to a live one by folder path alone.

daemon._briefing_groups: "a departed one from the same folder joined to it (a restart)". The match is `cwd == cwd`
with no look at `machine`. Two Macs with the same user name hold the same path (`/Users/mira/ws/shop` on studio and
on laptop), so a session that left on one machine is folded into the briefing section of a live session on the
other, and its record is read out as that session's past."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_mixed_harnesses import _join, node  # noqa: E402,F401  (node is a fixture)
from test_orchestrator import add, d  # noqa: E402,F401  (d is a fixture)


def test_a_departed_session_on_this_mac_is_not_joined_to_a_live_one_on_another_machine_by_path(d, node):
    # Names differ as in test_briefing's restart case: Registry.add deletes a departed session of the very same name
    gone = add(d, "cc-old", "shop/first-run", "/Users/mira/ws/shop")
    d.REGISTRY.departed[gone.id] = d.REGISTRY.sessions.pop(gone.id)  # it left, on this Mac
    live = _join(d, "laptop", "s1", "shop", cwd="/Users/mira/ws/shop")  # the same path, on the laptop
    groups = d._briefing_groups("")
    joined = next(g for g in groups if g[-1] is live)
    assert gone not in joined, f"{gone.name} on this Mac was folded into {live.name} on {live.machine}: {[(s.name, s.machine) for s in joined]}"


def test_a_departed_remote_session_is_not_joined_to_a_live_local_one_by_path(d, node):
    gone = _join(d, "laptop", "s1", "shop/first-run", cwd="/Users/mira/ws/shop")
    d.REGISTRY.departed[gone.id] = d.REGISTRY.sessions.pop(gone.id)  # it left, on the laptop
    live = add(d, "cc1", "shop", "/Users/mira/ws/shop")  # the same path, on this Mac
    groups = d._briefing_groups("")
    joined = next(g for g in groups if g[-1] is live)
    assert gone not in joined, f"{gone.name} on {gone.machine} was folded into {live.name} on this Mac"
