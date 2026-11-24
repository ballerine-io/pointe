"""Skip (skip.py, docs/features/skip.md): the owner skips what Pointe is saying, and the next line that waits follows.
By the button (POST /voice/skip), by the Mac's key (the same route), and by the words "skip" or "next". The skipped
line's words stay in the conversation; a skip answers nothing.

Offline: the real FeedInjector outside a pipeline, the brain faked at its seam. No microphone, no vendor.

uv run --locked pytest -q tests/test_skip.py
"""

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import guards  # noqa: E402
import skip  # noqa: E402
from test_orchestrator import add, client_for, d, fake_conn, with_permission  # noqa: E402,F401  (d is a fixture)
from test_session_click import FakeFront  # noqa: E402
from test_switch_stops_speech import report, wire  # noqa: E402


@pytest.mark.parametrize("said", ["skip", "Skip.", "next", "Next one.", "skip this", "okay, skip it", "skip this message",
                                  "next message, please", "דלג", "הבא"])
def test_the_skip_phrases(said):
    assert skip.intent(said)


@pytest.mark.parametrize("said", ["skip the tests", "next, run the linter", "what's next?", "tell billing to skip the "
                                  "migration", "next week", "yes", "stop", "skip to the deploy step"])
def test_other_sentences_are_not_a_skip(said):
    assert not skip.intent(said)


@pytest.mark.parametrize("said", ["skip", "next", "skip it", "next one"])
def test_a_skip_is_never_a_yes(said):
    assert guards.permission_answer(said) != "allow" and guards.consent(said) != "allow"


@pytest.fixture
def call(d, monkeypatch):
    """A live call; Pointe is in the middle of alpha's report, and beta's and gamma's wait behind it."""
    monkeypatch.setattr(d, "UPDATE_POLL_SECS", 0.01)
    monkeypatch.setattr(d, "FRONT", "brain")
    monkeypatch.setattr(d.flow, "QUIET_GAP_SECS", 60.0)  # news waits a minute of quiet here: a skip must not
    alpha, beta, gamma = add(d, "a", "alpha"), add(d, "b", "beta"), add(d, "c", "gamma")
    d.REGISTRY.set_active("a")
    conn = fake_conn()
    conn.injector = inj = wire(d)
    d.state.conn, d.state.front = conn, FakeFront()
    c = SimpleNamespace(d=d, inj=inj, front=d.state.front, alpha=alpha, beta=beta, gamma=gamma)

    async def speaking():
        inj._report, inj._report_speaking, inj._bot_speaking = report(d, "alpha", "The parser refactor is done."), True, True
        d.state.floor.bot_started(time.time())
        d.ECHO.speaking = True
        await inj.inject(report(d, "beta", "All 12 tests pass."), True)
        await inj.inject(report(d, "gamma", "The docs build is green."), True)
        assert inj.queued == 2 and inj.asked_to_speak() == []

    async def the_cut_lands():
        """The mouth stops: the pipeline's stop frame reaches the injector, as after any interruption."""
        d.ECHO.speaking = False
        await inj.process_frame(d.BotStoppedSpeakingFrame(), d.FrameDirection.UPSTREAM)
        d.state.floor.said_at = 0.0

    c.speaking, c.the_cut_lands = speaking, the_cut_lands
    return c


def test_a_skip_cuts_the_line_and_the_next_one_follows_at_once(call):
    async def run():
        await call.speaking()
        result = await call.d.skip_speech("button")
        assert result == {"skipped": True, "waiting": 2}
        await call.the_cut_lands()
        await asyncio.sleep(0.2)
    asyncio.run(run())
    assert call.inj.cuts == 1, "the line being said was not cut"
    assert call.front.brain.interrupts == 1, "the rest of the reply would still be said"
    said = call.inj.asked_to_speak()
    assert len(said) == 1, "the next line did not follow the skip (the quiet gap held it), or both went at once"
    assert "All 12 tests pass." in said[0] or "[updates: 2" in said[0]
    assert not any("[resume]" in t for t in said), "the skipped report was offered again"


def test_without_a_skip_the_next_one_waits_for_the_quiet_gap(call):
    """The control: the same call, the line ends by itself, and news waits for a gap in the conversation."""
    async def run():
        await call.speaking()
        await call.the_cut_lands()
        await asyncio.sleep(0.2)
    asyncio.run(run())
    assert call.inj.asked_to_speak() == []


def test_a_skipped_report_is_not_offered_again(call):
    async def run():
        await call.speaking()
        call.inj._updates = call.d.flow.Updates()  # nothing waits: only the skipped report could come back
        await call.d.skip_speech("button")
        await call.inj.process_frame(call.d.InterruptionFrame(), call.d.FrameDirection.DOWNSTREAM)
        await call.the_cut_lands()
        await call.the_cut_lands()
        await asyncio.sleep(0.2)
    asyncio.run(run())
    assert call.inj.queued == 0 and call.inj.asked_to_speak() == []


def test_nothing_being_said_nothing_is_cut(call):
    async def run():
        return await call.d.skip_speech("button")
    assert asyncio.run(run()) == {"skipped": False, "waiting": 0}
    assert call.inj.cuts == 0 and call.front.brain.interrupts == 0


def test_with_no_call_the_route_says_nothing_was_skipped(d):
    assert client_for(d).post("/voice/skip", json={}).json() == {"skipped": False, "waiting": 0}


def test_the_route_skips(call):
    async def run():
        await call.speaking()
        return await asyncio.to_thread(lambda: client_for(call.d).post("/voice/skip", json={}).json())
    assert asyncio.run(run()) == {"skipped": True, "waiting": 2}
    assert call.inj.cuts == 1


def test_the_phone_may_skip():
    assert "/voice/skip" in guards._PHONE_PATHS


def test_a_playing_briefing_skips_its_part(call, monkeypatch):
    steered = []

    async def control(intent):
        steered.append(intent)
        return True
    monkeypatch.setattr(call.d, "briefing_control", control)

    async def run():
        await call.speaking()
        return await call.d.skip_speech("button")
    assert asyncio.run(run())["skipped"] is True
    assert steered == ["skip"] and call.inj.cuts == 0, "the briefing's own skip was not the one used"


# ---------- by voice ----------

def ears(d):
    e = d.SonioxEars.__new__(d.SonioxEars)
    e.pushed = []

    async def push(frame, direction=None):
        e.pushed.append(frame)
    e.push_frame = push
    return e


def test_skip_said_over_a_line_skips_it_and_never_reaches_the_brain(call):
    """The owner's own word cut the mouth a moment ago (a barge-in): "skip" means that line, and the next follows."""
    e = ears(call.d)

    async def run():
        await call.speaking()
        await call.the_cut_lands()  # their voice cut it
        call.d.state.floor.bot_stopped(time.time())
        await e._take("skip")
        call.d.state.floor.bot_stopped(time.time() - 5)
        await asyncio.sleep(0.2)
    asyncio.run(run())
    assert not [f for f in e.pushed if isinstance(f, call.d.InputTextRawFrame)], "the word went to the brain as a request"
    assert len(call.inj.asked_to_speak()) == 1 and "[resume]" not in call.inj.asked_to_speak()[0]
    assert ("user", "skip") in [(who, text) for who, text in call.d.state.conversation]


def test_next_with_nothing_being_said_is_the_brains(call):
    """Long after Pointe's last word, "next" is a word like any other: the brain answers it."""
    call.d.state.floor.bot_stopped(time.time() - 60)

    async def run():
        assert not await call.d._skip_by_voice("next")
    asyncio.run(run())
    assert call.inj.cuts == 0


def test_a_skipped_permission_read_out_opens_no_yes_window(call):
    """The request's read-out was skipped: a yes after it must not approve what was not heard."""
    with_permission(call.alpha, "p1", delivered_at=time.time())
    call.d.state.last_line_id = "p1"

    async def run():
        await call.speaking()
        await call.d.skip_speech("button")
    asyncio.run(run())
    assert call.alpha.permission_delivered_at == float("inf"), "a yes would still approve a request the owner skipped"
