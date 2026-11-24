"""A typed message keeps its line breaks all the way to the session: the composer's new line (Shift+Enter on the page
and the Mac, Option+Enter on the Mac, the New line key on the iPhone), /voice/say, the conversation, and the send."""

import asyncio
import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import relay  # noqa: E402
from test_orchestrator import add, client_for, d, fake_conn, open_gates, record_dispatch, send  # noqa: E402,F401

TYPED = "Rename the column to total_cents.\nThen run the migration\nand the tests."


def test_typed_line_breaks_reach_the_conversation_and_the_screens(d, monkeypatch):
    d.state.conn = fake_conn()

    async def push(frame, direction=None):
        pass
    d.state.conn.injector.push_frame = push
    assert client_for(d).post("/voice/say", json={"text": f"  {TYPED}\n"}).status_code == 200
    assert d.state.conversation[-1] == ("user", TYPED)
    talk = client_for(d).get("/voice/status").json()["talk"]
    assert talk[-1]["text"] == TYPED and talk[-1]["typed"] is True


def test_a_send_of_the_typed_words_keeps_their_line_breaks(d, monkeypatch):
    add(d, "a", "billing")
    sent = record_dispatch(d, monkeypatch)
    open_gates(d, monkeypatch, TYPED)
    asyncio.run(send(d, "Rename the column to total_cents. Then run the migration and the tests."))
    assert sent == [("billing", TYPED)]


def test_a_send_that_wraps_the_typed_words_keeps_them_whole():
    message = "Ask: Rename the column to total_cents. Then run the migration and the tests. Report back."
    assert relay.keep_lines(message, TYPED) == f"Ask: {TYPED} Report back."


def test_spoken_words_and_reworded_sends_are_left_alone():
    assert relay.keep_lines("Run the tests.", "run the tests") == "Run the tests."
    assert relay.keep_lines("Rename it, then migrate.", TYPED) == "Rename it, then migrate."  # the brain's own words
    assert relay.keep_lines("line one\nline two", "line one\nline two") == "line one\nline two"
