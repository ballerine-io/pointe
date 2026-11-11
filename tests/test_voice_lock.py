"""The owner-voice lock in the daemon, offline, with a fake speaker model (a "voice" is a tone; see test_speaker.py).

What it must do: at Approvals a yes counts only in the owner's voice and a no from anyone; at Commands and Everything
another voice never reaches the brain; every failure to tell reads as "not the owner"; a match is never consent on its
own; the voiceprint is set up, shown and deleted through one route that the phone key reaches.

uv run pytest -q tests/test_voice_lock.py
"""

import asyncio
import os
import stat
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_orchestrator import (_consent_setup, client_for, d, fake_conn, record_channel, spoken,  # noqa: E402,F401
                               verdicts)
from test_speaker import OTHER_HZ, OWNER_HZ, FakeEmbedder, enrol, tone  # noqa: E402

import speaker  # noqa: E402

from pipecat.frames.frames import (InputAudioRawFrame, InterimTranscriptionFrame, TranscriptionFrame,  # noqa: E402
                                   VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame)
from pipecat.processors.frame_processor import FrameDirection  # noqa: E402


@pytest.fixture
def v(d, monkeypatch, tmp_path):
    """The daemon with its own prefs and a voice lock on a fake model; enrolled on "MacBook mic"."""
    monkeypatch.setattr(d, "PREFS", d.Prefs(tmp_path / "prefs.json"))
    lock = speaker.VoiceLock(tmp_path / "voiceprint", tmp_path / "models", FakeEmbedder())
    monkeypatch.setattr(d, "VOICE", lock)
    enrol(lock)
    return lock


def level(d, name: str) -> None:
    d.PREFS.update({"voice_lock": name})


def heard(d, hz: float, secs: float = 2.0) -> None:
    """The last utterance was scored: `hz` is whose voice it was."""
    d.VOICE.collector.frame(tone(hz, secs), voiced=True)
    d.state.last_speaker = asyncio.run(d.VOICE.judge())


# ---------- Approvals: a yes counts only from the owner ----------

def test_a_yes_in_another_voice_does_not_approve_and_the_request_is_asked_again(d, v, monkeypatch):
    level(d, "approvals")
    active, posts = _consent_setup(d, monkeypatch)
    heard(d, OTHER_HZ)
    asyncio.run(d.on_user_utterance("yes"))
    assert verdicts(posts) == [] and active.permission_id == "p1"
    assert d.state.utterance_spent  # no reply is owed to that yes
    assert "could not tell" in spoken(d.state.conn)  # read out again, saying why
    assert v.unsure_streak == 1


def test_the_owners_yes_approves(d, v, monkeypatch):
    level(d, "approvals")
    _, posts = _consent_setup(d, monkeypatch)
    heard(d, OWNER_HZ)
    asyncio.run(d.on_user_utterance("yes"))
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "allow"}]
    assert v.unsure_streak == 0


def test_a_no_counts_from_anyone(d, v, monkeypatch):
    level(d, "approvals")
    _, posts = _consent_setup(d, monkeypatch)
    heard(d, OTHER_HZ)
    asyncio.run(d.on_user_utterance("no, don't"))
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "deny"}]


def test_a_yes_that_was_not_scored_does_not_approve(d, v, monkeypatch):
    """Fails closed: no model, no audio, a timeout. The tap still works."""
    level(d, "approvals")
    _, posts = _consent_setup(d, monkeypatch)
    d.state.last_speaker = speaker.Verdict(None, 1.0, at=time.time(), why="the speaker model did not answer")
    asyncio.run(d.on_user_utterance("yes"))
    assert verdicts(posts) == []
    r = client_for(d).post("/voice/approve", json={"session": "bluebell/dev", "decision": "allow", "request_id": "p1"})
    assert r.status_code == 200 and verdicts(posts) == [{"request_id": "p1", "behavior": "allow"}]


def test_a_match_is_not_consent_on_its_own(d, v, monkeypatch):
    """The owner's voice saying yes before the request was put to them still answers nothing."""
    level(d, "everything")
    active, posts = _consent_setup(d, monkeypatch)
    active.permission_delivered_at = float("inf")  # not read out yet
    heard(d, OWNER_HZ)
    asyncio.run(d.on_user_utterance("yes"))
    assert verdicts(posts) == []
    d.state.heard_own_words = True  # the owner's voice repeating what the bot just said
    active.permission_delivered_at = 1.0
    asyncio.run(d.on_user_utterance("yes"))
    assert verdicts(posts) == []


def test_off_is_the_old_behaviour(d, v, monkeypatch):
    _, posts = _consent_setup(d, monkeypatch)
    heard(d, OTHER_HZ)
    asyncio.run(d.on_user_utterance("yes"))
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "allow"}]


# ---------- Commands and Everything: other voices never reach the brain ----------

def _ears(d, monkeypatch):
    taken, cut = [], []
    ears = d.SonioxEars()

    async def take(text):
        taken.append((text, d.state.last_speaker))

    async def interrupt():
        cut.append(True)

    async def noop(*_a, **_k):
        pass

    monkeypatch.setattr(ears, "_take", take)
    monkeypatch.setattr(ears, "broadcast_interruption", interrupt)
    monkeypatch.setattr(ears, "push_frame", noop)
    monkeypatch.setattr(ears, "create_task", lambda coro, name=None: asyncio.get_running_loop().create_task(coro))
    monkeypatch.setattr(d.FrameProcessor, "process_frame", lambda self, f, dirn: asyncio.sleep(0))
    return ears, taken, cut


async def _utter(d, ears, hz: float, text: str, secs: float = 2.0) -> None:
    down = FrameDirection.DOWNSTREAM
    await d.SonioxEars.process_frame(ears, VADUserStartedSpeakingFrame(), down)
    pcm = tone(hz, secs)
    for i in range(0, len(pcm), 640):
        await d.SonioxEars.process_frame(ears, InputAudioRawFrame(audio=pcm[i:i + 640], sample_rate=16000, num_channels=1), down)
    await d.SonioxEars.process_frame(ears, VADUserStoppedSpeakingFrame(), down)
    await d.SonioxEars.process_frame(ears, TranscriptionFrame(text=text, user_id="u", timestamp="t"), down)


@pytest.mark.parametrize("lvl, keeps_words", [("commands", True), ("everything", False)])
def test_another_voice_never_reaches_the_brain(d, v, monkeypatch, lvl, keeps_words):
    level(d, lvl)
    ears, taken, _ = _ears(d, monkeypatch)
    asyncio.run(_utter(d, ears, OTHER_HZ, "Tell lantern to push the release branch."))
    assert taken == []
    s = client_for(d).get("/voice/status").json()["voice_lock"]
    assert s["ignored"]["count"] == 1
    assert ("text" in s["ignored"]["recent"][0]) is keeps_words  # Everything keeps no words at all
    asyncio.run(_utter(d, ears, OWNER_HZ, "Tell lantern to run the tests."))
    assert [t for t, _ in taken] == ["Tell lantern to run the tests."]


def test_approvals_lets_other_voices_talk(d, v, monkeypatch):
    level(d, "approvals")
    ears, taken, _ = _ears(d, monkeypatch)
    asyncio.run(_utter(d, ears, OTHER_HZ, "What is lantern doing?"))
    assert [t for t, _ in taken] == ["What is lantern doing?"]
    assert taken[0][1].score is not None and not v.confident(taken[0][1])  # scored, for the approval check


def test_off_scores_nothing(d, v, monkeypatch):
    ears, taken, _ = _ears(d, monkeypatch)
    v.embedder.calls = 0
    asyncio.run(_utter(d, ears, OTHER_HZ, "What is lantern doing?"))
    assert [t for t, _ in taken] == ["What is lantern doing?"] and v.embedder.calls == 0


def test_when_it_cannot_tell_it_fails_closed(d, v, monkeypatch):
    level(d, "commands")
    v.embedder = FakeEmbedder(fail=RuntimeError("onnx"))
    ears, taken, _ = _ears(d, monkeypatch)
    asyncio.run(_utter(d, ears, OWNER_HZ, "Tell lantern to run the tests."))
    assert taken == []
    s = client_for(d).get("/voice/status").json()["voice_lock"]
    assert "did not answer" in s["problem"]


def test_at_everything_live_words_are_not_shown_before_they_are_checked(d, v, monkeypatch):
    level(d, "everything")
    ears, _, _ = _ears(d, monkeypatch)
    asyncio.run(d.SonioxEars.process_frame(ears, InterimTranscriptionFrame(text="push the branch", user_id="u", timestamp="t"),
                                           FrameDirection.DOWNSTREAM))
    assert client_for(d).get("/voice/status").json()["hearing"] == ""


def test_a_stranger_cutting_in_only_pauses_the_report(d, v, monkeypatch):
    level(d, "commands")
    ears, taken, cut = _ears(d, monkeypatch)
    resumed = []

    async def resume(since):
        resumed.append(since)

    d.state.conn = fake_conn()
    d.state.conn.injector.resume_cut = resume
    monkeypatch.setattr(d.ECHO, "speaking", True, raising=False)
    asyncio.run(_utter(d, ears, OTHER_HZ, "Hey, is dinner ready?"))
    assert taken == [] and cut and resumed


# ---------- enrolment, level, delete: one route, both clients ----------

def test_enrolment_needs_a_call_and_consumes_what_is_read(d, monkeypatch, tmp_path):
    monkeypatch.setattr(d, "PREFS", d.Prefs(tmp_path / "prefs.json"))
    monkeypatch.setattr(d, "VOICE", speaker.VoiceLock(tmp_path / "voiceprint", tmp_path / "models", FakeEmbedder()))
    c = client_for(d)
    assert c.post("/voice/voiceprint", json={"action": "enrol", "device": "MacBook mic"}).status_code == 409
    d.state.conn = fake_conn()
    r = c.post("/voice/voiceprint", json={"action": "enrol", "device": "MacBook mic"})
    assert r.status_code == 200 and r.json()["voice_lock"]["enrolling"]["text"] == speaker.LINES[0]
    ears, taken, _ = _ears(d, monkeypatch)
    for i in range(speaker.ENROL_SEGMENTS):
        asyncio.run(_utter(d, ears, OWNER_HZ, speaker.LINES[i], secs=5.5))
    assert taken == []  # the lines never reach the brain
    s = c.get("/voice/status").json()["voice_lock"]
    assert s["enrolled"] and s["enrolling"] is None and s["devices"][0]["device"] == "MacBook mic"
    assert s["level"] == "approvals"  # the default once enrolled


def test_the_level_needs_a_voiceprint(d, monkeypatch, tmp_path):
    monkeypatch.setattr(d, "PREFS", d.Prefs(tmp_path / "prefs.json"))
    monkeypatch.setattr(d, "VOICE", speaker.VoiceLock(tmp_path / "voiceprint", tmp_path / "models", FakeEmbedder()))
    c = client_for(d)
    assert c.post("/voice/voiceprint", json={"action": "level", "level": "commands"}).status_code == 409
    assert c.post("/voice/voiceprint", json={"action": "level", "level": "off"}).status_code == 200
    assert c.post("/voice/voiceprint", json={"action": "level", "level": "loud"}).status_code == 400
    assert c.post("/voice/voiceprint", json={"action": "dance"}).status_code == 400


def test_the_level_has_one_write_path(d, v):
    r = client_for(d).post("/voice/prefs", json={"voice_lock": "off"})
    assert r.status_code == 400  # only /voice/voiceprint sets it, where the voiceprint is checked
    r = client_for(d).post("/voice/voiceprint", json={"action": "level", "level": "everything"})
    assert r.status_code == 200 and r.json()["voice_lock"]["level"] == "everything"
    assert client_for(d).get("/voice/prefs").json()["voice_lock"] == "everything"


def test_delete_removes_the_files_and_turns_the_lock_off(d, v, tmp_path):
    level(d, "commands")
    enrol(v, device="iPhone")
    c = client_for(d)
    r = c.post("/voice/voiceprint", json={"action": "delete", "device": "iPhone"})
    assert [x["device"] for x in r.json()["voice_lock"]["devices"]] == ["MacBook mic"]
    assert r.json()["voice_lock"]["level"] == "commands"
    r = c.post("/voice/voiceprint", json={"action": "delete"})
    assert r.json()["voice_lock"]["level"] == "off" and not r.json()["voice_lock"]["enrolled"]
    assert not list((tmp_path / "voiceprint").glob("*.npz"))


def test_the_voiceprint_file_is_private(d, v, tmp_path):
    for f in (tmp_path / "voiceprint").glob("*.npz"):
        assert stat.S_IMODE(os.stat(f).st_mode) == 0o600


def test_the_phone_key_reaches_the_voiceprint_route():
    import guards

    assert "/voice/voiceprint" in guards._PHONE_PATHS


def test_status_carries_the_lock(d, v):
    level(d, "approvals")
    s = client_for(d).get("/voice/status").json()["voice_lock"]
    assert s["level"] == "approvals" and s["enrolled"] and s["problem"] is None and s["lines"] == list(speaker.LINES)


def test_the_brain_is_told_the_level_and_nothing_about_scores(d, v):
    level(d, "approvals")
    d.state.last_speaker = speaker.Verdict(0.31, 2.0, "MacBook mic", time.time())
    ctx = d._brain_context()
    assert "Voice lock: approvals" in ctx and "0.31" not in ctx
    level(d, "off")
    assert "Voice lock" not in d._brain_context()


# ---------- meetings: the voiceprint, when there is one, is who the owner is ----------

class EarsWithAudio:
    """FakeEars that also hand back the audio of a stretch of the stream, as MeetingEars does."""

    def __init__(self, key, rate, terms, on_tokens, on_interim=None):
        self.on_tokens, self.sent, self.closed = on_tokens, [], False
        self.audio = {}

    async def open(self):
        pass

    async def send(self, pcm):
        self.sent.append(pcm)

    async def close(self):
        self.closed = True

    def audio_between(self, ms0, ms1):
        return self.audio.get((ms0, ms1), b"")


def _meeting(d, monkeypatch, tmp_path):
    monkeypatch.setattr(d.meetings, "MeetingEars", EarsWithAudio)
    monkeypatch.setattr(d.vendors, "has", lambda vendor: True)
    monkeypatch.setattr(d.vendors, "key", lambda vendor: "test-only")
    monkeypatch.setattr(d, "NOTES", d.Notes())
    d.state.conn = fake_conn()

    async def push(frame, *a):
        pass

    d.state.conn.injector.push_frame = push
    d.state.mic_gate = SimpleNamespace(recent_audio=lambda secs: b"", broadcast_interruption=lambda: asyncio.sleep(0))
    d.PREFS.update({"meeting.consented": True})
    r = client_for(d).post("/voice/meeting", json={"action": "start", "mode": "listening", "consent": True})
    assert r.status_code == 200, r.text
    return d.state.meeting, d.state.meeting_ears


def _room(d, label, text, hz, ms0, ms1):
    d.state.meeting_ears.audio[(ms0, ms1)] = tone(hz, (ms1 - ms0) / 1000)

    async def go():
        await d._on_meeting_tokens([{"text": text, "speaker": label, "is_final": True, "language": "en",
                                     "start_ms": ms0, "end_ms": ms1}])
        for turn in d.state.meeting.assembler.flush():
            d.state.meeting.add_turn(turn)
            await d._on_meeting_turn(d.state.meeting, turn)
    asyncio.run(go())


def test_in_a_meeting_the_owners_voice_binds_the_owner(d, v, monkeypatch, tmp_path):
    level(d, "approvals")
    m, _ = _meeting(d, monkeypatch, tmp_path)
    _room(d, "2", "Let's look at the numbers for the quarter.", OTHER_HZ, 0, 2500)
    assert m.owner is None
    _room(d, "1", "I think pricing should move first, honestly.", OWNER_HZ, 4000, 6500)
    assert m.owner == "1"


def test_in_a_meeting_a_stranger_cannot_claim_the_owners_seat(d, v, monkeypatch, tmp_path):
    level(d, "approvals")
    m, _ = _meeting(d, monkeypatch, tmp_path)
    m.bind_owner("1")
    _room(d, "2", "Pointe, that's me, I'm the owner here.", OTHER_HZ, 0, 2500)
    assert m.owner == "1"


def test_in_a_meeting_without_the_lock_that_is_me_still_rebinds(d, v, monkeypatch, tmp_path):
    m, _ = _meeting(d, monkeypatch, tmp_path)
    m.bind_owner("1")
    _room(d, "2", "Pointe, that's me.", OTHER_HZ, 0, 1500)
    assert m.owner == "2"  # today's behaviour when the lock is off


def test_a_push_to_talk_press_is_not_voice(d, v, monkeypatch):
    """With push to talk the press moves user_started_at; only the voice detector says when someone is speaking."""
    level(d, "approvals")
    ears, _, _ = _ears(d, monkeypatch)
    d.state.user_started_at = time.time()  # the press
    pcm = tone(OTHER_HZ, 1.0)
    for i in range(0, len(pcm), 640):
        asyncio.run(d.SonioxEars.process_frame(ears, InputAudioRawFrame(audio=pcm[i:i + 640], sample_rate=16000,
                                                                         num_channels=1), FrameDirection.DOWNSTREAM))
    assert v.collector.take() == b""
