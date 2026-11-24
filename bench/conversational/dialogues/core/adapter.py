"""The adapter interface, the normalized events, and the one agent launch line every arm shares.

Every arm starts the coding agent the same way: interactive `claude --model claude-haiku-5-5 --permission-mode
acceptEdits` in a pty, in the task repository, with a fresh CLAUDE_CONFIG_DIR. The Pointe arm adds only `--plugin-dir
<pointe checkout>`. No arm uses `claude -p` or `--bare`. The file system is always the primary ground truth; events are
what the harness says it did.
"""

import fcntl
import json
import os
import re
import select
import signal
import struct
import subprocess
import termios
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

AGENT_MODEL = "claude-haiku-5-5"
PERMISSION_MODE = "acceptEdits"
CAPABILITIES = ("audio_in", "text_in", "speech_out", "approvals", "sessions", "interrupt")
ANSI = re.compile(r"\x1b\[[0-9;?<>=]*[A-Za-z~]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)|\x1b[()][A-Z0-9]|\x1b[=>78]")
KEYISH = re.compile(r"sk-ant-[A-Za-z0-9_\-.]{4,}|sk-[A-Za-z0-9]{20,}|AIza[\w-]{20,}")
EVENT_KINDS = ("delivered", "approval_request", "approval_decision", "agent_turn_done", "asked", "said", "stopped")


@dataclass
class Event:
    kind: str  # one of EVENT_KINDS
    t: float
    session: str | None = None
    text: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class SpendRow:
    vendor: str
    usd: float
    how: str  # metered | computed
    what: str = ""


@dataclass
class RunEnv:
    run_id: str
    slot: Path  # /tmp/pccb/<run>/<slot>: every repo and config dir of this item run
    stage: Path  # the answer keys: never given to an arm
    api_key: str  # the agent's ANTHROPIC_API_KEY: goes only into the agent processes' environment
    port: int  # this worker's first port
    pointe: Path  # the Pointe checkout under test
    keys: dict = field(default_factory=dict)  # other vendor keys the adapter's own calls need (router, ears)
    log: list = field(default_factory=list)
    allow: list = field(default_factory=list)  # extra Bash allow rules, the same in every arm (the stop dialogues' job)
    net: dict = field(default_factory=dict)  # call impairment: loss, jitter (seconds), reconnect


class Adapter(Protocol):
    name: str
    capabilities: frozenset

    def start(self, sessions: dict, env: RunEnv) -> None: ...
    def say(self, pcm: bytes, rate: int) -> tuple[float, float]: ...
    def type(self, text: str, session: str | None = None) -> None: ...
    def key(self, name: str, session: str | None = None) -> None: ...
    def events(self) -> list: ...
    def speech(self) -> list: ...
    def versions(self) -> dict: ...
    def spend(self) -> list: ...
    def stop(self) -> None: ...


def clean_env() -> dict:
    """The parent environment without Claude Code's own markers and without any vendor key."""
    drop = ("CLAUDECODE", "CLAUDE_PID", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
            "CLAUDE_CONFIG_DIR", "GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "SONIOX_API_KEY",
            "ELEVENLABS_API_KEY")
    return {k: v for k, v in os.environ.items()
            if not k.startswith("CLAUDE_CODE_") and not k.startswith("CLAUDE_VOICE_") and k not in drop}


HOOK = ("python3 -c 'import sys,json,time; d=json.load(sys.stdin); d[\"_t\"]=time.time(); "
        "open(sys.argv[1],\"a\").write(json.dumps(d)+chr(10))' {path}")


def write_config(cfg: Path, repo: Path, deny_dirs: list, pointe: Path | None = None, allow: list | None = None) -> None:
    """A fresh CLAUDE_CONFIG_DIR: onboarding done, the folder trusted, and the same settings file in every arm.
    The settings deny reads of the answer keys and of the bench itself, and log hook events for the runner."""
    cfg.mkdir(parents=True, exist_ok=True)
    real = os.path.realpath(repo)
    (cfg / ".claude.json").write_text(json.dumps({
        "hasCompletedOnboarding": True, "theme": "dark", "autoUpdates": False,
        "projects": {str(repo): {"hasTrustDialogAccepted": True}, real: {"hasTrustDialogAccepted": True}}}))
    events = cfg / "hook-events.jsonl"
    hook = [{"hooks": [{"type": "command", "command": HOOK.format(path=events), "timeout": 5}]}]
    deny = []
    for d in deny_dirs:
        deny += [f"Read({d}/**)", f"Edit({d}/**)", f"Bash(*{d}*)"]
    settings = {"permissions": {"deny": deny, "allow": list(allow or [])},
                "hooks": {name: hook for name in ("UserPromptSubmit", "Stop", "PermissionRequest", "PreToolUse",
                                                  "PostToolUse", "PostToolUseFailure", "Notification")},
                "env": {"DISABLE_AUTOUPDATER": "1"}}
    (cfg / "settings.json").write_text(json.dumps(settings, indent=1))


class AgentSession:
    """One Claude Code process in a pty, started with the shared launch line."""

    def __init__(self, name: str, repo: Path, cfg: Path, api_key: str, extra_args: tuple = (), extra_env: dict | None = None):
        self.name, self.repo, self.cfg = name, repo, cfg
        self.args = ["claude", "--model", AGENT_MODEL, "--permission-mode", PERMISSION_MODE, *extra_args]
        self._key = api_key
        self.extra_env = extra_env or {}
        self.screen = ""
        self.last_output = 0.0
        self.proc: subprocess.Popen | None = None
        self.fd: int | None = None
        self._stop = False
        self._handled: set = set()
        self._events_pos = 0
        self.hook_events: list = []
        self.banner = ""
        self.interrupted_at = 0.0
        self.started_at = time.time()

    # ---- process ----
    def start(self, timeout: float = 90) -> None:
        env = clean_env()
        env.update(self.extra_env)
        env.update(CLAUDE_CONFIG_DIR=str(self.cfg), ANTHROPIC_API_KEY=self._key, TERM="xterm-256color",
                   DISABLE_AUTOUPDATER="1")
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 200, 0, 0))

        def child():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        self.proc = subprocess.Popen(self.args, cwd=self.repo, env=env, stdin=slave, stdout=slave, stderr=slave,
                                     preexec_fn=child, close_fds=True)
        os.close(slave)
        self.fd = master
        threading.Thread(target=self._pump, daemon=True).start()
        deadline = time.time() + timeout
        while time.time() < deadline:
            flat = self.flat()
            if "apiusagebilling" in flat and "accepteditson" in flat:
                time.sleep(1.5)
                self.banner = self._banner()
                self.started_at = time.time()
                return
            if self.proc.poll() is not None:
                break
            time.sleep(0.3)
        raise RuntimeError(f"{self.name}: the agent did not reach its prompt: {scrub(self.flat()[-300:])}")

    def _banner(self) -> str:
        m = re.search(r"(haiku[\d.]*|sonnet[\d.]*|opus[\d.]*)·(apiusagebilling|claude\w+)", self.flat())
        return m.group(0) if m else ""

    def _pump(self) -> None:
        while not self._stop:
            try:
                r, _, _ = select.select([self.fd], [], [], 0.3)
            except (OSError, ValueError):
                return
            if r:
                try:
                    chunk = os.read(self.fd, 65536)
                except OSError:
                    return
                if not chunk:
                    return
                self.screen = (self.screen + ANSI.sub("", chunk.decode("utf-8", "replace")))[-200_000:]
                self.last_output = time.time()
            flat = self.flat()[-6000:]
            if "doyouwanttousethisapikey" in flat and "key" not in self._handled:
                self._handled.add("key")
                time.sleep(0.4)
                self._write(b"\x1b[A")
                time.sleep(0.3)
                self._write(b"\r")
            if "trustthisfolder" in flat and "trust" not in self._handled:
                self._handled.add("trust")
                time.sleep(0.4)
                self._write(b"\r")

    def _write(self, data: bytes) -> None:
        try:
            os.write(self.fd, data)
        except OSError:
            pass

    def type(self, text: str) -> None:
        # Bracketed paste keeps a multi-line or long text one message; Enter sends it.
        self._write(b"\x1b[200~" + text.replace("\n", " ").encode() + b"\x1b[201~")
        time.sleep(0.6)
        self._write(b"\r")

    def key(self, name: str) -> None:
        if name in ("escape", "deny"):
            self.interrupted_at = time.time()
        if name == "escape":
            self._write(b"\x1b")
            return
        options = self.prompt_options()
        if name == "approve":
            self._write((options.get("yes") or "1").encode())
        elif name == "deny":
            self._write((options.get("no") or "3").encode())
        time.sleep(0.2)

    def prompt_options(self) -> dict:
        tail = self.flat()[-3000:]
        start = tail.rfind("doyouwant")
        opts = {}
        for m in re.finditer(r"(\d)\.(yes|no)", tail[start:] if start >= 0 else tail):
            opts.setdefault(m.group(2), m.group(1))
        return opts

    def flat(self) -> str:
        return re.sub(r"\s+", "", self.screen).lower()

    def stop(self) -> None:
        self._stop = True
        if self.proc is None:
            return
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        try:
            os.close(self.fd)
        except (OSError, TypeError):
            pass

    # ---- what the agent did ----
    def hooks(self) -> list:
        """Hook events since the session started (UserPromptSubmit, Stop, PermissionRequest, PreToolUse, ...)."""
        path = self.cfg / "hook-events.jsonl"
        if path.exists():
            with open(path) as f:
                f.seek(self._events_pos)
                for line in f:
                    if line.endswith("\n"):
                        try:
                            self.hook_events.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
                self._events_pos = f.tell()
        return self.hook_events

    def busy(self) -> bool:
        """In a turn. Claude Code's renderer erases with cursor moves the runner does not emulate, so the screen text
        cannot say idle; its hooks and its output activity can. The last hook event decides: after Stop, only fresh
        output (a turn started by Pointe's inbox shows no UserPromptSubmit) means busy; a prompt or a tool step means
        busy; a permission request refused by keypress, or an Escape, ends the turn without a Stop."""
        now = time.time()
        ev = [e for e in self.hooks() if e.get("hook_event_name") in ("UserPromptSubmit", "PreToolUse", "PostToolUse",
                                                                      "PermissionRequest", "Stop")]
        fresh = now - self.last_output < 2.5
        if not ev:
            return fresh and now - self.started_at > 5
        last = ev[-1]
        name, t = last["hook_event_name"], last["_t"]
        if self.interrupted_at > t:
            return fresh and self.last_output > self.interrupted_at + 2.5
        if name == "Stop":
            return fresh and self.last_output > t + 2.0
        if name == "PermissionRequest" or self.pending_approval() is not None:
            return False  # waiting on the user, not working: the runner tracks the open request on its own
        return now - t < 600

    def pending_approval(self) -> dict | None:
        """The open permission request, from the PermissionRequest hook, until any later step of the session. Claude
        Code sometimes shows a prompt without firing that hook; then the permission_prompt notification after an
        unfinished PreToolUse stands for it, with that PreToolUse's tool input."""
        ev = self.hooks()
        for i in range(len(ev) - 1, -1, -1):
            name = ev[i].get("hook_event_name")
            if name == "Notification" and ev[i].get("notification_type") == "permission_prompt":
                before = [e for e in ev[:i] if e.get("hook_event_name") != "Notification"]
                if before and before[-1].get("hook_event_name") == "PreToolUse":
                    req = dict(before[-1], hook_event_name="PermissionRequest")
                    return None if self.interrupted_at > req["_t"] else req
                continue
            if name == "PermissionRequest":
                later = [e for e in ev[i + 1:] if e.get("hook_event_name") in ("PostToolUse", "Stop", "UserPromptSubmit",
                                                                               "PreToolUse")]
                return None if later or self.interrupted_at > ev[i]["_t"] else ev[i]
            if name in ("PostToolUse", "Stop", "UserPromptSubmit", "PreToolUse"):
                return None
        return None

    def stops(self) -> int:
        return sum(1 for e in self.hooks() if e.get("hook_event_name") == "Stop")

    def prompts(self) -> list:
        return [e for e in self.hooks() if e.get("hook_event_name") == "UserPromptSubmit"]

    def transcripts(self) -> list:
        return sorted((self.cfg / "projects").glob("*/*.jsonl"))

    def entries(self) -> list:
        out = []
        for path in self.transcripts():
            for line in path.read_text(errors="replace").splitlines():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return out

    def last_text(self, since: float = 0) -> str:
        """The agent's last assistant text (the final message of its last turn)."""
        texts = []
        for e in self.entries():
            if e.get("type") != "assistant":
                continue
            t = _ts(e.get("timestamp"))
            if t and t < since:
                continue
            for block in (e.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text", "").strip():
                    texts.append(block["text"].strip())
        return texts[-1] if texts else ""

    def texts_since(self, since: float) -> str:
        out = []
        for e in self.entries():
            if e.get("type") != "assistant" or (_ts(e.get("timestamp")) or 0) < since:
                continue
            for block in (e.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text", "").strip():
                    out.append(block["text"].strip())
        return "\n".join(out)

    def tool_inputs(self) -> list:
        out = []
        for e in self.entries():
            if e.get("type") != "assistant":
                continue
            for block in (e.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    out.append({"tool": block.get("name"), "input": block.get("input") or {}})
        return out

    def usage(self) -> list:
        """One (model, usage) per assistant message, de-duplicated by message id (streamed parts repeat it)."""
        seen = {}
        for e in self.entries():
            msg = e.get("message") or {}
            if e.get("type") == "assistant" and msg.get("id") and msg.get("usage"):
                seen[msg["id"]] = (msg.get("model") or AGENT_MODEL, msg["usage"])
        return list(seen.values())


def _ts(value) -> float | None:
    if not value:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def scrub(text: str) -> str:
    return KEYISH.sub("[key]", text)


def claude_version() -> str:
    got = subprocess.run(["claude", "--version"], capture_output=True, text=True, env=clean_env(), timeout=30)
    return got.stdout.strip().split()[0] if got.returncode == 0 and got.stdout.strip() else "unknown"
