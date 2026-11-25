"""A call that comes back while the user waits for an answer greets with that, not with the sessions' notes.

Tester round 4, net-02 (3 of 3): the question went to billing, the call dropped, and on the way back the greeting was
"Billing is connected and idle. It has read the notes file and is ready for your question about it.", 12 s before the
answer itself. The greeting now says what the user is waiting for.

uv run pytest -q tests/test_reconnect_greeting.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import add, d, fake_conn  # noqa: E402,F401  (d is the daemon fixture)


def _past_first_call(d, monkeypatch):  # noqa: F811
    monkeypatch.setattr(d, "first_call", lambda: False)


def test_a_question_still_out_is_what_the_greeting_says(d, monkeypatch):  # noqa: F811
    _past_first_call(d, monkeypatch)
    a = add(d, "a", "ledger")
    d.REGISTRY.active_id = a.id
    a.brief = {"state": "joined the voice, read the notes file"}
    d.state.unconfirmed = {a.id: ["What is the work branch called?"]}
    d.state.last_delegation_at = time.time() - 20
    assert d.fixed_greeting() == "Back. Still waiting on ledger's answer."


def test_an_answer_carried_over_the_drop_is_greeted_in_one_word(d, monkeypatch):  # noqa: F811
    _past_first_call(d, monkeypatch)
    a = add(d, "a", "ledger")
    d.REGISTRY.active_id = a.id
    a.brief = {"state": "x"}
    d.state.carried = [(time.time(), "[ledger finished its turn] It answered…")]
    assert d.fixed_greeting() == "Back."


def test_with_nothing_out_the_greeting_is_as_before(d, monkeypatch):  # noqa: F811
    _past_first_call(d, monkeypatch)
    a = add(d, "a", "ledger")
    d.REGISTRY.active_id = a.id
    a.brief = {"state": "x"}
    d.state.unconfirmed, d.state.carried = {}, []
    assert d.fixed_greeting() is None


def test_through_the_connect_itself(d, monkeypatch):  # noqa: F811
    """r9's net-02 after the first version of this fix: the connect clears what was sent before it, so the greeting
    never saw the question. What is still out is noted before that."""
    _past_first_call(d, monkeypatch)

    async def no_worker(_session):
        pass

    monkeypatch.setattr(d, "_add_worker", no_worker)
    a = add(d, "a", "ledger")
    d.REGISTRY.active_id = a.id
    a.brief = {"state": "joined the voice, read the notes file"}
    d.state.unconfirmed = {a.id: ["Question from the owner: what is the work branch called?"]}
    d.state.last_delegation_at = time.time() - 3
    asyncio.run(d._on_connect(fake_conn()))
    assert d.state.unconfirmed == {}  # nothing sent before the call counts as sent on it, as before
    assert d.fixed_greeting() == "Back. Still waiting on ledger's answer."
