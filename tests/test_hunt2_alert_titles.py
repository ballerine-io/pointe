"""Hunt (UI surfaces): what the daemon tells the clients about machines, against what the page, the app and the user
doc say. Expected to FAIL where the surfaces disagree; the sanity tests should pass."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import harnesses  # noqa: E402
from test_mixed_harnesses import node, _join  # noqa: E402,F401  (node is a fixture)
from test_orchestrator import add, client_for, d  # noqa: E402,F401  (d is a fixture)


def _titles(d):
    return {a["session"]: a["title"] for a in client_for(d).get("/voice/status").json()["attention"]
            if a["kind"] == "permission"}


def test_notification_title_matches_the_card_when_only_a_remote_machine_has_sessions(d, node):
    """ui.html whoLabel and Sessions.swift MachineView.label print "shop · devbox" for every remote session; the daemon's
    _alert_name adds the machine only when sessions span machines, so the notification says a bare "shop"."""
    shop = _join(d, "devbox", "s1", "shop")
    shop.permission_id = "p1"
    assert _titles(d) == {"shop": "shop · devbox needs approval"}


def test_notification_title_uses_the_documented_separator_when_machines_mix(d, node):
    """docs/multi-machine.md:49: 'An approval card, and its notification, say "shop · devbox needs approval"'. The card
    does (ui.html whoLabel, CallView RequestCard); the notification says "shop (devbox)"."""
    local = add(d, "cc1", "shop", "/repos/shop")
    local.permission_id = "p1"
    api = _join(d, "devbox", "abc", "api")
    api.permission_id = "p2"
    assert _titles(d)["api"] == "api · devbox needs approval"


def test_status_shape_both_clients_decode(d, node):
    """Sanity: API.swift's Codable types. Machine.id String, rtt_ms Int?, since Double?, Invite.code String non-optional."""
    local = add(d, "cc1", "shop", "/repos/shop")
    _join(d, "devbox", "abc", "api")
    s = client_for(d).get("/voice/status").json()
    assert s["machines"][0]["here"] is True and isinstance(s["machines"][0]["id"], str)
    for m in s["machines"]:
        assert m.get("rtt_ms") is None or isinstance(m["rtt_ms"], int)
        assert m.get("since") is None or isinstance(m["since"], (int, float))
    by_name = {x["name"]: x for x in s["sessions"]}
    assert by_name["shop"]["online"] is True and by_name["shop"]["machine"] == "studio"
    assert by_name["api"]["online"] is True and by_name["api"]["machine"] == "devbox"
    assert s["invite"] is None
    # An outstanding invite in the status always carries a string code (Invite.code is non-optional in Swift).
    import hub_nodes
    inv = hub_nodes.Invites(lambda: 100.0)
    assert inv.status() is None
    inv.make()
    st = inv.status()
    assert isinstance(st["code"], str) and st["expires_in"] == hub_nodes.INVITE_SECS


def test_an_offline_machines_need_count_in_status(d, node):
    """machines[].need counts a prompt on an offline machine, which neither client lets the user answer; the page recounts
    (excludes offline), the app ignores the field. Records the behaviour; not asserted as a defect."""
    api = _join(d, "devbox", "abc", "api")
    api.permission_id = "p2"
    node.machines["devbox"].online = False
    s = client_for(d).get("/voice/status").json()
    devbox = next(m for m in s["machines"] if m["name"] == "devbox")
    assert devbox["online"] is False
    assert devbox["need"] == 1  # counted although unanswerable here
    att = [a for a in s["attention"] if a["kind"] == "permission"]
    assert att and att[0]["approvable"] is False
