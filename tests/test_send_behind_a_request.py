"""A request sent to a session that waits on its permission prompt is not called sent: the user hears that it waits, and
the prompt is put to them again.

From the conversation suite at 0.9.0 (acc-05-focus-pronoun, both turns failed): "Let's work on atlas. What's its
biggest file?" went to atlas, which asked to run find; Pointe read the request once ("atlas wants to look around, read
only: find. Should it?") and nobody answered it. "Tell it to add a lazy loading attribute wherever the hero image is
used" then went to atlas too, the pronoun resolved right, and Pointe said "Sent to atlas." Claude Code never took the
message: it held it behind the open prompt for the 90 seconds left in the call, in silence. A machine of the user's
already refuses such a send in so many words (machines.refusal: "It takes a request once that is answered"); on this
Mac the message waits in Claude Code's inbox, so it goes, and the voice says what it waits on.

uv run --locked --group test-tools pytest -q tests/test_send_behind_a_request.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_orchestrator import Params, add, d, open_gates, record_dispatch, with_permission  # noqa: E402,F401

async def send(d, message: str) -> dict:
    """The brain's send_to_claude_code, aimed at atlas as on the call (session mode on atlas)."""
    p = Params(message=message, session="atlas/main")
    await d.send_to_claude_code(p)
    return p.results[0]


SAID = "Tell it to add a lazy loading attribute wherever the hero image is used."
BRIEF = 'Add a lazy loading attribute (loading="lazy") to every place the hero image is used in the atlas repo.'


def _atlas_waiting(d, monkeypatch):
    add(d, "b", "billing/main")
    atlas = add(d, "a", "atlas/main")
    d.REGISTRY.active_id = atlas.id
    d.REGISTRY.mode = "session"  # "mode -> session on atlas/main", as in the run
    with_permission(atlas, "p7", delivered_at=time.time() - 70,
                    text='[permission request] Bash: List files\n{"command": "find . -type f -not -path ./.git/*"}')
    atlas.permission_read_at = time.time() - 70  # read out once, and not answered
    sent = record_dispatch(d, monkeypatch)
    asked_again: list[tuple[str, str]] = []

    async def read_out_when_quiet(session, request_id):
        asked_again.append((session.name, request_id))

    monkeypatch.setattr(d, "_read_out_when_quiet", read_out_when_quiet)
    open_gates(d, monkeypatch, SAID)
    return atlas, sent, asked_again


def test_a_send_behind_an_open_request_says_so_and_asks_it_again(d, monkeypatch):  # noqa: F811
    atlas, sent, asked_again = _atlas_waiting(d, monkeypatch)

    async def run():
        result = await send(d, BRIEF)
        await asyncio.sleep(0)  # the read-out task starts
        return result

    result = asyncio.run(run())
    assert sent and sent[0][0] == "atlas/main"  # it waits in Claude Code's inbox: nothing is lost
    assert "waits on its request" in result.get("say", "") and "once that is answered" in result["say"]
    assert asked_again == [("atlas/main", "p7")]
    assert atlas.permission_id == "p7"  # never answered on the user's behalf


def test_a_send_to_a_session_with_no_open_request_is_as_ever(d, monkeypatch):  # noqa: F811
    atlas, sent, asked_again = _atlas_waiting(d, monkeypatch)
    atlas.permission_id = None
    result = asyncio.run(send(d, BRIEF))
    assert sent and "waits on its request" not in result.get("say", "") and not asked_again
