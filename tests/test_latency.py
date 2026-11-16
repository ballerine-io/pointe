"""Where a reply's time goes (latency.py): the stamps of one turn, the line the daemon logs at the first sound, and the
brain and the ears telling each stage as it is reached. Every sentence here is made up."""

import asyncio
import json
import time

import latency
from test_conversation_flow import _brain  # noqa: E402
from test_orchestrator import d  # noqa: E402,F401  (d is the daemon fixture)
from test_turn_taking import _ears  # noqa: E402


def test_a_turn_reports_each_stage_in_milliseconds_from_its_first_stamp_and_leaves_out_what_did_not_happen():
    turn = latency.Turn()
    for stage, at in (("last_word", 100.0), ("stt_final", 100.4), ("settled", 101.0), ("brain_sent", 101.002),
                      ("reply", 102.2), ("checked", 102.201), ("tts_request", 102.21), ("first_sound", 102.6)):
        turn.mark(stage, at)
    turn.mark("reply", 109.0)  # a second model step: the first stamp stays, the retry shows in `checked`
    turn.mark("no such stage", 1.0)
    turn.steps = 2
    record = json.loads(turn.line().split("turn timing: ", 1)[1])
    assert record == {"from": "last_word", "t0": 100.0, "stt_final": 400, "settled": 1000, "brain_sent": 1002, "reply": 2200,
                      "checked": 2201, "tts_request": 2210, "first_sound": 2600, "steps": 2}
    assert list(record)[2:9] == [s for s in latency.STAGES if s in record]  # in the order they happen
    turn.mark("tts_first_byte", 102.5)  # after the line was written nothing moves
    assert "tts_first_byte" not in turn.record()


def test_typed_words_have_no_ears_and_are_timed_from_the_turn():
    turn = latency.Turn()
    turn.mark("settled", 50.0)
    turn.mark("first_sound", 51.5)
    assert turn.record() == {"from": "settled", "t0": 50.0, "first_sound": 1500, "steps": 0}
    assert latency.Turn().record() == {}


def test_the_brain_tells_each_stage_of_a_reply_to_the_users_words_and_none_for_a_report(monkeypatch):
    b, spoken, _ = _brain(monkeypatch, ["Use the first one.", "Noted."])
    stages = []
    b.stage = stages.append
    asyncio.run(b.turn("Which release candidate should I ship?"))
    assert stages == ["brain_sent", "reply", "checked"] and spoken == ["Use the first one."]
    del stages[:]
    asyncio.run(b.turn("[billing finished] All checks pass."))  # nobody waits on this one
    assert stages == [] and spoken[-1] == "Noted."


def test_the_daemon_stamps_the_turn_from_the_ears_and_logs_one_line_at_the_first_sound(d, monkeypatch):
    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection

    lines = []
    monkeypatch.setattr(d.logger, "info", lambda message, *a, **k: lines.append(message))

    async def run():
        ears = _ears(d, monkeypatch)

        async def push(frame, direction=None):
            pass
        monkeypatch.setattr(ears, "push_frame", push)
        d.state.user_stopped_at = time.time() - 0.3
        await d.SonioxEars.process_frame(ears, TranscriptionFrame(text="What is a good name for the cache layer?", user_id="u",
                                                                  timestamp="t"), FrameDirection.DOWNSTREAM)
    asyncio.run(run())
    turn = d.state.timing
    assert turn is not None and list(turn.at) == ["last_word", "stt_final", "settled"]
    assert turn.at["last_word"] <= turn.at["stt_final"] <= turn.at["settled"]
    assert d.state.words_ended_at == d.state.final_at == 0.0  # they are this turn's only
    for stage in ("brain_sent", "reply", "checked", "tts_request", "tts_first_byte", "first_sound", "first_sound"):
        d._stage(stage)
    timed = [line for line in lines if line.startswith("turn timing: ")]
    assert len(timed) == 1  # once per turn, however often the voice starts and stops inside a reply
    record = json.loads(timed[0].split("turn timing: ", 1)[1])
    assert record["from"] == "last_word" and [s for s in latency.STAGES if s in record][-1] == "first_sound"
    assert "cache" not in timed[0]  # times only: never the words


def test_typed_words_start_a_turn_timed_from_when_it_was_taken(d):
    asyncio.run(d.on_user_utterance("Which session is waiting on me?"))
    assert list(d.state.timing.at) == ["settled"]
