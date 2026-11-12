"""The bot's own read-out, heard back through the speakers, is never the user's answer to a permission: not a no, not a
yes. Reproduces a live run (the session names are the test registry's: the waiting session is the one named) (synthetic speaker echo): the read-out "…approve it there, or say no" came back as a final
transcript after the echo tail had ended, passed as the user's words, and its "no" denied the request. A no the user
really says, over the bot or after it, still denies.

uv run pytest -q tests/test_echo_permission.py
"""

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_orchestrator import _consent_setup, d, verdicts  # noqa: E402,F401

from echo import EchoGuard  # noqa: E402
from pipecat.frames.frames import TranscriptionFrame  # noqa: E402
from pipecat.processors.frame_processor import FrameDirection  # noqa: E402

READ_OUT = "bluebell needs an approval I can't read out. It's on your screen: approve it there, or say no."
NEXT = "Connected to 3 sessions: bluebell, billing, docs. I'm still catching up on them."
MIRROR = ["Bluebell needs an approval I can't", " read out. It's on your screen.", " Approve it there, or say no. Con",
          "nected to 3 sessions. Bluebell, billing, docs. I'm still catching up on them."]
ECHOED = "On your screen. Approve it there, or say no. Connect it to 3 sessions. Bluebell."  # what the user's ears made of it


@pytest.fixture
def e(d, monkeypatch):
    """The daemon with a fresh echo guard, a pending permission whose read-out was just spoken, and ears that run the
    real final-transcript path into the consent check."""
    guard = EchoGuard()
    monkeypatch.setattr(d, "ECHO", guard)
    active, posts = _consent_setup(d, monkeypatch)
    ears = d.SonioxEars()

    async def noop(*_a, **_k):
        pass

    monkeypatch.setattr(ears, "push_frame", noop)
    monkeypatch.setattr(ears, "broadcast_interruption", noop)
    monkeypatch.setattr(ears, "create_task", lambda coro, name=None: asyncio.get_running_loop().create_task(coro))
    monkeypatch.setattr(d.FrameProcessor, "process_frame", lambda self, f, dirn: asyncio.sleep(0))
    monkeypatch.setattr(d, "ECHO_SETTLE_SECS", 0.0)
    return guard, active, posts, ears


def speak(guard: EchoGuard, *texts: str, mirror: list[str] = ()) -> None:
    guard.bot_started()
    for t in texts:
        guard.bot_said(t)
    for m in mirror:
        guard.mirror_heard(m, "")


def final(d, ears, text: str) -> None:
    asyncio.run(ears.process_frame(TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM))


@pytest.mark.parametrize("after", [3.0, 9.0])  # past the echo tail, and past the late-echo window
def test_the_read_out_heard_back_does_not_deny(d, e, after):
    guard, active, posts, ears = e
    speak(guard, READ_OUT, NEXT, mirror=MIRROR)
    guard.bot_stopped()
    guard.stopped_at = time.time() - after
    final(d, ears, ECHOED)
    assert verdicts(posts) == [] and active.permission_id == "p1"


def test_the_read_out_heard_back_does_not_approve_either(d, e):
    guard, active, posts, ears = e
    speak(guard, "billing wants to run the tests. Say yes to allow it, or no.", mirror=["Billing wants to run the tests.",
                                                                                         " Say yes to allow it, or no."])
    guard.bot_stopped()
    guard.stopped_at = time.time() - 3.0
    final(d, ears, "Say yes to allow it.")
    assert verdicts(posts) == [] and active.permission_id == "p1"


def test_a_no_said_over_the_bot_still_denies(d, e):
    guard, active, posts, ears = e
    speak(guard, READ_OUT, mirror=MIRROR[:2])  # still talking
    final(d, ears, "No, don't run it.")
    assert [v["behavior"] for v in verdicts(posts)] == ["deny"]


def test_a_no_said_after_it_still_denies(d, e):
    guard, active, posts, ears = e
    speak(guard, READ_OUT, NEXT, mirror=MIRROR)
    guard.bot_stopped()
    guard.stopped_at = time.time() - 3.0
    final(d, ears, "No, don't run that.")
    assert [v["behavior"] for v in verdicts(posts)] == ["deny"]


def test_echo_guard_names_a_repeat_of_its_recent_words():
    guard = EchoGuard()
    speak(guard, READ_OUT, NEXT, mirror=MIRROR)
    guard.bot_stopped()
    assert guard.repeats_bot(ECHOED)
    assert not guard.repeats_bot("No.") and not guard.repeats_bot("no, don't run that")
    assert not guard.repeats_bot("Yes, go ahead and approve it.")
    assert not guard.repeats_bot("No, it's not on your screen.")  # the user's own no, in the bot's words around it
