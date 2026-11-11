"""Defects an independent bug hunt proved at 0defe50, each as the scenario that showed it. Ordered as fixed."""

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ptt  # noqa: E402
import meeting as meetings  # noqa: E402
from test_orchestrator import add, d, with_permission  # noqa: E402,F401  (d is a fixture)
from test_meeting_daemon import _meeting_ready, _start  # noqa: E402
from test_speaker import OTHER_HZ, OWNER_HZ, tone  # noqa: E402
from test_voice_lock import v  # noqa: E402,F401  (fixture: an enrolled voice lock on a fake model)

T0 = 1000.0


# ---------- 1. voice lock at Commands / Everything: a no from another voice still denies ----------

def _real_ears(d, monkeypatch):
    """SonioxEars with its real _take, so a final transcript reaches on_user_utterance."""
    from test_voice_lock import FrameDirection, InputAudioRawFrame, TranscriptionFrame, VADUserStartedSpeakingFrame, \
        VADUserStoppedSpeakingFrame
    ears = d.SonioxEars()

    async def noop(*_a, **_k):
        pass

    monkeypatch.setattr(ears, "broadcast_interruption", noop)
    monkeypatch.setattr(ears, "push_frame", noop)
    monkeypatch.setattr(ears, "create_task", lambda coro, name=None: asyncio.get_running_loop().create_task(coro))
    monkeypatch.setattr(d.FrameProcessor, "process_frame", lambda self, f, dirn: asyncio.sleep(0))

    async def utter(hz: float, text: str, secs: float = 2.0) -> None:
        down = FrameDirection.DOWNSTREAM
        await d.SonioxEars.process_frame(ears, VADUserStartedSpeakingFrame(), down)
        pcm = tone(hz, secs)
        for i in range(0, len(pcm), 640):
            await d.SonioxEars.process_frame(ears, InputAudioRawFrame(audio=pcm[i:i + 640], sample_rate=16000, num_channels=1), down)
        await d.SonioxEars.process_frame(ears, VADUserStoppedSpeakingFrame(), down)
        await d.SonioxEars.process_frame(ears, TranscriptionFrame(text=text, user_id="u", timestamp="t"), down)
    return utter


@pytest.mark.parametrize("lvl", ["commands", "everything"])
def test_a_no_from_another_voice_still_denies_at_commands_and_everything(d, v, monkeypatch, lvl):
    """Rule: a "no" from any voice counts (speaker.py: 'A "no" counts from anyone'). At Commands and Everything the
    intake gate drops the stranger's words before on_user_utterance sees them, so the pending tool call stays pending."""
    from test_orchestrator import _consent_setup, verdicts
    d.PREFS.update({"voice_lock": lvl})
    active, posts = _consent_setup(d, monkeypatch)
    utter = _real_ears(d, monkeypatch)

    async def resume_cut(since):
        pass

    d.state.conn.injector.resume_cut = resume_cut
    asyncio.run(utter(OTHER_HZ, "no, don't"))
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "deny"}], (verdicts(posts), active.permission_id)


def test_the_owners_no_and_a_strangers_no_at_approvals_deny_through_the_same_path(d, v, monkeypatch):
    from test_orchestrator import _consent_setup, verdicts
    d.PREFS.update({"voice_lock": "commands"})
    active, posts = _consent_setup(d, monkeypatch)
    utter = _real_ears(d, monkeypatch)

    async def resume_cut(since):
        pass

    d.state.conn.injector.resume_cut = resume_cut
    asyncio.run(utter(OWNER_HZ, "no, don't"))
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "deny"}]
    d.PREFS.update({"voice_lock": "approvals"})
    with_permission(active, "p2", delivered_at=1.0)
    asyncio.run(utter(OTHER_HZ, "no, don't"))
    assert verdicts(posts)[-1] == {"request_id": "p2", "behavior": "deny"}


# ---------- 2. push to talk: a press does not survive a microphone setting change ----------

def test_a_press_closes_when_the_microphone_leaves_push_to_talk():
    """Rule: in push to talk, room audio never reaches the conversation unless pressed. A press is open; the setting goes
    to "always" and back to "ptt". The clients forget their press on a mode change, so a press left open would pass
    audio with no thumb on it for up to 90 s. Only the switch-back tail (the sentence under way) may pass."""
    p = ptt.Ptt()
    assert p.press(T0)
    assert p.audio(640, "ptt", T0 + 0.1)
    assert p.tick("always", T0 + 1.0) == ["closed"], "the setting changed under the press: it ends"
    assert p.closed_why == "the microphone setting changed"
    assert p.audio(640, "always", T0 + 1.1)
    p.tick("ptt", T0 + 2.0)
    assert not p.open
    after_the_tail = T0 + 2.0 + ptt.TAIL_SECS + ptt.LINK_SLACK_SECS + 0.1
    assert not p.audio(640, "ptt", after_the_tail), "no press is held, so no audio may pass"


def test_the_daemon_closes_a_press_when_the_microphone_setting_leaves_push_to_talk(d, monkeypatch):
    """The same, through the daemon's prefs and gate: the setting changes with no release message."""
    monkeypatch.setattr(d, "PREFS", d.Prefs(Path(d.STATE_DIR) / "prefs-ptt.json"))
    d.PREFS.update({"microphone": "ptt"})
    d.state.ptt.reset()
    d.state.ptt.press(T0)
    assert d.state.ptt.audio(640, d.PREFS.get("microphone"), T0 + 0.5)
    d.PREFS.update({"microphone": "always"})
    assert d.state.ptt.audio(640, d.PREFS.get("microphone"), T0 + 1)
    d.PREFS.update({"microphone": "ptt"})
    d.state.ptt.tick(d.PREFS.get("microphone"), T0 + 2)
    assert not d.state.ptt.passes("ptt", T0 + 3)


# ---------- 3. a session's permission request (its exact command) is not put to the brain during a meeting ----------

def test_a_permission_request_during_a_meeting_is_not_told_to_the_brain(d, monkeypatch):
    """_ask_permission feeds the request text with respond=False, which inject() does not hold during a meeting; in
    participating the brain can then say the command into the room when the owner asks it anything."""
    pushed, _ = _meeting_ready(d, monkeypatch)
    monkeypatch.setattr(d, "FRONT", "brain")
    s = add(d, "s1", "pricing")
    d.REGISTRY.active_id = s.id
    _start(d, "participating")
    d.state.front = SimpleNamespace(brain=SimpleNamespace(busy=False), _speak=None)
    asyncio.run(d._put_permission(s, "p9", "Bash", "delete the build folder", '{"command": "rm -rf build"}'))
    told = [t for t, respond in d.state.conn.injector.fed if "rm -rf build" in t]
    assert not told, told
