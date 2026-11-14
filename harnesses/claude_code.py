"""Claude Code: the transcript under its config dir's projects/ (several accounts each have their own), the session's
inbox socket (or its voice channel in launch mode), its PermissionRequest hook (bin/voice-permission-hook ->
/voice/permission-hook -> hold_permission), and `claude -p --resume --fork-session` for side questions."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from loguru import logger

from .base import HOST, Harness

DEFAULT_HOME = Path.home() / ".claude"


def home_of(session) -> Path:
    """The Claude config dir the session runs under: each account (CLAUDE_CONFIG_DIR) keeps its own transcripts."""
    return Path(getattr(session, "home", "") or DEFAULT_HOME)


class ClaudeCode(Harness):
    name = "claude-code"
    label = "claude-code"
    agent = "Claude"
    approvals = True
    attach = True
    joins_mid_turn = True  # /pointe:voice runs inside one of its turns
    permission_deadline = 280.0  # under the hook's own timeout, in hooks/hooks.json

    def __init__(self) -> None:
        self._gone: dict[int, bool] = {}  # pid -> the last probe found it a zombie (or unknown to ps)

    @property
    def side_questions(self) -> bool:  # type: ignore[override]
        return shutil.which("claude") is not None

    def alive(self, session) -> bool:
        if not session.pid:
            return False
        try:
            os.kill(session.pid, 0)
        except (ProcessLookupError, PermissionError):
            return False
        # A killed process its parent has not reaped yet is a zombie: it answers kill(0) but is gone. That check
        # asks ps, which stalled the event loop on a live call, so probe() runs it in a thread and this reads its verdict.
        return not self._gone.get(session.pid, False)

    async def probe(self, session) -> None:
        if not session.pid:
            return
        try:
            stat = await asyncio.to_thread(_stat_of, session.pid)
        except (OSError, subprocess.SubprocessError):
            return  # no verdict this round: alive() keeps the last one
        self._gone[session.pid] = not stat.strip() or "Z" in stat

    def watch(self, session, feed):
        from sessions import follow_transcript

        return [follow_transcript(session, feed, lambda: None)]

    async def send(self, session, text: str) -> bool:
        from sessions import post_inbox, voice_message

        if session.channel_url:
            return await HOST.post_channel(session, "/utterance", {"text": voice_message(text)})
        return await post_inbox(session, text)

    def transcript_path(self, session) -> str:
        """Claude Code's record of the process wins: the id a hook reported can name a file that never appears (launch
        mode), and /clear or /resume moves a running session to a new file."""
        home = home_of(session)
        try:
            session_id = json.loads((home / "sessions" / f"{session.pid}.json").read_text()).get("sessionId")
        except (OSError, ValueError):
            return session.transcript
        if not session_id or Path(session.transcript).stem == session_id:
            return session.transcript
        found = next((home / "projects").glob(f"*/{session_id}.jsonl"), None)
        return str(found) if found else session.transcript

    def title(self, session) -> str | None:
        from sessions import session_title

        return session_title(session.transcript)

    def noise(self, text: str) -> str:
        from brief import human_text

        return human_text(text)

    async def side_question(self, session, question: str) -> str | None:
        """`claude -p --resume --fork-session`, like Claude Code's own /btw: the live session is never touched. Locked down:
        no settings (so no hooks, plugins or allow rules), no MCP servers, nothing saved, and anything that would need a
        permission is refused, so it can read files but cannot write, run commands or fetch the web."""
        args = ["claude", "-p", "--resume", session.id, "--fork-session", "--no-session-persistence", "--strict-mcp-config",
                "--setting-sources", "", "--permission-mode", "dontAsk", "--output-format", "json"]
        model = _model_of(session)
        if model:
            args += ["--model", model]
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("CLAUDE_CODE_") and k not in ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_CONFIG_DIR")}
        if getattr(session, "home", ""):
            env["CLAUDE_CONFIG_DIR"] = session.home  # its own account: the fork reads that account's transcripts
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(*args, question, cwd=session.cwd, env=env,
                                                        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.PIPE)
            out, err = await proc.communicate()
            if proc.returncode == 0:
                return (json.loads(out).get("result") or "").strip() or None
            logger.warning(f"copy of {session.name} failed ({proc.returncode}): {err.decode(errors='replace')[-200:]}")
        except (OSError, ValueError) as e:
            logger.warning(f"copy of {session.name} failed: {type(e).__name__}")
        except asyncio.CancelledError:  # the caller's timeout
            if proc is not None and proc.returncode is None:
                proc.kill()
            raise
        return None


def _stat_of(pid: int) -> str:
    return subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout


def _model_of(session) -> str | None:
    """The live session's model: a copy on another model would read its whole history cold, slower and dearer."""
    try:
        with open(session.transcript, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 400_000))
            found = re.findall(rb'"model":\s*"([\w.:-]+)"', f.read())
        return found[-1].decode() if found else None
    except OSError:
        return None
