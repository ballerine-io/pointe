"""A barge-in drops the request it replaced.

From the independent tester's second round (bar-01): the user asked for a rundown of every session, then cut in with
"Wait, wait. Just tell me about lantern." The turn they talked over went on: its sends, still passing their checks, were
delivered to billing once and to lantern twice, after the barge-in. A send made for a turn the user talked over now
waits to learn what they said: new words drop it, an acknowledgement or a noise does not.

uv run pytest -q tests/test_barge_in_drops_request.py
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

import brain as brain_mod  # noqa: E402
from brain import Brain  # noqa: E402


def _brain(monkeypatch, steps: list, tool):
    """A brain whose model answers with `steps` in order, and one tool, send_to_claude_code, that is `tool`."""
    said = []

    async def speak(text):
        said.append(text)

    async def step(choice, instructions, messages, decls, heard=None):
        return SimpleNamespace(calls=steps.pop(0), said="", raw=None, vendor="main", usage={})

    monkeypatch.setattr(brain_mod.vendors, "step", step)
    send = SimpleNamespace(name="send_to_claude_code", description="send", properties={}, required=[], handler=tool)
    b = Brain("main:model", "s", [send], lambda: "[right now] x", speak)
    b.may_stay_silent = lambda: False
    return b, said


def _send(message: str) -> list:
    return [{"id": "c1", "name": "send_to_claude_code", "args": {"message": message, "session": "billing"}}]


def _speak(text: str) -> list:
    return [{"id": "c2", "name": "speak", "args": {"text": text}}]


def test_a_send_is_dropped_when_the_user_cut_in_and_said_something_new(monkeypatch):
    delivered, verdicts = [], []

    async def tool(params):
        await asyncio.sleep(0.2)  # the checks before a delivery: the user cuts in during them
        gone = await b.abandoned(wait=2.0)
        verdicts.append(gone)
        if not gone:
            delivered.append(params.arguments["message"])
        await params.result_callback({"error": "Not sent"} if gone else {"sent_to": "billing"})

    b, said = _brain(monkeypatch, [_send("Give a full rundown."), _speak("Lantern is idle.")], tool)

    async def call():
        first = asyncio.ensure_future(b.turn("Give me a full rundown of everything."))
        await asyncio.sleep(0.05)
        b.interrupt()  # the barge-in
        await asyncio.sleep(0.3)
        await b.turn("Wait, wait. Just tell me about lantern.")  # their new words
        await first

    asyncio.run(call())
    assert verdicts == [True] and delivered == []
    assert said == ["Lantern is idle."]  # the new words are the only turn answered


def test_a_cut_with_no_words_after_it_does_not_drop_the_send(monkeypatch):
    delivered = []

    async def tool(params):
        await asyncio.sleep(0.2)
        if not await b.abandoned(wait=0.3):  # a cough: nobody says anything new
            delivered.append(params.arguments["message"])
        await params.result_callback({"sent_to": "billing"})

    b, said = _brain(monkeypatch, [_send("Run the tests.")], tool)

    async def call():
        first = asyncio.ensure_future(b.turn("Tell billing to run the tests."))
        await asyncio.sleep(0.05)
        b.interrupt()
        await first

    asyncio.run(call())
    assert delivered == ["Run the tests."]


def test_a_send_nobody_talked_over_does_not_wait(monkeypatch):
    waits = []

    async def tool(params):
        import time
        t0 = time.time()
        gone = await b.abandoned()
        waits.append((gone, time.time() - t0))
        await params.result_callback({"sent_to": "billing"})

    b, said = _brain(monkeypatch, [_send("Run the tests.")], tool)
    asyncio.run(b.turn("Tell billing to run the tests."))
    assert waits and waits[0][0] is False and waits[0][1] < 0.05


def test_a_send_made_outside_a_turn_is_never_taken_for_the_turn_talked_over(monkeypatch):
    """A request sent as said (no model step) runs beside the old turn's tool: it is the user's new words, not the old turn."""
    async def tool(params):
        await params.result_callback({})

    b, said = _brain(monkeypatch, [], tool)
    b._run_turn = (0, 0)
    b.interrupt()
    assert asyncio.run(b.abandoned()) is False


def test_words_the_daemon_answers_itself_still_drop_the_send(monkeypatch):
    """Measured on a recorded "Stop." over a rundown: the stop was answered by the daemon, no turn of the model's began,
    and the send of the turn it cut went out four seconds later as if nobody had spoken."""
    delivered = []

    async def tool(params):
        await asyncio.sleep(0.2)
        if not await b.abandoned(wait=2.0):
            delivered.append(params.arguments["message"])
        await params.result_callback({"sent_to": "billing"})

    b, said = _brain(monkeypatch, [_send("Give a full rundown.")], tool)

    async def call():
        first = asyncio.ensure_future(b.turn("Give me a full rundown of everything."))
        await asyncio.sleep(0.05)
        b.interrupt()  # the barge-in
        b.user_spoke()  # "Stop.": heard, answered by the daemon, no model turn
        await first

    asyncio.run(call())
    assert delivered == []
