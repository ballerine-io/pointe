"""Claude Code: the transcript under its config dir's projects/ (several accounts each have their own), the session's
inbox socket (or its voice channel in launch mode), its PermissionRequest hook (bin/voice-permission-hook ->
/voice/permission-hook -> hold_permission), `claude -p --resume --fork-session` for side questions, and
`claude agents --json` for a prompt the session waits at in its own terminal."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from loguru import logger

import childenv

from .base import HOST, Harness, StartError, refuse_bypass

DEFAULT_HOME = Path.home() / ".claude"


# `claude agents --json`: the interface Claude Code supports for reading session state from outside. The transcript
# cannot tell a tool that runs from a tool that waits for an answer in the terminal; this can.
ROSTER = True  # tests turn it off: they never run the real `claude`
ROSTER_SECS = 15.0  # at most one read per account in this time, and only while a session could be at a prompt
ROSTER_QUIET_SECS = 5.0  # a session whose record moved this recently is working, not waiting
ROSTER_TIMEOUT_SECS = 3.0


def home_of(session) -> Path:
    """The Claude config dir the session runs under: each account (CLAUDE_CONFIG_DIR) keeps its own transcripts."""
    return Path(getattr(session, "home", "") or DEFAULT_HOME)


class ClaudeCode(Harness):
    name = "claude-code"
    label = "claude-code"
    agent = "Claude"
    approvals = True
    attach = True
    starts = True
    joins_mid_turn = True  # /pointe:voice runs inside one of its turns
    permission_deadline = 280.0  # under the hook's own timeout, in hooks/hooks.json
    # Claude Code has no supported way for another process to interrupt a running turn (docs/harnesses.md): its inbox
    # delivers between tool calls, and Escape is a key in its terminal. A hook that returns "continue": false ends the
    # turn after the hook runs, so the stop lands at the next tool step; a command already running finishes first.
    interrupts = "next_step"

    def __init__(self) -> None:
        self._gone: dict[int, bool] = {}  # pid -> the last probe found it a zombie (or unknown to ps)
        self._roster: dict[str, tuple[float, dict[int, str]]] = {}  # config dir -> when it was read, and pid -> its wait
        self._roster_asked: dict[str, float] = {}  # config dir -> when a read last began
        self._roster_seen: dict[str, float] = {}  # session id -> the read it last took its state from
        self._record_seen: dict[str, tuple] = {}  # session id -> (path, size, mtime) of its record when last read here

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
        state = stat.strip()  # the first letter is the state (Z zombie, X dead on Linux); the E flag (macOS): exiting
        self._gone[session.pid] = not state or state[0] in "ZX" or "E" in state
        if ROSTER and not session.followed:
            self._from_record(session)
        await self._see_prompt(session)

    def _from_record(self, session) -> None:
        """With nothing following its transcript (no call up on the hub), the end of the record says whether a turn is
        open, so a prompt it stops at is still read; only when the file changed."""
        path = self.transcript_path(session)
        try:
            st = os.stat(path)
        except (OSError, TypeError, ValueError):
            return
        seen = (path, st.st_size, st.st_mtime)
        if self._record_seen.get(session.id) == seen:
            return
        self._record_seen[session.id] = seen
        if st.st_mtime > session.active_at:  # it moved, as follow_transcript's _moved: a prompt read before is stale
            session.active_at = st.st_mtime
            session.blocked_on, session.blocked_since = "", None
        if (open_turn := turn_open(path)) is not None:
            session.busy = open_turn

    def _may_be_at_a_prompt(self, session, now: float) -> bool:
        """Worth a read: never looked at yet, known to wait, or in a tool call with a quiet record (the voice holding
        its request is the one wait already known)."""
        if session.id not in self._roster_seen or session.blocked_on:
            return True
        return bool(session.busy and not session.permission_id and now - session.active_at >= ROSTER_QUIET_SECS)

    async def _see_prompt(self, session) -> None:
        """Sets `blocked_on` when Claude Code says the session waits at a prompt in its terminal, and clears it when it
        says otherwise. One read serves every session of the account; a read that failed concludes nothing."""
        if not ROSTER:
            return
        home, now = getattr(session, "home", "") or "", time.time()
        if self._may_be_at_a_prompt(session, now) and now - self._roster_asked.get(home, 0.0) >= ROSTER_SECS:
            self._roster_asked[home] = now  # before the wait: the other sessions probed in this round do not read too
            self._roster[home] = (now, await _roster(home) or {})
        at, roster = self._roster.get(home, (0.0, {}))
        if at <= self._roster_seen.get(session.id, 0.0):
            return
        self._roster_seen[session.id] = at
        waits = roster.get(session.pid)
        if waits is None or session.active_at > at:
            return  # not listed, or its record moved after the read: that prompt was answered
        if not waits or session.permission_id:
            session.blocked_on, session.blocked_since = "", None
        elif session.blocked_on != waits:
            session.blocked_on, session.blocked_since = waits, now
            logger.info(f"{session.name} waits in its terminal: {waits}")

    def watch(self, session, feed):
        from sessions import follow_transcript

        return [follow_transcript(session, feed, lambda: None)]

    def can_start(self) -> str | None:
        if sys.platform != "darwin":
            return "Starting Claude Code needs a terminal window, which Pointe opens only on a Mac for now."
        return None if shutil.which("claude") else "Claude Code is not installed on this Mac."

    async def start(self, cwd: str, name: str, start_id: str) -> dict | None:
        """A new terminal window running `claude` in `cwd`: a real session the user can type into. Its SessionStart hook
        registers it with the voice (attach mode: its inbox socket), carrying `start_id`, so this returns None."""
        why = self.can_start()
        if why:
            raise StartError(why)
        script = start_script(cwd, name, start_id)
        try:
            await asyncio.to_thread(open_terminal, script)
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning(f"no terminal window for a new Claude Code session: {type(e).__name__}")
            raise StartError("Pointe could not open a terminal window for Claude Code.")
        return None

    reopens_in_terminal = True

    async def discover(self, since: float, cap: int) -> list:
        """Each known account's open sessions (`claude agents --json`, the inbox socket from Claude Code's own record of
        the process) and its recent transcripts. Whether the plugin's PermissionRequest hook runs in each, as far as
        its settings and command line say."""
        import discovery

        out = []
        known = list(HOST.known_homes() if HOST.known_homes else [])
        for key in await asyncio.to_thread(discovery.claude_homes, DEFAULT_HOME, known):
            home = Path(key) if key else DEFAULT_HOME
            # The default account by its path whenever that is not ~/.claude (tests): never the real one by accident
            entries = await _agents(key or ("" if DEFAULT_HOME == Path.home() / ".claude" else str(DEFAULT_HOME)))
            opened = await asyncio.to_thread(discovery.claude_open, home, entries or [], key)
            for found in opened:
                args = await asyncio.to_thread(discovery.process_args, found.pid)
                found.approvals = discovery.hook_applies(home, found.cwd, args, MANAGED_SETTINGS)
            recent = await asyncio.to_thread(discovery.claude_recent, home, since, {f.id for f in opened}, key, cap)
            why = self.can_start()
            for found in recent:
                found.approvals = discovery.hook_applies(home, found.cwd, "", MANAGED_SETTINGS)
                if why and found.joinable:
                    found.joinable, found.why = False, why.replace("Starting", "Reopening")
            out += opened + recent
        return out

    def attach_body(self, found) -> dict:
        """What /pointe:voice in that session would register: its id, folder, process, transcript, account and inbox
        socket. Checked again now: the process still runs and the socket is still this user's."""
        import discovery

        if not found.pid or not discovery.ours(found.pid):
            raise StartError(f"{found.name} has closed.")
        if not discovery.usable_socket(found.socket):
            raise StartError(f"Pointe cannot find how to type into {found.name}. Run /pointe:voice in that session.")
        return {"id": found.id, "name": found.name, "name_given": found.name_given, "cwd": found.cwd, "pid": found.pid,
                "transcript": found.transcript, "inbox_socket": found.socket, "config_dir": found.home}

    async def reopen(self, found, start_id: str) -> dict | None:
        """`claude --resume <id>` in a new terminal window in its folder and account, in the default permission mode;
        its SessionStart hook (matcher `resume`) joins it, carrying `start_id`, so this returns None."""
        why = self.can_start()
        if why:
            raise StartError(why.replace("Starting", "Reopening"))
        if not os.path.isdir(found.cwd):
            raise StartError(f"Not reopened: the folder of {found.name} is no longer there.")
        script = start_script(found.cwd, found.name, start_id, resume=found.id, home=found.home)
        try:
            await asyncio.to_thread(open_terminal, script)
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning(f"no terminal window to reopen a Claude Code session: {type(e).__name__}")
            raise StartError("Pointe could not open a terminal window for Claude Code.")
        return None

    async def send(self, session, text: str) -> bool:
        from sessions import post_inbox, voice_message

        if session.channel_url:
            return await HOST.post_channel(session, "/utterance", {"text": voice_message(text)})
        return await post_inbox(session, text, receipt=await asyncio.to_thread(may_hold, session))

    async def interrupt(self, session) -> bool:
        """Leaves a stop for bin/voice-stop-hook, the plugin's PreToolUse and PostToolUse hook, under the Claude Code
        session id the hook will be called with (the current transcript's name: it changes on /clear and /resume)."""
        path = stop_flag(session, self.transcript_path(session))
        if path is None:
            return False
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(f"{time.time()}\n")
        return True

    def stop_landed(self, session) -> bool:
        path = stop_flag(session, self.transcript_path(session))
        taken = path.with_name(path.name + ".taken") if path else None
        if taken is None or not taken.exists():
            return False
        taken.unlink(missing_ok=True)
        return True

    def drop_stop(self, session) -> None:
        path = stop_flag(session, self.transcript_path(session))
        for p in (path, path.with_name(path.name + ".taken")) if path else ():
            p.unlink(missing_ok=True)

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
        env = _env(getattr(session, "home", ""))  # its own account: the fork reads that account's transcripts
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


START_KEEP_SECS = 24 * 3600  # a start's script and settings: Claude Code reads the settings while it runs
PORT_ENV = "CLAUDE_VOICE_DAEMON_PORT"


STOP_DIR = "stop"  # under the state folder; bin/voice-stop-hook reads the same name


def stop_flag(session, transcript: str) -> Path | None:
    """Where a stop for this session waits for its hook: one file named by its Claude Code session id."""
    sid = Path(transcript or "").stem or session.id
    if not HOST.state_dir or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", sid):
        return None
    return Path(HOST.state_dir) / STOP_DIR / sid


def start_argv(name: str, settings: Path, resume: str = "") -> list[str]:
    """How Pointe starts Claude Code: its default permission mode, said outright (the flag wins over a `defaultMode` in
    the user's settings), and never a flag that skips prompts. A reopen resumes the session by its id and keeps its
    own name (the hook still joins it under the name read back)."""
    claude = shutil.which("claude") or "claude"
    if resume:
        argv = [claude, "--resume", resume, "--permission-mode", "default", "--settings", str(settings)]
    else:
        argv = [claude, "--permission-mode", "default", "--name", name, "--settings", str(settings)]
    refuse_bypass(*argv)
    return argv


def start_script(cwd: str, name: str, start_id: str, root: Path = Path(__file__).resolve().parents[2], resume: str = "",
                 home: str = "") -> Path:
    """The `.command` file a terminal runs for a new session (or a reopened one: `resume`, in account `home`), and the
    settings file with the hook that joins it. No secret is in either: the hook reads the daemon's token from the state
    dir, as /pointe:voice does."""
    state = Path(HOST.state_dir or os.environ.get("CLAUDE_VOICE_STATE", Path.home() / ".claude-voice"))
    port = str(getattr(HOST, "port", None) or os.environ.get(PORT_ENV, "7860"))
    folder = state / "starts"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    for old in folder.iterdir():  # yesterday's starts
        try:
            if time.time() - old.stat().st_mtime > START_KEEP_SECS:
                old.unlink()
        except OSError:
            pass
    settings, script = folder / f"{start_id}.json", folder / f"{start_id}.command"
    hook = " ".join(shlex.quote(a) for a in [str(root / "bin" / "register-session"), "--quiet", "--name", name, "--start", start_id])
    # "startup" only (or "resume" for a reopen): a /clear or /resume later must not register it again under a new id
    settings.write_text(json.dumps({"hooks": {"SessionStart": [{"matcher": "resume" if resume else "startup", "hooks": [
        {"type": "command", "timeout": 10, "command": hook}]}]}}))
    command = " ".join(shlex.quote(a) for a in start_argv(name, settings, resume))
    account = f" CLAUDE_CONFIG_DIR={shlex.quote(home)}" if home else ""
    script.write_text(f"#!/bin/sh\n# Written by Pointe: {'reopens' if resume else 'starts'} Claude Code here and joins it to "
                      f"the voice. Safe to delete.\n"
                      f"cd {shlex.quote(cwd)} || exit 1\n"
                      f"export CLAUDE_VOICE_STATE={shlex.quote(str(state))} {PORT_ENV}={shlex.quote(port)}{account}\n"
                      f"exec {command}\n")
    settings.chmod(0o600)
    script.chmod(0o700)
    return script


def terminal_app() -> str:
    """The terminal that gets the window: iTerm when it is the one running, else Terminal, which every Mac has."""
    try:
        running = subprocess.run(["pgrep", "-x", "iTerm2"], capture_output=True, timeout=3,
                                 env=childenv.child_env()).returncode == 0
    except (OSError, subprocess.SubprocessError):
        running = False
    return "iTerm" if running else "Terminal"


OPEN_WITH_ENV = "CLAUDE_VOICE_OPEN_WITH"  # the end-to-end tests: a program that runs the script out of sight (tmux)


def open_terminal(script: Path) -> None:
    """`open` hands the script to the terminal as a document: a new window runs it. No Automation permission is asked,
    which an AppleScript `tell` would need. Unit tests replace this; the end-to-end tests name a program that runs the
    script in a terminal of their own (CLAUDE_VOICE_OPEN_WITH), so the owner's screen is never touched."""
    instead = os.environ.get(OPEN_WITH_ENV)
    argv = [instead, str(script)] if instead else ["open", "-a", terminal_app(), str(script)]
    subprocess.run(argv, check=True, capture_output=True, timeout=15, env=childenv.child_env())


def _env(home: str) -> dict:
    """The environment for a `claude` this daemon starts: not the session's that started the daemon, no vendor key, the
    person's own gateway settings (vendors.FOR_CLAUDE_CODE), and the account (config dir) asked for."""
    import vendors

    env = {k: v for k, v in childenv.child_env(**vendors.FOR_CLAUDE_CODE).items()
           if not k.startswith("CLAUDE_CODE_") and k not in ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_CONFIG_DIR")}
    if home:
        env["CLAUDE_CONFIG_DIR"] = home
    return env


# Where Claude Code reads `crossSessionInbound` (its settings reference). The --settings flag sits between managed and
# user settings and cannot be seen from here.
MANAGED_SETTINGS = Path("/Library/Application Support/ClaudeCode/managed-settings.json")
INBOUND_ORDER = {"accept": 0, "hold": 1, "refuse": 2}
BYPASS_MODES = ("bypassPermissions", "plan")  # plan counts as bypassing when bypass is available: assume it can be
MODE_TAIL_BYTES = 256 << 10


def may_hold(session) -> bool:
    """Whether Claude Code could hold or refuse a message from the voice, so the send should ask for its receipt.
    Claude Code's rule: a `crossSessionInbound` value decides (managed, else user settings; the repository's own
    settings may only tighten it); with none, a session that bypasses permission prompts holds a message from a sender
    that asserts no mode, which the voice never does. Unknown counts as no: a reply address costs every answer."""
    value = None
    for path in (MANAGED_SETTINGS, home_of(session) / "settings.json"):
        value = _inbound(path)
        if value is not None:
            break
    cwd = Path(session.cwd or ".")
    for path in (cwd / ".claude" / "settings.json", cwd / ".claude" / "settings.local.json"):
        repo = _inbound(path)
        if repo is not None and INBOUND_ORDER[repo] > INBOUND_ORDER.get(value or "accept", 0):
            value = repo
    if value is not None:
        return value != "accept"
    return permission_mode(session.transcript) in BYPASS_MODES


def _inbound(path: Path) -> str | None:
    try:
        value = json.loads(path.read_text()).get("crossSessionInbound")
    except (OSError, ValueError, AttributeError):
        return None
    return value if value in INBOUND_ORDER else None


def permission_mode(transcript: str) -> str:
    """The session's permission mode as its transcript last recorded it (Claude Code writes it at every turn), or ""."""
    try:
        with open(transcript, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - MODE_TAIL_BYTES))
            tail = f.read().decode(errors="replace")
    except (OSError, TypeError):
        return ""
    for line in reversed(tail.splitlines()):
        if '"permissionMode"' in line:
            try:
                mode = json.loads(line).get("permissionMode")
            except (ValueError, AttributeError):
                continue
            if isinstance(mode, str):
                return mode
    return ""


def turn_open(transcript: str) -> bool | None:
    """The record's last turn has not ended: its last message is not a final answer, nor the user stopping it. None
    when the record holds no message to tell by."""
    try:
        with open(transcript, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - MODE_TAIL_BYTES))
            tail = f.read().decode(errors="replace")
    except (OSError, TypeError):
        return None
    for line in reversed(tail.splitlines()):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("isSidechain") or entry.get("isMeta") \
                or entry.get("type") not in ("user", "assistant"):
            continue
        message = entry.get("message") or {}
        if entry["type"] == "assistant":
            return message.get("stop_reason") != "end_turn"
        content = message.get("content")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
        text = " ".join(str(b.get("text") or "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
        return not text.lstrip().startswith("[Request interrupted")
    return None


def parse_roster(out: bytes | str) -> dict[int, str] | None:
    """`claude agents --json` as pid -> what that session waits for at a prompt ("" when it does not wait). Its
    `waitingFor` names the prompt ("permission prompt", "input needed", ...); None when the output is not the list."""
    try:
        entries = json.loads(out)
    except ValueError:
        return None
    if not isinstance(entries, list):
        return None
    roster = {}
    for e in entries:
        if isinstance(e, dict) and isinstance(e.get("pid"), int):
            roster[e["pid"]] = str(e.get("waitingFor") or "prompt") if e.get("status") == "waiting" else ""
    return roster


async def _agents_raw(home: str) -> bytes | None:
    """`claude agents --json` for an account, as printed. None when it could not be read: no `claude` on the path,
    one too old to know the command, or no answer in time."""
    claude = shutil.which("claude")
    if not claude:
        return None
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(claude, "agents", "--json", env=_env(home), stdin=asyncio.subprocess.DEVNULL,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), ROSTER_TIMEOUT_SECS)
    except (OSError, asyncio.TimeoutError, asyncio.CancelledError) as e:
        if proc is not None and proc.returncode is None:
            proc.kill()
        if isinstance(e, asyncio.CancelledError):  # the liveness loop's own limit
            raise
        if proc is not None:
            await proc.wait()  # reaped: a stuck `claude` leaves no zombie behind
        return None
    return out if proc.returncode == 0 else None


async def _roster(home: str) -> dict[int, str] | None:
    out = await _agents_raw(home)
    return None if out is None else parse_roster(out)


async def _agents(home: str) -> list | None:
    """Every session `claude agents --json` lists for an account; None when it could not be read."""
    out = await _agents_raw(home)
    try:
        entries = json.loads(out) if out is not None else None
    except ValueError:
        return None
    return entries if isinstance(entries, list) else None


def _stat_of(pid: int) -> str:
    return subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, timeout=5,
                          env=childenv.child_env()).stdout


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
