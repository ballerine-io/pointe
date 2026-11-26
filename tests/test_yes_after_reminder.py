"""A yes after Pointe's own reminder approves the one request it waits on, when that request was read in full and
nothing but the reminder was said since.

Tester round 6 (r6-04, t5-04; 6 of 6 samples): after "Lantern's still waiting on your yes or no", the user's "Yes, run
it" got the whole request read again and a second yes. The reminder asks for exactly that answer, so it no longer
closes the window. The invariant holds: a yes covers only what was heard in full. Anything else said since the read-out,
another request pending, or a read-out the user cut still means the request is read again first.

uv run pytest -q tests/test_yes_after_reminder.py
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import _read_out_setup, d, verdicts, with_permission  # noqa: E402,F401  (d is the daemon fixture)


def _remind(d, monkeypatch, active):  # noqa: F811
    """One round of the nudger: the short reminder for `active`, its words starting as they are said."""
    fixed = []

    async def say_fixed(text, *a, **k):
        fixed.append(text)
        d.state.conn.injector.bot_started_at = d.time.time()  # the reminder is being said

    monkeypatch.setattr(d, "_say_fixed", say_fixed)
    monkeypatch.setattr(d, "pick_nudge", lambda *a: active)
    monkeypatch.setattr(d.state, "connected_at", 0.0)
    real_sleep = asyncio.sleep

    async def one_round(seconds):
        if fixed:
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(d.asyncio, "sleep", one_round)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(d._nudger())
    assert fixed == [f"{d._spoken_names(active.name)}'s still waiting on your yes or no."]


def _read_in_full(d, active):  # noqa: F811
    active.permission_read_at = active.permission_delivered_at = d.time.time() - 60
    d.state.conn.injector.bot_started_at = active.permission_delivered_at + 0.1  # the read-out, and nothing since


def test_a_yes_after_the_reminder_approves_the_one_request_read_in_full(d, monkeypatch):  # noqa: F811
    active, posts, said = _read_out_setup(d, monkeypatch)
    _read_in_full(d, active)
    _remind(d, monkeypatch, active)
    asyncio.run(d.on_user_utterance("Yes, run it."))
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "allow"}]
    assert not any("rm -rf build" in s for s in said)  # not read again


def test_anything_else_said_since_the_read_out_still_reads_it_again(d, monkeypatch):  # noqa: F811
    active, posts, said = _read_out_setup(d, monkeypatch)
    _read_in_full(d, active)
    d._note_bot_speech("All the tests passed in the other session.")  # another line after the read-out
    _remind(d, monkeypatch, active)
    asyncio.run(d.on_user_utterance("Yes, run it."))
    assert verdicts(posts) == [] and said and "rm -rf build" in said[-1]


def test_a_second_pending_request_still_reads_it_again(d, monkeypatch):  # noqa: F811
    active, posts, said = _read_out_setup(d, monkeypatch)
    other = next(s for s in d.REGISTRY.sessions.values() if s is not active)
    with_permission(other, "p2", delivered_at=float("inf"))
    _read_in_full(d, active)
    _remind(d, monkeypatch, active)
    asyncio.run(d.on_user_utterance("Yes, run it."))
    assert verdicts(posts) == [] and said and "rm -rf build" in said[-1]


def test_a_read_out_the_user_cut_still_reads_it_again(d, monkeypatch):  # noqa: F811
    active, posts, said = _read_out_setup(d, monkeypatch)
    _read_in_full(d, active)
    d._read_out_cut_off()  # they talked over it: they may not have heard it all
    _remind(d, monkeypatch, active)
    asyncio.run(d.on_user_utterance("Yes, run it."))
    assert verdicts(posts) == [] and said and "rm -rf build" in said[-1]
