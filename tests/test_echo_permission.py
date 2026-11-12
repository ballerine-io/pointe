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

from echo import AudioClock, EchoGuard  # noqa: E402
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


def timed_final(d, ears, text: str, said: tuple[float, float]) -> None:
    """A final whose tokens place its words at `said` (wall times), on ears that have heard the last 20 s of audio."""
    clock, stream, now = AudioClock(), object(), time.time()
    for i in range(1000):
        clock.sent(stream, 0.02, now - 20 + (i + 1) * 0.02)
    d.EARS_CLOCK = clock
    ms = [round((t - (now - 20)) * 1000) for t in said]
    frame = TranscriptionFrame(text=text, user_id="u", timestamp="t",
                               result=[{"text": text, "start_ms": ms[0], "end_ms": ms[1], "is_final": True}])
    asyncio.run(ears.process_frame(frame, FrameDirection.DOWNSTREAM))


def test_a_yes_heard_over_the_read_out_never_approves_however_late_it_comes(d, e, monkeypatch):
    guard, active, posts, ears = e
    monkeypatch.setattr(d, "EARS_CLOCK", d.EARS_CLOCK)
    speak(guard, "billing wants to run the tests. Say yes to allow it, or no.", mirror=["Billing wants to run the tests.",
                                                                                         " Say yes to allow it, or no."])
    guard.bot_stopped()
    now = time.time()
    guard.stopped_at = now - 3.2  # Soniox finalized it 3.2 s after the bot stopped
    guard._played[-1] = [now - 7.0, now - 3.2]
    timed_final(d, ears, "Yes.", (now - 4.4, now - 4.1))  # said over "Say yes": the bot's own word
    assert verdicts(posts) == [] and active.permission_id == "p1"


def test_a_yes_said_after_the_read_out_still_approves(d, e, monkeypatch):
    guard, active, posts, ears = e
    monkeypatch.setattr(d, "EARS_CLOCK", d.EARS_CLOCK)
    speak(guard, "billing wants to run the tests. Say yes to allow it, or no.", mirror=["Billing wants to run the tests.",
                                                                                         " Say yes to allow it, or no."])
    guard.bot_stopped()
    now = time.time()
    guard.stopped_at = now - 3.2
    guard._played[-1] = [now - 7.0, now - 3.2]
    timed_final(d, ears, "Yes.", (now - 2.5, now - 2.2))  # the user's, 0.7 s after the bot stopped
    assert [v["behavior"] for v in verdicts(posts)] == ["allow"]


def test_echo_guard_names_a_repeat_of_its_recent_words():
    guard = EchoGuard()
    speak(guard, READ_OUT, NEXT, mirror=MIRROR)
    guard.bot_stopped()
    assert guard.repeats_bot(ECHOED)
    assert not guard.repeats_bot("No.") and not guard.repeats_bot("no, don't run that")
    assert not guard.repeats_bot("Yes, go ahead and approve it.")
    assert not guard.repeats_bot("No, it's not on your screen.")  # the user's own no, in the bot's words around it


def test_the_ears_clock_counts_only_audio_the_recognizer_receives(d, monkeypatch):
    from websockets.protocol import State

    class Socket:
        state = State.OPEN

    class Ears:
        sample_rate = 16000
        _websocket = None

        async def run_stt(self, audio):
            yield None

    async def feed(stt, n):
        for _ in range(n):
            async for _ in stt.run_stt(b"\0" * 640):  # 20 ms
                pass

    monkeypatch.setattr(d, "EARS_CLOCK", AudioClock())
    stt = Ears()
    d._clock_ears(stt)
    asyncio.run(feed(stt, 5))  # not connected: Soniox never gets these
    stt._websocket = Socket()
    asyncio.run(feed(stt, 50))
    assert d.EARS_CLOCK.wall(1000) == pytest.approx(time.time(), abs=0.5) and d.EARS_CLOCK.wall(1001) is None


READ_BACK = "billing wants to write notes2.text. Should it? Coming back to that report: scratch.txt is created."


def test_a_read_out_that_sounds_like_a_switch_is_still_echo(d, e, monkeypatch):
    guard, active, posts, ears = e
    taken = []

    async def take(heard):
        taken.append(heard)

    monkeypatch.setattr(ears, "_take", take)
    speak(guard, READ_BACK, mirror=[" Billing wants to write notes2.text.", " Should it? Coming back to that report:",
                                    " scratch.txt is created."])
    guard.bot_stopped()
    now = time.time()
    guard.stopped_at = now - 3.1  # the final, 3.1 s after the bot stopped
    guard._played[-1] = [now - 9.0, now - 3.1]
    assert d.switch_intent(READ_BACK)  # the shortcut for commands said once the bot is quiet would take it whole
    timed_final(d, ears, READ_BACK, (now - 8.9, now - 3.1))
    assert taken == []
    timed_final(d, ears, "Switch to billing.", (now - 1.5, now - 0.6))  # the user's own, said after it stopped
    assert taken == ["Switch to billing."]


def _cuts(guard, ears, monkeypatch, d, settle=0.3):
    """Interruptions with their times. A cut stops the bot, as the real one does a beat later."""
    cuts = []

    async def cut():
        cuts.append(time.time())
        guard.bot_stopped()

    monkeypatch.setattr(ears, "broadcast_interruption", cut)
    monkeypatch.setattr(d, "ECHO_SETTLE_SECS", settle)
    return cuts


def final_while(d, ears, text: str, during=None) -> float:
    """A final transcript; `during` runs while the daemon waits for the mirror. Returns when it started."""
    async def run():
        if during:
            asyncio.get_running_loop().call_later(0.1, during)
        await ears.process_frame(TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)
    started = time.time()
    asyncio.run(run())
    return started


def test_a_lone_stop_word_cuts_the_bot_in_without_waiting_for_the_mirror(d, e, monkeypatch):
    guard, active, posts, ears = e
    cuts = _cuts(guard, ears, monkeypatch, d)
    speak(guard, "Tel Aviv is in Israel Standard Time, two hours ahead of UTC, and moves an hour in summer.",
          mirror=[" Tel Aviv is in Israel Standard Time,"])
    started = final_while(d, ears, "Stop—")
    assert len(cuts) == 1 and cuts[0] - started < 0.1  # not after the 0.3 s wait


def test_a_lone_no_that_cut_the_bot_never_denies_once_it_proves_to_be_echo(d, e, monkeypatch):
    guard, active, posts, ears = e
    cuts = _cuts(guard, ears, monkeypatch, d)
    speak(guard, "billing wants to run the tests. Approve it on your screen.",  # its text lacks the end it spoke
          mirror=[" Billing wants to run the tests.", " Approve it on your screen."])
    final_while(d, ears, "No.", during=lambda: guard.mirror_heard(" Or say no.", ""))  # the mirror catches up
    assert len(cuts) == 1  # a false stop may silence the bot
    assert verdicts(posts) == [] and active.permission_id == "p1"  # but never denies


def test_a_lone_no_the_user_said_over_the_read_out_still_denies(d, e, monkeypatch):
    guard, active, posts, ears = e
    cuts = _cuts(guard, ears, monkeypatch, d)
    speak(guard, "billing wants to run the tests. Approve it on your screen.",
          mirror=[" Billing wants to run the tests.", " Approve it on your screen."])
    final_while(d, ears, "No.")
    assert len(cuts) == 1 and [v["behavior"] for v in verdicts(posts)] == ["deny"]
