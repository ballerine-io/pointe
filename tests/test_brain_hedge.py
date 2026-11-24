"""A slow model step is hedged: the fast model starts beside it, and the first good answer is used.

From the HLK rerun: while the brain model answered slowly, 26 of 72 runs hit the 8 s limit and heard "The model took
too long to answer". The fast fallback was only tried after the main model's 8 s were up (with 3.5 s left), or never.
Now it starts once the main step has taken HEDGE_AFTER_SECS, and whichever answers first is spoken; the other is
cancelled. A step that is quick never starts the second one.

uv run pytest -q tests/test_brain_hedge.py
"""

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import brain as brain_mod  # noqa: E402
from brain import Brain  # noqa: E402


def _step(delays: dict, calls: list):
    async def step(choice, instructions, messages, decls, heard=None):
        calls.append((choice, time.time()))
        await asyncio.sleep(delays[choice])
        return SimpleNamespace(calls=[{"id": f"s-{choice}", "name": "speak", "args": {"text": f"answer from {choice}"}}],
                               said="", raw=None, vendor=choice.split(":")[0], usage={})
    return step


def _brain(monkeypatch, delays):
    said, calls = [], []

    async def speak(text):
        said.append((text, time.time()))

    monkeypatch.setattr(brain_mod.vendors, "step", _step(delays, calls))
    monkeypatch.setattr(brain_mod, "HEDGE_AFTER_SECS", 0.3)
    monkeypatch.setattr(brain_mod, "FILLER_AFTER_SECS", 2.0)
    monkeypatch.setattr(brain_mod, "STEP_TIMEOUT_SECS", 3.0)
    b = Brain("main:model", "s", [], lambda: "[right now] x", speak, fallback="fast:model")
    b.may_stay_silent = lambda: False
    return b, said, calls


def test_a_slow_step_is_answered_by_the_fast_model_started_beside_it(monkeypatch):
    b, said, calls = _brain(monkeypatch, {"main:model": 5.0, "fast:model": 0.1})
    t0 = time.time()
    asyncio.run(b.turn("How did billing do?"))
    assert [t for t, _ in said] == ["answer from fast:model"]
    assert said[0][1] - t0 < 1.0  # not after the main model's whole timeout
    assert [c for c, _ in calls] == ["main:model", "fast:model"]


def test_a_quick_step_never_starts_the_second_model(monkeypatch):
    b, said, calls = _brain(monkeypatch, {"main:model": 0.05, "fast:model": 0.05})
    asyncio.run(b.turn("How did billing do?"))
    assert [t for t, _ in said] == ["answer from main:model"] and [c for c, _ in calls] == ["main:model"]


def test_the_main_model_still_wins_when_it_finishes_first(monkeypatch):
    b, said, calls = _brain(monkeypatch, {"main:model": 0.5, "fast:model": 2.5})
    asyncio.run(b.turn("How did billing do?"))
    assert [t for t, _ in said] == ["answer from main:model"]


def test_both_slow_is_still_the_slow_line(monkeypatch):
    b, said, calls = _brain(monkeypatch, {"main:model": 9.0, "fast:model": 9.0})
    asyncio.run(b.turn("How did billing do?"))
    assert [t for t, _ in said] == [brain_mod.SLOW_LINE]
