"""After a send that was refused or failed, the reply never says the work happened.

From the owner's live call (2026-11-25): the brain's send was refused, and it said "Speaking speed added." Nothing had
been sent, so nothing was added. The guard already refused "I've told Claude to do it" after a refusal; a reply that
claims the work itself is done ("added", "updated", "done") is refused the same way, and the truthful line is said.

uv run pytest -q tests/test_refused_send_truth.py
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import _brain, _say, _scripted  # noqa: E402


def _refusing_send(result):
    async def handler(params):
        await params.result_callback(result)
    return SimpleNamespace(name="send_to_claude_code", description="d", properties={}, required=[], handler=handler)


@pytest.mark.parametrize("claim", ["Speaking speed added.", "Done, the speaking speed is updated.", "It's set up now.",
                                   "Added a speaking speed setting to the page.", "מהירות הדיבור נוספה."])
@pytest.mark.parametrize("result", [{"error": "Not sent: it does not match what the user just said."},
                                    {"sent_to": [], "failed": ["lantern"]}])
def test_a_refused_or_failed_send_is_not_reported_as_done(monkeypatch, claim, result):
    import vendors

    b, spoken = _brain([], [_refusing_send(result)])
    truth = "I didn't send that, so nothing changed."
    _scripted(monkeypatch, [vendors.Step([{"id": "a", "name": "send_to_claude_code", "args": {"message": "Add a speaking speed setting."}}]),
                            _say(claim, "t"), _say(truth, "u")])
    asyncio.run(b.turn("Add a speaking speed setting."))
    assert spoken == [truth]


@pytest.mark.parametrize("said", ["Nothing was added: I didn't send it.", "The speed setting was not added yet.",
                                  "It wasn't sent, so it isn't done."])
def test_saying_it_did_not_happen_is_fine(said):
    b, _ = _brain([])
    assert b.speech_problem(said, False, refused=True) is None
