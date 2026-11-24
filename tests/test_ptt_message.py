"""Push to talk sends a press as one message, like a voice message (docs/design/push-to-talk-modes.md): while the button
is open nothing said is a turn, pauses included; on release (or the second tap) everything said goes as one turn, once
the ears gave the last words. Offline: the gate and the ears are driven with scripted transcripts and pauses.

uv run --locked pytest -q tests/test_ptt_message.py
"""

import asyncio
import inspect
import json
import re
import sys
import time
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import phone  # noqa: E402
import ptt  # noqa: E402
from test_orchestrator import client_for, d  # noqa: E402,F401  (d is a fixture)

T0 = 1000.0


@pytest.fixture(autouse=True)
def _always_on_after():
    yield
    if "daemon" in sys.modules:
        sys.modules["daemon"].PREFS.update({"microphone": "always"})


# ---------- the press's message, as pure state ----------

def _closed_and_finalized(g: ptt.Ptt, at: float) -> list[str]:
    g.release(at)
    return g.tick("ptt", at + ptt.TAIL_SECS + ptt.LINK_SLACK_SECS + 0.01)


def test_a_press_keeps_its_words_and_gives_them_once_as_one_message():
    g = ptt.Ptt()
    g.press(T0)
    g.hear("Let's look at the parser.")
    g.live = "and see"
    assert g.collecting and g.draft() == "Let's look at the parser. and see" and not g.sendable()
    g.hear("And see why it fails.")
    assert _closed_and_finalized(g, T0 + 5) == ["finalize"] and g.sendable()
    assert g.take() == "Let's look at the parser. And see why it fails."
    assert not g.collecting and g.take() == "" and g.draft() == ""


def test_a_press_with_nothing_heard_gives_nothing():
    g = ptt.Ptt()
    g.press(T0)
    _closed_and_finalized(g, T0 + 1)
    assert g.sendable() and g.take() == ""


def test_the_send_waits_for_the_finalize_and_then_no_longer_than_the_final_wait():
    g = ptt.Ptt()
    g.press(T0)
    g.hear("Run the tests.")
    g.release(T0 + 2)
    assert g.tick("ptt", T0 + 2.1) == [] and not g.sendable()  # the tail: the last word may still be on its way
    after = T0 + 2 + ptt.TAIL_SECS + ptt.LINK_SLACK_SECS + 0.01
    assert g.tick("ptt", after) == ["finalize"]
    assert g.tick("ptt", after + ptt.FINAL_WAIT_SECS - 0.1) == []  # waiting for the ears' last words
    assert g.tick("ptt", after + ptt.FINAL_WAIT_SECS + 0.01) == ["send"]
    assert g.tick("ptt", after + ptt.FINAL_WAIT_SECS + 0.5) == []  # once


def test_pressing_again_before_it_was_sent_goes_on_with_the_same_message():
    g = ptt.Ptt()
    g.press(T0)
    g.hear("Check the billing session.")
    g.release(T0 + 2)
    g.press(T0 + 2.3)
    assert not g.sendable() and g.said == ["Check the billing session."]
    g.hear("And the docs one.")
    _closed_and_finalized(g, T0 + 4)
    assert g.take() == "Check the billing session. And the docs one."


def test_without_pointe_s_own_ears_a_press_keeps_nothing():
    g = ptt.Ptt()
    g.press(T0, collect=False)
    assert not g.collecting
    _closed_and_finalized(g, T0 + 1)
    assert not g.sendable() and g.tick("ptt", T0 + 10) == []


def test_the_status_says_when_the_hearing_is_a_draft():
    g = ptt.Ptt()
    assert g.status("ptt")["draft"] is False
    g.press(T0)
    assert g.status("ptt")["draft"] is True
    _closed_and_finalized(g, T0 + 1)
    assert g.status("ptt")["draft"] is True  # closed, not sent yet
    g.take()
    assert g.status("ptt")["draft"] is False


# ---------- on the call: the gate, the ears, scripted transcripts ----------

class Ws:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(message)


def _call(d, monkeypatch, mode="ptt"):
    """The gate and the ears, as in the pipeline: what the gate pushes downstream reaches the ears; what the ears push
    (the user's turn) is recorded."""
    from pipecat.frames.frames import InputTextRawFrame

    d.PREFS.update({"microphone": mode})
    ws = Ws()
    gate = d.PttGate(type("Stt", (), {"_websocket": ws})())
    ears = d.SonioxEars()
    turns, said = [], []
    monkeypatch.setattr(d.FrameProcessor, "process_frame", lambda self, f, dirn: asyncio.sleep(0))
    monkeypatch.setattr(ears, "create_task", lambda coro, name=None: asyncio.get_running_loop().create_task(coro))

    async def gate_push(frame, direction=None):
        if isinstance(frame, d.PressEnd):
            await d.SonioxEars.process_frame(ears, frame, d.FrameDirection.DOWNSTREAM)

    async def ears_push(frame, direction=None):
        if isinstance(frame, InputTextRawFrame):
            turns.append(frame.text)

    async def heard(text):
        said.append(text)

    async def quiet():
        pass
    gate.push_frame, ears.push_frame = gate_push, ears_push
    gate.broadcast_interruption = ears.broadcast_interruption = quiet
    monkeypatch.setattr(d, "on_user_utterance", heard)
    monkeypatch.setattr(d, "_after_quiet", quiet)
    return gate, ears, ws, turns, said


async def _final(d, ears, text):
    from pipecat.frames.frames import TranscriptionFrame

    d.state.user_stopped_at = time.time()  # Soniox's final comes after the voice stopped
    await d.SonioxEars.process_frame(ears, TranscriptionFrame(text=text, user_id="u", timestamp="t"), d.FrameDirection.DOWNSTREAM)


async def _interim(d, ears, text):
    from pipecat.frames.frames import InterimTranscriptionFrame

    await d.SonioxEars.process_frame(ears, InterimTranscriptionFrame(text=text, user_id="u", timestamp="t"), d.FrameDirection.DOWNSTREAM)


async def _press(d, gate, open_):
    await d.PttGate.process_frame(gate, phone.PttFrame(open=open_), d.FrameDirection.DOWNSTREAM)


async def _tail(gate):
    """The tail runs out: the gate asks the ears for the last words."""
    await gate.tick(time.time() + ptt.TAIL_SECS + ptt.LINK_SLACK_SECS + 0.05)


async def _finalized(d, ears):
    """Soniox's <fin>, in the frame stream behind the last words."""
    await d.SonioxEars.process_frame(ears, d.PressEnd(why="finalized"), d.FrameDirection.DOWNSTREAM)


def test_nothing_said_while_the_button_is_open_is_a_turn_and_the_release_sends_it_all_as_one(d, monkeypatch):
    gate, ears, ws, turns, said = _call(d, monkeypatch)

    async def run():
        await _press(d, gate, True)
        await _final(d, ears, "Let's look at the parser.")  # whole, and the test's settle time is 0: once a turn at once
        await asyncio.sleep(1.2)  # a long pause inside the press
        await _final(d, ears, "Hold on.")  # a hold phrase is content inside a press
        await _final(d, ears, "Yes.")  # a short answer never waits outside a press
        await asyncio.sleep(0.5)
        await _final(d, ears, "And see why it fails because")  # unfinished
        await asyncio.sleep(0.5)
        assert turns == [] and said == [] and d.state.hold is None and d.state.ptt.collecting
        await _press(d, gate, False)
        await _final(d, ears, "the retry has no backoff.")  # inside the tail: still this press
        assert turns == []
        await _tail(gate)
        assert ws.sent == ['{"type": "finalize"}'] and turns == []  # the last words are being finalized
        await _finalized(d, ears)
        await asyncio.sleep(0.05)

    asyncio.run(run())
    message = "Let's look at the parser. Hold on. Yes. And see why it fails because the retry has no backoff."
    assert turns == [message] and said == [message]
    assert not d.state.ptt.collecting and d.state.hold is None


def test_the_last_words_finalized_after_the_release_are_in_the_message(d, monkeypatch):
    gate, ears, ws, turns, _ = _call(d, monkeypatch)

    async def run():
        await _press(d, gate, True)
        await _final(d, ears, "Ask docs whether the changelog is out.")
        await _interim(d, ears, "and the release")
        await _press(d, gate, False)
        await _tail(gate)
        await asyncio.sleep(0.3)  # Soniox is finalizing: nothing goes before its words
        assert turns == []
        await _final(d, ears, "And the release notes.")  # what the finalize gave
        await _finalized(d, ears)

    asyncio.run(run())
    assert turns == ["Ask docs whether the changelog is out. And the release notes."]


def test_a_finalized_word_before_the_tail_ends_sends_nothing_early(d, monkeypatch):
    gate, ears, ws, turns, _ = _call(d, monkeypatch)

    async def run():
        await _press(d, gate, True)
        await _final(d, ears, "Run the tests.")
        await _finalized(d, ears)  # a <fin> while open (an earlier finalize's): the press goes on
        await _press(d, gate, False)
        await _finalized(d, ears)  # and inside the tail, before this press's finalize
        assert turns == []
        await _tail(gate)
        await _finalized(d, ears)

    asyncio.run(run())
    assert turns == ["Run the tests."]


def test_when_the_ears_never_say_the_words_are_in_the_message_goes_after_the_final_wait(d, monkeypatch):
    gate, ears, ws, turns, _ = _call(d, monkeypatch)

    async def run():
        await _press(d, gate, True)
        await _final(d, ears, "Switch to billing.")
        await _press(d, gate, False)
        now = time.time() + ptt.TAIL_SECS + ptt.LINK_SLACK_SECS + 0.05
        await gate.tick(now)
        await gate.tick(now + ptt.FINAL_WAIT_SECS - 0.2)
        assert turns == []
        await gate.tick(now + ptt.FINAL_WAIT_SECS + 0.05)

    asyncio.run(run())
    assert turns == ["Switch to billing."]


def test_an_empty_press_sends_nothing(d, monkeypatch):
    gate, ears, ws, turns, said = _call(d, monkeypatch)

    async def run():
        await _press(d, gate, True)
        await asyncio.sleep(0.2)
        await _press(d, gate, False)
        await _tail(gate)
        await _finalized(d, ears)

    asyncio.run(run())
    assert turns == [] and said == [] and not d.state.ptt.collecting
    assert client_for(d).get("/voice/status").json()["hearing"] == ""


def test_a_call_that_ends_while_a_press_is_open_sends_nothing(d, monkeypatch):
    """The iPhone's Cancel and Hang up from the Lock Screen (docs/features/push-to-talk.md): the call ends with the press
    still open. The runner is cancelled, so the gate never releases it, and the next call's gate starts closed: what
    the press heard is never a turn, however long anything ticks after."""
    from pipecat.frames.frames import CancelFrame

    gate, ears, ws, turns, said = _call(d, monkeypatch)

    async def run():
        await _press(d, gate, True)
        await _final(d, ears, "Delete the staging branch.")
        await d.PttGate.process_frame(gate, CancelFrame(), d.FrameDirection.DOWNSTREAM)  # the hang-up
        nxt = d.PttGate(type("Stt", (), {"_websocket": ws})())  # the next call
        for later in (2.5, 10, 120):
            await nxt.tick(time.time() + later)
        await _finalized(d, ears)

    asyncio.run(run())
    assert turns == [] and said == [] and ws.sent == []
    assert not d.state.ptt.collecting and not d.state.ptt.open


def test_the_draft_shows_while_the_button_is_open_however_long_the_pause(d, monkeypatch):
    gate, ears, ws, turns, _ = _call(d, monkeypatch)
    monkeypatch.setattr(d, "HEARING_SECS", 0.1)  # live words go stale this fast outside a press
    c = client_for(d)
    seen = {}

    async def run():
        await _press(d, gate, True)
        await _final(d, ears, "The checkout keeps timing out.")
        await _interim(d, ears, "I think it's")
        await asyncio.sleep(0.3)
        seen["open"] = c.get("/voice/status").json()
        await _press(d, gate, False)
        seen["closed"] = c.get("/voice/status").json()
        await _tail(gate)
        await _finalized(d, ears)
        seen["sent"] = c.get("/voice/status").json()

    asyncio.run(run())
    assert seen["open"]["hearing"] == "The checkout keeps timing out. I think it's" and seen["open"]["ptt"]["draft"] is True
    assert seen["closed"]["ptt"]["draft"] is True and seen["closed"]["hearing"].startswith("The checkout")
    assert seen["sent"]["hearing"] == "" and seen["sent"]["ptt"]["draft"] is False
    assert turns == ["The checkout keeps timing out."]  # the interim was never finalized: Soniox's final carries it


def test_nothing_starts_speaking_between_the_release_and_the_send(d, monkeypatch):
    gate, ears, ws, turns, _ = _call(d, monkeypatch)
    monkeypatch.setattr(d, "USER_GAP_SECS", 0.0)

    async def run():
        await _press(d, gate, True)
        await _final(d, ears, "Ask river whether the migration ran.")
        d.state.user_stopped_at = time.time()  # a long pause in the press: the voice detector says stopped
        await asyncio.sleep(0.05)
        assert d._user_talking()
        await _press(d, gate, False)
        assert d._user_talking()  # closed, not sent: news would talk over the reply
        await _tail(gate)
        await _finalized(d, ears)
        assert not d._user_talking()

    asyncio.run(run())


def test_a_hold_s_silence_release_does_not_fire_inside_a_press(d, monkeypatch):
    gate, ears, ws, turns, _ = _call(d, monkeypatch)
    monkeypatch.setattr(d.turns, "HOLD_RELEASE_SILENCE_SECS", 0.2)

    async def run():
        await _final(d, ears, "Hold on.")  # outside a press (always on until now): a hold
        assert d.state.hold is not None
        d.PREFS.update({"microphone": "ptt"})
        await _press(d, gate, True)
        d.state.user_stopped_at = d.state.user_started_at = time.time()
        await asyncio.sleep(0.6)  # silence longer than the hold's release, inside the press
        assert d.state.hold is not None and turns == []
        await _press(d, gate, False)
        await _tail(gate)
        await _finalized(d, ears)

    d.PREFS.update({"microphone": "always"})
    asyncio.run(run())


def test_always_on_is_unchanged_each_final_is_a_turn(d, monkeypatch):
    gate, ears, ws, turns, _ = _call(d, monkeypatch, mode="always")

    async def run():
        await _press(d, gate, True)  # ignored: always on
        await _final(d, ears, "Let's look at the parser.")
        await asyncio.sleep(0.05)
        await _final(d, ears, "Yes.")
        await asyncio.sleep(0.05)

    asyncio.run(run())
    assert turns == ["Let's look at the parser.", "Yes."] and not d.state.ptt.collecting


def test_the_weakest_voice_and_any_echo_of_the_bot_answer_for_the_whole_message(d, monkeypatch):
    gate, ears, ws, turns, _ = _call(d, monkeypatch)
    monkeypatch.setattr(d.VOICE, "confident", lambda v: v == "owner")
    monkeypatch.setattr(d.speaker, "strong", lambda v: v == "owner")

    async def run():
        await _press(d, gate, True)
        d.state.ptt.hear("Yes.", "stranger")
        d.state.ptt.hear("Go ahead with the deploy.", "owner", own_words=True)
        d.state.last_speaker, d.state.heard_own_words = "owner", False
        await _press(d, gate, False)
        await _tail(gate)
        await _finalized(d, ears)

    asyncio.run(run())
    assert turns == ["Yes. Go ahead with the deploy."]
    assert d.state.last_speaker == "stranger" and d.state.heard_own_words is True


# ---------- Soniox's <fin> reaches the ears behind its words ----------

def test_soniox_s_fin_is_told_in_the_frame_stream_after_the_words_it_carried(d):
    from pipecat.services.soniox.stt import SonioxSTTService

    pushed = []

    class Socket:
        def __init__(self, messages):
            self.messages = messages

        def __aiter__(self):
            return self._each()

        async def _each(self):
            for m in self.messages:
                yield m

    stt = SonioxSTTService.__new__(SonioxSTTService)  # no key, no socket: only the reading is exercised
    words = json.dumps({"tokens": [{"text": "backoff.", "is_final": True}]})
    fin = json.dumps({"tokens": [{"text": "backoff.", "is_final": True}, {"text": "<fin>", "is_final": True}]})
    fin = fin.replace("<", "\\u003c").replace(">", "\\u003e")  # as Soniox sends it: escaped
    socket = Socket([words, json.dumps({"tokens": [{"text": "<end>", "is_final": True}]}), fin])
    stt._get_websocket = lambda: socket

    async def push(frame, direction=None):
        pushed.append(frame)
    stt.push_frame = push
    d._tell_finalized(stt)

    async def loop():  # as pipecat's receive loop: one message handled, its frames pushed, then the next
        async for message in stt._get_websocket():
            pushed.append(json.loads(message)["tokens"][-1]["text"])
    asyncio.run(loop())
    assert [p if isinstance(p, str) else p.why for p in pushed] == ["backoff.", "<end>", "<fin>", "finalized"]


def test_pipecat_s_soniox_still_reads_its_socket_where_the_marker_hooks_in():
    from pipecat.services.soniox.stt import FINALIZED_TOKEN, SonioxSTTService

    source = inspect.getsource(SonioxSTTService._receive_messages)
    assert "async for message in self._get_websocket()" in source
    assert FINALIZED_TOKEN == "<fin>"


def test_other_ears_are_left_alone(d):
    class OtherEars:
        def _get_websocket(self):
            return "socket"
    ears = OtherEars()
    d._tell_finalized(ears)
    assert ears._get_websocket() == "socket"


def test_the_press_end_survives_an_interruption(d):
    assert d.PressEnd().interruptible is False


# ---------- the draft on the page and in the app ----------

ROOT = Path(__file__).resolve().parents[1]
DRAFT_LINES = ("Draft · not sent yet", "Sending")


def test_the_page_and_the_app_say_draft_in_the_same_words():
    page = (ROOT / "pointe" / "ui.html").read_text()
    swift = (ROOT / "apps" / "PointeKit" / "Sources" / "PointeUI" / "PushToTalk.swift").read_text()
    for line in DRAFT_LINES:
        assert f"'{line}'" in page and f'"{line}"' in swift, line
    api = (ROOT / "apps" / "PointeKit" / "Sources" / "PointeUI" / "API.swift").read_text()
    assert re.search(r"let draft: Bool\?", api)  # an older Mac sends no draft: the bubble is the usual live one


CAPTION = ("(() => { const c = document.getElementById('caption'), l = document.getElementById('caption-draft'); "
           "return {hidden: c.hidden, draft: c.classList.contains('draft'), label: l.hidden ? '' : l.textContent, "
           "text: document.getElementById('caption-text').textContent}; })()")


@pytest.mark.skipif(not Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome").exists(),
                    reason="headless Chrome is not installed here")
def test_the_page_shows_a_press_s_words_as_a_draft_until_they_are_sent():
    from page_rig import Browser, StubMac, fixture, free_port

    async def run():
        status = fixture(connected=True)
        status["ptt"].update(mode="ptt", open=True, draft=True)
        status["hearing"] = "Let's look at the parser. And see why"
        stub = await StubMac(free_port()).start()
        stub.status = status
        browser = Browser()
        await browser.__aenter__()
        out = {}
        try:
            page = await browser.open(stub.url)
            await page.eval("(() => { call.state = 'live'; pttFollow(status); return true; })()")
            await page.eval("refresh()")
            out["open"] = await page.eval(CAPTION)
            status["ptt"]["open"] = False  # released; the last words are being finalized
            await page.eval("refresh()")
            out["sending"] = await page.eval(CAPTION)
            status["ptt"]["draft"], status["hearing"] = False, ""  # sent: it is a turn in the conversation now
            await page.eval("refresh()")
            out["sent"] = await page.eval(CAPTION)
            status["ptt"]["mode"], status["hearing"] = "always", "what time is it"  # always on: live words, no draft
            await page.eval("refresh()")
            out["always"] = await page.eval(CAPTION)
        finally:
            await browser.__aexit__(None, None, None)
            await stub.stop()
        return out

    out = asyncio.run(run())
    assert out["open"] == {"hidden": False, "draft": True, "label": "Draft · not sent yet", "text": "Let's look at the parser. And see why"}
    assert out["sending"]["draft"] and out["sending"]["label"] == "Sending"
    assert out["sent"]["hidden"] is True
    assert out["always"] == {"hidden": False, "draft": False, "label": "", "text": "what time is it"}
