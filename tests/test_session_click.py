"""A click on a session in the page or the phone app (/voice/switch): the voice drops what it was saying or about to say,
then says, in the daemon's own words, which session it is on, what that session waits for, and where it stood.

Offline: the brain, the mouth and the pipeline are faked at their seams (state.front, the injector)."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_orchestrator import FakeInjector, add, client_for, d, fake_conn, with_permission  # noqa: E402,F401


class CuttableInjector(FakeInjector):
    """The injector's barge-in seam: a cut stops the mouth, and a report it was reading is not offered again."""

    def __init__(self):
        super().__init__()
        self.cuts = 0
        self.report_dropped = 0

    async def broadcast_interruption(self):
        self.cuts += 1

    def forget_report(self):
        self.report_dropped += 1


class FakeFront:
    """BrainFront at its seams: what the mouth was given, and whether an in-flight reply was cancelled."""

    def __init__(self):
        self.said: list[tuple[str, str | None]] = []
        self.brain = SimpleNamespace(busy=False, interrupts=0)
        self.brain.interrupt = self._interrupt

    def _interrupt(self):
        self.brain.interrupts += 1

    async def _speak(self, text, request_id=None):
        self.said.append((text, request_id))


@pytest.fixture
def call(d, monkeypatch):
    """A live call on the default (brain) front, in session mode on alpha, with the bot mid-sentence about alpha."""
    monkeypatch.setattr(d, "FOCUS_SETTLE_SECS", 0.05)
    monkeypatch.setattr(d, "FRONT", "brain")
    monkeypatch.setattr(d, "_refresh_brief", lambda s: asyncio.sleep(0))
    alpha = add(d, "a", "alpha/main")
    beta = add(d, "b", "beta/main")
    gamma = add(d, "c", "gamma/main")
    alpha.brief = {"state": "Refactoring the parser."}
    d.REGISTRY.set_active("a")
    d.REGISTRY.mode = "session"
    conn = fake_conn()
    conn.injector = CuttableInjector()
    front = FakeFront()
    d.state.conn, d.state.front = conn, front
    return SimpleNamespace(d=d, alpha=alpha, beta=beta, gamma=gamma, conn=conn, front=front)


def click(c, *names):
    """Clicks, all in flight at once (a burst), each as its own request; then whatever they started has run."""
    async def run():
        sessions = [next(s for s in c.d.REGISTRY.sessions.values() if s.name == n) for n in names]
        await asyncio.gather(*(c.d.focus_by_click(s) for s in sessions))
        await asyncio.sleep(0.2)  # the permission read-out goes after the line, from a task
    asyncio.run(run())


def lines(c) -> list[str]:
    return [text for text, _ in c.front.said]


def test_a_click_cuts_the_old_topic_and_announces_the_new_session(call):
    call.beta.brief = {"state": "Tests pass; the deploy is next."}
    call.beta.open_questions = ["Should I deploy to staging?"]
    click(call, "beta/main")
    assert call.d.REGISTRY.active is call.beta
    assert call.front.brain.interrupts >= 1, "the reply being generated about alpha was not cancelled"
    assert call.conn.injector.cuts >= 1, "what the bot was saying about alpha was not cut off"
    assert call.conn.injector.report_dropped >= 1, "a report cut by the click would be offered again"
    assert lines(call) == ["I'm now in session beta/main. It's waiting on you: Should I deploy to staging? "
                           "Last state: Tests pass; the deploy is next."]
    assert not any(respond for _, respond in call.conn.injector.fed), "the brain was asked to word it"
    assert not any("do not announce" in t.lower() for t, _ in call.conn.injector.fed)


def test_a_pending_approval_is_announced_then_read_out(call):
    call.beta.brief = {"state": "About to clean the build."}
    with_permission(call.beta, "p7", delivered_at=float("inf"))
    call.beta.permission_spoken, call.beta.permission_cut = "run: rm -rf build", False
    click(call, "beta/main")
    said = lines(call)
    assert said[0] == "I'm now in session beta/main. It's waiting for your approval. Last state: About to clean the build."
    assert len(said) == 2 and "rm -rf build" in said[1], said  # the read-out comes after the line: it opens the yes window
    assert call.front.said[1][1] == "p7"


def test_nothing_waiting_and_no_notes_yet(call):
    click(call, "gamma/main")
    assert lines(call) == ["I'm now in session gamma/main. It's not waiting on anything. I have no notes on it yet."]


def test_a_working_session_says_so(call):
    call.gamma.busy = True
    call.gamma.brief = {"state": "Running the migration"}
    click(call, "gamma/main")
    assert lines(call) == ["I'm now in session gamma/main. It's working, not waiting on you. Last state: Running the migration."]


def test_rapid_clicks_announce_only_the_last(call):
    click(call, "beta/main", "gamma/main", "beta/main", "gamma/main")
    assert call.d.REGISTRY.active is call.gamma
    assert lines(call) == ["I'm now in session gamma/main. It's not waiting on anything. I have no notes on it yet."]


def test_clicking_the_focused_session_announces_it_again(call):
    """A deliberate re-click asks where it stands now: the same cut, the same line."""
    click(call, "alpha/main")
    assert call.conn.injector.cuts >= 1
    assert lines(call) == ["I'm now in session alpha/main. It's not waiting on anything. Last state: Refactoring the parser."]


def test_a_realtime_front_is_told_the_exact_line(call, monkeypatch):
    monkeypatch.setattr(call.d, "FRONT", "gemini")
    click(call, "gamma/main")
    asked = [t for t, respond in call.conn.injector.fed if respond]
    assert len(asked) == 1 and "I'm now in session gamma. It's not waiting on anything." in asked[0], asked


def test_the_click_endpoint_announces(call):
    """The page and the phone app share /voice/switch: the endpoint itself runs the focus change."""
    assert client_for(call.d).post("/voice/switch", json={"name": "gamma/main"}).json() == {"active": "gamma/main"}
    assert lines(call) == ["I'm now in session gamma/main. It's not waiting on anything. I have no notes on it yet."]
