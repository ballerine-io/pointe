"""The greeting when a call opens cannot act. From live calls: the opening carries the sessions' recent history, the
model read the user's last ask in it ("keep going on the checkout runs") and sent it again at every call start; the send
guard refused it each time, and the greeting became "I did not send your continue", on each of seven reconnects in eight
minutes. Synthetic sessions and text throughout."""

import asyncio
from types import SimpleNamespace

from pipecat.frames.frames import LLMRunFrame
from pipecat.processors.frame_processor import FrameDirection

from test_orchestrator import add, d  # noqa: F401  (d is the daemon fixture)

BRIEF = {"goal": "Ship the billing retry fix", "state": "Waiting on the user to approve the deploy", "open": []}


def _front(d, monkeypatch, wants_to_send: bool):
    """A call opening on a session with notes, so the model greets (no fixed line); its model sends when offered the tool."""
    s = add(d, "s1", "billing")
    s.brief = BRIEF
    d.REGISTRY.active_id = "s1"
    offered, sent, spoken = [], [], []

    async def step(_choice, _instructions, _messages, decls):
        offered.append([t["name"] for t in decls])
        names = offered[-1]
        if wants_to_send and "send_to_claude_code" in names and not sent:
            sent.append(True)
            call = {"id": "c1", "name": "send_to_claude_code", "args": {"message": "Continue the checkout runs"}}
        else:
            call = {"id": f"c{len(offered)}", "name": "speak", "args": {"text": "Billing waits on you to approve the deploy."}}
        return SimpleNamespace(calls=[call], said="", raw=None, vendor="fake", usage={})

    monkeypatch.setattr(d.vendors, "step", step)
    front = d.BrainFront(d._opening_context())

    async def speak(text, request_id=None):
        spoken.append(text)

    front.brain.speak = speak
    front.brain.speak_first = front.brain.speak_rest = None  # the whole reply at once
    tasks = []
    front.create_task = lambda coro, name=None: tasks.append(asyncio.ensure_future(coro))
    return front, offered, spoken, tasks


def test_the_greeting_when_a_call_opens_is_offered_speech_and_nothing_else(d, monkeypatch):
    front, offered, spoken, tasks = _front(d, monkeypatch, wants_to_send=True)

    async def run():
        await front.process_frame(LLMRunFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.gather(*tasks)

    asyncio.run(run())
    assert offered == [["speak"]]  # one step, and nothing in it could send
    assert spoken == ["Billing waits on you to approve the deploy."]


def test_the_turn_after_the_greeting_has_the_tools_again(d, monkeypatch):
    front, offered, spoken, tasks = _front(d, monkeypatch, wants_to_send=False)

    async def run():
        await front.process_frame(LLMRunFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.gather(*tasks)
        await front.brain.turn("What is billing waiting on?")

    asyncio.run(run())
    assert offered[0] == ["speak"] and "send_to_claude_code" in offered[1]
