"""The owner-voice lock's own rules, offline: when a score counts as the owner, how a voiceprint is learned and stored,
and that every failure reads as "not the owner". The speaker model is faked: a "voice" is a tone, and the fake embedding
is a bump at the tone's pitch, so two voices are far apart and one voice matches itself.

uv run pytest -q tests/test_speaker.py
"""

import asyncio
import os
import stat
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import speaker  # noqa: E402
from speaker import Verdict, owner_confident  # noqa: E402

OWNER_HZ, OTHER_HZ = 180.0, 420.0


def tone(hz: float, secs: float, amp: float = 0.3) -> bytes:
    t = np.arange(int(secs * speaker.RATE)) / speaker.RATE
    return (np.sin(2 * np.pi * hz * t) * amp * 32767).astype(np.int16).tobytes()


class FakeEmbedder:
    """Pitch -> a unit vector with a bump at that pitch: the same voice scores ~1, another ~0."""

    state = "ready"
    error = None

    def __init__(self, fail: Exception | None = None, delay: float = 0.0):
        self.fail, self.delay, self.calls = fail, delay, 0

    def embed(self, samples: np.ndarray) -> np.ndarray:
        self.calls += 1
        if self.delay:
            import time
            time.sleep(self.delay)
        if self.fail:
            raise self.fail
        spectrum = np.abs(np.fft.rfft(samples[:16000] if len(samples) >= 16000 else samples, n=16000))
        hz = float(np.argmax(spectrum))
        bins = np.arange(64) * 12.5
        v = np.exp(-((bins - hz) / 40.0) ** 2) + 1e-3
        return (v / np.linalg.norm(v)).astype(np.float32)


def lock(tmp_path, embedder=None) -> speaker.VoiceLock:
    return speaker.VoiceLock(tmp_path / "voiceprint", tmp_path / "models", embedder or FakeEmbedder())


def enrol(v: speaker.VoiceLock, hz: float = OWNER_HZ, device: str = "MacBook mic") -> None:
    v.start_enrolment(device)
    for _ in range(speaker.ENROL_SEGMENTS + 2):
        if v.enrolment is None:
            break
        v.collector.frame(tone(hz, 5.5), voiced=True)
        asyncio.run(v.judge())
    assert v.enrolment is None and v.enrolled


# ---------- when a score counts as the owner ----------

NOW = 1000.0
STRONG = Verdict(0.8, 3.0, "mac", NOW - 10)


@pytest.mark.parametrize("v, previous, want", [
    (Verdict(0.8, 3.0, "mac", NOW), None, True),  # a confident sentence on its own
    (Verdict(0.8, 0.5, "mac", NOW), None, False),  # too short to stand alone, however high
    (Verdict(speaker.T_LOW + 0.01, 0.5, "mac", NOW), STRONG, True),  # a short "yes" right after a confident sentence
    (Verdict(speaker.T_LOW + 0.01, 0.5, "phone", NOW), STRONG, False),  # but not on another device's profile
    (Verdict(speaker.T_LOW + 0.01, 0.5, "mac", NOW + speaker.CONTINUITY_SECS), STRONG, False),  # nor a minute later
    (Verdict(speaker.T_LOW - 0.01, 0.5, "mac", NOW), STRONG, False),  # nor below the low bar
    (Verdict(None, 3.0, "", NOW, "model failed"), STRONG, False),  # not scored: never the owner
    (None, STRONG, False),
    (Verdict(speaker.T_LOW + 0.01, 3.0, "mac", NOW), Verdict(speaker.T_LOW + 0.01, 3.0, "mac", NOW - 5), False),  # no chain of weak ones
])
def test_owner_confident_truth_table(v, previous, want):
    assert owner_confident(v, previous) is want


def test_thresholds_are_ordered():
    assert -1 < speaker.T_LOW < speaker.T_HIGH < 1


# ---------- enrolment and the voiceprint on disk ----------

def test_enrolment_learns_the_voice_and_the_file_is_private(tmp_path):
    v = lock(tmp_path)
    enrol(v)
    folder = tmp_path / "voiceprint"
    files = list(folder.glob("*.npz"))
    assert len(files) == 1
    assert stat.S_IMODE(os.stat(folder).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(files[0]).st_mode) == 0o600
    assert v.status("approvals")["devices"][0]["device"] == "MacBook mic"
    again = speaker.VoiceLock(folder, tmp_path / "models", FakeEmbedder())  # a daemon restart reads it back
    assert again.enrolled and again.profiles.devices()[0]["device"] == "MacBook mic"


def test_enrolment_skips_short_and_quiet_segments(tmp_path):
    v = lock(tmp_path)
    v.start_enrolment("MacBook mic")
    v.collector.frame(tone(OWNER_HZ, 0.6), voiced=True)  # too short
    asyncio.run(v.judge())
    v.collector.frame(tone(OWNER_HZ, 3.0, amp=0.002), voiced=True)  # too quiet
    asyncio.run(v.judge())
    e = v.status("off")["enrolling"]
    assert e["segments"] == 0 and e["rejected"] == 2 and e["last_reason"] == "too quiet"
    v.collector.frame(tone(OWNER_HZ, 3.0), voiced=True)
    asyncio.run(v.judge())
    e = v.status("off")["enrolling"]
    assert e["segments"] == 1 and 0 < e["progress"] < 1 and e["text"] == speaker.LINES[1]


def test_an_unfinished_enrolment_expires(tmp_path):
    v = lock(tmp_path)
    v.start_enrolment("iPhone")
    v.expire(now=v.enrolment.started_at + speaker.ENROL_EXPIRES_SECS + 1)
    assert v.enrolment is None and not v.enrolled


def test_delete_one_device_or_all(tmp_path):
    v = lock(tmp_path)
    enrol(v, device="MacBook mic")
    enrol(v, device="iPhone")
    assert {d["device"] for d in v.profiles.devices()} == {"MacBook mic", "iPhone"}
    assert v.profiles.delete("iPhone") == 1
    assert [d["device"] for d in v.profiles.devices()] == ["MacBook mic"]
    v.profiles.delete()
    assert not v.enrolled and not list((tmp_path / "voiceprint").iterdir())


def test_a_damaged_voiceprint_keeps_the_lock_closed(tmp_path):
    folder = tmp_path / "voiceprint"
    folder.mkdir()
    (folder / "macbook-mic.npz").write_bytes(b"not a voiceprint")
    v = speaker.VoiceLock(folder, tmp_path / "models", FakeEmbedder())
    assert v.enrolled  # never read as "no voiceprint", which would lift the lock
    assert "could not be read" in v.problem("commands")
    v.profiles.delete()
    assert not v.enrolled


# ---------- scoring ----------

def test_the_owner_matches_and_another_voice_does_not(tmp_path):
    v = lock(tmp_path)
    enrol(v)
    v.collector.frame(tone(OWNER_HZ, 2.0), voiced=True)
    mine = asyncio.run(v.judge())
    assert v.confident(mine) and mine.device == "MacBook mic"
    v.collector.frame(tone(OTHER_HZ, 2.0), voiced=True)
    theirs = asyncio.run(v.judge())
    assert theirs.score is not None and not v.confident(theirs)


def test_a_short_yes_leans_on_the_sentence_before_it(tmp_path):
    v = lock(tmp_path)
    enrol(v)
    v.collector.frame(tone(OWNER_HZ, 2.0), voiced=True)
    asyncio.run(v.judge())
    v.collector.frame(tone(OWNER_HZ, 0.5), voiced=True)
    assert v.confident(asyncio.run(v.judge()))
    v.collector.frame(tone(OTHER_HZ, 0.5), voiced=True)
    assert not v.confident(asyncio.run(v.judge()))


def test_only_voiced_audio_since_the_last_utterance_is_scored(tmp_path):
    c = speaker.Collector()
    for voiced, hz in ((False, OTHER_HZ), (True, OWNER_HZ)):  # room noise between turns, then the voice; 20 ms frames
        pcm = tone(hz, 1.0)
        for i in range(0, len(pcm), 640):
            c.frame(pcm[i:i + 640], voiced=voiced)
    got = c.take()
    assert abs(speaker.secs_of(got) - (1.0 + speaker.Collector.PREROLL_SECS)) < 0.05  # the voice, and a beat before it
    assert c.take() == b""


@pytest.mark.parametrize("embedder, why", [
    (FakeEmbedder(fail=RuntimeError("onnx")), "did not answer"),
    (FakeEmbedder(delay=speaker.SCORE_TIMEOUT_SECS + 0.4), "did not answer"),
])
def test_a_model_failure_or_a_slow_score_is_not_the_owner(tmp_path, embedder, why):
    v = lock(tmp_path)
    enrol(v)
    v.embedder = embedder
    v.collector.frame(tone(OWNER_HZ, 2.0), voiced=True)
    verdict = asyncio.run(v.judge())
    assert verdict.score is None and not v.confident(verdict)
    assert why in v.problem("approvals")


def test_too_little_audio_is_not_scored(tmp_path):
    v = lock(tmp_path)
    enrol(v)
    verdict = asyncio.run(v.judge())
    assert verdict.score is None and verdict.why == "too little audio"


def test_the_lock_on_without_a_voiceprint_says_why():
    v = speaker.VoiceLock(Path("/nonexistent/voiceprint"), Path("/nonexistent/models"), FakeEmbedder())
    assert v.problem("off") is None
    assert v.problem("approvals") == "no voiceprint is stored"


def test_ignored_speech_keeps_no_words_in_the_log(tmp_path, capfd):
    from loguru import logger

    sink = []
    handle = logger.add(lambda m: sink.append(str(m)), level="INFO")
    try:
        v = lock(tmp_path)
        v.ignore(Verdict(0.12, 1.8, "mac", NOW), text="push the release branch now")
    finally:
        logger.remove(handle)
    assert any("ignored: not the owner (1.8 s, score 0.12)" in line for line in sink)
    assert not any("release branch" in line for line in sink)
    assert v.status("commands")["ignored"]["count"] == 1


def test_the_model_is_pinned_and_licensed():
    assert len(speaker.MODEL_SHA256) == 64 and speaker.MODEL_URL.startswith("https://")
    assert "Apache-2.0" in speaker.MODEL_LICENSE
