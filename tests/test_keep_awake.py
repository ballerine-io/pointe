"""The Mac does not idle-sleep under a call from the phone, and never keeps awake on battery.

While a call from another device (the phone app, or the page over the private network) is up and the Mac is on AC power,
the daemon runs `caffeinate -i -w <its pid>`; it stops it when the call ends or the Mac goes to battery, and says which
in the status (`keep_awake`). Tests fake the power source and caffeinate: they never touch this Mac's sleep.

uv run --locked pytest -q tests/test_keep_awake.py
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mac  # noqa: E402
from test_orchestrator import client_for, d  # noqa: E402,F401


def test_the_power_source_is_read_from_pmset():
    assert mac.on_ac("Now drawing from 'AC Power'\n -InternalBattery-0 (id=1)\t100%; charged; present: true") is True
    assert mac.on_ac("Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t80%; discharging") is False
    assert mac.on_ac("Now drawing from 'UPS Power'") is False
    assert mac.on_ac("") is None


class FakeProc:
    def __init__(self):
        self.returncode = None
        self.terminated = False

    def terminate(self):
        self.terminated, self.returncode = True, -15

    async def wait(self):
        return self.returncode


class Power:
    def __init__(self, ac):
        self.ac, self.reads = ac, 0

    async def __call__(self):
        self.reads += 1
        return self.ac


def keeper(ac=True):
    started: list[FakeProc] = []

    async def start():
        started.append(FakeProc())
        return started[-1]

    power = Power(ac)
    return mac.KeepAwake(power=power, start=start), power, started


def test_a_call_from_elsewhere_on_ac_power_keeps_it_awake_once_and_the_end_of_the_call_lets_it_sleep():
    async def go():
        k, power, started = keeper(ac=True)
        await k.update(True)
        await k.update(True)
        assert k.on and len(started) == 1 and k.status() == {"on": True, "why": "a call from another device is up and the Mac is on power"}
        await k.update(False)
        assert not k.on and started[0].terminated and power.reads == 2  # no power read with no call
        assert k.status()["why"] == "no call from another device"

    asyncio.run(go())


@pytest.mark.parametrize("ac,why", [(False, "the Mac is on battery"), (None, "the power source is unknown")])
def test_never_on_battery_or_an_unknown_source(ac, why):
    async def go():
        k, power, started = keeper(ac=ac)
        await k.update(True)
        return k, started

    k, started = asyncio.run(go())
    assert not k.on and started == [] and k.status() == {"on": False, "why": why}


def test_unplugged_mid_call_it_lets_go_and_plugged_back_in_it_holds_again():
    async def go():
        k, power, started = keeper(ac=True)
        await k.update(True)
        power.ac = False
        await k.update(True)
        assert not k.on and started[0].terminated and k.status()["why"] == "the Mac is on battery"
        power.ac = True
        await k.update(True)
        assert k.on and len(started) == 2

    asyncio.run(go())


def test_a_caffeinate_that_died_is_started_again():
    async def go():
        k, power, started = keeper(ac=True)
        await k.update(True)
        started[0].returncode = 1
        assert not k.on
        await k.update(True)
        assert k.on and len(started) == 2

    asyncio.run(go())


def test_tests_never_touch_this_macs_sleep():
    assert mac.SYSTEM is False
    assert asyncio.run(mac.read_power()) is None and asyncio.run(mac.start_caffeinate()) is None


# ---------- the daemon ----------

class FakeSocket:
    def __init__(self, port=7860):
        self.scope = {"server": ("127.0.0.1", port), "state": {}}

    async def accept(self):
        pass

    async def close(self, code=1000, reason=""):
        pass

    async def send_text(self, text):
        pass


@pytest.fixture
def awake(d, monkeypatch):
    k, power, started = keeper(ac=True)
    monkeypatch.setattr(d, "KEEP_AWAKE", k)
    return SimpleNamespace(k=k, power=power, started=started)


def _call(d, monkeypatch, who: str, socket: FakeSocket) -> dict:
    during = {}

    async def run_call(transport):
        during.update(on=d.KEEP_AWAKE.on, elsewhere=d.state.call_from_elsewhere)

    monkeypatch.setattr(d, "run_call", run_call)
    asyncio.run(d.socket_call(socket, who))
    return during


def test_a_phone_call_keeps_the_mac_awake_while_it_is_up(d, monkeypatch, awake):
    assert _call(d, monkeypatch, "phone", FakeSocket()) == {"on": True, "elsewhere": True}
    assert not awake.k.on and awake.started[0].terminated and d.state.call_from_elsewhere is False


def test_a_page_call_on_this_mac_does_not_and_one_over_the_private_network_does(d, monkeypatch, awake):
    assert _call(d, monkeypatch, "page", FakeSocket()) == {"on": False, "elsewhere": False}
    assert _call(d, monkeypatch, "page", FakeSocket(port=d.remote.TLS_PORT)) == {"on": True, "elsewhere": True}


def test_the_status_says_whether_it_keeps_the_mac_awake_and_why(d, monkeypatch, awake):
    assert client_for(d).get("/voice/status").json()["keep_awake"] == {"on": False, "why": "no call from another device"}
    d.state.call_from_elsewhere = True
    asyncio.run(awake.k.update(True))
    assert client_for(d).get("/voice/status").json()["keep_awake"]["on"] is True
    d.state.call_from_elsewhere = False
