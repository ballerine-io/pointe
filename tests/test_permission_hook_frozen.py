"""The PermissionRequest hook gives the prompt back to the terminal at once when the daemon is frozen. From a QA run: with
the daemon stopped by SIGSTOP the hook was still blocked after 30 s, and it may wait up to 12 hours."""

import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which("lsof"), reason="the hook needs lsof (or ss, /proc) to tell its daemon")
def test_a_daemon_that_accepts_but_never_answers_leaves_the_prompt_to_the_terminal(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    # A listener that takes connections and never reads or answers them: what a stopped process looks like from outside.
    frozen = subprocess.Popen([sys.executable, "-c", f"import socket,time\ns=socket.socket()\ns.bind(('127.0.0.1',{port}))\n"
                               "s.listen(8)\nprint('up',flush=True)\nwhile True: time.sleep(60)"],
                              stdout=subprocess.PIPE, text=True)
    try:
        assert frozen.stdout.readline().strip() == "up"
        (tmp_path / "token").write_text("t")
        (tmp_path / "daemon.pid").write_text(str(frozen.pid))
        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(tmp_path), "CLAUDE_VOICE_STATE": str(tmp_path),
               "CLAUDE_VOICE_DAEMON_PORT": str(port)}
        began = time.time()
        got = subprocess.run([str(ROOT / "bin" / "voice-permission-hook")], env=env, capture_output=True, text=True,
                             input=json.dumps({"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "ls"}}),
                             timeout=30)
        assert got.returncode == 0 and got.stdout == ""
        assert time.time() - began < 10
    finally:
        frozen.kill()
        frozen.wait()
