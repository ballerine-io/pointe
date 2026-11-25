"""Spoken progress while a session works (progress.py, docs/features/progress.md). Off by default. On, and a session has
been working on the owner's request: one short line about 20 s in, then one every 45 s, each built from what the
session's own record shows (the newest tool it used, how long since the request), never from a model.

Pinned here: the timing; that every word of a line is true by the session's record; that nothing is said after the
answer, in a meeting, a hold, a brain dump or a challenge, or over anyone; that a switch ends the updates; that muted
the line is text; that drive mode still says it, short; and the two phrases that turn it on and off."""

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import drive  # noqa: E402
import progress  # noqa: E402
from test_orchestrator import add, client_for, d, fake_conn  # noqa: E402,F401  (d is a fixture)


# ---------- the phrases ----------

@pytest.mark.parametrize("said", ["keep me posted", "Keep me posted.", "okay, keep me updated", "give me progress updates",
                                  "tell me how it's going as it works", "progress updates on", "תעדכן אותי", "תעדכן אותי תוך כדי"])
def test_the_on_phrases(said):
    assert progress.intent(said) is True


@pytest.mark.parametrize("said", ["stop updates", "Stop the updates.", "no more updates", "stop progress updates",
                                  "progress updates off", "stop keeping me posted", "בלי עדכונים", "תפסיק לעדכן"])
def test_the_off_phrases(said):
    assert progress.intent(said) is False


@pytest.mark.parametrize("said", ["keep me posted on what billing decides about the queue", "tell billing to keep me posted",
                                  "stop", "stop the update of the changelog", "update the docs", "any updates?",
                                  "ask docs to stop updates to the schema"])
def test_other_sentences_change_nothing(said):
    assert progress.intent(said) is None


# ---------- what a step is called: from the tool and its input, nothing else ----------

@pytest.mark.parametrize("tool, tool_input, step", [
    ("Bash", {"command": "uv run pytest -q tests/", "description": "Look at the logs"}, "running the tests"),
    ("Bash", {"command": "cat build.log", "description": "Run the tests"}, "running a command"),  # the command decides
    ("Edit", {"file_path": "/work/shop/billing/pricing.py"}, "editing pricing.py"),
    ("Write", {"file_path": "notes/plan.md"}, "editing plan.md"),
    ("Read", {"file_path": "/work/shop/README.md"}, "reading README.md"),
    ("Grep", {"pattern": "retry_budget"}, "searching the code"),
    ("Glob", {"pattern": "**/*.py"}, "searching the code"),
    ("WebSearch", {"query": "stripe idempotency"}, "searching the web"),
    ("WebFetch", {"url": "https://example.com"}, "reading a web page"),
    ("Task", {"prompt": "find the flaky test"}, "running a helper agent"),
    ("TodoWrite", {}, "updating its task list"),
    ("mcp__linear__get_issue", {}, "using a tool"),
])
def test_a_step_is_named_from_the_tool_and_its_input(tool, tool_input, step):
    assert progress.step_of(tool, tool_input) == step


def test_a_step_never_says_the_command_or_the_whole_path():
    said = progress.step_of("Bash", {"command": "curl -H 'Authorization: Bearer sk-test-123' https://example.com"})
    assert said == "running a command"
    assert progress.step_of("Edit", {"file_path": "/Users/dana/secret-project/app.py"}) == "editing app.py"
    assert progress.step_of("Read", {}) == "reading a file"


@pytest.mark.parametrize("secs, said", [(20, "20 seconds"), (24, "20 seconds"), (65, "a minute"), (110, "a minute and a half"),
                                        (155, "2 and a half minutes"), (200, "3 minutes"), (3700, "an hour")])
def test_how_long_is_said_plainly(secs, said):
    assert progress.elapsed(secs) == said


def test_the_line():
    assert progress.line("Billing", 21, "running the tests", new=True) == "Billing is still working, 20 seconds in. Latest step: running the tests."
    assert progress.line("Billing", 66, "running the tests", new=False) == "Billing is still on the same step, a minute in: running the tests."
    assert progress.line("Billing", 66, None, new=False) == "Billing is still working, a minute in."
    he = progress.line("billing", 21, "running the tests", new=True, hebrew=True)
    assert "billing" in he and "20 שניות" in he and "מריץ את הטסטים" in he


def test_every_line_fits_drive_mode():
    longest = progress.line("River lantern staging copy", 155, "running a helper agent", new=False)
    assert len(longest.split()) <= drive.MAX_WORDS and "screen" not in longest


# ---------- the timing ----------

def test_the_first_line_is_due_at_twenty_seconds_and_then_every_forty_five():
    watch = progress.Watch()
    watch.asked("s1", 100.0)
    assert watch.due(119.0) == [] and watch.due(120.0) == ["s1"]
    watch.said("s1", 120.0, "running the tests")
    assert watch.due(164.0) == [] and watch.due(165.0) == ["s1"]
    watch.said("s1", 165.0, "running the tests")
    assert watch.due(209.9) == [] and watch.due(210.0) == ["s1"]
    assert (progress.FIRST_SECS, progress.EVERY_SECS) == (20.0, 45.0)


def test_a_new_request_to_the_same_session_starts_the_clock_again():
    watch = progress.Watch()
    watch.asked("s1", 100.0)
    watch.said("s1", 120.0, None)
    watch.asked("s1", 130.0)
    assert watch.due(149.0) == [] and watch.due(150.0) == ["s1"]


def test_done_and_clear():
    watch = progress.Watch()
    watch.asked("s1", 100.0)
    watch.asked("s2", 101.0)
    watch.done("s1")
    assert watch.due(500.0) == ["s2"] and watch.newest() == "s2"
    watch.clear()
    assert watch.due(500.0) == [] and watch.newest() is None


# ---------- the daemon ----------

@pytest.fixture(autouse=True)
def _off_after(d):
    yield
    d.PREFS.values.pop("progress.spoken", None)
    d.state.mute = False
    if d.state.drive.on():
        d.state.drive.leave()


def _call(d, monkeypatch, on: bool = True):
    """A call with billing on it, the setting on, and everything Pointe says collected."""
    said: list[str] = []

    async def speak(text, request_id=None):
        said.append(text)
        d._bot_says(text, request_id)

    d.state.conn = fake_conn()
    d.state.front = SimpleNamespace(_speak=speak, brain=SimpleNamespace(_user_turns=0, busy=False, interrupt=lambda: None))
    if on:
        d.PREFS.values["progress.spoken"] = True
    billing = add(d, "s1", "billing")

    async def deliver(target, message):
        return True
    monkeypatch.setattr(d, "deliver", deliver)
    return billing, said


def _ask(d, session, at: float):
    async def run():
        await d._dispatch(session, "run the whole test suite")
    asyncio.run(run())
    d.state.watch.asks[session.id].since = at  # the request went at `at` on the test's clock


def _tick(d, now: float):
    asyncio.run(d._progress_tick(now))


def _step(session, tool: str, tool_input: dict, at: float):
    session.step = (at, progress.step_of(tool, tool_input))


def test_off_by_default_nothing_is_said(d, monkeypatch):
    billing, said = _call(d, monkeypatch, on=False)
    assert client_for(d).get("/voice/prefs").json()["progress.spoken"] is False
    _ask(d, billing, 1000.0)
    for now in (1020.0, 1065.0, 1110.0):
        _tick(d, now)
    assert said == []


def test_a_ninety_second_job_two_lines_each_true_none_after_the_answer(d, monkeypatch):
    billing, said = _call(d, monkeypatch)
    _ask(d, billing, 1000.0)
    _tick(d, 1010.0)
    assert said == []  # 10 s in: nothing yet
    _step(billing, "Edit", {"file_path": "/work/shop/pricing.py"}, 1012.0)
    _tick(d, 1020.5)
    assert said == ["Billing is still working, 20 seconds in. Latest step: editing pricing.py."]
    _tick(d, 1040.0)
    assert len(said) == 1  # nothing between the lines
    _step(billing, "Bash", {"command": "pytest -q"}, 1050.0)
    _tick(d, 1065.5)
    assert said[1] == "Billing is still working, a minute in. Latest step: running the tests."
    billing.busy = False  # its turn ended: the answer is on its way by the usual rules
    _tick(d, 1090.0)
    _tick(d, 1111.0)
    _tick(d, 1200.0)
    assert len(said) == 2 and "s1" not in d.state.watch.asks


def test_with_no_new_step_the_line_says_so_and_with_no_step_at_all_it_names_none(d, monkeypatch):
    billing, said = _call(d, monkeypatch)
    _ask(d, billing, 1000.0)
    billing.step = (990.0, "running the tests")  # before the request: not this request's step
    _tick(d, 1020.5)
    assert said == ["Billing is still working, 20 seconds in."]
    _step(billing, "Bash", {"command": "make build"}, 1030.0)
    _tick(d, 1065.5)
    _tick(d, 1110.5)
    assert said[1:] == ["Billing is still working, a minute in. Latest step: running a command.",
                        "Billing is still on the same step, a minute and a half in: running a command."]


def test_a_session_waiting_on_the_owner_is_not_said_to_be_working(d, monkeypatch):
    billing, said = _call(d, monkeypatch)
    _ask(d, billing, 1000.0)
    billing.permission_id = "perm-1"  # its read-out is the news; "still working" would be false
    _tick(d, 1020.5)
    assert said == []
    billing.permission_id = None
    _tick(d, 1021.5)
    assert len(said) == 1


@pytest.mark.parametrize("where", ["meeting", "hold", "brain dump", "challenge", "briefing", "silent mode"])
def test_never_in_a_mode_that_has_its_own_rules_for_speech(d, monkeypatch, where):
    billing, said = _call(d, monkeypatch)
    _ask(d, billing, 1000.0)
    if where == "meeting":
        d.state.meeting = SimpleNamespace(status=lambda: {})
    elif where == "hold":
        d.state.hold = SimpleNamespace(status=lambda: {})
    elif where == "brain dump":
        monkeypatch.setattr(d, "_dumping", lambda: True)
    elif where == "challenge":
        d.state.challenge = SimpleNamespace(status=lambda: {})
    elif where == "briefing":
        d.state.briefing_play = SimpleNamespace()
    elif where == "silent mode":
        monkeypatch.setattr(d, "current_mode", lambda: SimpleNamespace(speech="never"))
    _tick(d, 1020.5)
    _tick(d, 1070.0)
    assert said == []


def test_a_line_waits_for_the_floor_and_is_dropped_if_the_answer_came_first(d, monkeypatch):
    billing, said = _call(d, monkeypatch)
    _ask(d, billing, 1000.0)
    monkeypatch.setattr(d, "_floor_blocked", lambda **_: "the user is talking")
    _tick(d, 1020.5)
    _tick(d, 1022.0)
    assert said == []  # never over the owner
    monkeypatch.setattr(d, "_floor_blocked", lambda **_: None)
    _tick(d, 1024.0)
    assert said == ["Billing is still working, 20 seconds in."]
    monkeypatch.setattr(d, "_floor_blocked", lambda **_: "Pointe is answering")
    _tick(d, 1070.0)
    billing.busy = False
    monkeypatch.setattr(d, "_floor_blocked", lambda **_: None)
    _tick(d, 1072.0)
    assert len(said) == 1


def test_a_switch_ends_the_updates(d, monkeypatch):
    billing, said = _call(d, monkeypatch)
    _ask(d, billing, 1000.0)
    asyncio.run(d._drop_old_topic())
    _tick(d, 1020.5)
    _tick(d, 1070.0)
    assert said == [] and d.state.watch.asks == {}


def test_the_call_ending_ends_the_updates(d, monkeypatch):
    billing, said = _call(d, monkeypatch)
    _ask(d, billing, 1000.0)
    d._call_ended()
    assert d.state.watch.asks == {}


def test_a_night_shifts_own_message_is_not_the_owners_request(d, monkeypatch):
    billing, said = _call(d, monkeypatch)

    async def run():
        await d._dispatch(billing, "Continue with the next task.", for_user=False)
    asyncio.run(run())
    assert d.state.watch.asks == {}


def test_muted_the_line_is_text_and_nothing_reaches_the_mouth(d, monkeypatch):
    billing, _ = _call(d, monkeypatch)
    d.state.mute = True
    pushed = []

    async def push(frame, direction=None):
        pushed.append(frame)
    d.state.front = SimpleNamespace(push_frame=push, _speak=None, brain=SimpleNamespace(_user_turns=0, busy=False, interrupt=lambda: None))
    d.state.front._speak = lambda text, request_id=None: d.BrainFront._speak(d.state.front, text, request_id)
    _ask(d, billing, 1000.0)
    _tick(d, 1020.5)
    line = "Billing is still working, 20 seconds in."
    assert [f.text for f in pushed if isinstance(f, d.TTSSpeakFrame)] == [line]

    async def run():
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.tests.utils import run_test
        from test_mute import _counting_mouth
        mouth = _counting_mouth(d)
        await run_test(Pipeline([d.MuteOut(), mouth]), frames_to_send=pushed)
        return mouth.asked
    assert asyncio.run(run()) == []  # shown, not synthesised
    talk = client_for(d).get("/voice/status").json()["talk"]
    assert talk[-1]["who"] == "assistant" and line in talk[-1]["text"]


def test_drive_mode_still_says_it(d, monkeypatch):
    billing, said = _call(d, monkeypatch)
    d.state.drive.enter("voice")
    _ask(d, billing, 1000.0)
    _step(billing, "Bash", {"command": "pytest -q"}, 1005.0)
    _tick(d, 1020.5)
    assert len(said) == 1 and len(said[0].split()) <= drive.MAX_WORDS


def test_hebrew_when_the_owner_speaks_hebrew(d, monkeypatch):
    billing, said = _call(d, monkeypatch)
    _ask(d, billing, 1000.0)
    d.state.last_utterance = "תריץ את הטסטים"
    _tick(d, 1020.5)
    assert said and "20 שניות" in said[0]


def test_the_state_line_says_which_session_works(d, monkeypatch):
    billing, _ = _call(d, monkeypatch, on=False)  # the state is shown whether or not the updates are spoken
    client = client_for(d)
    assert client.get("/voice/status").json()["phase"] is None
    _ask(d, billing, time.time() - 5)
    phase = client.get("/voice/status").json()["phase"]
    assert phase["name"] == "working" and phase["session"] == "billing"
    billing.busy = False
    assert client.get("/voice/status").json()["phase"] is None


def test_keep_me_posted_and_stop_updates_by_voice(d, monkeypatch):
    _, said = _call(d, monkeypatch, on=False)
    asyncio.run(d._progress_by_voice("keep me posted", True))
    assert d.PREFS.get("progress.spoken") is True and said == [progress.ON_LINE]
    asyncio.run(d._progress_by_voice("stop updates", False))
    assert d.PREFS.get("progress.spoken") is False and said[-1] == progress.OFF_LINE
    assert d.state.conversation[-1][0] == "assistant"


def test_stop_updates_with_the_setting_off_is_someone_elses_words(d):
    assert d._progress_words("stop updates") is None  # the brain's, as before
    assert d._progress_words("keep me posted") is True
    d.PREFS.values["progress.spoken"] = True
    assert d._progress_words("stop updates") is False


def test_the_setting_is_saved(d):
    client = client_for(d)
    assert client.post("/voice/prefs", json={"progress.spoken": True}).json()["progress.spoken"] is True
    assert client.post("/voice/prefs", json={"progress.spoken": "often"}).status_code == 400


def test_the_follower_records_the_newest_step(tmp_path):
    import json

    import sessions

    path = tmp_path / "t.jsonl"
    path.write_text("")
    s = sessions.Session(id="s1", name="billing", cwd="/work/shop", transcript=str(path))
    fed = []

    async def feed(session, text, respond):
        fed.append(text)

    async def run():
        import harnesses
        task = asyncio.create_task(sessions.follow_transcript(s, feed, lambda: None))
        await asyncio.sleep(0.2)
        with path.open("a") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "uv run pytest -q"}}]}}) + "\n")
        await asyncio.sleep(0.8)
        task.cancel()
        del harnesses
    orig = sessions.current_transcript
    sessions.current_transcript = lambda session: str(path)
    try:
        before = time.time()
        asyncio.run(run())
    finally:
        sessions.current_transcript = orig
    assert s.step is not None and s.step[1] == "running the tests" and s.step[0] >= before


# ---------- the words are the same everywhere ----------

def test_the_words_are_the_same_on_the_page_and_in_the_apps():
    root = Path(__file__).resolve().parents[1]
    page = (root / "pointe" / "ui_thinking.html").read_text()
    swift = (root / "apps" / "PointeKit" / "Sources" / "PointeUI" / "Thinking.swift").read_text()
    for key, words in progress.COPY.items():
        assert f"'{words}'" in page, (key, words)
        assert f'"{words}"' in swift, (key, words)
