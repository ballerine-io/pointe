"""Defects a second independent bug hunt proved at f9aee53, at the seams between the features (drive, challenge,
briefing, conflicts, whisper, voice lock, meeting), each as the scenario that showed it. Ordered as fixed."""

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_orchestrator import _consent_setup, client_for, d, fake_conn, record_channel, verdicts, with_permission  # noqa: E402,F401
from test_speaker import OTHER_HZ, OWNER_HZ  # noqa: E402
from test_voice_lock import _ears, _utter, heard, level, v  # noqa: E402,F401
from test_challenge import c, start  # noqa: E402,F401

import conflicts  # noqa: E402
import drive  # noqa: E402
import guards  # noqa: E402
import modes  # noqa: E402
from readout import mask  # noqa: E402

SECRET_URL = "postgres://app:hunter22x@db.internal/prod"
A_FINAL = f"The migration ran on staging against DATABASE_URL={SECRET_URL} and passed."
B_FINAL = "The refunds test failed on staging: column refund_reason does not exist."
REPLY = {"conflict": True, "still_current": True,
         "claim_a": f"the migration ran on staging against DATABASE_URL={SECRET_URL} and passed",
         "claim_b": "the refunds test failed on staging: column refund_reason does not exist",
         "why": f"Both talk to {SECRET_URL}; the column cannot both exist and be missing.", "severity": "high",
         "question_for_a": f"Did the migration run against {SECRET_URL}?", "question_for_b": "Which database did the test use?"}


def _report(sid, name, final, at):
    return conflicts.Report(session_id=sid, name=name, agent="Claude", cwd="/tmp/acme", root="/tmp/acme", branch="main",
                            at=at, final=final)


# ---------- 1. a challenge that starts while drive mode is entering lifts the road rules ----------

def test_a_challenge_started_during_the_drive_switch_does_not_lift_the_road_rules(d, c, monkeypatch):
    """set_drive awaits end_challenge (which awaits the brain) before drive.enter(). Words that arrive in that gap can
    start a new challenge; then both are on, current_mode() is CHALLENGE, and _answer_permission skips the road-safety
    and strong-voice checks: a plain yes approves `rm -rf build` while driving."""
    posts = record_channel(d, monkeypatch)
    assert start(d) is None and d.current_mode() is modes.CHALLENGE
    lantern = c.lantern
    with_permission(lantern, "p9", delivered_at=float("inf"))
    lantern.permission_spoken, lantern.permission_cut = "run: rm -rf build", False
    d.state.drive.note("p9", "Bash", {"command": "rm -rf build"}, lantern.cwd)

    said = []

    async def speak(text, request_id=None):
        said.append((text, request_id))
        d._note_bot_speech(text, request_id)

    monkeypatch.setattr(d.state, "front", SimpleNamespace(_speak=speak, brain=SimpleNamespace(busy=False)))
    monkeypatch.setattr(d.ECHO, "speaking", False)
    monkeypatch.setattr(d.ECHO, "stopped_at", 0.0)

    original_feed = d.feed
    raced = []

    async def feed_then_challenge(session, text, respond):  # the ears deliver "challenge this" while the brain is told
        if not raced:
            raced.append(True)
            await d.start_challenge("challenge this")
        await original_feed(session, text, respond)

    monkeypatch.setattr(d, "feed", feed_then_challenge)
    asyncio.run(d.set_drive(True, "button"))
    assert d.state.drive.on()
    # The invariant drive mode promises: while driving, a yes never approves what is not road safe.
    lantern.permission_delivered_at = time.time() - 1
    d.state.conn.injector.bot_started_at = time.time()
    d.state.user_started_at = 0.0
    asyncio.run(d.on_user_utterance("yes"))
    assert verdicts(posts) == [], f"approved while driving: challenge={d.state.challenge is not None}, mode={d.current_mode().name}"


# ---------- 2. conflicts: a session's secret rides the claims to the phone, the notes and the voice ----------

def test_conflict_claims_and_questions_carry_no_credential():
    """The claims are copied from the sessions' messages (by design) and reach /voice/status (the phone), a note, and
    the spoken alarm. briefing.py and challenge.py mask what they quote; conflicts.py does not."""
    alarm = conflicts.Alarm()
    a, b = _report("a", "migrate", A_FINAL, time.time() - 300), _report("b", "refunds", B_FINAL, time.time())
    found = alarm.accept(a, b, REPLY, time.time(), call=object())
    assert found is not None, "the fixture must be a conflict the code accepts"
    shown = json.dumps(found.public(), ensure_ascii=False)  # as the status sends it; escaped, the mask reads as a password
    assert "hunter22x" not in shown, shown
    assert mask(shown) == shown


def test_the_spoken_alarm_carries_no_credential(d):
    alarm = conflicts.Alarm()
    a, b = _report("a", "migrate", A_FINAL, time.time() - 300), _report("b", "refunds", B_FINAL, time.time())
    found = alarm.accept(a, b, REPLY, time.time(), call=object())
    said = d._conflict_speech(found)
    assert "hunter22x" not in said, said


def test_the_conflict_reader_is_never_shown_a_credential():
    a, b = _report("a", "migrate", A_FINAL, time.time() - 300), _report("b", "refunds", B_FINAL, time.time())
    a.say = f"connected with {SECRET_URL}"
    assert "hunter22x" not in conflicts.check_prompt(a, b)


# ---------- 3. drive mode + voice lock Off: the ears never collect the audio the drive rule must score ----------

def test_drive_mode_with_the_lock_off_scores_the_owners_yes_through_the_ears(d, v, monkeypatch):
    """docs: 'Utterances are scored while driving even with the lock Off.' The collector in SonioxEars.process_frame is
    gated on VOICE.wanted(lock_level()) (daemon.py ~868), not on _scores_voices(), so at Off the judge gets no audio:
    every yes is 'I couldn't be sure that was you' and drive-mode voice approval never works with a voiceprint."""
    level(d, "off")
    d.state.conn = fake_conn()
    asyncio.run(d.set_drive(True, "button"))
    assert d._scores_voices()
    ears, taken, _ = _ears(d, monkeypatch)
    asyncio.run(_utter(d, ears, OWNER_HZ, "yes, go ahead", secs=2.0))
    verdict = taken[-1][1]
    assert verdict is not None and verdict.score is not None, f"not scored: {verdict}"
    assert d.speaker.strong(verdict)
