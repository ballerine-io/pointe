"""Every test runs against a throwaway state dir: daemon.py reads CLAUDE_VOICE_STATE once, at import,
and a test that imports it first must never point it at the live ~/.claude-voice."""

import os
import tempfile
from pathlib import Path

_STATE = Path(tempfile.mkdtemp(prefix="cv-test-state-"))
(_STATE / "token").write_text("test-token")
(_STATE / "first-hello").write_text("")  # a Mac set up already: tests of the first call remove it (test_first_hello.py)
os.environ["CLAUDE_VOICE_STATE"] = str(_STATE)
os.environ["CLAUDE_VOICE_SKIP_KEY_CHECK"] = "1"  # no test reaches a vendor with its synthetic keys (doctor.check_keys)

import sys  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import harnesses.claude_code  # noqa: E402

harnesses.claude_code.ROSTER = False  # a probe never runs the machine's real `claude agents --json`; tests that read it fake it

# Nor does a send read this machine's Claude Code settings: an empty account and no managed settings, unless a test says.
harnesses.claude_code.DEFAULT_HOME = _STATE / "claude-home"
harnesses.claude_code.MANAGED_SETTINGS = _STATE / "managed-settings.json"

import mac  # noqa: E402

mac.SYSTEM = False  # nor this Mac's idle time, power or sleep


def pytest_runtest_setup(item):
    """A conversational benchmark's tests run with its own harness importable (tests/conv_suite.py)."""
    key = getattr(getattr(item, "module", None), "CONV_SUITE", None)
    if key:
        import conv_suite

        conv_suite.enter(key)
