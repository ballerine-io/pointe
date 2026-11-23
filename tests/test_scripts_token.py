"""The scripts that talk to the daemon: what they send rides on no command line, and the token or the page key goes only
to the daemon itself, never to another program that took its port while it was down (bin/voice-ours)."""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
TOKEN = "synthetic-daemon-token-0123456789"


class FakeDaemon:
    """A listener on 127.0.0.1 in this test's own process, which records each request and answers `answer`."""

    def __init__(self, state: Path, answer: dict):
        self.requests, self.answer = [], answer
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _serve(self):
                size = int(self.headers.get("content-length") or 0)
                outer.requests.append({"path": self.path, "auth": self.headers.get("authorization"),
                                       "body": self.rfile.read(size).decode() if size else ""})
                body = json.dumps(outer.answer).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = _serve

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.state = state
        state.mkdir(exist_ok=True)
        (state / "token").write_text(TOKEN)
        (state / "page_key").write_text("synthetic-page-key")
        self.ours()

    def ours(self):
        (self.state / "daemon.pid").write_text(str(os.getpid()))

    def env(self, **extra) -> dict:
        return {"PATH": os.environ["PATH"], "HOME": str(self.state.parent), "CLAUDE_VOICE_STATE": str(self.state),
                "CLAUDE_VOICE_DAEMON_PORT": str(self.port), "CLAUDE_VOICE_NO_BROWSER": "1", **extra}

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def daemon(tmp_path):
    d = FakeDaemon(tmp_path / "state", {})
    yield d
    d.close()


def _context(n_messages: int) -> dict:
    return {"tokens": None, "breakdown": [], "connected": True, "notes": {},
            "messages": [{"role": "user", "content": f"message {i} " + "x" * 2000} for i in range(n_messages)]}


def test_voice_context_reads_the_context_on_stdin_not_its_command_line(daemon):
    """2 MB of context: past macOS's limit for a command line, and on one any local user could read with ps."""
    daemon.answer = _context(1000)
    got = subprocess.run([str(BIN / "voice-context")], env=daemon.env(), capture_output=True, text=True, timeout=30)
    assert got.returncode == 0, got.stderr[-500:]
    assert "messages: 1000 (showing 20)" in got.stdout
    script = (BIN / "voice-context").read_text()
    assert '"$BODY"' not in script.split("python3", 1)[1].split("\n", 1)[0], "the body is never an argument"


def _stub_open(tmp: Path) -> tuple[Path, Path]:
    stubs, opened = tmp / "stubs", tmp / "opened"
    stubs.mkdir(exist_ok=True)
    for name in ("open", "xdg-open"):
        (stubs / name).write_text(f'#!/bin/sh\necho "$@" >>{opened}\n')
        (stubs / name).chmod(0o755)
    return stubs, opened


SCRIPTS = {  # each script, as a session or a person runs it: (argv, extra environment, stdin)
    "register-session": (["register-session", "--quiet"], {"CLAUDE_PID": "4242"},
                         json.dumps({"session_id": "sess-1", "transcript_path": "/tmp/none.jsonl"})),
    "voice-talk": (["voice-talk", "on"], {}, ""),
    "voice-context": (["voice-context", "--json"], {}, ""),
    "claude-voice-attach status": (["claude-voice-attach", "status"], {}, ""),
    "claude-voice-attach off": (["claude-voice-attach", "off"], {"CLAUDE_CODE_SESSION_ID": "sess-1"}, ""),
    "voice-open": (["voice-open"], {}, ""),
}


def _run(daemon, name):
    argv, extra, stdin = SCRIPTS[name]
    stubs, opened = _stub_open(daemon.state.parent)
    env = daemon.env(**extra)
    env["PATH"] = f"{stubs}:{env['PATH']}"
    got = subprocess.run([str(BIN / argv[0]), *argv[1:]], env=env, input=stdin, capture_output=True, text=True,
                         timeout=30, cwd=daemon.state.parent)
    return got, (opened.read_text() if opened.exists() else "")


@pytest.mark.parametrize("pid", ["1", None], ids=["another-process", "no-pid-file"])
@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_a_secret_goes_only_to_the_daemon_that_owns_the_port(daemon, name, pid):
    """The daemon is down and another program listens on its port: it gets no token, no page key, no session details."""
    daemon.answer = _context(1) | {"open": True, "name": "api"}
    if pid:
        (daemon.state / "daemon.pid").write_text(pid)
    else:
        (daemon.state / "daemon.pid").unlink()
    got, opened = _run(daemon, name)
    assert not [r for r in daemon.requests if r["auth"] or r["body"]], f"{name} sent to a stranger: {daemon.requests}"
    assert "synthetic-page-key" not in opened, f"{name} opened the page with its key on another program's port"


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_with_the_daemon_listening_each_script_reaches_it_as_before(daemon, name):
    daemon.answer = _context(1) | {"open": True, "name": "api"}
    got, opened = _run(daemon, name)
    if name == "voice-open":
        assert "synthetic-page-key" in opened and str(daemon.port) in opened, got.stderr
    else:
        assert [r for r in daemon.requests if r["auth"] == f"Bearer {TOKEN}"], f"{name}: {got.stderr}"


def test_the_permission_hook_uses_the_same_check():
    hook = (BIN / "voice-permission-hook").read_text()
    assert '"$BIN/voice-ours" </dev/null || exit 0' in hook and "pgrep" not in hook
