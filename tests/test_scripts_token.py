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
