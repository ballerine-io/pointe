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
    b.stage = lambda stage, when=None: stages.append(stage)
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
    for stage in ("brain_sent", "first_token", "first_sentence", "checked", "tts_request", "tts_first_byte", "first_sound"):
        d._stage(stage)
    # The first sentence was said ahead: the sound is out and the model step still runs. The line waits for its tokens.
    assert not [line for line in lines if line.startswith("turn timing: ")]
    d._stage("reply")
    d.make_brain(None).on_usage({"context": 8000, "cached": 7900, "ms": 900})
    d._stage("first_sound")
    timed = [line for line in lines if line.startswith("turn timing: ")]
    assert len(timed) == 1  # once per turn, however often the voice starts and stops inside a reply
    assert json.loads(timed[0].split("turn timing: ", 1)[1]).items() >= {"steps": 1, "cached": 7900, "early": True}.items()
    record = json.loads(timed[0].split("turn timing: ", 1)[1])
    assert record["from"] == "last_word" and [s for s in latency.STAGES if s in record][-1] == "first_sound"
    assert "layer" not in timed[0] and "name" not in timed[0]  # times and counts only: never the words


def test_typed_words_start_a_turn_timed_from_when_it_was_taken(d):
    asyncio.run(d.on_user_utterance("Which session is waiting on me?"))
    assert list(d.state.timing.at) == ["settled"]


# ---------- the first sentence is said while the model still writes the rest ----------

import conversation as cv  # noqa: E402
import pytest  # noqa: E402
import vendors  # noqa: E402
from types import SimpleNamespace  # noqa: E402


def _streaming_brain(monkeypatch, replies: list[str], known: str = "", interrupt_after_first: bool = False):
    """A brain whose model writes each reply a few characters at a time, as a vendor that streams does. `events` keeps
    the order of what was said and when the model finished."""
    import brain as brain_module

    events, steps = [], []

    async def step(choice, instructions, messages, decls, heard=None):
        steps.append(heard is not None)
        text = replies.pop(0)
        if heard is not None:
            heard("")
            for end in range(4, len(text) + 4, 4):
                heard(text[:end])
                await asyncio.sleep(0)
                await asyncio.sleep(0)
        events.append("model done")
        return SimpleNamespace(calls=[{"id": f"c{len(steps)}", "name": "speak", "args": {"text": text}}], said="", raw=None,
                               vendor="fake", usage={})

    async def speak(text, request_id=None):
        events.append(("speak", text))

    async def speak_first(text):
        events.append(("first", text))
        if interrupt_after_first:
            b.interrupt()

    async def speak_rest(rest, whole):
        events.append(("rest", rest, whole))

    monkeypatch.setattr(brain_module.vendors, "step", step)
    b = brain_module.Brain("fake:model", "instructions", [], lambda: f"[right now] {known or ' '.join(replies)}", speak)
    b.may_stay_silent = lambda: False
    b.limit = lambda trigger, asked: cv.limit_for(trigger, asked)
    b.speak_first, b.speak_rest = speak_first, speak_rest
    return b, events, steps


TWO = "Postgres, in my read. It is stricter and has the richer feature set."


def test_the_first_sentence_is_said_before_the_model_has_finished_and_the_rest_follows(monkeypatch):
    b, events, steps = _streaming_brain(monkeypatch, [TWO])
    stages = []
    b.stage = lambda stage, when=None: stages.append(stage)
    asyncio.run(b.turn("Postgres or MySQL for a small team?"))
    assert events == [("first", "Postgres, in my read."), "model done",
                      ("rest", "It is stricter and has the richer feature set.", TWO)]
    assert stages == ["brain_sent", "first_token", "first_sentence", "checked", "reply"] and steps == [True]
    assert [m for m in b.messages if m["role"] == "tool"][0]["results"][0]["result"] == "spoken"
    assert b._last_spoken == TWO  # the repeat filter knows the whole reply, once


def test_a_reply_of_one_sentence_is_said_whole_as_before(monkeypatch):
    b, events, _ = _streaming_brain(monkeypatch, ["Canberra."])
    asyncio.run(b.turn("What is the capital of Australia?"))
    assert events == ["model done", ("speak", "Canberra.")]


LONG = ("Use a queue when work can wait. It lets the web request return at once, it smooths bursts of traffic, it lets "
        "workers retry a failed job without the user waiting, and it keeps one slow consumer from blocking the others. "
        "It also adds a moving part to run. Want an example?")


def test_a_reply_over_its_words_is_sent_back_for_what_follows_the_sentence_already_said(monkeypatch):
    """The retry stays (the model shortens better than a cut), and costs the user no wait: the first sentence is playing.
    The model is told what was heard, so the next step goes on from it."""
    assert "Too long for speech" in cv.retry_problem(LONG, cv.REPLY)
    b, events, steps = _streaming_brain(monkeypatch, [LONG, "It lets a request return at once and smooths bursts."])
    asyncio.run(b.turn("Why do people use a message queue?"))
    assert steps == [True, False] and events[0] == ("first", "Use a queue when work can wait.")
    refusal = [m for m in b.messages if m["role"] == "tool"][0]["results"][0]["result"]["error"]
    assert "Too long for speech" in refusal and "already heard your first sentence: 'Use a queue when work can wait.'" in refusal
    kind, rest, whole = events[-1]
    assert kind == "rest" and rest == "It lets a request return at once and smooths bursts."
    assert whole == f"Use a queue when work can wait. {rest}" == b._last_spoken
    assert len([e for e in events if e[0] in ("first", "rest", "speak")]) == 2  # said once: its first sentence, then the rest


@pytest.mark.parametrize("again", ["Use a queue when work can wait. It smooths bursts of traffic.",  # word for word
                                   "A queue is for work that can wait. It smooths bursts of traffic."])  # in other words
def test_sent_back_the_model_does_not_get_to_say_the_first_sentence_twice(monkeypatch, again):
    b, events, _ = _streaming_brain(monkeypatch, [LONG, again])
    asyncio.run(b.turn("Why do people use a message queue?"))
    assert events[-1] == ("rest", "It smooths bursts of traffic.", "Use a queue when work can wait. It smooths bursts of traffic.")


def test_still_too_long_after_being_sent_back_the_rest_is_cut_in_code_and_the_model_gets_no_third_go(monkeypatch):
    b, events, steps = _streaming_brain(monkeypatch, [LONG, LONG.split(". ", 1)[1]])
    asyncio.run(b.turn("Why do people use a message queue?"))
    kind, rest, whole = events[-1]
    assert len(steps) == 2 and kind == "rest" and whole == cv.trim(LONG, cv.REPLY) == f"Use a queue when work can wait. {rest}"
    assert cv.length_problem(whole, cv.REPLY) is None and whole.endswith("Want an example?")  # the closing question is kept


def test_the_model_failing_after_the_first_sentence_adds_no_say_that_again(monkeypatch):
    b, events, _ = _streaming_brain(monkeypatch, [LONG])  # the step it is sent back for fails: no reply left
    asyncio.run(b.turn("Why do people use a message queue?"))
    assert [e for e in events if e != "model done"] == [("first", "Use a queue when work can wait.")]
    assert b._last_spoken == "Use a queue when work can wait."


@pytest.mark.parametrize("reply,why", [
    ("On it. I asked billing to run the checks.", "nothing was sent"),
    ("Look at `src/retry.py` first. Then run the checks.", "a path"),
    ("It took 4,200 requests a second. That is plenty.", "a number nobody gave it"),
])
def test_a_first_sentence_that_would_be_sent_back_is_not_said_ahead(monkeypatch, reply, why):
    b, events, steps = _streaming_brain(monkeypatch, [reply, "I have not sent anything yet."], known="I have not sent anything yet.")
    asyncio.run(b.turn("Can you take care of the checks?"))
    assert not [e for e in events if e[0] in ("first", "rest")], why
    assert len(steps) == 2 and events[-1] == ("speak", "I have not sent anything yet.")  # sent back once, as ever


def test_a_reply_that_fails_a_check_after_its_first_sentence_is_sent_back_with_the_reason_as_ever(monkeypatch):
    reply = "The fix is in the retry loop. Open `src/retry.py` to see it."
    b, events, steps = _streaming_brain(monkeypatch, [reply, "It adds a backoff."], known="The fix is in the retry loop. It adds a backoff.")
    asyncio.run(b.turn("Where is the fix?"))
    assert events == [("first", "The fix is in the retry loop."), "model done", "model done",
                      ("rest", "It adds a backoff.", "The fix is in the retry loop. It adds a backoff.")]
    refusal = [m for m in b.messages if m["role"] == "tool"][0]["results"][0]["result"]["error"]
    assert "path or code" in refusal and "do not say it again" in refusal and steps == [True, False]


def test_nothing_is_said_ahead_to_an_acknowledgment_a_report_or_in_a_mode_with_its_own_rules(monkeypatch):
    b, events, steps = _streaming_brain(monkeypatch, [TWO, TWO, TWO, TWO])
    b.may_stay_silent = lambda: True  # "okay, thanks": the right reply may be silence
    asyncio.run(b.turn("Okay, thanks."))
    assert not [e for e in events if e[0] == "first"]
    b.may_stay_silent = lambda: False
    asyncio.run(b.turn("[billing finished its turn] All checks pass."))  # a report: its prepared text, whole
    assert steps[-1] is False
    b.may_speak_early = lambda: False  # a meeting, a challenge
    asyncio.run(b.turn("And for a large team?"))
    assert steps[-1] is False
    b.may_speak_early, b.limit = lambda: True, lambda trigger, asked: None  # no limit: said as it is, whole
    asyncio.run(b.turn("And for one person?"))
    assert not [e for e in events if e[0] == "first"]


def test_cut_off_after_the_first_sentence_the_history_keeps_what_was_heard(monkeypatch):
    b, events, _ = _streaming_brain(monkeypatch, [TWO], interrupt_after_first=True)
    asyncio.run(b.turn("Postgres or MySQL for a small team?"))
    assert events == [("first", "Postgres, in my read.")]  # the rest was never said
    assert b.messages[-1] == {"role": "assistant", "calls": [], "said": "Postgres, in my read."}
    assert b._last_spoken == "Postgres, in my read."


def test_a_first_sentence_that_repeats_what_was_just_said_is_not_said_ahead(monkeypatch):
    ready = "The staging migration for the billing tables is ready."
    b, events, _ = _streaming_brain(monkeypatch, [f"{ready} It ran clean twice.", f"{ready} Lint is green too."])
    asyncio.run(b.turn("How is the release going?"))
    assert events[0] == ("first", ready)
    del events[:]
    asyncio.run(b.turn("And the rest of it?"))
    assert events == ["model done", ("speak", "Lint is green too.")]  # the repeat is cut from the whole reply, as ever


# ---------- the vendor seam: a step read as it is written ----------

def test_the_words_of_a_speak_call_are_read_from_json_still_being_written():
    whole = json.dumps({"text": 'She said "no" — 3.5 MB.\nשלום 😀 done'})
    for cut in range(len(whole) + 1):
        assert json.loads(whole)["text"].startswith(vendors.partial_text(whole[:cut])), cut
    assert vendors.partial_text(whole) == json.loads(whole)["text"]
    assert vendors.partial_text('{"te') == "" and vendors.partial_text('{"text": "a\\') == "a"


class _FakeStream:
    def __init__(self, events, final):
        self.events, self.final = events, final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    def __aiter__(self):
        async def run():
            for event in self.events:
                yield event
        return run()

    async def get_final_message(self):
        return self.final


def _block(index, kind, name=None):
    return SimpleNamespace(type="content_block_start", index=index, content_block=SimpleNamespace(type=kind, name=name))


def _json(index, piece):
    return SimpleNamespace(type="content_block_delta", index=index, delta=SimpleNamespace(type="input_json_delta", partial_json=piece))


def _anthropic_reads(monkeypatch, events) -> tuple[list[str], dict]:
    heard, sent = [], {}

    def stream(**request):
        sent.update(request)
        return _FakeStream(events, "the final message")
    monkeypatch.setattr(vendors, "_anthropic", lambda: SimpleNamespace(messages=SimpleNamespace(stream=stream)))
    tools = [{"name": "speak", "input_schema": {}}, {"name": "send_to_claude_code", "input_schema": {}}]
    final = asyncio.run(vendors._anthropic_stream({"model": "m", "tools": tools}, heard.append))
    assert final == "the final message"
    return heard, sent


def test_a_streamed_step_tells_the_reply_as_it_grows_when_the_reply_comes_first(monkeypatch):
    heard, sent = _anthropic_reads(monkeypatch, [
        _block(0, "thinking"), _block(1, "tool_use", "speak"), _json(1, '{"text": "Use the fi'), _json(1, 'rst one. It'),
        _json(1, ' passed."}'), SimpleNamespace(type="content_block_stop", index=1)])
    assert heard == ["", "", "Use the fi", "Use the first one. It", "Use the first one. It passed."]
    # only the speak call streams unchecked: the tools that act keep the API's check of their input
    assert [t.get("eager_input_streaming", False) for t in sent["tools"]] == [True, False]


@pytest.mark.parametrize("before", [_block(0, "tool_use", "send_to_claude_code"), _block(0, "text")])
def test_a_reply_that_follows_a_tool_call_or_text_is_never_told_ahead(monkeypatch, before):
    """A tool called first may change what is true by the time the words are said, and text before a speak call is the
    model thinking aloud: it is not spoken."""
    heard, _ = _anthropic_reads(monkeypatch, [before, _block(1, "tool_use", "speak"), _json(1, '{"text": "On it. Sent."}')])
    assert set(heard) == {""}


def test_only_a_vendor_that_streams_is_handed_the_listener(monkeypatch):
    got = {}

    async def whole(model, system, messages, tools):
        got["gemini"] = True
        return vendors.Step([])

    async def streamed(model, system, messages, tools, heard=None):
        got["anthropic"] = heard
        return vendors.Step([])
    monkeypatch.setitem(vendors._STEP, "gemini", whole)
    monkeypatch.setitem(vendors._STEP, "anthropic", streamed)
    listener = lambda text: None  # noqa: E731
    asyncio.run(vendors.step("gemini:x", "s", [], [], heard=listener))
    asyncio.run(vendors.step("anthropic:x", "s", [], [], heard=listener))
    assert got == {"gemini": True, "anthropic": listener}


# ---------- the daemon: two hand-offs to the mouth, one reply in the journal ----------

def test_the_daemon_hands_the_mouth_two_parts_and_logs_the_reply_once(d, monkeypatch):
    from pipecat.frames.frames import TTSSpeakFrame

    lines, pushed = [], []
    monkeypatch.setattr(d.logger, "info", lambda message, *a, **k: lines.append(message))
    front = d.BrainFront.__new__(d.BrainFront)

    async def push(frame, direction=None):
        pushed.append(frame.text if isinstance(frame, TTSSpeakFrame) else frame)
    monkeypatch.setattr(front, "push_frame", push, raising=False)

    async def run():
        await front._speak_first("Postgres, in my read.")
        await front._speak_rest("It is stricter.", "Postgres, in my read. It is stricter.")
    asyncio.run(run())
    assert pushed == ["Postgres, in my read.", "It is stricter."]
    assert [line for line in lines if line.startswith("speak: ")] == ["speak: 'Postgres, in my read. It is stricter.'"]
    assert d.state.conversation[-1] == ("assistant", "Postgres, in my read. It is stricter. ")  # one turn on the page
    assert not d.state.floor.blocked(time.time() + 60, False, False)  # a statement: the floor is not held for an answer
    pushed.clear()
    asyncio.run(front._speak_rest("", "Only this."))  # the rest was dropped: nothing more to the mouth
    assert pushed == []
