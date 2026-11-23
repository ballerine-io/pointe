"""The one agent launch every arm shares: interactive `claude --model <m> --permission-mode <mode>` in a pty, in the item
repo, with a fresh CLAUDE_CONFIG_DIR and the API key in its environment only. Pointe adds `--plugin-dir`, nothing else.

Isolation: HOME is untouched (the Keychain must never see a fake HOME); the config folder is new for every run, so no
login, no user plugin and no user setting reaches the session. Its settings file allows only the shell commands the
benchmark's tasks need and denies reads of the staging folder and of this suite's own code (same file in every arm).
"""

import fcntl
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import termios
import threading
import time
from pathlib import Path

from . import keys, ledger
from .adapter import now

MODEL = "claude-haiku-5-5"
ANSI = re.compile(r"\x1b\[[0-9;?<>=]*[A-Za-z~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Z0-9]|\x1b[=>78]")
KEYS = {"escape": b"\x1b", "enter": b"\r", "up": b"\x1b[A", "down": b"\x1b[B", "ctrl-c": b"\x03"}


def claude_binary() -> str:
    """The real Claude Code binary, never a terminal multiplexer's wrapper on PATH."""
    found = shutil.which("claude") or ""
    real = os.path.realpath(found) if found else ""
    if not real or "shim" in real:
        real = os.environ.get("CLAUDE_CODE_EXECPATH", "")
    if not real or not os.path.exists(real):
        raise RuntimeError("Claude Code is not installed")
    return real


def claude_version() -> str:
    out = subprocess.run([claude_binary(), "--version"], capture_output=True, text=True, timeout=30).stdout
    return out.split()[0] if out.split() else "unknown"


def clean_env(extra: dict | None = None) -> dict:
    """The parent environment without any Claude Code session marker, multiplexer hook or vendor key."""
    drop = ("CLAUDE", "ANTHROPIC", "CMUX", "OPENAI", "GOOGLE", "GEMINI", "SONIOX", "ELEVENLABS")
    env = {k: v for k, v in os.environ.items() if not k.startswith(drop)}
    env["PATH"] = ":".join(p for p in env.get("PATH", "").split(":") if "shim" not in p)
    env.update(TERM="xterm-256color", LANG="en_US.UTF-8")
    env.update(extra or {})
    return env


def write_config(cfg: Path, repo: Path, allow: list[str], deny: list[str]) -> None:
    cfg.mkdir(parents=True, exist_ok=True)
    trusted = {str(p): {"hasTrustDialogAccepted": True} for p in {str(repo), os.path.realpath(repo)}}
    (cfg / ".claude.json").write_text(json.dumps({"hasCompletedOnboarding": True, "theme": "dark", "projects": trusted}))
    hook = cfg / "allow_in_repo.py"
    shutil.copy(Path(__file__).parent / "allow_in_repo.py", hook)
    settings = {"permissions": {"allow": allow, "deny": deny}}
    if allow:  # the preflight probe runs with no rule and no hook
        settings["hooks"] = {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "timeout": 5, "command": f"/usr/bin/python3 -I {hook} {repo}"}]}]}
    (cfg / "settings.json").write_text(json.dumps(settings, indent=1))


def preflight(cfg_root: Path, mode: str) -> dict:
    """The session is billed to the API key: a one-token probe with the same environment and a fresh config folder
    must report an API-key source, and the folder must hold no login. Stops the run otherwise."""
    repo, cfg = cfg_root / "probe-repo", cfg_root / "probe-cfg"
    repo.mkdir(parents=True, exist_ok=True)
    write_config(cfg, repo, [], [])
    env = clean_env({"CLAUDE_CONFIG_DIR": str(cfg), "ANTHROPIC_API_KEY": keys.get("ANTHROPIC_API_KEY")})
    out = subprocess.run([claude_binary(), "-p", "--output-format", "stream-json", "--verbose", "--model", MODEL,
                          "--permission-mode", mode, "Reply with the single word ok."],
                         cwd=repo, env=env, capture_output=True, text=True, timeout=120)
    env.clear()
    init, result = {}, {}
    for line in out.stdout.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") == "system" and d.get("subtype") == "init":
            init = d
        if d.get("type") == "result":
            result = d
    login = [p.name for p in cfg.iterdir() if "credential" in p.name.lower()]
    found = {"apiKeySource": init.get("apiKeySource"), "model": init.get("model"),
             "permissionMode": init.get("permissionMode"), "claude_code_version": init.get("claude_code_version"),
             "login_files": login, "usd": result.get("total_cost_usd", 0.0)}
    shutil.rmtree(cfg_root, ignore_errors=True)
    if found["apiKeySource"] != "ANTHROPIC_API_KEY" or login or found["model"] != MODEL or found["permissionMode"] != mode:
        raise RuntimeError(f"preflight failed: {found}")
    return found


class AgentPty:
    """One Claude Code session in a pty. Every byte it prints is kept with its receive time on the runner's clock."""

    def __init__(self, repo: Path, cfg: Path, mode: str, allow: list[str], deny: list[str],
                 extra_args: tuple[str, ...] = (), env_extra: dict | None = None):
        self.repo, self.cfg, self.mode = repo, cfg, mode
        self.allow, self.deny, self.extra_args, self.env_extra = allow, deny, extra_args, env_extra or {}
        self.chunks: list[tuple[float, str]] = []
        self.screen = ""
        self.handled: set[str] = set()
        self.lines: list[tuple[float, dict]] = []  # transcript lines with the time this runner first saw them
        self._stop = False
        self.pid = self.fd = None

    # ---------- start and stop ----------

    def start(self, timeout: float = 60) -> None:
        write_config(self.cfg, self.repo, self.allow, self.deny)
        env = clean_env({"CLAUDE_CONFIG_DIR": str(self.cfg), "ANTHROPIC_API_KEY": keys.get("ANTHROPIC_API_KEY"),
                         **self.env_extra})
        argv = ["claude", "--model", MODEL, "--permission-mode", self.mode, *self.extra_args]
        binary = claude_binary()
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(self.repo)
            os.execve(binary, argv, env)
        env.clear()
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 200, 0, 0))
        threading.Thread(target=self._pump, daemon=True).start()
        threading.Thread(target=self._tail, daemon=True).start()
        deadline = now() + timeout
        while now() < deadline:
            flat = self.flat()[-3000:]
            if "key" in self.handled and ("acceptedits" in flat or "⏵⏵" in flat) and "notloggedin" not in flat:
                time.sleep(1.0)
                return
            if "notloggedin" in flat:
                raise RuntimeError("the session is not on the API key")
            time.sleep(0.2)
        raise TimeoutError("Claude Code did not reach its prompt")

    def stop(self) -> None:
        self._stop = True
        for _ in range(2):
            try:
                os.write(self.fd, b"\x03")
            except (OSError, TypeError):
                break
            time.sleep(0.3)
        try:
            os.close(self.fd)
        except (OSError, TypeError):
            pass
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(self.pid, sig)
            except (ProcessLookupError, PermissionError, TypeError):
                pass
            time.sleep(0.3)
        try:
            for _ in range(30):
                if os.waitpid(self.pid, os.WNOHANG) != (0, 0):
                    break
                time.sleep(0.1)
        except (ChildProcessError, TypeError):
            pass

    # ---------- the terminal ----------

    def _pump(self) -> None:
        while not self._stop:
            try:
                r, _, _ = select.select([self.fd], [], [], 0.05)
            except (OSError, ValueError):
                return
            if r:
                try:
                    text = ANSI.sub("", os.read(self.fd, 65536).decode("utf-8", "replace"))
                except OSError:
                    return
                self.chunks.append((now(), text))
                self.screen = (self.screen + text)[-200_000:]
            flat = self.flat()[-4000:]
            if "doyouwanttousethisapikey" in flat and "key" not in self.handled:
                self.handled.add("key")
                time.sleep(0.3)
                self._write(KEYS["up"])
                time.sleep(0.2)
                self._write(KEYS["enter"])
            if "trustthisfolder" in flat and "trust" not in self.handled:
                self.handled.add("trust")
                time.sleep(0.3)
                self._write(KEYS["down"])
                time.sleep(0.2)
                self._write(KEYS["enter"])

    def _write(self, data: bytes) -> None:
        try:
            os.write(self.fd, data)
        except OSError:
            pass

    def flat(self) -> str:
        return re.sub(r"\s+", "", self.screen).lower()

    def type(self, text: str) -> float:
        """Types the text and presses Enter. Returns the time Enter was sent."""
        self._write(text.encode())
        time.sleep(0.4)
        at = now()
        self._write(KEYS["enter"])
        return at

    def key(self, name: str) -> float:
        at = now()
        self._write(KEYS[name])
        return at

    # ---------- the transcript ----------

    def transcript_path(self) -> Path | None:
        found = sorted(self.cfg.glob("projects/*/*.jsonl"), key=lambda p: p.stat().st_mtime)
        return found[-1] if found else None

    def _tail(self) -> None:
        offset, path = 0, None
        while not self._stop:
            path = path or self.transcript_path()
            if path is not None:
                try:
                    with path.open() as f:
                        f.seek(offset)
                        data = f.read()
                except OSError:
                    data = ""
                done = data.rfind("\n") + 1
                offset += len(data[:done].encode())
                t = now()
                for line in data[:done].splitlines():
                    try:
                        self.lines.append((t, json.loads(line)))
                    except ValueError:
                        pass
            time.sleep(0.05)

    def assistant_texts(self, since: float = 0) -> list[tuple[float, str]]:
        out = []
        for t, d in list(self.lines):
            if t >= since and d.get("type") == "assistant":
                for block in d.get("message", {}).get("content", []) or []:
                    if isinstance(block, dict) and block.get("type") == "text" and block.get("text", "").strip():
                        out.append((t, block["text"]))
        return out

    def turn_done_at(self, since: float) -> float | None:
        """When the agent last finished a turn (end_turn) after `since`; None while it works."""
        done = None
        for t, d in list(self.lines):
            if t < since:
                continue
            m = d.get("message", {}) if isinstance(d.get("message"), dict) else {}
            if d.get("type") == "assistant" and m.get("stop_reason") == "end_turn":
                done = t
            elif d.get("type") == "assistant" and m.get("stop_reason") == "tool_use":
                done = None
            elif d.get("type") == "user" and "[Request interrupted" in json.dumps(m.get("content", ""))[:200]:
                done = t  # Escape: the turn ends without an end_turn
            elif d.get("type") == "user" and done is not None and not _is_tool_result(m):
                done = None
        return done

    def final_text(self, done: float) -> str:
        """The text of the message that ended the turn at `done` (all of its blocks, by message id)."""
        lines = list(self.lines)
        ended = [d for t, d in lines if abs(t - done) < 1e-6 and d.get("type") == "assistant"
                 and d.get("message", {}).get("stop_reason") == "end_turn"]
        if not ended:
            return ""
        mid = ended[-1]["message"].get("id")
        parts = []
        for _, d in lines:
            m = d.get("message", {})
            if d.get("type") == "assistant" and isinstance(m, dict) and m.get("id") == mid:
                parts += [b.get("text", "") for b in m.get("content", []) or [] if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p.strip())

    def tool_uses(self) -> list[dict]:
        out = []
        for t, d in list(self.lines):
            if d.get("type") == "assistant":
                for block in d.get("message", {}).get("content", []) or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        out.append({"t": t, "name": block.get("name"), "input": block.get("input", {})})
        return out

    def usage_usd(self) -> tuple[float, dict]:
        """Computed spend of the session from the usage on each assistant message (one per message id)."""
        by_id: dict[str, tuple[str, dict]] = {}
        for _, d in list(self.lines):
            m = d.get("message", {})
            if d.get("type") == "assistant" and isinstance(m, dict) and m.get("usage"):
                by_id[m.get("id") or str(len(by_id))] = (m.get("model", MODEL), m["usage"])
        total, tokens = 0.0, {"input_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                              "output_tokens": 0, "messages": len(by_id)}
        for model, usage in by_id.values():
            model = model if model in ledger.PRICES["anthropic_per_mtok"] else MODEL
            total += ledger.anthropic_usd(model, usage)
            for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens"):
                tokens[k] += usage.get(k, 0) or 0
        return total, tokens

    def permission_mode_seen(self) -> str | None:
        for _, d in list(self.lines):
            if d.get("permissionMode"):
                return d["permissionMode"]
        return None


def _is_tool_result(message: dict) -> bool:
    content = message.get("content")
    return isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def sweep(root: Path) -> list[int]:
    """Kills every process whose working folder is under `root` (a job the agent left running). Returns the pids."""
    out = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fpn"], capture_output=True, text=True).stdout
    pids, pid = [], None
    real = os.path.realpath(root)
    for line in out.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid and (line[1:].startswith(str(root)) or line[1:].startswith(real)):
            if pid != os.getpid():
                pids.append(pid)
    for p in pids:
        try:
            os.kill(p, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    return pids
