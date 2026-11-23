"""One coding-agent session, launched the same way in every arm: interactive `claude --model M --permission-mode P` in
a pty, in its own /tmp repo, with a fresh CLAUDE_CONFIG_DIR. The Pointe arm adds only `--plugin-dir <checkout>`.

Billing: the fresh config's `apiKeyHelper` reads the API key from the Keychain inside that one process, so the key is
never in a file, an argument or the environment, and the session can never fall back to the owner's login.
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
from datetime import datetime
from pathlib import Path

from . import ledger

ANSI = re.compile(r"\x1b\[[0-9;?<>=]*[A-Za-z~]|\x1b\][^\x07]*\x07|\x1b[()][A-Z0-9]|\x1b[=>78]")
KEY_HELPER = ("security find-generic-password -s pointe.anthropic-api-key -w 2>/dev/null || "
              "security find-generic-password -s anthropic-api-key -w")
# Nothing of the owner's reaches a child: no vendor key, no Claude Code markers, no live Pointe settings.
DROP_PREFIXES = ("CLAUDE_CODE_", "CLAUDE_VOICE_", "ANTHROPIC_", "POINTE_", "OPENAI_", "GOOGLE_", "GEMINI_", "SONIOX_",
                 "ELEVEN")
DROP = {"CLAUDECODE", "CLAUDE_PID", "CLAUDE_CONFIG_DIR"}


def clean_env(extra: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(DROP_PREFIXES) and k not in DROP}
    env["DISABLE_AUTOUPDATER"] = "1"  # one Claude Code version for the whole run
    env.update(extra or {})
    return env


def claude_version() -> str:
    return subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()


def cwd_of(pid: int) -> str | None:
    out = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True).stdout
    return next((l[1:] for l in out.splitlines() if l.startswith("n")), None)


class AgentSession:
    def __init__(self, name: str, repo: Path, home: Path, model: str, mode: str, *, plugin_dir: Path | None = None,
                 env: dict | None = None, deny_reads: list[Path] = (), deny_paths: list[Path] = ()):
        self.name, self.repo, self.home, self.model, self.mode = name, repo, home, model, mode
        self.plugin_dir, self.extra_env, self.deny_reads = plugin_dir, env or {}, list(deny_reads)
        self.deny_paths = list(deny_paths)  # the other repos of this conversation: no Read, Edit or Write there
        self.cfg = home / "config"
        self.stops_file = home / "stops"
        self.screen = ""
        self.pid: int | None = None
        self.fd: int | None = None
        self._stop = False
        self.last_busy = 0.0  # the last time the working spinner ("esc to interrupt") was drawn
        self.declined_upto = 0  # screen offset of the last permission dialog answered with Escape
        self.prompt_since: float | None = None

    def args(self) -> list[str]:
        extra = ["--plugin-dir", str(self.plugin_dir)] if self.plugin_dir else []
        return ["claude", *extra, "--model", self.model, "--permission-mode", self.mode]

    def prepare(self) -> None:
        self.cfg.mkdir(parents=True, exist_ok=False)
        settings = {
            "apiKeyHelper": KEY_HELPER,
            # `//` starts an absolute path in a permission rule; a single `/` is relative to the settings file.
            "permissions": {"deny": [f"Read(/{p}/**)" for p in self.deny_reads] + ["Bash(find /:*)", "Bash(find ~:*)"]
                            + [f"{tool}(/{path}/**)" for p in self.deny_paths for path in sorted({str(p), os.path.realpath(p)})
                               for tool in ("Read", "Edit", "Write")]},
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": f"printf 'stop\\n' >> '{self.stops_file}'"}]}]},
        }
        (self.cfg / "settings.json").write_text(json.dumps(settings, indent=1))
        (self.cfg / ".claude.json").write_text(json.dumps({
            "hasCompletedOnboarding": True, "theme": "dark",
            "projects": {os.path.realpath(self.repo): {"hasTrustDialogAccepted": True}}}))

    def start(self) -> None:
        self.prepare()
        env = clean_env({**self.extra_env, "CLAUDE_CONFIG_DIR": str(self.cfg)})
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(self.repo)
            os.execvpe("claude", self.args(), env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 200, 0, 0))
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        while not self._stop:
            try:
                r, _, _ = select.select([self.fd], [], [], 0.3)
                if r:
                    chunk = ANSI.sub("", os.read(self.fd, 65536).decode("utf-8", "replace"))
                    if "esctointerrupt" in re.sub(r"\s+", "", chunk).lower():
                        self.last_busy = time.time()
                    self.screen = (self.screen + chunk)[-300_000:]
            except (OSError, ValueError):
                return

    def flat(self, tail: int = 4000) -> str:
        return re.sub(r"\s+", "", self.screen[-tail * 3:]).lower()[-tail:]

    def wait_ready(self, timeout: float = 90) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if "accepteditson" in self.flat() or "forshortcuts" in self.flat():
                time.sleep(1.5)
                return
            time.sleep(0.5)
        raise TimeoutError(f"{self.name}: Claude Code did not show its input box:\n{self.flat()[-600:]}")

    def mode_shown(self) -> str:
        """The permission mode the session's status line shows (preflight 3)."""
        flat = self.flat(20000)
        return "acceptEdits" if "accepteditson" in flat else "unknown"

    def type(self, text: str) -> None:
        os.write(self.fd, text.encode())
        time.sleep(0.6)
        os.write(self.fd, b"\r")

    def busy(self) -> bool:
        """The spinner redraws while the agent works; two quiet seconds without it means the turn has ended."""
        return time.time() - self.last_busy < 2.5

    def prompt_pending(self) -> bool:
        """A permission dialog is open in the terminal (it stops the agent without a Stop hook)."""
        flat = re.sub(r"\s+", "", self.screen[self.declined_upto:][-6000:]).lower()
        i = flat.rfind("doyouwant")
        return i >= 0 and "esctocancel" in flat[i:] and not self.busy()

    def prompt_stays_in_repo(self) -> bool:
        """Every path the open dialog names is inside this session's own repo (or is /dev/...)."""
        flat = re.sub(r"\s+", "", self.screen[self.declined_upto:][-6000:])
        i = flat.lower().rfind("doyouwant")
        segment = flat[max(0, i - 2500):]
        own = {p.lower() for p in (str(self.repo), os.path.realpath(self.repo))}
        own |= {"/private" + p for p in own if p.startswith("/tmp/")} | {p[8:] for p in own if p.startswith("/private/tmp/")}
        for m in re.finditer(r"(/(?:private/)?tmp/|/users/|/home/|/volumes/|~/)", segment, re.I):
            if not any(segment[m.start():].lower().startswith(o) for o in own):
                return False
        return True

    def approve(self) -> None:
        """Enter on the highlighted first option, "Yes", once."""
        os.write(self.fd, b"\r")
        self.declined_upto = len(self.screen)
        self.prompt_since = None

    def decline(self) -> None:
        """Escape, as a person at the keyboard who does not approve."""
        os.write(self.fd, b"\x1b")
        self.declined_upto = len(self.screen)
        self.prompt_since = None

    def stops(self) -> int:
        return len(self.stops_file.read_text().splitlines()) if self.stops_file.exists() else 0

    def transcripts(self) -> list[Path]:
        return sorted((self.cfg / "projects").glob("*/*.jsonl"))

    def activity(self) -> float:
        """The last time any transcript of this session changed."""
        return max((p.stat().st_mtime for p in self.transcripts()), default=0.0)

    def messages(self) -> list[dict]:
        out = []
        for path in self.transcripts():
            for line in path.read_text(errors="ignore").splitlines():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
        return out

    def usage(self) -> dict:
        """Tokens and computed spend from the transcript, one count per API message id."""
        seen, usd, models, tokens = set(), 0.0, set(), {}
        for m in self.messages():
            msg = m.get("message") or {}
            if m.get("type") != "assistant" or not msg.get("usage") or msg.get("id") in seen:
                continue
            seen.add(msg.get("id"))
            model = msg.get("model", self.model)
            models.add(model)
            u = msg["usage"]
            for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                tokens[k] = tokens.get(k, 0) + (u.get(k) or 0)
            usd += ledger.anthropic_usd(model if model in ledger.PRICES["anthropic"] else self.model, u)
        return {"usd": usd, "models": sorted(models), "tokens": tokens, "api_messages": len(seen)}

    def tool_inputs(self) -> list[dict]:
        out = []
        for m in self.messages():
            try:
                t = datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00")).timestamp()
            except (KeyError, ValueError, AttributeError):
                t = None
            for block in (m.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    out.append({"tool": block.get("name"), "input": block.get("input"), "t": t})
        return out

    def alive(self) -> bool:
        if self.pid is None:
            return False
        try:
            return os.waitpid(self.pid, os.WNOHANG) == (0, 0)
        except ChildProcessError:
            return False

    def stop(self) -> None:
        self._stop = True
        if self.pid is None:
            return
        try:
            os.killpg(self.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        for _ in range(50):
            try:
                if os.waitpid(self.pid, os.WNOHANG) != (0, 0):
                    break
            except ChildProcessError:
                break
            time.sleep(0.1)


def leftovers(root: Path) -> list[str]:
    """Processes still running whose command line or working folder is under this run's /tmp root."""
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    me = os.getpid()
    found = [l.strip() for l in out.splitlines() if str(root) in l and int(l.split()[0]) != me]
    for pid in subprocess.run(["pgrep", "-x", "claude"], capture_output=True, text=True).stdout.split():
        cwd = cwd_of(int(pid)) or ""
        if cwd.startswith((str(root), os.path.realpath(root))):
            found.append(f"{pid} claude in {cwd}")
    return found
