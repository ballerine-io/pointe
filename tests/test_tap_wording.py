"""A request that cannot be read out waits for a tap on the page or the phone, or the terminal. The brain's lines must say
so: a live take said "answer in the billing terminal" when a tap was the quicker way, and was available."""

import asyncio
import os
import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_orchestrator import _consent_setup, client_for, d, spoken, verdicts  # noqa: E402,F401


def test_a_yes_to_a_request_that_cannot_be_read_out_points_to_a_tap_on_the_page_or_phone(d, monkeypatch):
    active, posts = _consent_setup(d, monkeypatch)
    active.permission_cut = True
    asyncio.run(d.on_user_utterance("yes"))
    told = spoken(d.state.conn)
    assert verdicts(posts) == []
    assert "tap" in told and "page or phone" in told and "or in the terminal" in told
    assert "answer in that session's terminal" not in told


def test_the_brain_is_told_a_request_that_cannot_be_read_out_waits_for_a_tap(d, monkeypatch):
    client = client_for(d)
    auth = {"authorization": "Bearer secret"}
    base = {"cwd": "/tmp", "pid": os.getpid(), "transcript": "/tmp/none.jsonl"}
    client.post("/voice/register", headers=auth, json={"id": "e", "name": "billing", "channel_url": "http://127.0.0.1:1/ch", **base})
    client.post("/voice/permission", headers=auth, json={"channel_url": "http://127.0.0.1:1/ch", "request_id": "abcde",
                                                         "tool_name": "Bash", "description": "reset",
                                                         "input_preview": '{"command": "git reset --hard HEAD~3"}'})
    text = d.REGISTRY.active.permission_text
    assert "a yes will not count" in text and "a tap on the page or phone, or the terminal" in text
    assert "the terminal must answer it" not in text
