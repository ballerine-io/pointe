"""The coding agent every arm drives: interactive Claude Code in a pty, one launch line for all arms.

    claude --model claude-haiku-5-5 --permission-mode default [--plugin-dir <pointe>]

Each run gets a fresh CLAUDE_CONFIG_DIR in its own /tmp folder, the API key in the child's environment only, HOME
untouched, and a settings file (the same for every arm) whose hooks log approval requests, tool results, prompts and turn
ends to `hooks.jsonl`. `FakeAgent` plays the same part with no model, for the offline tests.
"""

import fcntl
import json
import os
import pty
import re
import select
import shlex
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
from datetime import datetime
from pathlib import Path

MODEL = "claude-haiku-5-5"
ANSI = re.compile(r"\x1b\[[0-9;?<>=]*[A-Za-z~]|\x1b\][^\x07]*\x07|\x1b[()][A-Z0-9]|\x1b[>=<]")
KEYS = {"approve": b"\r", "deny": b"\x1b", "escape": b"\x1b"}
DROP_ENV = ("CLAUDECODE", "CLAUDE_PID", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GOOGLE_API_KEY", "GEMINI_API_KEY",
            "OPENAI_API_KEY", "SONIOX_API_KEY", "ELEVENLABS_API_KEY", "CLAUDE_VOICE_STATE", "CLAUDE_VOICE_DAEMON_PORT")
HOOK_EVENTS = ("PermissionRequest", "PostToolUse", "UserPromptSubmit", "Stop")
REJECTED = "doesn't want to proceed"  # Claude Code's own refusal; a hook's deny reads "The user denied this."


def claude_version() -> str:
    out = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
    return out.split()[0] if out else "unknown"


def write_config(folder: Path, allow: list[str], deny_reads: list[str]) -> Path:
    """The fresh config folder: onboarding done, the repo trusted, the logging hooks, the class's allow rules."""
    folder, cfg, repo = Path(folder), Path(folder) / "cfg", Path(folder) / "repo"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / ".claude.json").write_text(json.dumps({
        "hasCompletedOnboarding": True, "theme": "dark", "numStartups": 1, "autoUpdates": False,
        "projects": {os.path.realpath(repo): {"hasTrustDialogAccepted": True, "hasCompletedProjectOnboarding": True}}}))
    hook = folder / "hook.py"
    hook.write_text("import json, sys, time\n"
                    "event = json.load(sys.stdin)\nevent['_t'] = time.time()\n"
                    f"with open({str(folder / 'hooks.jsonl')!r}, 'a') as f:\n    f.write(json.dumps(event) + '\\n')\n")
    python = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
    command = f"{shlex.quote(python)} -I {shlex.quote(str(hook))}"
    hooks = {name: [{"hooks": [{"type": "command", "command": command, "timeout": 10}]}] for name in HOOK_EVENTS}
    (cfg / "settings.json").write_text(json.dumps({
        "hooks": hooks,
        "permissions": {"allow": allow, "deny": [f"Read({p}/**)" for p in deny_reads]},
        "env": {"DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}}))
    return cfg


def read_hooks(folder: Path) -> list[dict]:
    path = Path(folder) / "hooks.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def _ts(entry: dict) -> float:
    try:
        return datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00")).timestamp()
    except (KeyError, ValueError):
        return 0.0


def transcript(cfg: Path) -> list[dict]:
    entries = []
    for path in sorted(Path(cfg).glob("projects/*/*.jsonl")):
        for line in path.read_text(errors="replace").splitlines():
            try:
                entries.append(json.loads(line))
            except ValueError:
                pass
    return entries


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


def parse(entries: list[dict]) -> dict:
    """Normalized facts from a Claude Code transcript: prompts the session received, tool calls and how each was
    decided, interruptions, the last assistant text, and token usage per model (deduplicated by message id)."""
    prompts, tools, results, interrupts, usage, last_text = [], {}, {}, [], {}, ""
    seen = set()
    queued = set()
    for e in entries:
        msg = e.get("message") or {}
        if e.get("type") == "queue-operation" and e.get("operation") == "enqueue" and e.get("content"):
            # a message sent while the agent works: it waits in Claude Code's queue, and only reaches the transcript as
            # a user turn later (or is absorbed mid-turn); the enqueue is when the harness delivered it
            prompts.append({"t": _ts(e), "text": e["content"], "via": "queue"})
            queued.add(e["content"].strip())
            continue
        if e.get("type") == "user" and isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, list) and any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "tool_result":
                        body = c.get("content")
                        body = body if isinstance(body, str) else json.dumps(body)
                        denied = REJECTED in body or (bool(c.get("is_error")) and "denied" in body.lower())
                        results[c.get("tool_use_id")] = {"t": _ts(e), "denied": denied, "error": bool(c.get("is_error"))}
                continue
            text = _text_of(content)
            if text.startswith("[Request interrupted"):
                interrupts.append(_ts(e))
            elif text and not e.get("isMeta"):
                prompts.append({"t": _ts(e), "text": text, "via": "typed"})
            elif text and (e.get("origin") or {}).get("kind") == "peer":  # a message through the inbox socket (Pointe's send)
                if not any(q in text for q in queued):  # the same message, already counted when it was queued
                    prompts.append({"t": _ts(e), "text": text, "via": "inbox"})
        elif e.get("type") == "assistant" and isinstance(msg, dict):
            for c in msg.get("content") or []:
                if c.get("type") == "tool_use":
                    tools[c.get("id")] = {"t": _ts(e), "name": c.get("name"), "input": c.get("input") or {}}
                elif c.get("type") == "text" and c.get("text"):
                    last_text = c["text"]
            mid = msg.get("id")
            if msg.get("usage") and mid not in seen:
                seen.add(mid)
                u, m = msg["usage"], msg.get("model", "?")
                acc = usage.setdefault(m, {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0})
                acc["input"] += u.get("input_tokens", 0)
                acc["output"] += u.get("output_tokens", 0)
                acc["cache_write"] += u.get("cache_creation_input_tokens", 0)
                acc["cache_read"] += u.get("cache_read_input_tokens", 0)
    calls = [{"id": i, **t, **({"decided_at": results[i]["t"], "denied": results[i]["denied"]} if i in results else {})}
             for i, t in tools.items()]
    return {"prompts": prompts, "calls": calls, "interrupts": interrupts, "usage": usage, "last_text": last_text}


def usage_usd(usage: dict, prices: dict) -> float:
    total = 0.0
    for model, u in usage.items():
        p = prices["anthropic"].get(model) or prices["anthropic"]["claude-haiku-5-5"]
        total += (u["input"] * p["input"] + u["output"] * p["output"] + u["cache_write"] * p["cache_write"]
                  + u["cache_read"] * p["cache_read"]) / 1e6
    return total


class AgentSession:
    """Interactive Claude Code in a pty. `extra_args` is empty for every arm but Pointe's `--plugin-dir`."""

    def __init__(self, folder: Path, api_key: str, extra_args: tuple = (), extra_env: dict | None = None,
                 mode: str = "default"):
        self.folder, self.repo, self.cfg = Path(folder), Path(folder) / "repo", Path(folder) / "cfg"
        self.args = ["claude", *extra_args, "--model", MODEL, "--permission-mode", mode]
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_") and k not in DROP_ENV}
        env.update(extra_env or {})
        env.update(CLAUDE_CONFIG_DIR=str(self.cfg), DISABLE_AUTOUPDATER="1")
        self._env, self._key = env, api_key
        self.screen, self.typed = "", []
        self.pid = self.fd = None
        self._stop = False

    def start(self, timeout: float = 60) -> None:
        env = {**self._env, "ANTHROPIC_API_KEY": self._key}
        self.pid, self.fd = pty.fork()
        if self.pid == 0:  # the child: a new session, so the whole group can be killed at the end
            os.chdir(self.repo)
            os.execvpe(self.args[0], self.args, env)
        del env
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 200, 0, 0))
        threading.Thread(target=self._pump, daemon=True).start()
        if not self.wait_screen("shortcuts", timeout):
            raise TimeoutError("Claude Code did not reach its input box")
        time.sleep(1.0)

    def flat(self) -> str:
        return re.sub(r"\s+", "", self.screen).lower()

    def wait_screen(self, needle: str, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if needle in self.flat()[-6000:]:
                return True
            time.sleep(0.2)
        return False

    def _pump(self) -> None:
        answered = False
        while not self._stop:
            try:
                ready, _, _ = select.select([self.fd], [], [], 0.3)
            except (OSError, ValueError):
                return
            if ready:
                try:
                    self.screen += ANSI.sub("", os.read(self.fd, 65536).decode("utf-8", "replace"))
                except OSError:
                    return
                self.screen = self.screen[-120_000:]
            if not answered and "doyouwanttousethisapikey" in self.flat()[-4000:]:
                answered = True  # "Yes" is the first option; the cursor starts on "No (recommended)"
                time.sleep(0.4)
                os.write(self.fd, b"\x1b[A")
                time.sleep(0.3)
                os.write(self.fd, b"\r")

    def type(self, text: str) -> None:
        self.typed.append({"t": time.time(), "text": text})
        os.write(self.fd, text.encode())
        time.sleep(0.6)
        os.write(self.fd, b"\r")

    def key(self, name: str) -> None:
        os.write(self.fd, KEYS[name])

    def hooks(self) -> list[dict]:
        return read_hooks(self.folder)

    def facts(self) -> dict:
        return parse(transcript(self.cfg))

    def cost(self, timeout: float = 8) -> float | None:
        """Claude Code's own total for the session (`/cost`), which counts its side calls too."""
        for _ in range(2):
            os.write(self.fd, b"\x1b")
            time.sleep(0.5)
        mark = len(self.screen)
        self.type("/cost")
        deadline = time.time() + timeout
        while time.time() < deadline:
            m = re.search(r"(?:Total|Estimated) cost:\s*\$([0-9.]+)", self.screen[mark:])  # 2.1.330: "Estimated cost:"
            if m:
                return float(m.group(1))
            time.sleep(0.3)
        return None

    def stop(self) -> None:
        self._stop = True
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(self.pid, sig)
            except (ProcessLookupError, PermissionError, TypeError):
                pass
            time.sleep(0.3)
        try:
            os.close(self.fd)
        except (OSError, TypeError):
            pass
        try:
            for _ in range(30):
                if os.waitpid(self.pid, os.WNOHANG) != (0, 0):
                    break
                time.sleep(0.1)
        except (ChildProcessError, TypeError):
            pass


class FakeAgent:
    """The offline stand-in: no model, no keys. A typed `Run exactly this shell command ...: `cmd`` asks for approval
    (logged through the same hooks file); approve runs it in the repo, deny or Escape refuses it; a working job is
    stopped by Escape. It writes a transcript in Claude Code's shape, so the parser and the scorer are the ones used for
    real runs."""

    def __init__(self, folder: Path, *_, **__):
        self.folder, self.repo, self.cfg = Path(folder), Path(folder) / "repo", Path(folder) / "cfg"
        self.typed, self._pending, self._job, self._n = [], None, None, 0
        self._log = self.cfg / "projects" / "fake" / "session.jsonl"

    def start(self, timeout: float = 0) -> None:
        self._log.parent.mkdir(parents=True, exist_ok=True)
        self._log.touch()

    def _write(self, entry: dict) -> None:
        entry["timestamp"] = datetime.now().astimezone().isoformat()
        with open(self._log, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def _hook(self, event: dict) -> None:
        event["_t"] = time.time()
        with open(self.folder / "hooks.jsonl", "a") as f:
            f.write(json.dumps(event) + "\n")

    def type(self, text: str) -> None:
        self.typed.append({"t": time.time(), "text": text})
        self._write({"type": "user", "message": {"role": "user", "content": text}})
        self._hook({"hook_event_name": "UserPromptSubmit", "prompt": text})
        m = re.search(r"`([^`]+)`", text)
        self._n += 1
        tid = f"tool{self._n}"
        if m and "Run exactly" in text:
            command = m.group(1)
            self._write({"type": "assistant", "message": {"id": tid, "content": [
                {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": command}}]}})
            if command == "./long_job.sh":
                self._job = (tid, subprocess.Popen(["sh", "./long_job.sh"], cwd=self.repo, start_new_session=True,
                                                   env={**os.environ, "MARLSTONE_STEP": os.environ.get("MARLSTONE_STEP", "2")}))
                return
            if command.startswith("cat "):
                self._finish(tid, "fine")
                return
            self._pending = (tid, command)
            self._hook({"hook_event_name": "PermissionRequest", "tool_name": "Bash", "tool_input": {"command": command},
                        "permission_mode": "default"})
        elif "unittest" in text or "tests" in text.lower():
            subprocess.run(["python3", "-m", "unittest", "-q"], cwd=self.repo, capture_output=True)
            self._finish(tid, "OK")
        else:
            self._finish(None, "noted")

    def _finish(self, tid, out) -> None:
        if tid:
            self._write({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": out}]}})
        self._write({"type": "assistant", "message": {"id": f"m{time.time()}", "content": [{"type": "text", "text": "Done."}]}})
        self._hook({"hook_event_name": "Stop"})

    def key(self, name: str) -> None:
        if self._pending:
            tid, command = self._pending
            self._pending = None
            if name == "approve":
                subprocess.run(command, shell=True, cwd=self.repo, capture_output=True)
                self._finish(tid, "ok")
            else:
                self._write({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid,
                             "content": f"The user {REJECTED} with this tool use.", "is_error": True}]}})
            return
        if self._job and name in ("escape", "deny"):
            tid, proc = self._job
            os.killpg(proc.pid, signal.SIGKILL)
            self._job = None
            self._write({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid,
                         "content": "Interrupted", "is_error": True}]}})
            self._write({"type": "user", "message": {"content": "[Request interrupted by user]"}})

    def hooks(self) -> list[dict]:
        return read_hooks(self.folder)

    def facts(self) -> dict:
        return parse(transcript(self.cfg))

    def cost(self, timeout: float = 0) -> float | None:
        return 0.0

    def stop(self) -> None:
        if self._job:
            try:
                os.killpg(self._job[1].pid, signal.SIGKILL)
            except OSError:  # already gone (macOS answers EPERM for a group that has exited)
                pass
