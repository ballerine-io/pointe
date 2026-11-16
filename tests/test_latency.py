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
    assert "at most 23 more words, in one sentence" in refusal  # the room that is left, not the limit it already used up
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


# ---------- the model reads a finished sentence while it settles ----------

def _foreseeing_brain(monkeypatch, replies: list, delay: float = 0.02, tools=()):
    """A brain whose model takes `delay` to answer. `requests` keeps what each request was sent and how it ended."""
    import brain as brain_module

    requests, spoken = [], []

    async def step(choice, instructions, messages, decls, heard=None):
        request = {"asked": [m["content"] for m in messages if m["role"] == "user"], "at": time.time(), "ended": "running"}
        requests.append(request)
        try:
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            if heard is not None:
                heard("")
                heard(reply if isinstance(reply, str) else "")
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            request["ended"] = "cancelled"
            raise
        request["ended"] = "answered"
        calls = [{"id": f"c{len(requests)}", "name": "speak", "args": {"text": reply}}] if isinstance(reply, str) else reply
        return SimpleNamespace(calls=calls, said="", raw=None, vendor="fake", usage={})

    async def speak(text, request_id=None):
        spoken.append(text)

    monkeypatch.setattr(brain_module.vendors, "step", step)
    b = brain_module.Brain("fake:model", "instructions", list(tools), lambda: "[right now] Nothing is waiting.", speak)
    b.may_stay_silent = lambda: False
    return b, requests, spoken


ASKED = "Is it better to rebase or to merge a feature branch?"


def test_a_step_started_while_the_sentence_settles_is_the_turns_own_first_step(monkeypatch):
    b, requests, spoken = _foreseeing_brain(monkeypatch, ["Rebase it."], delay=0.05)
    sent = []
    b.stage = lambda stage, when=None: sent.append(when) if stage == "brain_sent" else None

    async def run():
        b.foresee(ASKED)
        await asyncio.sleep(0.03)  # the settle time
        assert b.messages == [] and spoken == [] and not b.busy  # only a request: no history, no speech, the floor is free
        taken = time.time()
        await b.turn(ASKED)
        return taken
    taken = asyncio.run(run())
    assert len(requests) == 1 and requests[0]["ended"] == "answered" and spoken == ["Rebase it."]
    assert requests[0]["asked"][-2:] == [ASKED, "[right now] Nothing is waiting."]  # exactly what the turn would have sent
    assert sent and sent[0] < taken  # the timing line says when the request really left
    assert [m["content"] for m in b.messages if m["role"] == "user"] == [ASKED, "[right now] Nothing is waiting."]


def test_the_user_said_more_so_the_step_started_ahead_is_dropped_and_the_whole_turn_is_answered(monkeypatch):
    b, requests, spoken = _foreseeing_brain(monkeypatch, ["Rebase it.", "Merge it then."], delay=0.05)

    async def run():
        b.foresee(ASKED)
        await asyncio.sleep(0.01)
        b.foresee(f"{ASKED} We have forty people on it.")  # the next final joined the first: read again
        await asyncio.sleep(0.01)
        await b.turn(f"{ASKED} We have forty people on it.")
    asyncio.run(run())
    assert [r["ended"] for r in requests] == ["cancelled", "answered"] and spoken == ["Merge it then."]
    assert requests[1]["asked"][-2] == f"{ASKED} We have forty people on it."


def test_news_that_arrived_meanwhile_or_other_words_drop_the_step_started_ahead(monkeypatch):
    b, requests, spoken = _foreseeing_brain(monkeypatch, ["Rebase it.", "Rebase it, and billing is done.", "x", "Squash it."], delay=0.05)

    async def run():
        b.foresee(ASKED)
        await asyncio.sleep(0.01)
        b.add_news("[billing finished its turn] All checks pass.")  # the history is not what the step read
        await b.turn(ASKED)
        b.foresee("Should I squash the commits first?")
        await asyncio.sleep(0.01)
        await b.turn("Should I squash them first?")  # not the words that were read ahead
    asyncio.run(run())
    assert [r["ended"] for r in requests] == ["cancelled", "answered", "cancelled", "answered"]
    assert "[billing finished its turn] All checks pass." in requests[1]["asked"] and spoken[-1] == "Squash it."


def test_a_step_started_ahead_runs_no_tool_and_says_nothing_until_its_turn_is_taken(monkeypatch):
    ran = []

    async def handler(params):
        ran.append(params.arguments)
        await params.result_callback({"sent_to": "billing"})
    tool = SimpleNamespace(name="send_to_claude_code", description="send", properties={}, required=[], handler=handler)
    b, requests, spoken = _foreseeing_brain(
        monkeypatch, [[{"id": "t1", "name": "send_to_claude_code", "args": {"message": "run the checks"}}], "Sent."], tools=[tool])

    async def run():
        b.foresee("Ask billing to run the checks.")
        await asyncio.sleep(0.1)  # long past the model's answer
        assert ran == [] and spoken == [] and b.messages == []
        await b.turn("Ask billing to run the checks.")
    asyncio.run(run())
    assert ran == [{"message": "run the checks"}] and spoken == ["Sent."] and len(requests) == 2  # the tool ran once, in the turn


def test_forgetting_cancels_the_request_and_a_busy_brain_starts_none(monkeypatch):
    b, requests, spoken = _foreseeing_brain(monkeypatch, ["Rebase it.", "First answer.", "Second answer."], delay=0.05)

    async def run():
        b.foresee(ASKED)
        await asyncio.sleep(0.01)
        b.forget()  # an unfinished sentence followed: nothing is read ahead for it
        await asyncio.sleep(0.01)
        assert requests[0]["ended"] == "cancelled" and b._foreseen is None
        answering = asyncio.ensure_future(b.turn("What is a mutex?"))
        await asyncio.sleep(0.01)
        b.foresee(ASKED)  # the brain is answering: the history will have changed by the time this turn comes
        assert b._foreseen is None
        await answering
    asyncio.run(run())
    assert len(requests) == 2 and spoken == ["First answer."]


def test_a_step_started_ahead_that_failed_or_went_stale_is_not_used(monkeypatch):
    import brain as brain_module

    b, requests, spoken = _foreseeing_brain(monkeypatch, [RuntimeError("503"), "Rebase it.", "Too old.", "Merge it."], delay=0.01)

    async def run():
        b.foresee(ASKED)
        await asyncio.sleep(0.03)
        await b.turn(ASKED)  # the failure is not the turn's: it asks again itself
        monkeypatch.setattr(brain_module, "FORESEEN_SECS", 0.02)
        b.foresee("And for a hotfix?")
        await asyncio.sleep(0.05)
        await b.turn("And for a hotfix?")
    asyncio.run(run())
    assert spoken == ["Rebase it.", "Merge it."] and len(requests) == 4


def test_what_the_model_wrote_before_the_turn_was_taken_is_said_the_moment_it_is(monkeypatch):
    b, requests, spoken = _foreseeing_brain(monkeypatch, [TWO], delay=0.2)
    events = []

    async def speak_first(text):
        events.append(("first", text, requests[0]["ended"]))

    async def speak_rest(rest, whole):
        events.append(("rest", rest, requests[0]["ended"]))
    b.speak_first, b.speak_rest = speak_first, speak_rest
    b.limit = lambda trigger, asked: cv.limit_for(trigger, asked)

    async def run():
        b.foresee("Postgres or MySQL for a small team?")
        await asyncio.sleep(0.05)
        assert events == []  # the model has written its first sentence, and nothing is said: the turn is not taken
        await b.turn("Postgres or MySQL for a small team?")
    asyncio.run(run())
    assert events == [("first", "Postgres, in my read.", "running"), ("rest", "It is stricter and has the richer feature set.", "answered")]
    assert len(requests) == 1


def test_only_words_that_would_reach_the_brain_as_they_are_get_read_ahead(d):
    from test_orchestrator import add, with_permission

    assert d._foreseeable("What is a good name for the cache layer?")
    for words, why in (("The thing I keep forgetting to check is the", "an unfinished sentence"),
                       ("Hold on, let me finish.", "a hold"), ("Brief me on the night.", "the daemon answers it"),
                       ("Meeting mode, listening.", "a mode"), ("Start a brain dump.", "a brain dump")):
        assert not d._foreseeable(words), why
    billing = add(d, "s1", "billing")
    with_permission(billing)
    assert not d._foreseeable("What is a good name for the cache layer?")  # the words may be the answer to the request
    billing.permission_id = None
    d.state.dump = SimpleNamespace(state="review")
    assert not d._foreseeable("What is a good name for the cache layer?")  # or to the brain dump's review
    d.state.dump = None
    d.state.challenge = SimpleNamespace()
    assert not d._foreseeable("What is a good name for the cache layer?")  # a challenge has its own rules
    d.state.challenge = None
    assert d._foreseeable("What is a good name for the cache layer?")


def test_the_ears_have_the_brain_read_a_whole_sentence_while_it_settles_and_forget_an_unfinished_one(d, monkeypatch):
    from pipecat.frames.frames import TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection

    monkeypatch.setitem(d.turns.LEVELS, "normal", d.turns.Patience(complete=0.3, unfinished=0.6, maximum=5.0))
    read, taken = [], []
    front = d.BrainFront.__new__(d.BrainFront)
    front.brain = SimpleNamespace(foresee=lambda text: read.append(text), forget=lambda: read.append(None))
    d.state.front = front

    async def run():
        ears = _ears(d, monkeypatch)

        async def take(text):
            taken.append((text, list(read)))
        monkeypatch.setattr(ears, "_take", take)

        async def final(text):
            d.state.user_stopped_at = time.time()
            await d.SonioxEars.process_frame(ears, TranscriptionFrame(text=text, user_id="u", timestamp="t"), FrameDirection.DOWNSTREAM)
        await final("Is it better to rebase or to merge?")
        assert read == ["Is it better to rebase or to merge?"] and taken == []  # read at the start of the settle, not its end
        await asyncio.sleep(0.1)
        await final("I mean for a team of")  # they went on, and stopped mid-sentence: nothing is read ahead for that
        assert read[-1] is None
        await asyncio.sleep(0.1)
        await final("forty people.")
        assert read[-1] == "Is it better to rebase or to merge? I mean for a team of forty people."
        await asyncio.sleep(0.5)
        await final("Yes.")  # a short answer is the turn at once: there is no settle to read in
    asyncio.run(run())
    assert [t for t, _ in taken] == ["Is it better to rebase or to merge? I mean for a team of forty people.", "Yes."]
    assert len(read) == 3
