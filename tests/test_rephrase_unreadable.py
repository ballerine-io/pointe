"""A shell command that cannot be read out is sent back once, asking for plain commands, before it strands a voice user.

From the HLK benchmark: 44 of Pointe's 72 permission requests could not be read out (a loop, a python -c with strings,
three commands joined), so a spoken yes could not approve them, and in 31 of 45 failed runs the work stopped there.
The rule stays: a spoken yes approves only what was read out word for word. What changes is the first answer to such a
request while someone is on the call: Claude is told the user is on voice and asked to run the same step as plain
commands, one at a time, which the read-out can say. At most twice in ten minutes per session.

Since "everything can be done by voice" (test_everything_by_voice.py): a short unusual command is read word for word
instead, and only one too long to follow by ear (over REPHRASE_WORDS read) is sent back; after the limit it is read word
for word, never left to a tap.

uv run pytest -q tests/test_rephrase_unreadable.py
"""

import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import add, d, fake_conn  # noqa: E402,F401  (d is the daemon fixture)

LOOP = {"command": "for f in pipeline/a.py pipeline/b.py pipeline/c.py pipeline/d.py; do echo \"== $f\"; "
                   "python3 -m py_compile \"$f\" && wc -l \"$f\" && head -n 40 \"$f\" | grep -n def || echo none; "
                   "done; git status --short; git diff --stat | tail -n 3; ls -la pipeline tests scripts"}
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


def test_at_most_twice_then_read_word_for_word(d):  # noqa: F811
    s = add(d, "b", "billing")
    d.state.conn = fake_conn()
    assert d._rephrase_first(s, "Bash", LOOP, None) is not None
    assert d._rephrase_first(s, "Bash", LOOP, None) is not None
    assert d._rephrase_first(s, "Bash", LOOP, None) is None
    assert "word for word" in d.spoken_request("Bash", LOOP, s.cwd)


def test_no_call_or_not_a_shell_command_is_left_alone(d):  # noqa: F811
    s = add(d, "b", "billing")
    d.state.conn = None
    assert d._rephrase_first(s, "Bash", LOOP, None) is None
    d.state.conn = fake_conn()
    assert d._rephrase_first(s, "WebFetch", {"url": "https://example.com"}, None) is None


MEASURED = {"command": 'pwd; ls -la; git log --oneline --all; git status --short; python3 -c "import unirest" 2>&1; '
                       'python3 -m pip show unirest 2>&1 | head -5'}


def test_a_command_long_to_hear_is_sent_back_though_it_is_few_words(d):  # noqa: F811
    """From the independent tester's third round: this one was read word for word for 27 seconds ("python 3 dash c
    import unirest 2 ampersand greater than 1"). It is 21 words on the page, under the old limit of 40."""
    s = add(d, "b", "billing")
    d.state.conn = fake_conn()
    out = d._rephrase_first(s, "Bash", MEASURED, None)
    assert out and out["hookSpecificOutput"]["decision"]["behavior"] == "deny"
    assert "only read" in out["hookSpecificOutput"]["decision"]["message"]


def test_a_short_unusual_command_and_a_long_look_are_still_put_to_the_user(d):  # noqa: F811
    s = add(d, "b", "billing")
    d.state.conn = fake_conn()
    assert d._rephrase_first(s, "Bash", {"command": "sh scripts/slow_check.sh 3"}, None) is None  # short: word for word
    look = {"command": "pwd && ls -la && git status --short && find . -name 'test*.py' -not -path './.git/*' | head -50"}
    assert d._rephrase_first(s, "Bash", look, None) is None  # long, and only looks: said in a few words
    assert d.spoken_request("Bash", look, s.cwd).startswith("look around, read only:")
