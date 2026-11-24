"""Two echo edges from live runs at rig echo 0.3 (scenarios.py brain): a transcript that starts inside one of the bot's
words, and a reply whose text was written before it played."""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

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


def test_text_queued_behind_another_sentence_is_the_bots(clock):
    g = EchoGuard()
    events = [
        (7.1, "said", "Denied. That check wasn't run, and the README isn't deleted."), (7.4, "start", None),
        (15.3, "stop", None),
        (17.2, "said", "cv-repo-echo: README not deleted; the check was denied, so nothing changed."), (17.4, "start", None),
        (22.3, "stop", None),
        (29.1, "said", "Asked Claude to create the empty scratch file. Not confirmed yet."), (29.3, "start", None),
        (30.4, "said", "cv repo echo wants to write scratch.txt. Should it?"),  # queued behind the sentence playing
        (33.85, "stop", None), (33.85, "start", None),  # the voice stops and starts again inside one reply
        (38.0, "said", "Claude wants to write the empty scratch file. Should it?"),
        (38.5, "stop", None), (38.7, "start", None), (42.1, "stop", None),
        (42.3, "mirror", "Claude wants to write the empty scratch file. Should it?"),  # the only part the mirror got
    ]
    for at, kind, text in events:
        clock[0] = 1000.0 + at
        {"said": lambda: g.bot_said(text), "start": g.bot_started, "stop": g.bot_stopped,
         "mirror": lambda: g.mirror_heard(text, "")}[kind]()
    clock[0] = 1045.1  # Soniox's final, 3 s after the bot stopped
    said = "Echo wants to write scratch.txt, should it? Claude wants to write the empty scratch file, should it?"
    assert g.user_part(said, spoken=(1031.6, 1041.9)) == ""


# From a live call at rig echo 0.3 (tests/e2e/page_conversation.py): the bot announced a session, the user started a brain
# dump as it ended, and Soniox gave one final holding the whole announcement and then the user's thought. The bot had
# stopped and the thought was the user's, so all of it was taken as theirs: the reviewed prompt read "Context: I'm now in
# Session Lantern. It's not waiting on anything. …", and the voice asked whether to send it.

ANNOUNCED = ("I'm now in session lantern. It's not waiting on anything. Last state: No work is recorded for this session "
             "yet. There is nothing done, in progress, failed, or blocked.")
HEARD_BACK = ("I'm now in Session Lantern. It's not waiting on anything. Last state: no work is recorded for this session "
              "yet. There is nothing done, in progress, failed, or blocked.")
THOUGHT = "Ask billing to re-run the invoice check for April."


def _announced(clock) -> EchoGuard:
    g = EchoGuard()
    clock[0] = 1012.0
    g.bot_said(ANNOUNCED)
    g.bot_started()
    clock[0] = 1023.0
    g.mirror_heard(HEARD_BACK, "")
    g.bot_stopped()
    return g


def test_the_bots_whole_sentences_before_the_users_words_are_not_the_users(clock):
    g = _announced(clock)
    clock[0] = 1028.0  # the final: the announcement off the speakers, then the user's thought, as one transcript
    assert g.user_part(f"{HEARD_BACK} {THOUGHT}", spoken=(1012.5, 1027.5)) == THOUGHT


def test_a_sentence_the_user_adds_to_stays_whole_and_so_does_a_short_overlap(clock):
    g = _announced(clock)
    clock[0] = 1028.0
    # not one whole sentence of the bot's before their words: nothing is taken off (the mask is fuzzy; a cut could eat theirs)
    assert g.user_part("It's not waiting on anything, but ask billing anyway.", spoken=(1024.0, 1027.5)) \
        == "It's not waiting on anything, but ask billing anyway."
    assert g.user_part(f"Or blocked. {THOUGHT}", spoken=(1022.5, 1027.5)) == f"Or blocked. {THOUGHT}"  # two words: too few
