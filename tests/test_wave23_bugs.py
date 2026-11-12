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
from test_briefing import b, night, sec  # noqa: E402,F401
from test_whisper import _ears as _quiet_ears  # noqa: E402

import briefing  # noqa: E402

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


# ---------- 4. the road allowlist: force-adding an ignored file, then pushing it ----------

@pytest.mark.parametrize("command", ["git add -f .env", "git add -f .env && git commit -m 'env' && git push"])
def test_the_road_refuses_force_adding_ignored_files(command):
    """drive.py: 'sending data ... waits for a tap'. `git add -f` exists to defeat .gitignore, where secrets live; with
    push allowed, a spoken yes from the road publishes them."""
    assert guards.readable_request("Bash", {"command": command}, "/tmp/acme-shop"), command
    assert not drive.road_safe("Bash", {"command": command}, "/tmp/acme-shop"), command


@pytest.mark.parametrize("command", [
    "git add --force .env", "git add -Af .env", "git add --forc .env", "git push --force-with-lease=main",
    "git push --forc", "git push -uf origin main", "git commit --no-ver -m 'x'", "git commit --am -m 'x'",
    "git commit -an -m 'x'", "git pull --upload-pack=/tmp/x", "git fetch --upload-pack=/tmp/x",
    "git push --receive-pack=/tmp/x", "git push --repo=evil", "git diff --output=cart.py", "git log --output cart.py",
    "git -c core.hooksPath=/tmp/x commit -m 'x'", "git -C /tmp status", "git --git-dir=/tmp/x status", "git st",
])
def test_the_road_refuses_git_force_and_command_flags_in_every_spelling(command):
    """Git takes a long option by any unambiguous prefix and short ones bundled; neither, nor an option before the
    subcommand or an alias, is on either allowlist (readout's exact flag tokens, drive._SUBS). A guard against widening
    either one."""
    assert not drive.road_safe("Bash", {"command": command}, "/tmp/acme-shop"), command


@pytest.mark.parametrize("command", ["git add -A", "git add cart.py", "git commit -m 'fix the total'",
                                     "git push -u origin feature-cart", "git log -n 5", "git diff --stat"])
def test_the_road_still_allows_plain_git(command):
    assert drive.road_safe("Bash", {"command": command}, "/tmp/acme-shop"), command


# ---------- 5. a briefing asked by voice runs inside a challenge ----------

def test_a_briefing_asked_by_voice_is_refused_during_a_challenge(d, c, monkeypatch):
    """The brain's `briefing` tool is refused in a challenge (modes.CHALLENGE), but the spoken 'brief me' is caught in
    SonioxEars._take before _challenge_words and _briefing_refusal knows nothing of a challenge: the parts are spoken and
    each one is recorded as an objection."""
    assert start(d) is None
    started = []
    monkeypatch.setattr(d, "start_briefing", lambda *a, **k: started.append(a))
    ears = d.SonioxEars()
    asyncio.run(ears._take("brief me on the night"))
    assert not started, "a briefing started inside a challenge"
    assert client_for(d).post("/voice/briefings", json={"action": "start"}).status_code == 409


# ---------- 6. owner rule: a no from any voice denies, in every mode ----------

def test_stop_during_a_briefing_ends_it_and_denies_the_pending_request(d, b, tmp_path, monkeypatch):
    lantern, _, _ = night(d, b, tmp_path)
    d.REGISTRY.active_id = lantern.id
    lantern.permission_delivered_at = lantern.permission_read_at = time.time() - 1
    posts = record_channel(d, monkeypatch)
    d.state.briefing_play = d.BriefingPlay(briefing=briefing.assemble([sec("docs", "done")], "today", "normal", 0, 0))
    asyncio.run(d.SonioxEars()._take("stop"))
    assert d.state.briefing_play is None
    assert [v["behavior"] for v in verdicts(posts)] == ["deny"] and lantern.permission_id is None


@pytest.mark.parametrize("words", ["enough", "די", "skip"])
def test_a_briefing_word_that_is_no_no_answers_nothing(d, b, tmp_path, monkeypatch, words):
    lantern, _, _ = night(d, b, tmp_path)
    d.REGISTRY.active_id = lantern.id
    lantern.permission_delivered_at = lantern.permission_read_at = time.time() - 1
    posts = record_channel(d, monkeypatch)
    d.state.briefing_play = d.BriefingPlay(briefing=briefing.assemble([sec("docs", "done")], "today", "normal", 0, 0))
    asyncio.run(d.SonioxEars()._take(words))
    assert verdicts(posts) == [] and lantern.permission_id == "p9"


# ---------- 7. "back to normal" with several modes on: drive, then the challenge, then whisper ----------

def test_back_to_normal_ends_drive_then_the_challenge_then_whisper(d, c, monkeypatch):
    """One "back to normal" ends one mode, in one order: drive mode, then a challenge, then whisper mode. Drive and a
    challenge are never on together (set_drive ends the challenge); both are forced on here to pin the order anyway."""
    ears, reached, _ = _quiet_ears(d, monkeypatch)
    d.PREFS.update({"whisper": True})
    assert start(d) is None
    d.state.drive.enter("button")
    asyncio.run(ears._take("back to normal"))
    assert not d.state.drive.on() and d.state.challenge is not None and d.PREFS.get("whisper") is True
    asyncio.run(ears._take("back to normal"))
    assert d.state.challenge is None and d.PREFS.get("whisper") is True
    asyncio.run(ears._take("back to normal"))
    assert d.PREFS.get("whisper") is False and not reached


def test_stop_whispering_during_a_challenge_ends_whisper_only(d, c, monkeypatch):
    ears, reached, _ = _quiet_ears(d, monkeypatch)
    d.PREFS.update({"whisper": True})
    assert start(d) is None
    asyncio.run(ears._take("stop whispering"))
    assert d.PREFS.get("whisper") is False and d.state.challenge is not None


# ---------- 8. "drive mode" said while a meeting is starting ----------

def test_drive_mode_by_voice_is_refused_while_a_meeting_starts(d, monkeypatch):
    """The route refuses it (409) while state.meeting_starting; a held half sentence released by _release_held can
    still reach _take in that gap."""
    ears, reached, _ = _quiet_ears(d, monkeypatch)
    d.state.conn = fake_conn()
    d.state.meeting_starting = True
    try:
        asyncio.run(ears._take("drive mode"))
        assert not d.state.drive.on() and not reached
        assert client_for(d).post("/voice/drive", json={"on": True}).status_code == 409
    finally:
        d.state.meeting_starting = False

