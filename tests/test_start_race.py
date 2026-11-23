"""Two daemon starts at the same moment leave one daemon, the one the pidfile names, so status and stop see it. QA round
2: two /pointe:voice at once left an orphan holding the port, status said stopped, stop left it, and every later start
failed on the port (3 of 3)."""

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not shutil.which("lsof") or sys.platform == "win32", reason="needs lsof")

SERVER = """
import http.server, sys, time
time.sleep(1.0)  # a real daemon takes seconds to bind: the window two starts used to race in
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a):
        pass
http.server.HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def plugin(tmp_path):
    """bin/voice-daemon and bin/voice-listeners as shipped; a uv whose `run ... daemon.py --port N` is a tiny server."""
    bin_ = tmp_path / "plugin" / "bin"
    bin_.mkdir(parents=True)
    for name in ("voice-daemon", "voice-listeners", "pointe-installs"):
        shutil.copy(ROOT / "bin" / name, bin_ / name)
    for name in ("uv-sync", "link-pointe"):
        (bin_ / name).write_text("#!/bin/bash\nexit 0\n")
    (tmp_path / "server.py").write_text(SERVER)
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "uv").write_text(f'#!/bin/bash\nfor a in "$@"; do case "$a" in *daemon.py) shift $#; '
                             f'exec {sys.executable} {tmp_path / "server.py"} "$PORT_FOR_TEST" ;; esac; done\nexit 0\n')
    for f in (*bin_.iterdir(), fake / "uv"):
        f.chmod(0o755)
    port, state = _free_port(), tmp_path / "state"
    env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}", "CLAUDE_VOICE_STATE": str(state),
           "CLAUDE_VOICE_DAEMON_PORT": str(port), "PORT_FOR_TEST": str(port)}
    yield bin_ / "voice-daemon", env, port, state
    pids = subprocess.run(["lsof", "-nP", f"-tiTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout.split()
    for pid in pids:
        os.kill(int(pid), signal.SIGKILL)


def _listeners(port: int) -> list[str]:
    return subprocess.run(["lsof", "-nP", f"-tiTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout.split()


def test_two_starts_at_once_leave_one_daemon_that_status_and_stop_see(plugin):
    script, env, port, state = plugin
    starts = [subprocess.Popen([str(script), "ensure"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
              for _ in range(3)]
    results = [p.communicate(timeout=120) for p in starts]
    assert [p.returncode for p in starts] == [0, 0, 0], results
    assert all(out.strip() == f"http://127.0.0.1:{port}" for out, _ in results)
    assert _listeners(port) == [(state / "daemon.pid").read_text().strip()]
    assert subprocess.run([str(script), "status"], env=env, capture_output=True, text=True).stdout.startswith("running")
    subprocess.run([str(script), "stop"], env=env, capture_output=True, text=True, timeout=60)
    assert not _listeners(port) and not (state / "start.lock").exists()


def test_a_lock_left_by_a_start_that_died_is_taken_over(plugin):
    script, env, port, state = plugin
    (state / "start.lock").mkdir(parents=True)
    dead = subprocess.Popen(["true"])
    dead.wait()
    (state / "start.lock" / "pid").write_text(str(dead.pid))
    got = subprocess.run([str(script), "ensure"], env=env, capture_output=True, text=True, timeout=60)
    assert got.returncode == 0, got.stderr
    subprocess.run([str(script), "stop"], env=env, capture_output=True, text=True, timeout=60)
