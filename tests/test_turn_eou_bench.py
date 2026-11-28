"""bench/turn_eou.py scores the words with a text end-of-turn model once and replays the rules on the cached scores.
The cache must hold every text the replay can judge, whatever the rule waits, or a rule silently reads no score.
Synthetic rows only; no model runs here."""

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent.parent / "bench")]

import turn_eou  # noqa: E402
import turn_rules  # noqa: E402


def _row(segments, resume=None, pause=None):
    return {"clip": "pause.X.00" if pause else "end.X.00", "voice": "X", "began": 100.0, "resume": resume,
            "pause": pause, "sound_ends": [1.0, 3.0] if resume else [1.0], "stops": [[101.0, 0.5]],
            "segments": [[100.0 + at, text, kind] for at, text, kind in segments]}


ROWS = [
    _row([(1.4, "Move the tests", "fin"), (3.4, "to the shared folder.", "end")], resume=1.9, pause=0.8),
    _row([(1.4, "Move the tests.", "fin"), (2.0, "", "fin"), (3.4, "Then run them.", "end")], resume=2.5, pause=1.2),
    _row([(1.4, "Ship the release notes today.", "end")]),
]


def test_the_cache_holds_every_text_the_replay_judges_at_any_wait():
    for row in ROWS:
        texts = set(turn_eou.judged_texts(row))
        for fixed in (0.0, 0.3, 1.0, 1.3, 3.0, 9.0):
            seen = []

            def wait(text, held, sound, endpoint, paused, fixed=fixed, seen=seen):
                seen.append(text)
                return fixed

            turn_rules.replay(row, wait, False)
            assert set(seen) <= texts, (row["clip"], fixed, set(seen) - texts)


def test_wilson_interval():
    low, high = turn_eou.wilson(5, 10)
    assert abs(low - 0.2366) < 1e-3 and abs(high - 0.7634) < 1e-3
    assert turn_eou.wilson(0, 20)[0] == 0.0
    assert turn_eou.wilson(0, 0) == (0.0, 1.0)


def test_a_rule_on_the_score_keeps_the_text_rules_and_moves_only_whole_sentences():
    scores = {"Ship the release notes today.": {"m": 0.97}, "We should look at the": {"m": 0.99},
              "And the retry loop.": {"m": 0.004}, "Stop.": {"m": 0.001}}
    wait = turn_eou.eou_rule("m", sure=0.9, sure_wait=0.6, doubt=0.01, doubt_wait=2.0, scores=scores)
    assert wait("Ship the release notes today.", False, None, False, False) == 0.6
    assert wait("Ship the release notes today.", True, None, False, False) == 1.3  # said in parts: no shorter wait
    assert wait("We should look at the", False, None, False, False) == 3.0  # reads unfinished, whatever the score
    assert wait("And the retry loop.", False, None, False, False) == 2.0
    assert wait("Stop.", False, None, False, False) == 0.0
    assert wait("Not scored at all, this one.", False, None, False, False) == 1.3
