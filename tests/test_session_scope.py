"""Session mode speaks about one session. Every path that could speak about another session while the owner is focused
holds it instead: shown on the screens as a count, never spoken, told on the way back to orchestrator mode or when asked.

Offline: the brain, the mouth and the reading model are faked at their seams; the injector is the real FeedInjector,
so its queue, its parking and its delivery are the ones a call runs."""

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_orchestrator import add, client_for, d, fake_conn  # noqa: E402,F401  (d is a fixture)


class Voice:
    """The real FeedInjector, with what it hands the voice model recorded instead of pushed."""

    def __init__(self, d):
        self.d = d
        self.injector = d.FeedInjector()
        self.frames: list = []

        async def push(frame, direction=None):
            self.frames.append(frame)
        self.injector.push_frame = push

    def spoken(self) -> str:
        """What the voice was asked to say (a turn it answers)."""
        out = []
        for f in self.frames:
            if isinstance(f, self.d.InputTextRawFrame):
                out.append(f.text)
            elif isinstance(f, self.d.LLMMessagesAppendFrame) and f.run_llm:
                out += [m["content"] for m in f.messages]
        return "\n".join(out)

    def told(self) -> str:
        """Everything the voice model was given, spoken or kept in mind."""
        out = []
        for f in self.frames:
            if isinstance(f, self.d.InputTextRawFrame):
                out.append(f.text)
            elif isinstance(f, self.d.LLMMessagesAppendFrame):
                out += [m["content"] for m in f.messages]
        return "\n".join(out)


@pytest.fixture
def focus(d, monkeypatch):
    """A call on the brain front, focused on alpha (session mode); beta and gamma run in the background."""
    monkeypatch.setattr(d, "FRONT", "brain")
    monkeypatch.setattr(d, "_refresh_brief", lambda s: asyncio.sleep(0))
    monkeypatch.setattr(d, "_night_report", lambda s, r: asyncio.sleep(0))
    alpha = add(d, "a", "alpha")
    beta = add(d, "b", "beta")
    gamma = add(d, "c", "gamma")
    d.REGISTRY.set_active("a")
    d.REGISTRY.mode = "session"
    conn = fake_conn()
    voice = Voice(d)
    conn.injector = voice.injector
    d.state.conn, d.state.front, d.state.meeting = conn, None, None
    chimes: list[bool] = []

    async def tone(up):
        chimes.append(up)
    monkeypatch.setattr(d, "_tone", tone)
    held = getattr(d, "HELD", None)
    if held is not None:
        held.take()
    yield SimpleNamespace(d=d, alpha=alpha, beta=beta, gamma=gamma, conn=conn, voice=voice, chimes=chimes)
    if held is not None:
        held.take()
    d.state.conn = None


def _reports(d, monkeypatch, urgency: str = "normal") -> None:
    async def digest(session, text):
        return {"line": f"{session.name}: all 12 tests pass.", "say": f"{session.name} finished: all 12 tests pass.",
                "final": "All 12 tests pass, and the migration ran.", "urgency": urgency,
                "excerpt": "All 12 tests pass.", "speak": True}
    monkeypatch.setattr(d, "_digest_turn", digest)


def finished(d) -> str:
    return f"[beta {d.FINISHED_MARK} {d.FINAL_MARK}All 12 tests pass."


def held(c) -> dict:
    return client_for(c.d).get("/voice/status").json()["held"]


async def settle():
    await asyncio.sleep(0.05)


# ---------- path 1: background reports and "X finished" ----------

@pytest.mark.parametrize("urgency", ["normal", "high"])
def test_a_report_from_another_session_is_held_not_spoken_and_not_told_to_the_brain(focus, monkeypatch, urgency):
    c = focus
    _reports(c.d, monkeypatch, urgency)

    async def run():
        await c.d.feed(c.beta, finished(c.d), True)
        await settle()
    asyncio.run(run())
    assert "beta" not in c.voice.told()  # not said, and not kept in the brain's context either
    view = held(c)
    assert view["count"] == 1 and view["line"] == "1 update from other sessions"
    assert view["items"][0]["session"] == "beta" and "12 tests" in view["items"][0]["line"]


def test_a_report_of_the_focused_session_is_still_said(focus, monkeypatch):
    c = focus
    _reports(c.d, monkeypatch)

    async def run():
        await c.d.feed(c.alpha, f"[alpha {c.d.FINISHED_MARK} {c.d.FINAL_MARK}All 12 tests pass.", True)
        await settle()
    asyncio.run(run())
    assert "12 tests" in c.voice.spoken()
    assert held(c)["count"] == 0


def test_a_report_queued_before_the_focus_is_not_said_after_it(focus, monkeypatch):
    """Orchestrator mode queues beta's report while the bot talks; the owner then focuses on alpha. When the floor frees,
    the queue must not say beta's news into session mode."""
    c = focus
    _reports(c.d, monkeypatch)
    c.d.REGISTRY.mode = "orchestrator"

    async def run():
        c.voice.injector._bot_speaking = True  # the floor is taken: the report waits in the queue
        await c.d.feed(c.beta, finished(c.d), True)
        assert c.voice.injector.queued == 1
        c.d.REGISTRY.mode = "session"  # the owner focused on alpha meanwhile
        c.voice.injector._bot_speaking = False
        await c.voice.injector._deliver_if_free()
        await settle()
    asyncio.run(run())
    assert "beta" not in c.voice.spoken()
    assert held(c)["count"] == 1


# ---------- path 2: approvals, alerts and conflict alarms from other sessions ----------

def _request(d, session, request_id="p9"):
    preview = json.dumps({"command": "pytest -q", "description": "Run the tests"})
    return d._put_permission(session, request_id, "Bash", "Run the tests", preview)


def test_an_approval_from_another_session_is_not_spoken_stays_tappable_and_chimes_once(focus):
    c = focus

    async def run():
        await _request(c.d, c.beta)
        await settle()
        await _request(c.d, c.beta)  # the same request again (a node re-offers it): no second cue
        await settle()
    asyncio.run(run())
    assert "beta" not in c.voice.told()
    assert c.chimes == [False]  # one short cue, no words
    status = client_for(c.d).get("/voice/status").json()
    row = next(s for s in status["sessions"] if s["name"] == "beta")
    assert row["waiting"] and row["request_id"] == "p9"  # the card stays on every screen
    alert = next(a for a in status["attention"] if a["kind"] == "permission")
    assert alert["session"] == "beta" and not alert["quiet"]  # the phone and the desktop still raise it
    assert status["held"]["approvals"] == 1
    assert client_for(c.d).post("/voice/approve", json={"session": "beta", "request_id": "p9", "verdict": "deny"}) \
        .status_code != 404  # a tap still reaches it


def test_waiting_approvals_of_other_sessions_are_not_announced_when_a_call_connects(focus, monkeypatch):
    c = focus
    monkeypatch.setattr(c.d, "_add_worker", lambda s: asyncio.sleep(0))
    monkeypatch.setattr(c.d, "_night_watchers", lambda s: asyncio.sleep(0))
    c.beta.permission_id, c.beta.permission_text = "p7", "[permission request] Bash: run the tests\npytest -q"
    conn = c.conn
    c.d.state.conn = None

    async def run():
        await c.d._on_connect(conn)
        await settle()
    asyncio.run(run())
    assert "beta" not in c.voice.told()
    assert held(c)["approvals"] == 1


def test_another_sessions_request_kept_in_its_terminal_is_not_announced(focus, monkeypatch):
    """Approvals set to "terminal": the voice tells the user a session waits there. Not another session's, while focused."""
    c = focus
    monkeypatch.setattr(c.d.vendors, "config", lambda: {"approvals": "terminal"})

    async def run():
        await c.d._harness_permission(c.beta, "Bash", {"command": "pytest -q"})
        await settle()
    asyncio.run(run())
    assert "beta" not in c.voice.told()
    assert held(c)["items"][-1]["kind"] == "terminal"


def _conflict(d):
    now = time.time()
    return d.conflicts.Conflict(id="k1", a="b", b="c", a_name="beta", b_name="gamma", a_agent="Claude Code",
                                b_agent="Claude Code", claim_a="the migration passed", claim_b="the migration failed",
                                at_a=now - 30, at_b=now, at=now, why="opposite outcomes", severity="high",
                                question_a="Did it pass?", question_b="Did it fail?")


def test_a_conflict_alarm_between_other_sessions_is_held_and_its_card_stays(focus, monkeypatch):
    c = focus
    c.d.PREFS.update({"conflicts.spoken": True})
    conflict = _conflict(c.d)

    async def run():
        await c.d._raise_conflict(conflict)
        await settle()
    asyncio.run(run())
    assert "disagree" not in c.voice.told() and "beta" not in c.voice.told()
    assert held(c)["count"] == 1 and held(c)["items"][0]["kind"] == "conflict"


def test_a_machine_dropping_with_another_sessions_approval_is_held(focus, monkeypatch):
    c = focus
    c.beta.machine, c.beta.permission_id = "devbox", "p3"
    monkeypatch.setattr(c.d, "paired_machines", lambda: [SimpleNamespace(name="devbox", online=False, since=None)])
    c.d.state.machines_down = set()

    async def run():
        await c.d._watch_machines()
        await settle()
    asyncio.run(run())
    assert "devbox" not in c.voice.told()
    assert c.d.HELD.view()["count"] == 1  # (status reads the machines, faked here only for the drop)


# ---------- path 3: joins, closes, meeting and briefing leftovers ----------

def test_another_session_joining_is_not_announced(focus, monkeypatch):
    c = focus
    monkeypatch.setattr(c.d, "_add_worker", lambda s: asyncio.sleep(0))

    async def run():
        await c.d._join({"id": "dd", "cwd": "/tmp", "name": "delta", "name_given": True, "pid": 0})
        await settle()
    asyncio.run(run())
    assert "delta" not in c.voice.told()
    assert held(c)["items"][-1]["kind"] == "joined"


def test_another_session_closing_is_not_announced(focus, monkeypatch):
    c = focus
    monkeypatch.setattr(type(c.beta), "alive", lambda self: self.id != "b")

    async def run():
        await c.d._reap_dead()
        await settle()
    asyncio.run(run())
    assert "beta" not in c.voice.told()
    assert held(c)["items"][-1]["kind"] == "closed"


def test_news_held_by_a_meeting_is_not_said_into_session_mode(focus, monkeypatch):
    """A meeting holds beta's report; the owner focuses on alpha; the meeting ends: the news the meeting held is not said."""
    c = focus
    _reports(c.d, monkeypatch)
    c.d.REGISTRY.mode = "orchestrator"
    c.d.state.meeting = SimpleNamespace(mode="listening")

    async def run():
        await c.d.feed(c.beta, finished(c.d), True)
        assert c.d.state.monologue_held  # the meeting kept it for its end
        c.d.REGISTRY.mode = "session"
        c.d.state.meeting = None
        await c.d._after_quiet()
        await settle()
    asyncio.run(run())
    assert "beta" not in c.voice.spoken()
    assert held(c)["count"] == 1


def test_a_ready_briefing_is_not_offered_in_session_mode(focus, monkeypatch):
    c = focus
    c.d.PREFS.update({"briefings.speak_on_connect": True})
    alert = {"id": "briefing:x", "kind": "briefing", "text": "Your 08:00 briefing is ready.", "at": time.time()}
    monkeypatch.setattr(c.d, "_briefing_alert", lambda: alert)

    async def run():
        await c.d._offer_briefing(c.conn)
        await settle()
    asyncio.run(run())
    assert "briefing" not in c.voice.spoken().lower()
    assert held(c)["items"][-1]["kind"] == "briefing"


def test_focusing_stops_a_briefing_that_is_playing(focus, monkeypatch):
    """A briefing covers every session: focusing on one ends the parts left, which are about the others."""
    c = focus
    c.d.REGISTRY.mode = "orchestrator"
    monkeypatch.setattr(c.d, "FOCUS_SETTLE_SECS", 0.0)
    c.d.state.briefing_play = SimpleNamespace(briefing=SimpleNamespace(parts=lambda: ["a", "b", "c"], sections=[]),
                                              index=1, paused="")

    async def run():
        await c.d.focus_by_click(c.alpha)
        await settle()
    asyncio.run(run())
    assert c.d.state.briefing_play is None


# ---------- path 4: the brain's own context ----------

def test_the_brain_is_not_told_what_other_sessions_need_in_session_mode(focus):
    c = focus
    c.beta.needs = {"need": "a decision on the schema", "unblock": "say keep it"}
    c.gamma.permission_id = "p5"
    context = c.d._brain_context()
    assert "beta" not in context and "gamma" not in context and "schema" not in context
    assert "alpha" in context


def test_the_opening_context_names_no_other_sessions_state_in_session_mode(focus):
    c = focus
    c.beta.brief = {"state": "Migrating the invoices table."}
    opening = json.dumps(c.d._opening_context())
    assert "invoices" not in opening and "beta" not in opening


def test_orchestrator_mode_still_tells_the_brain_every_session(focus):
    c = focus
    c.d.REGISTRY.mode = "orchestrator"
    c.beta.needs = {"need": "a decision on the schema", "unblock": "say keep it"}
    assert "schema" in c.d._brain_context()


# ---------- told when the owner comes back, or asks ----------

def _hold_one(c, monkeypatch):
    _reports(c.d, monkeypatch)

    async def run():
        await c.d.feed(c.beta, finished(c.d), True)
        await settle()
    asyncio.run(run())
    assert held(c)["count"] == 1


def test_going_back_to_orchestrator_mode_tells_what_was_held(focus, monkeypatch):
    c = focus
    _hold_one(c, monkeypatch)

    async def run():
        assert client_for(c.d).post("/voice/mode", json={"mode": "orchestrator"}).status_code == 200
        await settle()
    asyncio.run(run())
    assert "12 tests" in c.voice.spoken() and "beta" in c.voice.spoken()
    assert held(c)["count"] == 0


def test_going_back_to_orchestrator_mode_by_voice_tells_what_was_held(focus, monkeypatch):
    c = focus
    _hold_one(c, monkeypatch)

    async def run():
        c.d._apply_mode("orchestrator")
        await settle()
    asyncio.run(run())
    assert "12 tests" in c.voice.spoken()


@pytest.mark.parametrize("asked", ["anything from the others?", "What about the other sessions?", "what did I miss",
                                   "מה עם האחרים?"])
def test_asking_about_the_others_tells_what_was_held_and_stays_focused(focus, monkeypatch, asked):
    c = focus
    _hold_one(c, monkeypatch)
    assert c.d.scope.others_intent(asked)

    async def run():
        await c.d._user_text(asked)
        await settle()
    asyncio.run(run())
    assert "12 tests" in c.voice.spoken()
    assert c.d.REGISTRY.mode == "session" and held(c)["count"] == 0


def test_the_badge_button_tells_what_was_held(focus, monkeypatch):
    c = focus
    _hold_one(c, monkeypatch)

    async def run():
        assert client_for(c.d).post("/voice/held", json={"action": "tell"}).status_code == 200
        await settle()
    asyncio.run(run())
    assert "12 tests" in c.voice.spoken()


def test_asking_with_nothing_held_says_so(focus):
    c = focus

    async def run():
        await c.d._user_text("anything from the others?")
        await settle()
    asyncio.run(run())
    assert c.d.scope.NONE_HELD in c.voice.spoken()


def test_focusing_on_a_session_drops_its_own_held_news(focus, monkeypatch):
    c = focus
    _hold_one(c, monkeypatch)
    monkeypatch.setattr(c.d, "FOCUS_SETTLE_SECS", 0.0)

    async def run():
        await c.d.focus_by_click(c.beta)
        await settle()
    asyncio.run(run())
    assert held(c)["count"] == 0


@pytest.mark.parametrize("said", ["anything else?", "what about the tests", "others"])
def test_other_words_are_not_the_question(d, said):
    import scope
    assert not scope.others_intent(said)


def test_the_badge_words():
    import scope
    assert scope.count_line(0) == "" and scope.count_line(1) == "1 update from other sessions"
    assert scope.count_line(3) == "3 updates from other sessions"
