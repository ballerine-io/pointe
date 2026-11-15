"""The phone stays quiet while the user is at the Mac.

The daemon reads the Mac's idle time (IOKit HIDIdleTime, through `ioreg`, in a subprocess, cached) and gives it in the
status. An attention item is `quiet` for a client that is not on this Mac (the phone app, the page over the private
network) while the Mac was used within mac.AT_MAC_SECS, except an approval about to go back to its terminal. The app and
a page elsewhere post nothing for a quiet item and post it once it is not; a page on this Mac is never quieted, since
its desktop alerts are for the person at the Mac.

uv run --locked pytest -q tests/test_at_the_mac.py
"""

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harnesses  # noqa: E402
import mac  # noqa: E402
from test_orchestrator import add, client_for, d  # noqa: E402,F401

IOREG_OUT = """+-o IOHIDSystem  <class IOHIDSystem, id 0x100000abc, registered, matched, active, busy 0 (0 ms), retain 23>
  |   "HIDIdleTime" = 12500000000
"""


def test_the_idle_time_is_read_from_ioreg_in_seconds():
    assert mac.parse_idle(IOREG_OUT) == 12.5
    assert mac.parse_idle("no such key") is None


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_the_clock_reads_in_the_background_at_most_every_few_seconds_and_forgets_a_stale_reading():
    clock, reads = Clock(), []

    async def read():
        reads.append(clock.now)
        return 3.0

    async def go():
        idle = mac.IdleClock(read=read, clock=clock)
        assert idle.secs() is None  # nothing read yet: the caller does not wait for ioreg
        await asyncio.sleep(0)
        assert idle.secs() == 3.0 and idle.in_use()
        clock.now += 2
        idle.secs()
        await asyncio.sleep(0)
        assert len(reads) == 1  # read at most every IDLE_READ_SECS
        clock.now += mac.IDLE_READ_SECS
        idle.secs()
        await asyncio.sleep(0)
        assert len(reads) == 2
        idle._read = lambda: asyncio.sleep(10)  # ioreg stuck from now on
        clock.now += mac.IDLE_STALE_SECS + 1
        assert idle.secs() is None and not idle.in_use()  # stale: unknown, never "at the Mac"

    asyncio.run(go())


def test_idle_for_a_minute_is_away():
    async def go():
        idle = mac.IdleClock(read=lambda: asyncio.sleep(0, mac.AT_MAC_SECS + 1))
        idle.secs()
        await asyncio.sleep(0.01)
        return idle.in_use()

    assert asyncio.run(go()) is False


def test_tests_never_read_this_machine():
    assert mac.SYSTEM is False and asyncio.run(mac.read_idle()) is None


# ---------- the status ----------

@pytest.fixture
def at_mac(d, monkeypatch):
    """The user touched the Mac `idle` seconds ago."""
    idle = {"secs": 5.0}
    monkeypatch.setattr(d.IDLE, "secs", lambda: idle["secs"])
    return idle


def _waiting(d, name="bluebell", left=200.0):
    s = add(d, "cc1", name)
    s.permission_id, s.permission_text = "a1b2c3d4", "run: git status"
    s.permission_since = time.time() - harnesses.of(s).permission_deadline + left
    return s


def test_the_status_carries_the_idle_time(d, at_mac):
    assert client_for(d).get("/voice/status").json()["mac_idle_secs"] == 5.0
    at_mac["secs"] = None
    assert client_for(d).get("/voice/status").json()["mac_idle_secs"] is None


def test_an_alert_is_quiet_off_the_mac_while_the_mac_is_in_use(d, at_mac, monkeypatch):
    _waiting(d, left=200.0)
    monkeypatch.setattr(d, "_off_the_mac", lambda request: True)
    item = client_for(d).get("/voice/status").json()["attention"][0]
    assert item["kind"] == "permission" and item["quiet"] is True
    at_mac["secs"] = mac.AT_MAC_SECS + 1  # walked away
    assert client_for(d).get("/voice/status").json()["attention"][0]["quiet"] is False
    at_mac["secs"] = None  # unknown: never quiet
    assert client_for(d).get("/voice/status").json()["attention"][0]["quiet"] is False


def test_an_approval_about_to_go_back_to_its_terminal_is_never_quiet(d, at_mac, monkeypatch):
    _waiting(d, left=30.0)
    monkeypatch.setattr(d, "_off_the_mac", lambda request: True)
    assert client_for(d).get("/voice/status").json()["attention"][0]["quiet"] is False


def test_the_page_on_this_mac_is_never_quiet(d, at_mac):
    _waiting(d)
    assert client_for(d).get("/voice/status").json()["attention"][0]["quiet"] is False


def test_every_kind_is_quiet_off_the_mac_and_the_attention_endpoint_agrees(d, at_mac, monkeypatch):
    s = add(d, "cc1", "bluebell")
    s.blocked_on, s.blocked_since = "input needed", time.time() - 60  # a question in its terminal
    monkeypatch.setattr(d, "_off_the_mac", lambda request: True)
    item = client_for(d).get("/voice/status").json()["attention"][0]
    assert item["kind"] == "terminal" and item["quiet"] is True
    assert client_for(d).post("/voice/attention", json={"id": "nothing"}).json()["attention"][0]["quiet"] is True


# ---------- the page elsewhere ----------

def test_the_page_skips_a_quiet_item_and_alerts_it_once_it_is_not():
    page = (Path(__file__).resolve().parents[1] / "ui.html").read_text()
    start = page.index("function desktopAlerts(s)")
    body = page[start:page.index("\n  }\n", start)]
    assert "if (a.quiet) continue;" in body
    assert body.index("if (a.quiet) continue;") < body.index("desk.seen.add(a.id)")  # not marked seen: alerted later
