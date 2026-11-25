"""The dialogue suite's scorer (bench/conversational/dialogues/dialogues/score.py) on hand-made rows: what counts as the
first word, a turn left silent, and a stop that had no running job to stop. No keys, no models, no agent."""

import conv_suite

CONV_SUITE = "dialogues"
conv_suite.enter(CONV_SUITE)

from dialogues import score  # noqa: E402


def row(said, turns, hooks=()):
    return {"dialogue": "t-01", "dim": "latency", "ended": 100.0, "changed": [], "said": list(said), "turns": turns,
            "sessions": {"billing": {"prompts": [], "hooks": list(hooks)}}}


def turn(start, end, kind="answer", when="quiet", **expect):
    return {"start": start, "end": end, "say": "x", "lang": "en", "when": when, "need": 5,
            "expect": {"kind": kind, "session": "billing", **expect}}


def test_waiting_sound_is_not_the_first_word():
    r = row([(11.8, 12.0, ""), (12.5, 13.5, "Asking billing.")], [turn(5, 10, facts=["billing"])])
    t = score.turn_scores(r)[0]
    assert t["ttfw"] == 2.5 and t["first_sound"] == 1.8


def test_a_silent_turn_is_the_slowest_first_word_not_left_out():
    spoken = [turn(5, 10), turn(20, 25), turn(40, 45)]
    said = [(11.0, 12.0, "One."), (26.0, 27.0, "Two.")]  # the third turn gets no word at all
    m = score.metrics([row(said, spoken)])
    assert m["silent_turns"] == 1 and m["speech_turns"] == 3
    assert m["ttfw_median"] == 1.0  # 1.0, 1.0, silent: the silent turn sorts last
    assert m["ttfw_p90"] == float("inf")  # the 90th percentile falls on the silent turn: unknown, not 1.0
    assert score.fmt(m["ttfw_p90"]) == "silent"


def test_stop_while_the_job_only_waits_on_a_permission_is_not_scored():
    hooks = [{"name": "PreToolUse", "t": 3.0, "tool": "Bash"}, {"name": "PermissionRequest", "t": 3.1, "tool": "Bash"},
             {"name": "Stop", "t": 13.0}]
    t = score.turn_scores(row([], [turn(5, 10, kind="stop", when="working", within=15)], hooks))[0]
    assert t["job_running"] is False and t["ok"] is None


def test_stop_of_a_running_job_is_scored():
    hooks = [{"name": "PreToolUse", "t": 3.0, "tool": "Bash"}, {"name": "Stop", "t": 13.0}]
    t = score.turn_scores(row([], [turn(5, 10, kind="stop", when="working", within=15)], hooks))[0]
    assert t["job_running"] is True and t["ok"] is True and t["ttua"] == 3.0
