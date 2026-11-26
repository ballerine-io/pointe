""""No, sorry, I meant quarry, not billing" takes the request back from billing, not only re-sends it to quarry.

Tester round 6 (rec-02; 3 of 3 samples where billing still had something pending): the request reached quarry, but
billing kept working on the one sent to it by mistake. Its permission request stayed open, Pointe kept nudging about
it ("Billing's still waiting on your yes or no", "Should I tell Billing to drop it?"), and quarry's own request waited
behind it. The model's own "Disregard..." to billing was refused as a second send for one utterance. Now the daemon
tells billing to drop the request, and says no to what billing asked for it since (a no is always safe).

uv run pytest -q tests/test_correction_withdraws.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import Params, add, d, open_gates, record_channel, record_dispatch, verdicts, with_permission  # noqa: E402,F401,E501


def _send(d, message, session=None):  # noqa: F811
    p = Params(message=message, **({"session": session} if session else {}))
    asyncio.run(d.send_to_claude_code(p))
    return p.results[0]


def _misrouted(d, monkeypatch):  # noqa: F811
    billing, quarry = add(d, "b", "billing/main"), add(d, "q", "quarry/main")
    d.REGISTRY.mode = "orchestrator"
    sent, posts = record_dispatch(d, monkeypatch), record_channel(d, monkeypatch)
    open_gates(d, monkeypatch, "Tell billing to add a type hint to load batches.")
    assert _send(d, "Add a type hint to load batches.", "billing/main")["sent_to"] == ["billing/main"]
    return billing, quarry, sent, posts


def test_a_correction_tells_the_wrong_session_to_drop_the_request(d, monkeypatch):  # noqa: F811
    billing, quarry, sent, posts = _misrouted(d, monkeypatch)
    with_permission(billing, "p1")  # billing asked to look around for the request sent to it by mistake
    billing.permission_since = time.time()
    open_gates(d, monkeypatch, "No, sorry, I meant quarry, not billing.")
    result = _send(d, "Add a type hint to load batches.", "quarry/main")
    assert result["sent_to"] == ["quarry/main"]
    to_billing = [m for name, m in sent if name == "billing/main"]
    assert len(to_billing) == 2 and "type hint" in to_billing[1]
    assert "another session" in to_billing[1] and "no changes" in to_billing[1]
    assert verdicts(posts) == [{"request_id": "p1", "behavior": "deny"}] and billing.permission_id is None
    assert "billing" in result.get("say", "").lower()


def test_a_request_billing_had_before_the_mistake_is_left_alone(d, monkeypatch):  # noqa: F811
    billing, quarry, sent, posts = _misrouted(d, monkeypatch)
    with_permission(billing, "p0")
    billing.permission_since = time.time() - 600  # it was waiting before the request went there
    open_gates(d, monkeypatch, "No, sorry, I meant quarry, not billing.")
    _send(d, "Add a type hint to load batches.", "quarry/main")
    assert verdicts(posts) == [] and billing.permission_id == "p0"


def test_a_new_request_for_another_session_takes_nothing_back(d, monkeypatch):  # noqa: F811
    billing, quarry, sent, posts = _misrouted(d, monkeypatch)
    open_gates(d, monkeypatch, "Tell quarry to run the nightly import.")
    _send(d, "Run the nightly import.", "quarry/main")
    assert len([m for name, m in sent if name == "billing/main"]) == 1
