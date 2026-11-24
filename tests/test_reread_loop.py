"""A yes said a beat early, over the bot, never approves, and must not loop. Replays a live run at rig echo 0.3
(scenarios.py brain): "כן, תאשר." begun over the read-out was refused and the whole request was read again. Soniox split
the answer in two, so "תאשר." cut that re-read off and was refused too, and the request was read again, 24 times."""

import asyncio
import sys
import time
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_orchestrator import _read_out_setup, d, verdicts  # noqa: E402,F401

REQUEST = "run: python3 pytest"
COMMAND = "python3 pytest"  # what a Hebrew read-out says word for word; its verb is said in Hebrew (test_hebrew_readout_verb.py)


def _hebrew_request(d, monkeypatch):
    active, posts, said = _read_out_setup(d, monkeypatch)
    active.permission_spoken = REQUEST
    d.state.last_utterance = "תבקש מקלוד קוד לתקן את הבאג ולהריץ את הבדיקות."
    return active, posts, said


def _early(d, text: str, cut_the_bot: bool) -> None:
    """The user's words, begun while the bot talked; with `cut_the_bot`, their final still arrives over it."""
    d.ECHO.bot_started()
    if cut_the_bot:
        d._read_out_cut_off()  # the final-path barge-in: InterruptionFrame -> BrainFront
    else:
        d.ECHO.bot_stopped()
    d.state.user_started_at = d.ECHO.stopped_at - 0.5 if not cut_the_bot else time.time() - 0.5
    asyncio.run(d.on_user_utterance(text))


def _fresh_yes(d, text: str = "כן, תאשר.") -> None:
    d.ECHO.bot_started()
    d.ECHO.bot_stopped()
    d.ECHO.stopped_at = time.time() - 5
    d.state.user_started_at = time.time() - 1
    d.state.conn.injector.bot_started_at = time.time()
    asyncio.run(d.on_user_utterance(text))


def test_an_early_yes_gets_one_short_line_and_the_split_answer_does_not_loop(d, monkeypatch):
    active, posts, said = _hebrew_request(d, monkeypatch)
    asyncio.run(d._read_out(active))
    assert said[-1].endswith("לבצע?") and COMMAND in said[-1]
    reads = len(said)

    _early(d, "כן.", cut_the_bot=False)  # begun over the read-out's last words; the read-out itself was heard
    assert verdicts(posts) == []
    assert len(said) == reads + 1 and COMMAND not in said[-1] and "אחרי שאני מסיים" in said[-1]

    _early(d, "תאשר.", cut_the_bot=True)  # the split answer's second half, over that line, cuts it off
    assert verdicts(posts) == []
    assert len(said) == reads + 2 and COMMAND not in said[-1]

    _early(d, "כן.", cut_the_bot=True)  # a third: nothing more is said, it waits for a fresh yes or a tap
    assert verdicts(posts) == [] and len(said) == reads + 2

    _fresh_yes(d)
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "allow"}]


def test_an_early_yes_that_cut_the_read_out_hears_it_again_at_most_twice(d, monkeypatch):
    active, posts, said = _hebrew_request(d, monkeypatch)
    asyncio.run(d._read_out(active))
    reads = len(said)

    _early(d, "כן.", cut_the_bot=True)  # over the read-out, which it cut: the request was not heard to its end
    assert verdicts(posts) == []
    assert len(said) == reads + 1 and "אחרי שאני מסיים" in said[-1] and COMMAND in said[-1]

    _early(d, "תאשר.", cut_the_bot=True)
    _early(d, "כן.", cut_the_bot=True)
    _early(d, "תאשר.", cut_the_bot=True)
    assert verdicts(posts) == [] and len(said) == reads + 2  # bounded: two, then it waits

    _fresh_yes(d)  # the last read-out was cut: this yes brings it once more, and does not approve
    assert verdicts(posts) == [] and COMMAND in said[-1]
    _fresh_yes(d)
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "allow"}]


def test_an_early_yes_in_english_gets_the_line_in_english(d, monkeypatch):
    active, posts, said = _read_out_setup(d, monkeypatch)
    d.state.last_utterance = "Run the tests in this repo."
    asyncio.run(d._read_out(active))
    _early(d, "Yes, go ahead.", cut_the_bot=False)
    assert verdicts(posts) == [] and said[-1] == "I need the yes after I finish. Say it again."
