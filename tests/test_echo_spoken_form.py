"""The bot writes "cat README.md"; the speakers say "cat readme dot md". Fragments from a live run at rig echo 0.3
(scenarios.py brain): the read-out of a command cut itself off and came back as the user's words, eight times in a row."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import echo  # noqa: E402
from echo import EchoGuard, spoken_form, words  # noqa: E402

READ_OUT = "cv repo echo wants to run: cat README.md then echo then cat test_pricing.py then echo then python3 pytest. Should it?"


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(echo.time, "time", lambda: now[0])
    return now


def test_the_spoken_form_reads_names_as_the_voice_does():
    assert words(spoken_form("cat README.md then cat test_pricing.py")) == \
        "cat readme dot md then cat test underscore pricing dot py".split()
    assert words(spoken_form("python3 pytest on notes2.text")) == "python three pytest on notes two dot text".split()
    assert words(spoken_form("cd /private/tmp")) == "cd slash private slash tmp".split()
    assert words(spoken_form("rm -rf build --force")) == "rm dash rf build dash dash force".split()
    assert words(spoken_form("UTC+2, 10% off, version 3.8")) == "utc plus two ten percent off version three point eight".split()


def test_a_read_out_of_a_command_does_not_cut_itself_off(clock):
    g = EchoGuard()
    g.bot_said(READ_OUT)
    g.bot_started()
    clock[0] = 103.4
    g.mirror_heard(" cv-repo-echo wants to run", "")  # the mirror trails the words it has not finalized yet
    clock[0] = 108.0
    assert not g.is_barge_in(' cv-repo-echo wants to run "cat readme dot md" then echo then cat test underscore pr',
                             spoken=(100.3, 107.6))
    assert g.is_barge_in(' cv-repo-echo wants to run "cat readme dot md" then. No, wait, run the tests only')


def test_its_echo_after_the_cut_is_not_the_users(clock):
    g = EchoGuard()
    g.bot_said(READ_OUT)
    g.bot_started()
    clock[0] = 103.4
    g.mirror_heard(" cv-repo-echo wants to run", "")
    clock[0] = 107.9
    g.bot_stopped()  # cut off by its own echo
    clock[0] = 109.2
    said = 'cv-repo-echo wants to run "cat readme dot md" then echo then cat test underscore pricing dot.'
    assert g.user_part(said, spoken=(100.3, 107.8)) == ""
    assert g.user_part(said) == ""  # no word timings: inside the arrival tail
