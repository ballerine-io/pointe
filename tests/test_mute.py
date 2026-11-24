"""Mute (mute.py, docs/features/mute.md): the owner muted Pointe's voice. Nothing reaches the mouth, so nothing is
synthesised; every line still arrives as text and the status says "Writing…" where it would have said "Speaking…";
muting in the middle of a reply cuts the audio and not the reply; "stop talking, I'll read" and "talk again" are the
button by voice; approvals and read-backs keep their rules. Offline: the mouth is a counting TTS service in a real
pipecat pipeline; the rest is faked at its seams."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mute  # noqa: E402
from test_orchestrator import _read_out_setup, client_for, d, fake_conn, verdicts  # noqa: E402,F401  (d is a fixture)


@pytest.fixture(autouse=True)
def _talking_after(d):
    yield
    d.state.mute, d.state.read_through, d.state.wrote_at, d.state.mouth_gate = False, -1, 0.0, None
    if d.state.drive.on():
        d.state.drive.leave()


# ---------- the phrases ----------

@pytest.mark.parametrize("said", ["stop talking, I'll read", "Stop talking. I will read it.", "I'll read", "reading mode",
                                  "text only", "just write", "okay, reading mode on", "מצב קריאה", "תפסיק לדבר, אני אקרא"])
def test_the_on_phrases(said):
    assert mute.intent(said) is True


@pytest.mark.parametrize("said", ["talk again", "you can talk again", "reading mode off", "back to normal", "speak again",
                                  "תדבר שוב", "חזרה לרגיל"])
def test_the_off_phrases(said):
    assert mute.intent(said) is False


@pytest.mark.parametrize("said", ["stop talking", "stop", "be quiet", "let me read it", "I'll read the diff later",
                                  "tell billing to talk to the API again", "what does reading mode do?"])
def test_other_sentences_change_nothing(said):
    assert mute.intent(said) is None


# ---------- nothing is synthesised, the text still arrives ----------

def _counting_mouth(d):
    from pipecat.services.tts_service import TTSService

    class CountingMouth(TTSService):
        """A TTS service that counts what it was asked to synthesise and makes no sound."""

        def __init__(self):
            super().__init__(sample_rate=24000)
            self.asked: list[str] = []

        async def run_tts(self, text: str, context_id: str):
            self.asked.append(text)
            yield None

    return CountingMouth()


def _through_the_mouth(d, *texts):
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.tests.utils import run_test

    mouth = _counting_mouth(d)
    down, up = asyncio.run(run_test(Pipeline([d.MuteOut(), mouth]),
                                    frames_to_send=[d.TTSSpeakFrame(t) for t in texts]))
    return mouth.asked, down, up


def test_muted_nothing_reaches_the_mouth(d):
    d.state.mute = True
    asked, down, up = _through_the_mouth(d, "Billing finished: all 12 tests pass.", "Anything else?")
    assert asked == []  # no TTS call: no vendor cost
    assert not [f for f in down if isinstance(f, (d.TTSSpeakFrame, d.OutputAudioRawFrame))]
    starts = [f for f in up if isinstance(f, d.BotStartedSpeakingFrame)]
    stops = [f for f in up if isinstance(f, d.BotStoppedSpeakingFrame)]
    assert len(starts) == len(stops) == 2  # a turn of no length each: the yes window and the floor see it end


def test_unmuted_the_mouth_speaks(d):
    d.state.mute = False
    asked, _, _ = _through_the_mouth(d, "Billing finished.")
    assert asked == ["Billing finished."]


def test_drive_mode_holds_mute(d):
    d.state.mute = True
    d.state.drive.enter("voice")
    asked, _, _ = _through_the_mouth(d, "Billing finished.")
    assert asked == ["Billing finished."]  # on the road Pointe talks
    status = client_for(d).get("/voice/status").json()["reading"]
    assert status["on"] is True and status["held"] == "drive"


def test_the_text_arrives_unread_and_talking_reads_it(d):
    d.state.mute = True

    async def push(frame, direction=None):
        pass

    async def run():
        await d.BrainFront._speak(SimpleNamespace(push_frame=push), "Billing finished: all 12 tests pass.")
    asyncio.run(run())
    talk = client_for(d).get("/voice/status").json()["talk"]
    line = next(t for t in talk if t["who"] == "assistant")
    assert "12 tests" in line["text"] and line["unread"] is True
    asyncio.run(d.on_user_utterance("thanks"))
    talk = client_for(d).get("/voice/status").json()["talk"]
    assert not [t for t in talk if t["who"] == "assistant" and t["unread"]]


def test_a_tap_marks_lines_read_and_more_words_make_a_line_unread_again(d):
    d.state.mute = True
    d._remember("assistant", "First line. ")
    first = d._last_reply_id()
    client = client_for(d)
    assert client.post("/voice/read", json={"through": first}).json()["reading"]["read_through"] == first
    d._remember("assistant", "And more words. ")  # the same reply grows
    assert client.get("/voice/status").json()["talk"][-1]["unread"] is True
    assert client.post("/voice/read", json={}).status_code == 200  # Mark all read
    assert client.get("/voice/status").json()["talk"][-1]["unread"] is False
    assert client.post("/voice/read", json={"through": "x"}).status_code == 400


def test_no_filler_is_said_while_muted(d):
    d.state.mute = True
    pushed = []

    async def push(frame, direction=None):
        pushed.append(frame)
    front = SimpleNamespace(push_frame=push)
    asyncio.run(d.BrainFront._filler(front))
    assert pushed == []


# ---------- "Writing…" where it would have said "Speaking…" ----------

def _reading_status(d):
    return client_for(d).get("/voice/status").json()["reading"]


def test_while_muted_a_line_for_the_mouth_makes_the_status_say_writing(d):
    d.state.mute = True
    assert _reading_status(d)["writing"] is False  # muted and nothing to say: not writing
    _through_the_mouth(d, "Billing finished: all 12 tests pass.")
    status = client_for(d).get("/voice/status").json()
    assert status["reading"]["writing"] is True and status["speaking"] != "bot"
    d.state.wrote_at -= mute.WRITING_SECS + 0.1  # the line has been on screen a moment: back to listening
    assert _reading_status(d)["writing"] is False


def test_unmuted_the_status_never_says_writing(d):
    _through_the_mouth(d, "Billing finished.")
    assert _reading_status(d)["writing"] is False
    d.state.mute, d.state.wrote_at = True, __import__("time").time()
    d.state.drive.enter("voice")  # held by drive mode: Pointe talks, so it is not writing
    assert _reading_status(d)["writing"] is False


def test_the_two_states_have_their_words():
    assert mute.COPY["speaking"] == "Speaking…" and mute.COPY["writing"] == "Writing…"


# ---------- muting in the middle of a reply ----------

def _gate(d):
    """The gate before the mouth, with what it pushes recorded."""
    gate, pushed = d.MuteOut(), []

    async def push(frame, direction=d.FrameDirection.DOWNSTREAM):
        pushed.append((type(frame).__name__, direction))
    gate.push_frame = push
    return gate, pushed


def test_muting_mid_speech_cuts_the_audio_at_once_and_never_the_reply(d):
    _call(d)
    gate, pushed = _gate(d)
    cut = []
    d.state.front = SimpleNamespace(brain=SimpleNamespace(interrupt=lambda: cut.append("brain")))
    try:
        asyncio.run(d._set_mute(True, "button"))
    finally:
        d.state.front = None
    # the mouth and the speakers are flushed (downstream only); the brain keeps writing the rest of the reply
    assert pushed == [("InterruptionFrame", d.FrameDirection.DOWNSTREAM)] and cut == []


def test_the_rest_of_a_reply_muted_mid_speech_is_shown_and_not_spoken(d):
    _call(d)
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.tests.utils import SleepFrame, run_test

    mouth = _counting_mouth(d)

    class MuteNow(d.FrameProcessor):
        """The tap on the mute button, between the first sentence and the second."""

        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            if isinstance(frame, d.TTSSpeakFrame) and frame.text == "Second sentence.":
                await d._set_mute(True, "button")
            await self.push_frame(frame, direction)

    asyncio.run(run_test(Pipeline([MuteNow(), d.MuteOut(), mouth]),
                         frames_to_send=[d.TTSSpeakFrame("First sentence."), SleepFrame(0.2), d.TTSSpeakFrame("Second sentence.")]))
    assert mouth.asked == ["First sentence."]
    assert _reading_status(d)["writing"] is True


def test_unmuting_or_muting_under_drive_mode_cuts_nothing(d):
    _call(d)
    gate, pushed = _gate(d)
    asyncio.run(d._set_mute(False, "button"))
    d.state.drive.enter("voice")
    asyncio.run(d._set_mute(True, "button"))  # held: Pointe keeps talking on the road
    assert pushed == []


# ---------- turning it on and off ----------

class Socket:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_text(self, text):
        self.sent.append(json.loads(text))


def _call(d):
    d.state.conn, d.state.call_socket = fake_conn(), Socket()
    return d.state.call_socket


def _ears(d, monkeypatch):
    ears = d.SonioxEars()
    reached, said = [], []

    async def push(frame, *a):
        reached.append(frame)

    async def say_exactly(line, tag, readback=False):
        said.append(line)
    ears.push_frame = push
    monkeypatch.setattr(d, "_say_exactly", say_exactly)
    return ears, reached, said


def test_saying_it_turns_it_on_tells_the_device_and_shows_the_line(d, monkeypatch):
    sock = _call(d)
    ears, reached, said = _ears(d, monkeypatch)
    asyncio.run(ears._take("stop talking, I'll read"))
    assert d.state.mute is True and not reached  # the brain never got the words
    assert said == [mute.ON_LINE] and sock.sent == [{"type": "reading", "on": True}]
    asyncio.run(ears._take("talk again"))
    assert d.state.mute is False and said[-1] == mute.OFF_LINE
    assert sock.sent[-1] == {"type": "reading", "on": False}


def test_talk_again_while_not_muted_is_someone_elses_words(d, monkeypatch):
    _call(d)
    ears, reached, said = _ears(d, monkeypatch)
    asyncio.run(ears._take("talk again"))
    assert reached and not said


def test_typing_it_works_too(d, monkeypatch):
    _call(d)
    _, _, said = _ears(d, monkeypatch)
    asyncio.run(d._user_text("I'll read"))
    assert d.state.mute is True and said == [mute.ON_LINE]


def test_asked_while_driving_it_waits_for_the_end_of_drive_mode(d, monkeypatch):
    _call(d)
    d.state.drive.enter("voice")
    ears, _, said = _ears(d, monkeypatch)
    asyncio.run(ears._take("I'll read"))
    assert d.state.mute is True and not d._muted() and said == [mute.HELD_LINE]


def test_the_button_sets_the_calls_choice_and_tells_the_device(d):
    sock = _call(d)
    client = client_for(d)
    reply = client.post("/voice/reading", json={"on": True}).json()
    assert reply["applied"] is True and reply["reading"]["on"] is True
    assert sock.sent == [{"type": "reading", "on": True}]
    assert client.post("/voice/reading", json={"on": "yes"}).status_code == 400


def test_with_no_call_the_device_keeps_its_choice_alone(d):
    d.state.conn = None
    reply = client_for(d).post("/voice/reading", json={"on": True}).json()
    assert reply["applied"] is False and reply["reading"]["on"] is False


def test_each_call_starts_with_its_devices_choice():
    """The call's address carries the device's choice (?reading=1), read before the pipeline greets anyone."""
    source = (Path(__file__).resolve().parents[1] / "pointe" / "daemon.py").read_text()
    assert 'state.mute = websocket.query_params.get("reading") == "1"' in source
    start = source.index("async def socket_call")
    assert source.index("state.mute = websocket.query_params", start) < source.index("await run_call(transport)", start)


def test_the_phone_key_reaches_the_two_routes():
    from guards import _PHONE_PATHS
    assert {"/voice/reading", "/voice/read"} <= _PHONE_PATHS


# ---------- approvals and read-backs: unchanged ----------

ANSWERS = ["yes", "yes please", "go ahead", "no", "no, don't run it", "wait, what is it?", "כן", "לא"]


def _outcome(d, monkeypatch, text, on):
    d.state.mute = on
    active, posts, said = _read_out_setup(d, monkeypatch)
    asyncio.run(d.on_user_utterance(text))
    return verdicts(posts), active.permission_id


@pytest.mark.parametrize("text", ANSWERS)
def test_an_answer_to_a_read_out_request_is_judged_exactly_as_with_the_voice(d, monkeypatch, text):
    assert _outcome(d, monkeypatch, text, True) == _outcome(d, monkeypatch, text, False)


def test_a_typed_yes_still_approves_nothing(d, monkeypatch):
    d.state.mute = True
    active, posts, said = _read_out_setup(d, monkeypatch)

    async def push(frame, direction=None):
        pass
    d.state.conn.injector.push_frame = push
    asyncio.run(d._user_text("yes"))
    assert verdicts(posts) == [] and active.permission_id == "p1"


def test_the_brain_is_told_only_while_it_applies(d):
    d.state.mute = True
    assert mute.RULE in d._brain_context()
    d.state.drive.enter("voice")
    assert mute.RULE not in d._brain_context()


def test_the_words_are_the_same_on_every_surface():
    """The page's and both apps' words, word for word (the page's file is the source)."""
    root = Path(__file__).resolve().parents[1]
    page = " ".join((root / "pointe" / "ui_mute.html").read_text().split()) + " ".join((root / "pointe" / "ui.html").read_text().split())
    swift = (root / "apps" / "PointeKit" / "Sources" / "PointeUI" / "Mute.swift").read_text()
    for key, words in mute.COPY.items():
        assert words in page, (key, words)
        assert f'"{words}"' in swift, (key, words)
