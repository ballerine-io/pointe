"""No turn on the user's own words ends in silence.

From the independent tester's second round: three of 66 turns got no reply at all, and on the owner's real calls 34 of
287 did. The causes differ (a noise the voice detector took for speech cut the reply and nobody said anything after it;
a refused send the model was told not to mention; a reply lost between its checks), so the cure is one watch on every
taken turn: with Pointe idle and nothing said since the user's words, the model is asked once more, and if that is
silent too a fixed line asks them to say it again.

uv run pytest -q tests/test_no_silent_turn.py
"""

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).parent))

from pipecat.frames.frames import InputTextRawFrame, TTSSpeakFrame  # noqa: E402
from pipecat.processors.frame_processor import FrameDirection  # noqa: E402

from test_orchestrator import add, d, fake_conn  # noqa: E402,F401  (d is the daemon fixture)


def _call(d, monkeypatch, replies: list):  # noqa: F811
    """A call with one session; the model's steps answer with `replies` in order (None: a step that says nothing)."""
    monkeypatch.setattr(d, "FIRST_HELLO", Path("/dev/null"))  # someone was answered before: no first-call greeting
    monkeypatch.setattr(d, "SILENT_TURN_SECS", 0.2)
    monkeypatch.setattr(d, "SILENT_TURN_POLL_SECS", 0.02)
    asked = []

    async def step(choice, instructions, messages, decls, heard=None):
        asked.append(next((m["content"] for m in reversed(messages) if m["role"] == "user"), ""))
        reply = replies.pop(0) if replies else None
        if isinstance(reply, float):  # a step cut by a noise this long into it
            await asyncio.sleep(reply)
            front.brain.interrupt()
            await asyncio.sleep(0.01)
            reply = "never said"
        calls = [{"id": f"c{len(asked)}", "name": "speak", "args": {"text": reply}}] if reply is not None else []
        return SimpleNamespace(calls=calls, said="", raw=None, vendor="fake", usage={})

    monkeypatch.setattr(d.vendors, "step", step)
    add(d, "s1", "billing")
    d.REGISTRY.active_id = "s1"
    d.state.conn = fake_conn()
    d.state.conn.injector.queued_reports = lambda: {}
    front = d.BrainFront(d._opening_context())
    d.state.front = front
    spoken, tasks = [], []

    async def push(frame, direction=FrameDirection.DOWNSTREAM):
        if isinstance(frame, TTSSpeakFrame):
            spoken.append(frame.text)

    front.push_frame = push
    front.create_task = lambda coro, name=None: tasks.append(asyncio.ensure_future(coro))

    async def say(text: str) -> None:
        d.state.last_utterance, d.state.last_user_speech_at = text, time.time()
        d.state.utterance_spent = False
        await front.process_frame(InputTextRawFrame(text=text), FrameDirection.DOWNSTREAM)
        while tasks:
            await asyncio.gather(*[tasks.pop(0)])

    return front, spoken, asked, say


def test_a_reply_cut_by_a_noise_is_asked_for_again_and_said(d, monkeypatch):  # noqa: F811
    front, spoken, asked, say = _call(d, monkeypatch, [0.05, "Billing is idle."])
    asyncio.run(say("What is billing doing?"))
    assert spoken == ["Billing is idle."]
    assert asked[-1].startswith("[silent turn]")


def test_a_second_silence_gets_the_fixed_line(d, monkeypatch):  # noqa: F811
    front, spoken, asked, say = _call(d, monkeypatch, [0.05, 0.05])
    asyncio.run(say("What is billing doing?"))
    assert spoken == [d.SILENT_TURN_LINE]


def test_a_turn_that_was_answered_is_left_alone(d, monkeypatch):  # noqa: F811
    front, spoken, asked, say = _call(d, monkeypatch, ["Billing is idle."])
    asyncio.run(say("What is billing doing?"))
    assert spoken == ["Billing is idle."] and len(asked) == 1


def test_an_acknowledgement_may_end_in_silence(d, monkeypatch):  # noqa: F811
    front, spoken, asked, say = _call(d, monkeypatch, [""])
    asyncio.run(say("Okay, thanks."))
    assert spoken == [] and len(asked) == 1


def test_new_words_from_the_user_end_the_watch_on_the_old_ones(d, monkeypatch):  # noqa: F811
    front, spoken, asked, say = _call(d, monkeypatch, [0.05, "Lantern is idle."])

    async def run():
        first = asyncio.ensure_future(say("What is billing doing?"))
        await asyncio.sleep(0.1)
        d.state.last_utterance, d.state.last_user_speech_at = "And lantern?", time.time()  # they went on
        await first

    asyncio.run(run())
    assert not any(a.startswith("[silent turn]") for a in asked)


def test_a_long_awaited_answer_is_cut_and_said_not_sent_back(d, monkeypatch):  # noqa: F811
    """heb-01: the session's answer to the user's question came back over the limit, was sent back to the model, and on a
    slow machine was never said at all. An awaited answer over its limit is cut in code and said at once."""
    long = ("Three tests failed, all in the refunds test file. They are about rounding half-cent refunds to the nearest "
            "cent. The number is from the notes file, which records the last run. Nothing was rerun since then, so the "
            "count may be out of date by now.")
    front, spoken, asked, say = _call(d, monkeypatch, [long, "never needed"])
    trigger = ("[claude-code finished its turn] It answered the question you sent it. Tell the user its answer in "
               "English, in one or two short sentences, the answer first:\n3 failures, all in tests/test_refunds.py, "
               "about rounding half-cent refunds. From the notes file; nothing was rerun since.")
    asyncio.run(front.brain.turn(trigger))
    assert len(asked) == 1  # one model step: not sent back to be shortened
    assert len(spoken) == 1 and spoken[0].startswith("Three tests failed")
    assert len(spoken[0].split()) < len(long.split())
