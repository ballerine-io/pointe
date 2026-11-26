"""The phone's call through a bad network, end to end: the daemon's socket_call and pipecat transport, a stand-in phone
that speaks protocol 5 as the app does, and tests/netshaper.py between them (tests/net_bench.py runs it). Bounds, not
exact numbers: a 7 s outage (past the phone's 6 s silence, so it dials a new link) drops no call, a network switch is bridged on a new link, a capped link adds bounded
latency, a typed line is acknowledged quickly and taken once, and the voice reaches a client half a second ahead of its
playing, so a jittery, lossy path does not break it. No vendor and no key: the bot is synthetic.

Measured before and after protocol 5 with the same rig (the old app and daemon): docs/phone.md, "On a weak network".
"""

import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = {"t-outage": 9750, "t-switch": 9760, "t-capped": 9770, "t-lead": 9780, "t-relay": 9790}  # each takes its port and the next: 9700-9799 is ours
pytestmark = pytest.mark.serial  # it measures a call's latency: beside other workers a busy runner adds to it


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """The runs at once, each in its own process and state folder: about 25 s together. Under xdist every worker
    with a test here asks for them: the first runs them, the rest read its result, so the fixed ports are bound once."""
    if not os.environ.get("PYTEST_XDIST_WORKER"):
        return _run_all()
    shared = tmp_path_factory.getbasetemp().parent / "bad-network.json"  # one folder per session, every worker's parent
    with open(shared.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not shared.exists():
            shared.write_text(json.dumps(_run_all()))
        return json.loads(shared.read_text())


def _run_all() -> dict:
    procs = {name: subprocess.Popen([sys.executable, "-I", str(ROOT / "tests" / "net_bench.py"), name, "new"],
                                    env={**os.environ, "POINTE_NET_PORT": str(port)},
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for name, port in SCENARIOS.items()}
    out = {}
    for name, proc in procs.items():
        stdout, stderr = proc.communicate(timeout=120)
        lines = [line for line in stdout.splitlines() if line.startswith("{")]
        assert lines, f"{name} printed no result:\n{stderr[-3000:]}"
        out[name] = json.loads(lines[-1])
    return out


@pytest.mark.slow
def test_an_outage_drops_no_call_and_a_line_typed_during_it_arrives_once(runs):
    r = runs["t-outage"]
    assert r["calls"] == 1 and r["call_drops"] == 0, r
    assert r["dials"] >= 2, f"the outage outlasted the phone's patience: the call came back on a new link: {r}"
    assert None not in r["typed_ack_secs"], r
    assert r["replies"] == 3, f"each typed line taken once, a resend included: {r}"
    assert r["typed_ack_secs"][2] < 3, f"after the outage a line is acknowledged at once: {r}"
    assert r["offline_secs"] < 10, r


def test_a_network_switch_moves_the_call_to_a_new_link(runs):
    r = runs["t-switch"]
    assert r["calls"] == 1 and r["call_drops"] == 0, r
    assert r["dials"] == 2, f"one new link, dialled once the old one went quiet: {r}"
    assert r["offline_secs"] < 9, r
    assert r["typed_ack_secs"][1] is not None and r["typed_ack_secs"][1] < 3, r


def test_a_capped_link_adds_bounded_latency_both_ways(runs):
    r = runs["t-capped"]
    assert r["calls"] == 1, r
    assert max(r["reply_late_secs"]) < 2.0, f"a reply finishes playing within 2 s of a perfect link: {r}"
    assert r["up_behind_secs"] < 2.0, f"the user's words reach the Mac within 2 s: {r}"
    assert r["phone_heard_secs"] >= 0.9 * r["bot_said_secs"], f"and nothing of the reply is lost: {r}"
    assert max(r["typed_ack_secs"]) < 2.0, r


def test_the_voice_reaches_the_client_half_a_second_ahead_of_its_playing(runs):
    """socket_call paces the transport with phone.send_ahead: pipecat's own clock keeps a client one chunk ahead."""
    r = runs["t-lead"]
    assert r["lead_secs"] == 0.5, r
    assert 0.4 <= r["ahead_max_secs"] <= 0.8, f"the first reply came in that far ahead of its playing: {r}"
    assert r["page"]["gaps_per_min"] == 0 and r["app"]["gaps_per_min"] == 0, r
    assert r["phone_heard_secs"] == r["bot_said_secs"], r


def test_on_a_jittery_lossy_relay_the_voice_does_not_break(runs):
    """tests/netshaper.py's "relay": 70 ms, up to 80 ms of jitter, a segment in 200 lost. On 0.10.0's pacing the page
    broke about 13 times a minute and the apps about 4 (docs/phone.md, "The voice plays smoothly")."""
    r = runs["t-relay"]
    for client in ("page", "app"):
        assert r[client]["gap_ms_per_min"] <= 150, (client, r)
    assert r["phone_heard_secs"] >= 0.95 * r["bot_said_secs"], r
