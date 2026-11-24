"""A switch stops speech at once. The owner moves to the orchestrator or to a session, by a click, by voice, from any
surface: what Pointe is saying is cut, and everything that waited to be said for the place they left is dropped. Nothing
queued plays after the switch. The dropped lines are not lost: they are in the conversation as text.

Offline: the injector is the real FeedInjector, and the mouth is a slow fake TTS service in a real pipecat pipeline that
makes silent frames; the brain is faked at its seam (state.front). No microphone, no vendor.

uv run --locked pytest -q tests/test_switch_stops_speech.py
"""

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harnesses import FINISHED_MARK  # noqa: E402
from test_orchestrator import Params, add, client_for, d, fake_conn  # noqa: E402,F401  (d is a fixture)
from test_session_click import FakeFront  # noqa: E402


def wire(d):
    """The real injector, outside a pipeline: what it hands on is recorded, and a cut is counted."""
    class Wire(d.FeedInjector):
        def __init__(self):
            super().__init__()
            self.pushed, self.cuts = [], 0

        async def push_frame(self, frame, direction=d.FrameDirection.DOWNSTREAM):
            self.pushed.append(frame)

        async def broadcast_interruption(self):
            self.cuts += 1

        def asked_to_speak(self) -> list[str]:
            """What the voice was asked to say: a user-side line for a realtime model, or one the brain must answer."""
            out = [f.text for f in self.pushed if isinstance(f, d.InputTextRawFrame)]
            return out + [m["content"] for f in self.pushed if isinstance(f, d.LLMMessagesAppendFrame) and f.run_llm
                          for m in f.messages]

    return Wire()


def report(d, name: str, line: str) -> str:
    """A session's finished-turn report, as the daemon queues it: the model's prompt, and the line the screens show."""
    return d._about(f"[{name} {FINISHED_MARK} Say this as it is:\n{line}", name, "report", line)


@pytest.fixture
def call(d, monkeypatch):
    """A live call in orchestrator mode with three sessions; Pointe is mid-sentence, and three reports wait behind it."""
    monkeypatch.setattr(d, "FOCUS_SETTLE_SECS", 0.02)
    monkeypatch.setattr(d, "UPDATE_POLL_SECS", 0.01)
    monkeypatch.setattr(d, "FRONT", "brain")
    monkeypatch.setattr(d, "_refresh_brief", lambda s: asyncio.sleep(0))
    alpha, beta, gamma = add(d, "a", "alpha"), add(d, "b", "beta"), add(d, "c", "gamma")
    d.REGISTRY.set_active("a")
    conn = fake_conn()
    conn.injector = wire(d)
    d.state.conn, d.state.front = conn, FakeFront()
    return SimpleNamespace(d=d, alpha=alpha, beta=beta, gamma=gamma, inj=conn.injector, front=d.state.front)


LINES = {"alpha": "The parser refactor is done.", "beta": "All 12 tests pass.", "gamma": "The docs build is green."}


async def queue_three(c, queued: int = 3) -> None:
    """Pointe is speaking, so each report waits: the update queue holds all three. In session mode only the focused
    session's waits there (`queued`): the others' are held for the screens, as ever (scope.py)."""
    c.inj._bot_speaking = True
    c.d.state.floor.bot_started(time.time())
    for name, line in LINES.items():
        await c.inj.inject(report(c.d, name, line), True)
    assert c.inj.queued == queued and c.inj.asked_to_speak() == []


async def the_floor_frees(c) -> None:
    """Pointe's line ends and the room is quiet: anything still queued would be said now."""
    c.inj._bot_speaking = False
    c.d.state.floor.bot_stopped(time.time() - 60)
    c.d.state.floor.said_at = 0.0
    await c.inj._deliver_if_free()
    await asyncio.sleep(0.15)


def written(c) -> str:
    return " ".join(t["text"] for t in client_for(c.d).get("/voice/status").json()["talk"])


def test_a_click_on_a_session_empties_the_queue_and_says_only_the_new_line(call):
    async def run():
        await queue_three(call)
        await call.d.focus_by_click(call.beta)
        assert call.inj.queued == 0 and not call.inj.holding, "the reports for the place the owner left still wait"
        await the_floor_frees(call)
    asyncio.run(run())
    assert call.inj.cuts >= 1, "what Pointe was saying was not cut"
    assert call.inj.asked_to_speak() == [], "a queued report was said after the switch"
    assert [t for t, _ in call.front.said] == ["I'm now in session beta. It's not waiting on anything. I have no notes on it yet."]


def test_the_dropped_reports_stay_readable_as_text(call):
    async def run():
        await queue_three(call)
        await call.d.focus_by_click(call.beta)
    asyncio.run(run())
    text = written(call)
    for name, line in LINES.items():
        assert line in text and name in text, f"{name}'s report was dropped from the conversation too"


def test_the_brain_keeps_what_was_dropped_and_is_told_not_to_say_it(call):
    async def run():
        await queue_three(call)
        await call.d.focus_by_click(call.beta)
    asyncio.run(run())
    kept = [m["content"] for f in call.inj.pushed if isinstance(f, call.d.LLMMessagesAppendFrame) and not f.run_llm
            for m in f.messages if "not said" in m["content"]]
    assert len(kept) == 1 and all(line in kept[0] for line in LINES.values()), kept


def test_the_mode_toggle_to_the_orchestrator_cuts_and_empties_the_queue(call):
    call.d.REGISTRY.mode = "session"

    async def run():
        await queue_three(call, queued=1)
        await call.d.mode_by_click(SimpleNamespace(json=lambda: asyncio.sleep(0, {"mode": "orchestrator"})))
        queued = call.inj.queued_reports()
        await the_floor_frees(call)
        return queued
    queued = asyncio.run(run())
    assert call.d.REGISTRY.mode == "orchestrator"
    assert call.inj.cuts >= 1, "what Pointe was saying was not cut"
    assert call.front.brain.interrupts >= 1, "the reply being generated was not cancelled"
    assert queued == {}, "alpha's report, queued for session mode, still waits"
    # What the other sessions said while the owner was focused is the orchestrator's to tell, once, on the way back
    # (scope.py): that summary is the one thing said. Alpha's own queued report is not.
    said = call.inj.asked_to_speak()
    assert len(said) == 1 and said[0].startswith("[news held") and LINES["alpha"] not in said[0], said
    assert LINES["alpha"] in written(call)


def test_the_mode_toggle_to_session_mode_cuts_too(call):
    async def run():
        await queue_three(call)
        await call.d.mode_by_click(SimpleNamespace(json=lambda: asyncio.sleep(0, {"mode": "session"})))
        assert call.inj.queued == 0
        await the_floor_frees(call)
    asyncio.run(run())
    assert call.inj.cuts >= 1 and call.inj.asked_to_speak() == []


def test_the_same_mode_again_cuts_nothing(call):
    async def run():
        await queue_three(call)
        await call.d.mode_by_click(SimpleNamespace(json=lambda: asyncio.sleep(0, {"mode": "orchestrator"})))
    asyncio.run(run())
    assert call.inj.cuts == 0 and call.inj.queued == 3, "a tap on the mode already on is no switch"


def test_a_spoken_switch_empties_the_queue_and_keeps_the_reply_to_it(call):
    """By voice the owner's own words already cut the mouth; the turn that runs the switch must live to answer it."""
    async def run():
        await queue_three(call)
        note = await call.d._focus_by_voice(call.beta)
        assert note["active"] == "beta" and call.d.REGISTRY.mode == "session"
        assert call.inj.queued == 0 and not call.inj.holding
        await the_floor_frees(call)
    asyncio.run(run())
    assert call.front.brain.interrupts == 0, "the turn that switched was cancelled: nothing would say where it landed"
    assert call.inj.cuts == 0, "an interruption from the injector reaches the brain and ends the turn that switched"
    assert call.inj.asked_to_speak() == []
    assert all(line in written(call) for line in LINES.values())


def test_orchestrator_mode_by_voice_empties_the_queue(call, monkeypatch):
    call.d.REGISTRY.mode = "session"
    monkeypatch.setattr(call.d, "_await_fresh_speech", lambda since: asyncio.sleep(0, True))
    call.d.state.last_utterance = "orchestrator mode"

    async def run():
        await queue_three(call, queued=1)
        params = Params()
        await call.d.set_mode(params)
        assert params.results == [{"mode": "orchestrator"}]
        assert call.inj.queued_reports() == {}
    asyncio.run(run())
    assert call.front.brain.interrupts == 0 and LINES["alpha"] in written(call)


def test_speech_held_behind_the_bot_is_dropped_too(call):
    """Not only the update queue: a line that waited for the bot to stop (the reply timer's list) goes with it."""
    async def run():
        call.inj._bot_speaking = True
        await call.inj.inject("[permission answered] Say in one line that it went through.", True)
        assert call.inj.holding
        await call.d.focus_by_click(call.gamma)
        assert not call.inj.holding
        await the_floor_frees(call)
    asyncio.run(run())
    assert call.inj.asked_to_speak() == []


def test_a_report_cut_by_the_switch_is_not_offered_again(call):
    async def run():
        call.inj._report, call.inj._report_speaking, call.inj._bot_speaking = report(call.d, "alpha", LINES["alpha"]), True, True
        call.inj._cut = "an older report the owner talked over"
        await call.d.focus_by_click(call.beta)
        await call.inj.process_frame(call.d.BotStoppedSpeakingFrame(), call.d.FrameDirection.UPSTREAM)
        await call.inj.process_frame(call.d.BotStoppedSpeakingFrame(), call.d.FrameDirection.UPSTREAM)
        await the_floor_frees(call)
    asyncio.run(run())
    assert call.inj.queued == 0 and not any("[resume]" in t for t in call.inj.asked_to_speak())


def test_news_that_arrives_after_the_switch_is_still_said(call):
    """The cut is for what waited before: the session the owner moved to reports, and it is said."""
    async def run():
        await queue_three(call)
        await call.d.focus_by_click(call.beta)
        await the_floor_frees(call)
        await call.inj.inject(report(call.d, "beta", "The deploy went out."), True)
        await the_floor_frees(call)
    asyncio.run(run())
    assert len(call.inj.asked_to_speak()) == 1 and "The deploy went out." in call.inj.asked_to_speak()[0]


# ---------- the mouth: three lines queued for it, a switch, and no further audio ----------

def test_no_audio_frame_is_sent_after_the_switch(d, monkeypatch):
    """Three lines are with the mouth, the first is being played. The click cuts it: not one more audio frame reaches the
    call, of that line or of the two behind it, and the injector's queue is empty."""
    from pipecat.frames.frames import TTSAudioRawFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.processors.frame_processor import FrameProcessor
    from pipecat.services.tts_service import TTSService

    monkeypatch.setattr(d, "FOCUS_SETTLE_SECS", 0.02)
    monkeypatch.setattr(d, "FRONT", "brain")
    monkeypatch.setattr(d, "_refresh_brief", lambda s: asyncio.sleep(0))
    add(d, "a", "alpha"), add(d, "b", "beta")
    d.REGISTRY.set_active("a")

    class SlowMouth(TTSService):
        """Silence, 20 ms at a time, about a second for each line: time enough to switch in the middle of the first."""

        def __init__(self):
            super().__init__(sample_rate=24000)
            self.asked: list[str] = []

        async def run_tts(self, text: str, context_id: str):
            self.asked.append(text)
            for _ in range(50):
                await asyncio.sleep(0.02)
                yield TTSAudioRawFrame(audio=b"\0" * 960, sample_rate=24000, num_channels=1, context_id=context_id)

    class Speaker(FrameProcessor):
        """The call's end of the pipeline: when each audio frame left for the device."""

        def __init__(self):
            super().__init__()
            self.audio: list[float] = []

        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            if isinstance(frame, TTSAudioRawFrame):
                self.audio.append(time.monotonic())
            await self.push_frame(frame, direction)

    async def run():
        injector, mouth, speaker = d.FeedInjector(), SlowMouth(), Speaker()
        worker = d.PipelineWorker(Pipeline([injector, d.MuteOut(), mouth, speaker]), cancel_on_idle_timeout=False)
        started = asyncio.Event()

        @worker.event_handler("on_pipeline_started")
        async def _started(_worker, _frame):
            started.set()

        runner = d.WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
        running = asyncio.create_task(runner.run())
        await asyncio.wait_for(started.wait(), 5)
        conn = fake_conn()
        conn.injector = injector
        d.state.conn, d.state.front = conn, FakeFront()
        for line in ("The parser refactor is done.", "All 12 tests pass.", "The docs build is green."):
            await worker.queue_frame(d.TTSSpeakFrame(line))
        for _ in range(200):  # the first line is being played
            if len(speaker.audio) >= 5:
                break
            await asyncio.sleep(0.01)
        assert len(speaker.audio) >= 5, "the mouth never started"
        injector._bot_speaking = True
        await injector.inject(f"[alpha {FINISHED_MARK} Say this as it is:\nThe lint is clean.", True)
        await d.focus_by_click(d.REGISTRY.sessions["b"])
        switched = time.monotonic()
        await asyncio.sleep(1.5)  # long enough for the two lines behind it to have played
        late = [at for at in speaker.audio if at > switched + 0.05]
        queued, asked = injector.queued, list(mouth.asked)
        await worker.cancel()
        await asyncio.wait_for(running, 5)
        return late, queued, asked

    late, queued, asked = asyncio.run(run())
    assert late == [], f"{len(late)} audio frame(s) reached the call after the switch"
    assert queued == 0, "the injector's queue was not emptied"
    assert asked == ["The parser refactor is done."], "a line behind the one being played was synthesised"
