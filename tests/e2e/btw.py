"""A "by the way" judgment question answered by a read-only copy of a live session, which itself is left untouched.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-btw CLAUDE_VOICE_DAEMON_PORT=7872 uv run python -u -I tests/e2e/btw.py
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from hook_session import JoinedSession  # noqa: E402
from rig import Browser, fresh_state, log_lines, stop_daemon, transcribe  # noqa: E402
from scenarios import TEST_MODEL, check, reset_repo, results  # noqa: E402

REPO = Path("/tmp/cv-repo-btw")


def user_turns(transcript: Path) -> int:
    n = 0
    for line in transcript.read_text(errors="ignore").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("type") == "user" and not r.get("isMeta") and isinstance((r.get("message") or {}).get("content"), str):
            n += 1
    return n


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    reset_repo(REPO)
    fresh_state()
    session = JoinedSession(REPO, "--model", TEST_MODEL, "--permission-mode", "default")
    session.start()
    browser = Browser()
    try:
        (REPO / "ROLLOUT.md").write_text("Rollout owner: Priya Nandakumar. Rollback window: 40 minutes after deploy.\n")
        session.type("Read ROLLOUT.md and reply with only the word done. Do not repeat what it says.")
        await asyncio.sleep(30)
        await browser.connect()
        await asyncio.sleep(8)
        sessions_dir = Path.home() / ".claude" / "projects" / ("-private" + str(REPO).replace("/", "-"))
        before_files = {p.name for p in sessions_dir.glob("*.jsonl")}
        live = max(sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        turns_before = user_turns(live)
        asked = time.time()
        await browser.say("By the way, who owns the rollout, and how long is the rollback window?")
        deadline = time.time() + 90
        while time.time() < deadline and not log_lines(r"copy of .* answered in"):
            await asyncio.sleep(1)
        answered = log_lines(r"copy of .* answered in")
        check("the question goes to a copy of the session and comes back", bool(answered) and "''" not in answered[-1],
              answered=[a[-160:] for a in answered][-1:])
        await asyncio.sleep(15)
        spans = browser.speaker.speech_spans(since=asked)
        said = await transcribe(browser.speaker.audio(spans[0][0], spans[-1][1])) if spans else ""
        check("the bot says the copy's answer", "priya" in said.lower() and ("40" in said or "forty" in said.lower()),
              said=said[-300:])
        new_files = {p.name for p in sessions_dir.glob("*.jsonl")} - before_files
        check("the live session is untouched and the copy leaves no session behind",
              user_turns(live) == turns_before and not new_files, new_files=sorted(new_files),
              turns=(turns_before, user_turns(live)))
    finally:
        await browser.close()
        session.stop()
        stop_daemon()
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (by the way)")


asyncio.run(main())
