""""Going back to the import: who reviews that change?" goes back to the session the import was asked of.

t3-02 in tester round 5 (3 of 3): the user had moved on to billing, then said "Going back to the import, who reviews
that change?". The classifier picked lantern, the right one, and the off-thread guard asked "you were talking about
billing, ask which", so the user heard "That question didn't go out". Words that say they return to an earlier topic,
to a session asked something earlier in this call, go there.

uv run pytest -q tests/test_going_back_to.py
"""

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import add, d  # noqa: E402,F401  (d is the daemon fixture)


def _two(d, monkeypatch, asked_earlier: bool):  # noqa: F811
    billing, lantern = add(d, "b", "ledger"), add(d, "l", "lantern")
    d.REGISTRY.mode = "orchestrator"
    d.state.connected_at = time.time() - 120
    d.state.thread = (billing.id, time.time())
    lantern.last_delegation_at = time.time() - 60 if asked_earlier else 0.0

    async def classify(message, sessions, tie=False):
        return lantern
    monkeypatch.setattr(d, "_classify_target", classify)
    monkeypatch.setattr(d, "_just_mentioned", lambda s: False)
    return billing, lantern


@pytest.mark.parametrize("said", ["Going back to the import, who reviews that change?",
                                  "Back to the import: is the index built?"])
def test_a_return_to_an_earlier_topic_goes_to_the_session_it_was_asked_of(d, monkeypatch, said):  # noqa: F811
    billing, lantern = _two(d, monkeypatch, asked_earlier=True)
    assert asyncio.run(d._route("Who reviews the nightly import change?", said)) == ([lantern], "auto")


def test_without_the_return_or_without_an_earlier_ask_it_is_asked_about_as_before(d, monkeypatch):  # noqa: F811
    billing, lantern = _two(d, monkeypatch, asked_earlier=True)
    assert asyncio.run(d._route("Who reviews the import change?", "Who reviews that change?"))[1] == "off-thread"
    billing, lantern = _two(d, monkeypatch, asked_earlier=False)
    assert asyncio.run(d._route("Who reviews the import change?", "Going back to the import, who reviews it?"))[1] == "off-thread"
