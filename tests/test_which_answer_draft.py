"""The answer to "which one?" sends the request to that session in words that name it, not the model's first guess.

Tester round 4's first sample and the after-run, amb-01: "In the toll one, bump the version." was drafted as "Bump the
version in the toll-api project" and refused with "Toll API or toll web?". "The web one." then sent toll-web the
first draft, word for word: "Bump the version in the toll-api project". The model's own second call said toll-web.

uv run pytest -q tests/test_which_answer_draft.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import _gates_open, add, d, record_dispatch  # noqa: E402,F401  (d is the daemon fixture)


def test_a_first_draft_that_named_the_other_session_is_not_sent(d, monkeypatch):  # noqa: F811
    api, web = add(d, "a", "toll-api"), add(d, "b", "toll-web")
    d.REGISTRY.active_id = api.id
    sent = record_dispatch(d, monkeypatch)
    _gates_open(d, monkeypatch, "The web one.")
    d.state.pending_route = (time.time(), None, "Bump the version in the toll-api project.")
    assert asyncio.run(d._send("Bump the version in the toll-web project."))["sent_to"] == ["toll-web"]
    assert sent == [("toll-web", "Bump the version in the toll-web project.")]


def test_a_first_draft_that_named_no_session_is_still_sent_as_it_was(d, monkeypatch):  # noqa: F811
    api, web = add(d, "a", "toll-api"), add(d, "b", "toll-web")
    d.REGISTRY.active_id = api.id
    sent = record_dispatch(d, monkeypatch)
    _gates_open(d, monkeypatch, "The web one.")
    d.state.pending_route = (time.time(), None, "Bump the version.")
    assert asyncio.run(d._send("Bump the version, please."))["sent_to"] == ["toll-web"]
    assert sent == [("toll-web", "Bump the version.")]
