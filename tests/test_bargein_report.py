"""The barge-in set's report (bench/conversational/dialogues/bargein_report.py) on hand-made rows: the first reaction
is the duck where there is one, else the cut; a backchannel the daemon cut counts as a false stop; a clip that landed
while the voice was quiet is left out. No keys, no models, no agent."""

import time

import conv_suite

CONV_SUITE = "dialogues"
conv_suite.enter(CONV_SUITE)

import bargein_report  # noqa: E402

T0 = time.mktime(time.strptime("2026-11-28 10:00:00", "%Y-%m-%d %H:%M:%S"))


def _log(secs: float, text: str) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(T0 + int(secs)))
    return f"{stamp}.{int(round((secs % 1) * 1000)):03d} | INFO     | __main__:x:1 - {text}"


def _row(dialogue: str, log: list, said=((11.0, 30.0, "A long answer goes on and on."),), at_start=True) -> dict:
    turns = [{"start": T0 + 5, "end": T0 + 7, "say": "x", "lang": "en", "when": "idle", "need": 60,
              "expect": {"kind": "answer", "need": 60}},
             {"start": T0 + 14, "end": T0 + 15, "say": "y", "lang": "en", "when": "speaking", "need": 0,
              "speaking_at_start": at_start, "expect": {"kind": "none", "need": 0}}]
    return {"dialogue": dialogue, "dim": "turn-taking", "ended": T0 + 60, "changed": [], "turns": turns,
            "said": [(T0 + s, T0 + e, x) for s, e, x in said], "log": log, "sessions": {"billing": {"prompts": [], "hooks": []}}}


def test_the_first_reaction_is_the_duck_where_the_build_has_one():
    r = bargein_report.row_result(_row("bi-int-01", [_log(14.21, "voice ducked"), _log(14.9, "barge-in: 'wait stop'")]))
    assert r["kind"] == "interrupt" and r["react"] == 0.21 and r["ducked"] and r["cut"]


def test_without_a_duck_the_first_reaction_is_the_cut():
    r = bargein_report.row_result(_row("bi-int-02", [_log(14.9, "barge-in: voice well above the echo")]))
    assert r["react"] == 0.9 and not r["ducked"]


def test_a_backchannel_the_daemon_cut_is_a_false_stop_and_its_resume_is_seen():
    r = bargein_report.row_result(_row("bi-back-01", [_log(14.6, "barge-in: voice well above the echo"),
                                                      _log(15.8, "reply resumed from the sentence that was cut (x)")]))
    assert r["kind"] == "backchannel" and r["cut"] and r["resumed"]
    kept = bargein_report.row_result(_row("bi-back-02", [_log(14.2, "voice ducked"), _log(14.7, "voice back to full volume")]))
    assert kept["ducked"] and not kept["cut"]


def test_a_backchannel_the_daemon_let_through_is_not_a_cut():
    """The daemon logs "no barge-in: a backchannel over the voice": that line is the opposite of a cut."""
    r = bargein_report.row_result(_row("bi-back-04", [_log(14.2, "voice ducked"),
                                                      _log(14.6, "no barge-in: a backchannel over the voice: ' Ok'")]))
    assert not r["cut"] and r["react"] == 0.2


def test_lines_outside_the_turn_do_not_count():
    r = bargein_report.row_result(_row("bi-back-03", [_log(9.0, "barge-in: earlier"), _log(13.0, "voice ducked")]))
    assert not r["cut"] and not r["ducked"] and r["react"] is None


def test_a_clip_that_landed_while_the_voice_was_quiet_is_left_out(tmp_path, monkeypatch):
    import json

    run = tmp_path / "results" / "r1"
    run.mkdir(parents=True)
    rows = [_row("bi-back-01", [_log(14.6, "barge-in: x")]), _row("bi-back-02", [], at_start=False)]
    (run / "rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    monkeypatch.setattr(bargein_report, "HERE", tmp_path)
    text = bargein_report.report(["r1"])
    assert "2 rows, 1 landed while the voice was quiet" in text and "false stop): 1/1" in text
