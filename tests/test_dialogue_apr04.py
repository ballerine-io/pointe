"""apr-04 (a destructive request, read in full) must reach its permission request on every run. In the review's runs
the user's line said "its own tmp folder": the agent searched /tmp, where the run's repositories live, and asked which
path, so no delete was ever asked for and the dialogue scored on luck. The file is now at the top of quarry's project
and the line says so. Offline: the suite's spec and fixtures only, no agent, no voice.
"""

import re

import conv_suite

CONV_SUITE = "dialogues"
conv_suite.enter(CONV_SUITE)

from dialogues import spec  # noqa: E402
from dialogues.fixtures import FIXTURES  # noqa: E402


def _apr04():
    return next(d for d in spec.load() if d.id == "apr-04-destructive-read-in-full")


def test_the_file_to_delete_is_at_the_top_of_quarrys_project():
    d = _apr04()
    assert d.sessions == ["quarry"]
    assert "scratch.txt" in FIXTURES["quarry"] and not any("/" in path and "scratch" in path for path in FIXTURES["quarry"])


def test_the_line_names_the_file_and_where_it_is_and_never_a_tmp_folder():
    ask = _apr04().turns[0]
    assert ask.kind == "send" and ask.when == "idle"
    assert "scratch dot t x t" in ask.say and "top of its own project" in ask.say and "r m" in ask.say
    assert not re.search(r"\btmp\b|\btemp\b", ask.say, re.I)


def test_the_delete_itself_needs_a_permission_and_the_yes_answers_it():
    d = _apr04()
    assert not any(re.match(r"Bash\((rm|unlink|trash)\b", rule) for rule in d.allow)  # the delete is never pre-allowed
    yes = d.turns[1]
    assert (yes.say, yes.when, yes.kind) == ("Yes.", "approval", "approve")
    assert yes.expect["request"] == r"\brm\b" and "scratch" in yes.expect["readout"]
