"""Two echo edges from live runs at rig echo 0.3 (scenarios.py brain): a transcript that starts inside one of the bot's
words, and a reply whose text was written before it played."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import echo  # noqa: E402
from echo import EchoGuard  # noqa: E402

COMMAND = ("cv repo echo wants to run: cat README.md then echo then cat pricing.py then echo then cat test_pricing.py then "
           "echo then python3 pytest. Should it?")


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(echo.time, "time", lambda: now[0])
    return now


def test_a_transcript_starting_inside_a_bot_word_does_not_cut_it_off():
    g = EchoGuard()
    g.bot_said(COMMAND)
    g.bot_started()
    assert not g.is_barge_in("On three Pi")  # "pyth|on three pytest": Soniox began a segment inside "python"
    assert g.is_barge_in("On second thought, run the tests only")
    assert g.is_barge_in("No, wait")

