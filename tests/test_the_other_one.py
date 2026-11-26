""""And how many tests are failing in the other one?" with two sessions goes to the one not just asked.

Tester round 6 (t3-02; 3 of 4 samples): after a question to one session, "the other one" got "Which session do you
mean? Billing or Lantern?" With two sessions and the last request sent to one of them, it has one meaning.

uv run pytest -q tests/test_the_other_one.py
"""

import sys
import time
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import add, d  # noqa: E402,F401  (d is the daemon fixture)


def _two(d):  # noqa: F811
    lantern, billing = add(d, "l", "lantern/main"), add(d, "b", "billing/main")
    d.state.thread = (lantern.id, time.time())  # the last request went to lantern
    return lantern, billing


@pytest.mark.parametrize("said,message", [
    ("And how many tests are failing in the other one?", "How many tests are failing?"),
    ("How many tests are failing in the other session?", "How many tests are failing?"),
])
def test_the_other_one_is_the_session_not_just_asked(d, said, message):  # noqa: F811
    lantern, billing = _two(d)
    assert d._fast_send(said) == (billing, message)


def test_with_three_sessions_the_other_one_is_the_models(d):  # noqa: F811
    _two(d)
    add(d, "h", "harbor/main")
    assert d._fast_send("And how many tests are failing in the other one?") is None


def test_with_nothing_asked_yet_the_other_one_is_the_models(d):  # noqa: F811
    _two(d)
    d.state.thread = None
    assert d._fast_send("And how many tests are failing in the other one?") is None
