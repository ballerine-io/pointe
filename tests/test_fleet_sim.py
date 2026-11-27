"""The fleet simulator's own test (bench/fleet/sim.py): two machines with three scripted sessions each, on real links,
with the models stubbed (bench/fleet/voice.py, POINTE_BENCH_MODELS=stub): no vendor, no key. One voice daemon and one
node process, on a folder in /tmp and on ports chosen free at run time.

Slow: it starts two processes and holds a call."""

import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_fleet import load  # noqa: E402
from fleet import until  # noqa: E402

gen, bench, sim = load("gen", "run", "sim")


@pytest.mark.slow
def test_a_small_fleet_comes_up_reports_a_finished_turn_and_shows_where_a_send_landed():
    described = gen.fleet("2x3")
    root = Path(tempfile.mkdtemp(prefix="pfs-", dir="/tmp"))
    fleet = sim.FleetSim(described, root / "f")
    try:
        fleet.up()
        assert not {fleet.voice.port, fleet.voice.tls_port, *(n.port for n in fleet.nodes.values())} & {7860, 7443}
        # every session is in the voice's status, with its machine
        want = {s["id"]: s["machine"] for s in described["sessions"]}
        assert fleet.machines_seen() == want
        shown = {(s["name"], s.get("machine")) for s in fleet.voice.status()["sessions"]}
        assert len(shown) == 6 and {m for _, m in shown} == {"studio", "avi-box"}
        names = fleet.names()
        assert sorted(names.values()).count("shop") == 1 and "shop avi-box" in names.values()  # the shared name, told apart
        fleet.settle_notes()
        watch = bench.Watch(fleet)
        fleet.open_call()
        fleet.start_states()
        watch.settle(least=2.0, most=40.0)

        # a send lands in the inbox of the session it names, on the other machine, and in no other
        far = next(s for s in described["sessions"] if s["machine"] == "avi-box" and not s["shared_name"])
        seen = {"deliveries": [], "calls": [], "said": []}
        fleet.type(f"Tell {far['name']} to run the tests.")
        watch.settle(seen, least=2.0, most=40.0)
        assert [d["session"] for d in seen["deliveries"]] == [far["id"]], seen
        assert "run the tests" in seen["deliveries"][0]["text"]
        assert all(not s.requests() for sid, s in fleet.sessions.items() if sid != far["id"])
        assert any(c["kind"] == "step" and c["answers"].endswith("run the tests.") for c in seen["calls"])

        # a scripted finish produces a report line
        worker = next(s for s in described["sessions"] if s["state"] == "working")
        before = len(seen["said"])
        fleet.sessions[worker["id"]].finish()
        until("the finished turn is reported", lambda: watch.settle(seen, least=1.0, most=5.0) and len(seen["said"]) > before, 40)
        assert any(c["kind"] == "text" and c.get("caller") == "_read_model" for c in seen["calls"])  # the reader was asked
        assert time.time() - seen["said"][-1]["at"] < 60
    except BaseException:
        print(fleet.logs()[-6000:])
        raise
    finally:
        fleet.close()
        shutil.rmtree(root, ignore_errors=True)
