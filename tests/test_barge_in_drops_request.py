"""A barge-in drops the request it replaced.

From the independent tester's second round (bar-01): the user asked for a rundown of every session, then cut in with
"Wait, wait. Just tell me about lantern." The turn they talked over went on: its sends, still passing their checks, were
delivered to billing once and to lantern twice, after the barge-in. A send made for a turn the user talked over now
waits to learn what they said: new words drop it, an acknowledgement or a noise does not.

uv run pytest -q tests/test_barge_in_drops_request.py
"""

import asyncio
import time
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

import brain as brain_mod  # noqa: E402
from brain import Brain  # noqa: E402
from test_orchestrator import d  # noqa: E402,F401  (d is the daemon fixture)


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


def test_a_voice_whose_words_are_not_in_yet_holds_the_send_until_they_are(monkeypatch):
    """Measured on recorded people: "Stop." ended 0.2 s before the send it was meant to stop went out, because no word
    of it had reached the daemon yet and nothing had cut the turn. A voice being heard is enough to wait for its words."""
    delivered = []

    async def tool(params):
        if not await b.abandoned(wait=2.0, voicing=lambda: True):  # the voice detector hears the user
            delivered.append(params.arguments["message"])
        await params.result_callback({"sent_to": "billing"})

    b, said = _brain(monkeypatch, [_send("Give a full rundown.")], tool)

    async def call():
        first = asyncio.ensure_future(b.turn("Give me a full rundown of everything."))
        await asyncio.sleep(0.3)
        b.interrupt()
        b.user_spoke()  # the words arrive: "Stop."
        await first

    asyncio.run(call())
    assert delivered == []


def test_a_voice_that_turns_out_to_be_nothing_lets_the_send_go(monkeypatch):
    delivered = []

    async def tool(params):
        if not await b.abandoned(wait=0.3, voicing=lambda: True):  # a cough: no words ever come
            delivered.append(params.arguments["message"])
        await params.result_callback({"sent_to": "billing"})

    b, said = _brain(monkeypatch, [_send("Run the tests.")], tool)
    asyncio.run(b.turn("Tell billing to run the tests."))
    assert delivered == ["Run the tests."]


def _over_the_bot(d, monkeypatch, b, then):  # noqa: F811
    """The daemon's own check, `_abandoned`, run as a send of `b`'s turn while the bot speaks and a voice has just
    begun over it, too new for the level gate to tell from the echo. `then` plays what follows, with `b`."""
    monkeypatch.setattr(d.ECHO, "speaking", True, raising=False)
    monkeypatch.setattr(d.LEVEL, "loud", lambda: False)
    d.state.front = SimpleNamespace(brain=b)
    d.state.last_user_speech_at = time.time() - 5  # the words that started the turn
    d.state.user_stopped_at = d.state.last_user_speech_at
    verdicts = []

    async def tool(params):
        d.state.user_started_at = time.time()  # the voice began 0.2 s ago in the recording; here, now
        verdicts.append(await d._abandoned(params.arguments["message"]))
        await params.result_callback({})

    b.tools[0].handler = tool

    async def call():
        first = asyncio.ensure_future(b.turn("Give me a full rundown of everything."))
        await then(b)
        await first

    t0 = time.time()
    asyncio.run(call())
    return verdicts, time.time() - t0


def test_a_voice_begun_over_the_bot_holds_the_send_until_the_barge_in_shows(d, monkeypatch):  # noqa: F811
    """bar-01 on 0.8.5 (suite 2): "Wait," began over the rundown 1 s before its send to billing, the level gate could
    not yet tell it from the echo, and the send went out 1 ms before the barge-in's first word cut the turn."""
    b, _ = _brain(monkeypatch, [_send("Give a full rundown."), _speak("Lantern is idle.")], None)

    async def then(b):
        await asyncio.sleep(0.25)
        b.interrupt()  # "Wait,": the barge-in
        d.ECHO.speaking = False
        await asyncio.sleep(0.3)
        d.state.last_utterance = "Wait, wait. Just tell me about lantern."
        b.user_spoke()

    verdicts, _ = _over_the_bot(d, monkeypatch, b, then)
    assert verdicts == [True]


def test_the_bots_own_echo_delays_a_send_only_a_moment(d, monkeypatch):  # noqa: F811
    b, _ = _brain(monkeypatch, [_send("Run the tests."), _speak("Sent.")], None)

    async def then(b):
        return None  # the voice is the bot's own, and no barge-in ever comes

    verdicts, took = _over_the_bot(d, monkeypatch, b, then)
    assert verdicts == [False] and took < 1.6
