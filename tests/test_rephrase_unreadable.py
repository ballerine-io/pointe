"""A shell command that cannot be read out is sent back once, asking for plain commands, before it strands a voice user.

From the HLK benchmark: 44 of Pointe's 72 permission requests could not be read out (a loop, a python -c with strings,
three commands joined), so a spoken yes could not approve them, and in 31 of 45 failed runs the work stopped there.
The rule stays: a spoken yes approves only what was read out word for word. What changes is the first answer to such a
request while someone is on the call: Claude is told the user is on voice and asked to run the same step as plain
commands, one at a time, which the read-out can say. At most twice in ten minutes per session; then the tap, as before.

uv run pytest -q tests/test_rephrase_unreadable.py
"""

import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import add, d, fake_conn  # noqa: E402,F401  (d is the daemon fixture)

LOOP = {"command": 'for f in a.py b.py; do echo "== $f"; cat "$f"; done'}
PLAIN = {"command": "python3 -m unittest -v"}


def test_an_unreadable_command_on_a_call_is_sent_back_for_plain_commands(d):  # noqa: F811
    s = add(d, "b", "billing")
    d.state.conn = fake_conn()
    out = d._rephrase_first(s, "Bash", LOOP, None)
    decision = out["hookSpecificOutput"]["decision"]
    assert decision["behavior"] == "deny"
    assert "voice" in decision["message"] and "one at a time" in decision["message"]


def test_a_readable_command_is_put_to_the_user_as_ever(d):  # noqa: F811
    s = add(d, "b", "billing")
    d.state.conn = fake_conn()
    assert d._rephrase_first(s, "Bash", PLAIN, None) is None


def test_at_most_twice_then_the_tap(d):  # noqa: F811
    s = add(d, "b", "billing")
    d.state.conn = fake_conn()
    assert d._rephrase_first(s, "Bash", LOOP, None) is not None
    assert d._rephrase_first(s, "Bash", LOOP, None) is not None
    assert d._rephrase_first(s, "Bash", LOOP, None) is None


def test_no_call_or_not_a_shell_command_is_left_alone(d):  # noqa: F811
    s = add(d, "b", "billing")
    d.state.conn = None
    assert d._rephrase_first(s, "Bash", LOOP, None) is None
    d.state.conn = fake_conn()
    assert d._rephrase_first(s, "WebFetch", {"url": "https://example.com"}, None) is None
