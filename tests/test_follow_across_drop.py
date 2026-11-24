"""What a session wrote while the call was down is read when the call comes back.

From the conversation suite (net-02, every round): the user asked billing for its work branch, the call dropped, and
billing answered 0.9 s later, inside the 2.5 s gap. The transcript follower runs only while a call is up, and a new one
started at the file's end: the answer was never read, and the call came back to "nothing needs you right now". A
follower now starts where the last one stopped on the same file, if that was within RESUME_FOLLOW_SECS.

uv run pytest -q tests/test_follow_across_drop.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import sessions  # noqa: E402

FINAL = {"type": "assistant", "message": {"stop_reason": "end_turn",
                                          "content": [{"type": "text", "text": "The branch is fix-refund-rounding."}]}}


def _follow_for(session, secs):
    fed = []

    async def feed(s, text, respond):
        fed.append(text)

    async def run():
        task = asyncio.create_task(sessions.follow_transcript(session, feed, lambda: None))
        await asyncio.sleep(secs)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    asyncio.run(run())
    return fed


def _session(tmp_path, monkeypatch):
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps({"type": "user", "message": {"content": "old"}}) + "\n")
    s = sessions.Session(id="b", name="billing", cwd=str(tmp_path), pid=1, transcript=str(path))
    monkeypatch.setattr(sessions, "current_transcript", lambda session: str(path))
    return s, path


def test_an_answer_written_between_two_followers_is_read(tmp_path, monkeypatch):
    s, path = _session(tmp_path, monkeypatch)
    _follow_for(s, 0.4)
    with path.open("a") as f:
        f.write(json.dumps(FINAL) + "\n")  # written while no call was up
    fed = _follow_for(s, 0.8)
    assert any("fix-refund-rounding" in t for t in fed)


def test_a_first_follower_starts_at_the_end(tmp_path, monkeypatch):
    s, path = _session(tmp_path, monkeypatch)
    with path.open("a") as f:
        f.write(json.dumps(FINAL) + "\n")  # before Pointe ever followed it: history, not news
    assert _follow_for(s, 0.5) == []
