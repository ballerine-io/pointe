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
