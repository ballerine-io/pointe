"""Live check of the routing classifier. RUN_LIVE=1 uv run pytest -q tests/test_routing_live.py"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
pytestmark = pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="calls the Gemini API; set RUN_LIVE=1")

CASES = [  # (user said, request, expected session or None for active/unclear)
    ("What's the launch date in the notes?", "What is the launch date in the notes?", "cv-notes/main"),
    ("Fix the discount bug and run the tests.", "Fix the discount bug and run the tests.", "cv-repo/main"),
    ("Show me the pricing function.", "Show the apply_discount function in pricing.py.", "cv-repo/main"),
    ("Add a note that the launch moved to April.", "Add a note that the launch moved to April.", "cv-notes/main"),
    ("What time is it?", "What time is it?", None),
]


def _transcript(tmp: Path, name: str, text: str) -> str:
    p = tmp / f"{name.replace('/', '_')}.jsonl"
    p.write_text(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}) + "\n")
    return str(p)


@pytest.mark.parametrize("said,request_text,expected", CASES)
def test_routing(said, request_text, expected, tmp_path):
    (tmp_path / "token").write_text("t")
    os.environ["CLAUDE_VOICE_STATE"] = str(tmp_path)
    import vendors
    vendors.key("gemini")  # the environment first, then the Keychain, as the daemon reads it
    import daemon
    from sessions import Session

    repo = Session(id="r", name="cv-repo/main", cwd="/tmp/cv-repo", pid=os.getpid(), transcript=_transcript(
        tmp_path, "repo", "pricing.py has apply_discount and total; test_pricing.py has two tests."))
    notes = Session(id="n", name="cv-notes/main", cwd="/tmp/cv-notes", pid=os.getpid(), transcript=_transcript(
        tmp_path, "notes", "notes.md lists the product launch plan and dates."))
    daemon.state.last_utterance = said
    picked = asyncio.run(daemon._classify_target(request_text, [repo, notes]))
    assert (picked.name if picked else None) == expected
