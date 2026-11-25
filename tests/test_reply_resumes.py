"""A reply cut by someone only listening goes on from the sentence it was in.

People say "mm-hm" and "okay" to a colleague without thinking, and a cough or a door can cut the voice as a word does.
The reply was lost either way: the model was told it had been cut off, and the user had to ask again. Now a cut followed
by a backchannel, a short acknowledgement or no words at all resumes the reply once, from the sentence the cut fell in;
real words still take the turn, and "stop" or "enough" still end it.

uv run pytest -q tests/test_reply_resumes.py
"""

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).parent))

from pipecat.frames.frames import InputTextRawFrame  # noqa: E402
from pipecat.processors.frame_processor import FrameDirection  # noqa: E402

from test_no_silent_turn import _call  # noqa: E402
from test_orchestrator import d  # noqa: E402,F401  (d is the daemon fixture)

REPLY = ("Billing finished the refund fix. Three tests still fail in the refunds file. "
         "The staging deploy stays blocked until they pass.")


async def _cut_mid_reply(d, front, spoken, heard_secs: float = 3.0):  # noqa: F811
    """The voice is `heard_secs` into REPLY (about 14 characters a second) when something cuts it."""
    d.state.last_utterance, d.state.last_user_speech_at = "What is billing doing?", time.time() - 10
    await front._speak(REPLY)
    front._speaking = True
    front._spoke_since = time.time() - heard_secs
    front._interrupted()  # what an InterruptionFrame does here
    front._speaking = False
    del spoken[:]


async def _hear(d, front, tasks_done, text: str):  # noqa: F811
    d.state.last_utterance, d.state.last_user_speech_at = text, time.time()
    d.state.utterance_spent = False
    await front.process_frame(InputTextRawFrame(text=text), FrameDirection.DOWNSTREAM)
    await tasks_done()


def _rig(d, monkeypatch, replies):  # noqa: F811
    monkeypatch.setattr(d, "REPLY_RESUME_SECS", 0.3)
    front, spoken, asked, say = _call(d, monkeypatch, replies)
    pending = []
    original = front.create_task
    front.create_task = lambda coro, name=None: pending.append(asyncio.ensure_future(coro))

    async def tasks_done():
        while pending:
            await asyncio.gather(pending.pop(0))

    del original
    return front, spoken, asked, tasks_done


@pytest.mark.parametrize("words", ["Mm-hm.", "Okay.", "כן."])
def test_a_backchannel_over_the_reply_resumes_it_from_the_cut_sentence(d, monkeypatch, words):  # noqa: F811
    front, spoken, asked, tasks_done = _rig(d, monkeypatch, [])

    async def run():
        await _cut_mid_reply(d, front, spoken, heard_secs=3.0)  # about 42 characters in: inside the second sentence
        await _hear(d, front, tasks_done, words)

    asyncio.run(run())
    assert spoken == ["Three tests still fail in the refunds file. The staging deploy stays blocked until they pass."]
    assert asked == []  # no model step: the words left are said as they were


def test_a_cut_with_no_words_after_it_resumes_the_reply(d, monkeypatch):  # noqa: F811
    front, spoken, asked, tasks_done = _rig(d, monkeypatch, [])

    async def run():
        await _cut_mid_reply(d, front, spoken, heard_secs=6.0)
        await tasks_done()

    asyncio.run(run())
    assert spoken == ["The staging deploy stays blocked until they pass."]


@pytest.mark.parametrize("words", ["Wait, just tell me about quarry.", "Okay, stop.", "Enough."])
def test_real_words_take_the_turn_and_nothing_is_resumed(d, monkeypatch, words):  # noqa: F811
    front, spoken, asked, tasks_done = _rig(d, monkeypatch, ["Quarry is idle."])

    async def run():
        await _cut_mid_reply(d, front, spoken, heard_secs=3.0)
        await _hear(d, front, tasks_done, words)

    asyncio.run(run())
    assert not any("Three tests still fail" in line or "staging deploy" in line for line in spoken)


def test_a_reply_cut_in_its_last_words_is_not_brought_back(d, monkeypatch):  # noqa: F811
    front, spoken, asked, tasks_done = _rig(d, monkeypatch, [])

    async def run():
        d.state.last_utterance, d.state.last_user_speech_at = "Is billing done?", time.time() - 10
        await front._speak("Yes. It is done.")
        front._speaking = True
        front._spoke_since = time.time() - 0.6
        front._interrupted()  # what an InterruptionFrame does here
        front._speaking = False
        del spoken[:]
        await tasks_done()

    asyncio.run(run())
    assert spoken == []


def test_a_yes_over_a_question_of_pointes_answers_it(d, monkeypatch):  # noqa: F811
    front, spoken, asked, tasks_done = _rig(d, monkeypatch, ["Asked billing."])

    async def run():
        d.state.last_utterance, d.state.last_user_speech_at = "Check the tests.", time.time() - 10
        await front._speak("Billing or quarry has tests like that. Do you want me to ask billing to run them now?")
        front._speaking = True
        front._spoke_since = time.time() - 3.5
        front._interrupted()  # what an InterruptionFrame does here
        front._speaking = False
        del spoken[:]
        await _hear(d, front, tasks_done, "Yes.")

    asyncio.run(run())
    assert spoken == ["Asked billing."] and len(asked) == 1  # the yes went to the model as the answer
