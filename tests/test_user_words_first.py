"""The user's own words are never swallowed by session news queued behind them. From a live run: "Send lantern this
question: ..." was typed while a report and the conflict alarm were still queued; the news reached the brain right
after the words, became the last message the model read, and the model answered the news and never sent. Typed and
spoken words take the same path (an InputTextRawFrame into the brain), so both are covered here."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import vendors  # noqa: E402
from test_orchestrator import _brain, _say  # noqa: E402

ASK = "Send lantern this question: which database did the migration run against?"
NEWS = "[billing finished its turn, not the active session] Say one short line, starting with its name:\nBilling's test failed."
NOTE = "[lantern finished its turn, keep this in mind, say nothing] It ran the migration."


def _last_text(messages):
    return next(m["content"] for m in reversed(messages) if m["role"] == "user" and "right now" not in m["content"])


def _setup(monkeypatch, slow_first=0.05):
    """A model that sends when the newest thing it reads is the user's request, and reads out the news otherwise."""
    sent, read = [], []

    async def send(params):
        sent.append(params.arguments["message"])
        await params.result_callback({"sent_to": ["lantern"]})

    tool = SimpleNamespace(name="send_to_claude_code", description="d", properties={}, required=[], handler=send)
    b, spoken = _brain([], [tool])

    async def step(_choice, _system, messages, _tools):
        last = _last_text(messages)
        read.append(last)
        await asyncio.sleep(slow_first if len(read) == 1 else 0)
        if messages[-1]["role"] == "tool":
            return _say("Done.", f"done{len(read)}")
        if last == ASK:
            return vendors.Step([{"id": f"s{len(read)}", "name": "send_to_claude_code",
                                  "args": {"message": "Which database did the migration run against?"}}])
        return _say("Billing's test failed.", f"n{len(read)}")

    monkeypatch.setattr(vendors, "step", step)
    return b, spoken, sent, read


def test_news_queued_right_after_the_users_words_waits_for_their_answer(monkeypatch):
    b, spoken, sent, read = _setup(monkeypatch)

    async def go():
        user = asyncio.create_task(b.turn(ASK))  # what BrainFront does with the typed or spoken words
        news = asyncio.create_task(b.turn(NEWS))  # and with news the feed releases a moment later
        await asyncio.gather(user, news)

    asyncio.run(go())
    assert read[0] == ASK  # the user's words were what the model answered first
    assert sent == ["Which database did the migration run against?"]
    assert spoken[-1] == "Billing's test failed."  # the news still follows
    users = [m["content"] for m in b.messages if m["role"] == "user" and "right now" not in m["content"]]
    assert users.index(ASK) < users.index(NEWS)


def test_news_arriving_while_the_users_turn_is_already_running_follows_it(monkeypatch):
    b, spoken, sent, read = _setup(monkeypatch, slow_first=0.1)

    async def go():
        user = asyncio.create_task(b.turn(ASK))
        await asyncio.sleep(0.03)  # the model is reading the user's words now
        b.add_news(NOTE)  # a "say nothing" line the feed appends meanwhile
        news = asyncio.create_task(b.turn(NEWS))
        await asyncio.gather(user, news)

    asyncio.run(go())
    assert sent and read[0] == ASK
    users = [m["content"] for m in b.messages if m["role"] == "user" and "right now" not in m["content"]]
    assert users.index(ASK) < users.index(NOTE) < users.index(NEWS)
    assert spoken[-1] == "Billing's test failed."


def test_with_no_words_waiting_news_goes_at_once(monkeypatch):
    b, spoken, sent, read = _setup(monkeypatch, slow_first=0)
    b.add_news(NOTE)
    assert b.messages[-1]["content"] == NOTE
    asyncio.run(b.turn(NEWS))
    assert spoken == ["Billing's test failed."] and sent == []


def test_new_words_from_the_user_still_replace_the_ones_before(monkeypatch):
    """Two utterances in a row: the second interrupts the first (as before), and news waits for the second."""
    b, spoken, sent, read = _setup(monkeypatch, slow_first=0.1)

    async def go():
        first = asyncio.create_task(b.turn("hmm, wait"))
        await asyncio.sleep(0.03)
        b.interrupt()
        second = asyncio.create_task(b.turn(ASK))
        news = asyncio.create_task(b.turn(NEWS))
        await asyncio.gather(first, second, news)

    asyncio.run(go())
    assert sent == ["Which database did the migration run against?"]
    assert spoken[-1] == "Billing's test failed."
