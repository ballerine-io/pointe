""""Tell harbor to add alt text to the hero image, and also, how many tests failed in billing?" sends both parts.

Tester round 6 (adv-03; 4 of 4 samples): the first part went to harbor, and the second, the question to billing, was
refused as a second send for one utterance ("Not sent, because the user has not asked for anything new"); the reply
was cut to "I asked harbor to add the alt text. Want me to send it again?". Each part names its own session, so each
is a request of its own; one session named twice, or a part that names none, is still one delivery.

uv run pytest -q tests/test_two_part_request.py
"""

import asyncio
import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import Params, add, d, open_gates, record_dispatch  # noqa: E402,F401  (d is the daemon fixture)


def _send(d, message, session):  # noqa: F811
    p = Params(message=message, session=session)
    asyncio.run(d.send_to_claude_code(p))
    return p.results[0]


def test_each_part_naming_its_own_session_is_sent(d, monkeypatch):  # noqa: F811
    add(d, "h", "harbor/main"), add(d, "b", "billing/main")
    sent = record_dispatch(d, monkeypatch)
    open_gates(d, monkeypatch, "Tell harbor to add an alt text to the hero image, and also how many tests failed in billing?")
    assert _send(d, "Add alt text to the hero image.", "harbor/main")["sent_to"] == ["harbor/main"]
    second = _send(d, "How many tests failed in billing?", "billing/main")
    assert second.get("sent_to") == ["billing/main"], second
    assert [name for name, _ in sent] == ["harbor/main", "billing/main"]


def test_one_part_sent_twice_is_still_one_delivery(d, monkeypatch):  # noqa: F811
    add(d, "h", "harbor/main"), add(d, "b", "billing/main")
    sent = record_dispatch(d, monkeypatch)
    open_gates(d, monkeypatch, "Tell harbor to add an alt text to the hero image.")
    _send(d, "Add alt text to the hero image.", "harbor/main")
    again = _send(d, "Add alt text to the hero image, please.", "billing/main")
    assert "sent_to" not in again and [name for name, _ in sent] == ["harbor/main"]


def test_a_second_part_that_names_no_session_is_not_a_second_delivery(d, monkeypatch):  # noqa: F811
    add(d, "h", "harbor/main"), add(d, "b", "billing/main")
    sent = record_dispatch(d, monkeypatch)
    open_gates(d, monkeypatch, "Tell harbor to add an alt text to the hero image, and also how is it going?")
    _send(d, "Add alt text to the hero image.", "harbor/main")
    again = _send(d, "How is it going?", "billing/main")
    assert "sent_to" not in again and [name for name, _ in sent] == ["harbor/main"]


def test_the_second_part_aimed_at_the_first_session_is_not_sent_twice(d, monkeypatch):  # noqa: F811
    add(d, "h", "harbor/main"), add(d, "b", "billing/main")
    sent = record_dispatch(d, monkeypatch)
    open_gates(d, monkeypatch, "Tell harbor to add an alt text to the hero image, and also how many tests failed in billing?")
    _send(d, "Add alt text to the hero image.", "harbor/main")
    again = _send(d, "How many tests failed?", "harbor/main")
    assert "sent_to" not in again and [name for name, _ in sent] == ["harbor/main"]
