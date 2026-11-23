"""The one agent launch line, in a pty (design section 3): interactive
`claude --model <model> --permission-mode <mode> [--plugin-dir <Pointe>]` in the item repo, with a fresh
CLAUDE_CONFIG_DIR under the item folder and the API key in its environment only. HOME is untouched.

The fresh config folder gets: onboarding marked done and the repo trusted (so no dialog differs between arms), a
settings file that denies reads of the bench and staging folders, allows the benchmark's shell commands (read-only
ones by default; identifiers allows all, see its README), and adds a Stop
hook that appends a time to a file outside the repo (how the runner knows a turn ended). The API-key dialog of an
interactive session is answered "Yes" on the pty. A permission prompt that reaches the terminal is denied with Escape,
in every arm alike; that interrupts the turn, which then counts as ended.
"""

import fcntl
import json
import os
import pty
import re
import select
import signal
import struct
import subprocess
import termios
import threading
import time
from pathlib import Path

from . import ledger, scrub

ANSI = re.compile(r"\x1b\[[0-9;?<>=]*[A-Za-z~]|\x1b\][^\x07]*\x07|\x1b[()][A-Z0-9]|\x1b[=>78]")
READ_ONLY_BASH = ["ls", "cat", "head", "tail", "grep", "rg", "find", "wc", "pwd", "git status", "git diff", "git log",
                  "git grep", "git show"]


def claude_version() -> str:
    got = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=30)
    return got.stdout.strip().split(" ")[0]


def clean_env() -> dict:
    """The runner may itself run inside Claude Code: a child that inherits its markers is no real session."""
    return {k: v for k, v in os.environ.items()
            if not k.startswith("CLAUDE_CODE_") and k not in ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT",
                                                              "CLAUDE_CONFIG_DIR", "ANTHROPIC_API_KEY")}


def write_config(config: Path, repo: Path, deny_read: list[str], stops: Path, allow: list[str] | None = None) -> None:
    config.mkdir(parents=True, exist_ok=True)
    real = str(repo.resolve())
    (config / ".claude.json").write_text(json.dumps({
        "hasCompletedOnboarding": True, "theme": "dark",
        "projects": {p: {"hasTrustDialogAccepted": True} for p in {real, str(repo)}}}))
    deny = [f"Read({d}/**)" for d in deny_read] + [f"Edit({d}/**)" for d in deny_read]
    (config / "settings.json").write_text(json.dumps({
        "permissions": {"allow": allow if allow is not None else [f"Bash({c}:*)" for c in READ_ONLY_BASH], "deny": deny},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": f"date +%s >> '{stops}'"}]}]},
    }, indent=1))


class AgentPty:
    def __init__(self, repo: Path, config: Path, model: str, mode: str, deny_read: list[str], api_key: str,
                 extra_args: tuple = (), extra_env: dict | None = None, allow: list[str] | None = None):
        self.repo, self.config, self.model, self.mode = repo, config, model, mode
        self.stops = config.parent / f"{config.name}.stops"
        self.stops.write_text("")
        write_config(config, repo, deny_read, self.stops, allow)
        self.args = ("--model", model, "--permission-mode", mode, *extra_args)
        self.env = clean_env()
        self.env.update(CLAUDE_CONFIG_DIR=str(config), ANTHROPIC_API_KEY=api_key, **(extra_env or {}))
        self.screen = ""
        self.prompts_denied = 0
        self._stop = False
        self.pid = self.fd = None
        self.started = 0.0
        self._mark = 0  # screen text before this is already handled

    # ---------- life ----------

    def start(self, timeout: float = 60) -> None:
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(self.repo)
            os.execvpe("claude", ["claude", *self.args], self.env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 200, 0, 0))
        self.started = time.time()
        threading.Thread(target=self._pump, daemon=True).start()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if "?forshortcuts" in self.flat()[-3000:] or "acceptedits" in self.flat()[-3000:]:
                time.sleep(1.5)
                return
            time.sleep(0.3)
        raise TimeoutError("the agent's input box never came up: " + scrub.text(self.flat()[-400:]))

    def _pump(self) -> None:
        handled: set[str] = set()
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
                self.screen += ANSI.sub("", chunk.decode("utf-8", "replace"))
                if len(self.screen) > 200_000:
                    cut = len(self.screen) - 200_000
                    self.screen, self._mark = self.screen[cut:], max(0, self._mark - cut)
            tail = self.flat()[-2500:]
            if "doyouwanttousethisapikey" in tail and "key" not in handled:
                handled.add("key")
                time.sleep(0.4), self._write(b"\x1b[A"), time.sleep(0.3), self._write(b"\r")
            if "trustthisfolder" in tail and "trust" not in handled:
                handled.add("trust")
                time.sleep(0.4), self._write(b"\x1b[B"), time.sleep(0.2), self._write(b"\r")
            fresh = re.sub(r"\s+", "", self.screen[self._mark:]).lower()
            if "doyouwanttoproceed" in fresh or "doyouwanttomakethisedit" in fresh:
                self.prompts_denied += 1
                time.sleep(0.5), self._write(b"\x1b")
                self._mark = len(self.screen)
                with self.stops.open("a") as f:  # Escape ends the turn without the Stop hook: count it as the end
                    f.write(f"{time.time():.0f} denied\n")

    def _write(self, data: bytes) -> None:
        try:
            os.write(self.fd, data)
        except OSError:
            pass

    def flat(self) -> str:
        return re.sub(r"\s+", "", self.screen).lower()

    def type(self, text: str) -> float:
        self._write(text.replace("\n", " ").encode())
        time.sleep(0.6)
        self._write(b"\r")
        return time.time()

    def key(self, name: str) -> None:
        self._write({"escape": b"\x1b", "deny": b"\x1b", "approve": b"\r"}[name])

    def stop_count(self) -> int:
        return len([l for l in self.stops.read_text().splitlines() if l.strip()]) if self.stops.exists() else 0

    def wait_stops(self, more_than: int, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.stop_count() > more_than:
                return True
            if self.pid and not self.alive():
                return False
            time.sleep(0.5)
        return False

    def alive(self) -> bool:
        try:
            return os.waitpid(self.pid, os.WNOHANG) == (0, 0)
        except ChildProcessError:
            return False

    def stop(self) -> None:
        self._stop = True
        if self.pid is None:
            return
        for _ in range(2):
            self._write(b"\x03")
            time.sleep(0.3)
        try:
            os.close(self.fd)
        except OSError:
            pass
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(self.pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
            time.sleep(0.3)
        for _ in range(30):
            try:
                if os.waitpid(self.pid, os.WNOHANG) != (0, 0):
                    break
            except ChildProcessError:
                break
            time.sleep(0.1)

    # ---------- what it did ----------

    def transcripts(self) -> list[Path]:
        return sorted((self.config / "projects").rglob("*.jsonl")) if (self.config / "projects").exists() else []

    def messages(self) -> list[dict]:
        out = []
        for t in self.transcripts():
            for line in t.read_text(errors="ignore").splitlines():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
        return out

    def last_text(self) -> str:
        """The agent's final message so far: the text blocks of its last assistant message."""
        text = ""
        for rec in self.messages():
            content = (rec.get("message") or {}).get("content")
            if rec.get("type") == "assistant" and isinstance(content, list):
                said = "".join(c.get("text", "") for c in content if c.get("type") == "text").strip()
                if said:
                    text = said
        return text

    def usage(self) -> dict:
        """Tokens by model from the transcripts, one count per API message (a message spans several lines)."""
        seen, by_model = set(), {}
        for rec in self.messages():
            msg = rec.get("message") or {}
            u, mid = msg.get("usage"), msg.get("id")
            if rec.get("type") != "assistant" or not u or mid in seen:
                continue
            seen.add(mid)
            m = by_model.setdefault(msg.get("model", "unknown"), {"input": 0, "cache_read": 0, "cache_write": 0,
                                                                   "output": 0, "messages": 0})
            m["input"] += u.get("input_tokens", 0)
            m["cache_read"] += u.get("cache_read_input_tokens", 0)
            m["cache_write"] += u.get("cache_creation_input_tokens", 0)
            m["output"] += u.get("output_tokens", 0)
            m["messages"] += 1
        return by_model

    def usd(self) -> float:
        return sum(ledger.tokens_usd(model, u) for model, u in self.usage().items())

    def init_info(self) -> dict:
        """Permission mode and model as the session recorded them."""
        for rec in self.messages():
            if rec.get("permissionMode"):
                return {"permission_mode": rec.get("permissionMode"), "version": rec.get("version")}
        return {}


def preflight(item_dir: Path, model: str, api_key: str, deny_read: list[str], allow: list[str] | None = None) -> dict:
    """Design 4.3: a fresh config folder and the key start a session billed to the key, with no login and no user
    plugins. A one-token `claude -p` probe in the identical environment must report an API-key source."""
    repo, config = item_dir / "repo", item_dir / "config"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    stops = item_dir / "config.stops"
    write_config(config, repo, deny_read, stops, allow)
    env = clean_env()
    env.update(CLAUDE_CONFIG_DIR=str(config), ANTHROPIC_API_KEY=api_key)
    got = subprocess.run(["claude", "-p", "--output-format", "stream-json", "--verbose", "--model", model,
                          "Reply with the single word OK."], cwd=repo, env=env, capture_output=True, text=True,
                         timeout=120)
    init, result = {}, {}
    for line in got.stdout.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "system" and e.get("subtype") == "init":
            init = e
        if e.get("type") == "result":
            result = e
    creds = [p.name for p in config.rglob("*") if "credential" in p.name.lower()]
    oauth = "oauthAccount" in json.loads((config / ".claude.json").read_text() or "{}")
    user_plugins = [x.get("name") for x in init.get("plugins") or [] if x.get("path") != "builtin"]
    ok = (init.get("apiKeySource") == "ANTHROPIC_API_KEY" and not creds and not oauth and not user_plugins
          and init.get("model") == model)
    return {"ok": ok, "api_key_source": init.get("apiKeySource"), "model": init.get("model"),
            "user_plugins": user_plugins, "builtin_plugins": len(init.get("plugins") or []) - len(user_plugins), "credentials_files": creds, "oauth": oauth,
            "claude_code": init.get("claude_code_version"), "usd": float(result.get("total_cost_usd") or 0)}
