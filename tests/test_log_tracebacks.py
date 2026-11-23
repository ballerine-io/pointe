"""loguru's default sink prints every frame's local variables under a traceback (`diagnose`): an `api_key`, a WebSocket
URL with `?key=`. daemon.log and node.log hold what that sink writes, and /pointe:voice shows their last lines in a
transcript on a failure. The daemon and the node replace it, and every sink Pointe adds has diagnose off."""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SECRET = "synthetic-local-variable-secret-0123"

PROBE = """
import sys
sys.path.insert(0, sys.argv[1])
import {module}
from loguru import logger

def call_vendor():
    api_key = "{secret}"
    raise ValueError("refused" + api_key[:0])  # the line names the variable, as a real call would

try:
    call_vendor()
except ValueError:
    logger.exception("the vendor refused")
"""


@pytest.mark.parametrize("module", ["daemon", "node"])
def test_a_logged_exception_shows_no_local_variable(module, tmp_path):
    (tmp_path / "token").write_text("synthetic-token")
    probe = tmp_path / "probe.py"  # a file: diagnose annotates only source it can read
    probe.write_text(PROBE.format(module=module, secret=SECRET))
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "CLAUDE_VOICE_STATE": str(tmp_path),
           "ORT_DISABLE_TELEMETRY": "1"}
    got = subprocess.run([sys.executable, "-I", str(probe), str(ROOT)], env=env,
                         capture_output=True, text=True, timeout=120, cwd=tmp_path)
    assert "the vendor refused" in got.stderr and "ValueError: refused" in got.stderr, got.stderr[-2000:]
    assert SECRET not in got.stderr, "a local variable's value reached the log"


def test_every_sink_pointe_adds_has_diagnose_off():
    bad = []
    for path in sorted([*ROOT.glob("*.py"), *ROOT.glob("harnesses/*.py")]):
        for call in ast.walk(ast.parse(path.read_text())):
            if isinstance(call, ast.Call) and ast.unparse(call.func) == "logger.add":
                kw = {k.arg: ast.unparse(k.value) for k in call.keywords}
                if kw.get("diagnose") != "False":
                    bad.append(f"{path.name}:{call.lineno}")
    assert not bad, "logger.add(..., diagnose=False):\n" + "\n".join(bad)


def test_a_key_the_daemon_holds_is_masked_in_every_log_line(tmp_path, monkeypatch):
    """A vendor's error or a library's debug line that carries a key (or the page key in an address) must not reach
    daemon.log or the journal: /pointe:voice shows daemon.log's last lines in a transcript on a failure."""
    from loguru import logger

    import daemon
    import vendors

    key = "synthetic-vendor-key-9f8e7d6c5b4a3210"
    monkeypatch.setitem(vendors._found, "gemini", ("pointe.gemini-api-key", key))
    monkeypatch.setattr(daemon, "JOURNAL", tmp_path / "journal.jsonl")
    monkeypatch.setattr(daemon, "_journal_sink", None)
    daemon._start_journal()
    lines = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="DEBUG", diagnose=False)
    try:
        as_daemon = logger.patch(lambda r: r.update(name="daemon"))  # the journal keeps the daemon's own lines
        as_daemon.info(f"gemini refused wss://example.invalid/ws?key={key}")
        logger.debug(f"a library's request: key={key} page={daemon.PAGE_KEY}")
    finally:
        logger.remove(sink)
    journal = (tmp_path / "journal.jsonl").read_text()
    assert "gemini refused" in journal and len(lines) == 2
    for text in [journal, *lines]:
        assert key not in text and daemon.PAGE_KEY not in text, text
    assert "?key=[key]" in lines[0]
