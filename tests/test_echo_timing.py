"""Echo transcripts that arrive late: placed by when their words were said, not by when Soniox sent them.

Fragments are the ones a live run at speaker echo 0.3 let through (tests/e2e/page_challenge.py): Soniox finalizes an echoed
sentence about 3 s after the bot stops, past the arrival-time tail.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import echo  # noqa: E402
from echo import AudioClock, EchoGuard  # noqa: E402

BOT = ("Heads up: Redis lost 41 in-flight retries on the restart test, which breaks your zero-loss bar. Unless you lift "
       "that bar, I'd keep the outbox for Thursday. Holding for now. Want it sent?")
MIRROR = [(3.4, " Heads up: Redis lost"), (5.2, " 41 inflight retries on the rest"), (7.1, "art test, which breaks your zero"),
          (12.2, "-loss bar. Unless you lift that bar, I'd keep the outbox for Thursday. Holding for now. Want it sent?")]
STOP = 12.0  # the bot spoke from 0 to 12 s


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(echo.time, "time", lambda: now[0])
    return now


def _turn(clock) -> EchoGuard:
    g = EchoGuard()
    g.bot_said(BOT)
    g.bot_started()
    for at, chunk in MIRROR:
        if at > STOP and g.speaking:
            clock[0] = 100.0 + STOP
            g.bot_stopped()
        clock[0] = 100.0 + at
        g.mirror_heard(chunk, "")
    return g


def test_a_late_echo_with_one_misheard_word_is_still_echo(clock):
    g = _turn(clock)
    clock[0] = 100.0 + STOP + 2.95  # past the arrival tail: before, one unmatched word ("inflate") made it all the user's
    said = ("Heads up, Redis lost 41 inflate retries on the restart test, which breaks your zero-loss bar. Unless you lift "
            "that bar, I'd keep the outbox for Thursday. Holding for now. Want it sent?")
    assert g.user_part(said, spoken=(100.2, 100.0 + STOP)) == ""


def test_short_echo_fragments_said_over_the_bot_are_echo_however_late(clock):
    g = _turn(clock)
    clock[0] = 100.0 + STOP + 3.5
    assert g.user_part("Restart.", spoken=(106.6, 107.0)) == ""
    assert g.user_part("Test, which.", spoken=(107.0, 107.6)) == ""
    assert g.user_part("Want it sent?", spoken=(110.9, 100.0 + STOP + 0.02)) == ""


def test_without_timing_nothing_changes(clock):
    g = _turn(clock)
    clock[0] = 100.0 + STOP + 3.5
    assert g.user_part("Restart.") == "Restart."  # no word timings (another vendor): the arrival-time rules, as before


def test_a_quick_answer_said_after_the_bot_stopped_stays_the_users(clock):
    g = EchoGuard()
    g.bot_said("Claude Code wants to delete the README. Yes or no?")
    g.bot_started()
    clock[0] += 4
    g.bot_stopped()
    stop = clock[0]
    clock[0] = stop + 3.2  # Soniox's final comes late
    assert g.user_part("Yes.", spoken=(stop + 0.6, stop + 0.9)) == "Yes."
    assert g.user_part("No.", spoken=(stop + 0.6, stop + 0.9)) == "No."


def test_a_new_sentence_after_the_bot_stopped_stays_whole(clock):
    g = _turn(clock)
    clock[0] = 100.0 + STOP + 4.0
    said = "Fine. Do it. Send that to lantern."
    assert g.user_part(said, spoken=(100.0 + STOP + 1.5, 100.0 + STOP + 3.0)) == said
    said = "That risk does not apply, because we have a second region."
    assert g.user_part(said, spoken=(100.0 + STOP + 0.4, 100.0 + STOP + 3.0)) == said  # inside the tail, its own words


def test_the_audio_clock_maps_word_offsets_to_when_they_were_heard():
    c = AudioClock()
    stream = object()
    for i in range(100):  # 2 s of 20 ms chunks, the first arriving at t=50.02
        c.sent(stream, 0.02, 50.0 + (i + 1) * 0.02)
    assert c.wall(1000) == pytest.approx(51.0)
    assert c.span([{"text": "Re", "start_ms": 400, "end_ms": 460}, {"text": "start", "start_ms": 520, "end_ms": 580},
                   {"text": "<end>", "start_ms": 1900, "end_ms": 1960}]) == pytest.approx((50.4, 50.58))
    assert c.wall(2600) is None  # audio it never sent
    c.sent(object(), 0.02, 60.02)  # a reconnect: a new stream starts at 0
    assert c.wall(10) == pytest.approx(60.01)
    assert c.span([{"text": "hi"}]) is None  # no timings: another vendor


CHALLENGE = ("Strongest objection: this plan brings back the queue that lost 41 retries. The challenge is that nothing has "
             "changed since then. What makes Redis safe now?")
CHALLENGE_MIRROR = [(3.3, " Strongest objection. This plan"), (5.2, " brings back the queue that lost"),
                    (7.0, " 41 retries. The challenge is"), (8.9, " that nothing has changed since"), (10.7, " then. What makes")]


def _talking(clock, text, mirror, until) -> EchoGuard:
    g = EchoGuard()
    g.bot_said(text)
    g.bot_started()
    for at, chunk in mirror:
        if at <= until:
            clock[0] = 100.0 + at
            g.mirror_heard(chunk, "")
    clock[0] = 100.0 + until
    return g


def test_a_short_phrase_over_the_bot_is_the_users_unless_the_bot_said_it_then(clock):
    g = _talking(clock, CHALLENGE, CHALLENGE_MIRROR, until=12.0)
    # said at 10.6-11.4 s, while the bot said "then, what makes": its turn holds "challenge" and "this", long before
    assert g.user_part("Challenge this.", spoken=(110.6, 111.4)) == "Challenge this."
    assert g.user_part("Challenge this.", spoken=(109.5, 110.4)) == ""  # over "changed since": a mishearing of it
    assert g.user_part("Changed since.", spoken=(107.6, 108.3)) == ""  # what it was saying right then: echo
    assert g.user_part("Challenge is.", spoken=(105.2, 105.8)) == ""


def test_a_yes_over_the_bot_is_still_echo_when_the_bot_said_yes_earlier(clock):
    g = _talking(clock, "Say yes to allow it, or no. I'll wait while you look at the diff on your screen.",
                 [(3.0, " Say yes to allow it, or no."), (5.0, " I'll wait while you look"), (7.0, " at the diff on")], until=8.0)
    assert g.user_part("Yes.", spoken=(106.8, 107.1)) == ""  # an answer word the bot said stays echo: never loosened
    assert g.user_part("Diff on.", spoken=(105.6, 106.4)) == ""


def test_without_the_mirror_a_short_phrase_over_the_bot_is_judged_as_before(clock):
    g = _talking(clock, CHALLENGE, [], until=12.0)
    assert g.user_part("Challenge this.", spoken=(110.6, 111.4)) == ""  # nothing time-local to compare against


def test_a_short_echo_is_caught_by_the_bots_text_when_the_mirror_lags(clock):
    g = _talking(clock, CHALLENGE, CHALLENGE_MIRROR[:1], until=12.0)  # after a cut-off the mirror can trail by 9 s
    assert g.user_part("Changed since.", spoken=(107.6, 108.3)) == ""
    assert g.user_part("Challenge this.", spoken=(110.6, 111.4)) == "Challenge this."


def test_an_answer_word_near_one_the_bot_said_stays_echo(clock):
    g = _talking(clock, "Okay, I'll hold it. Read the diff on your screen while I wait for the tests to finish.",
                 [(3.0, " Okay, I'll hold it."), (5.0, " Read the diff on your"), (7.0, " screen while I wait")], until=9.0)
    assert g.user_part("OK.", spoken=(107.8, 108.0)) == ""  # "ok" is how the STT can spell its "okay"


def test_the_start_of_its_own_word_does_not_cut_the_bot_off():
    g = EchoGuard()
    g.bot_said("Holding, nothing sent. One risk: Redis lost 41 in-flight retries on the restart test.")
    g.bot_started()
    g.mirror_heard("", " Holding. Nothing")
    assert not g.is_barge_in(" Hold")  # "Holding" half heard: a stop word only if it stays one
    assert not g.is_barge_in(" Holding. No")  # "Nothing" half heard
    assert g.is_barge_in(" Hold on")
    assert g.is_barge_in("stop")
    assert g.is_barge_in(" Holding. Nothing sent. Wait")


def test_text_written_before_two_quick_turns_is_still_the_bots(clock):
    g = EchoGuard()
    g.bot_started()  # an earlier answer, done
    clock[0] += 3
    g.bot_stopped()
    clock[0] = 144.2
    g.bot_said("I've asked cv repo echo to run the tests and report what fails. It's working on it, and I'll tell you "
               "when it reports.")
    clock[0] = 146.9
    g.bot_said("cv repo echo wants to run: ls /private/tmp/cv-repo-echo then echo then ls /private/tmp. Should it?")
    clock[0] = 148.8  # it plays 4.7 s after it was written, and the voice stops and starts again between the two
    g.bot_started()
    clock[0] = 156.4
    g.bot_stopped()
    g.bot_started()
    clock[0] = 164.9
    g.bot_stopped()
    clock[0] = 165.5
    said = ("I've asked cv-repo-echo to run the tests and report what fails. It's working on it, and I'll tell you when it "
            "reports. cv-repo-echo wants to run. ls /private/tmp/cv-repo-echo then.")
    assert g.user_part(said, spoken=(149.3, 164.8)) == ""
    assert not g.is_barge_in(said)


def test_a_long_echo_is_matched_against_the_mirror_for_all_of_it(clock):
    g = EchoGuard()
    g.bot_said("Asked cv repo echo to create notes2.text with the word hello.")
    g.bot_started()
    for at, chunk in [(3.0, " Asked cv repo echo to create"), (5.0, " notes2.text with the word hello."),
                      (8.0, " cv-repo-echo needs an approval I can't read out."), (11.0, " It's on your screen."),
                      (14.0, " Approve it there, or say no."), (17.0, " Back to the earlier report:"),
                      (19.5, " scratch.txt is created, 0 bytes.")]:
        clock[0] = 100.0 + at
        if at in (5.0, 14.0):  # the voice stops and starts again between its pieces
            g.bot_stopped()
            g.bot_started()
        if at == 8.0:
            g.bot_said("cv-repo-echo needs an approval I can't read out. It's on your screen. Approve it there, or say no. "
                       "Back to the earlier report: scratch.txt is created, 0 bytes.")
        g.mirror_heard(chunk, "")
    g.bot_stopped()
    clock[0] = 120.5
    said = ("Asked cv-repo-echo to create notes2.text with the word hello. cv-repo-echo needs an approval I can't read "
            "out. It's on your screen. Approve it there, or say no. Back to the earlier report: scratch.txt is created, "
            "0 bytes.")
    assert g.user_part(said, spoken=(100.4, 119.4)) == ""
