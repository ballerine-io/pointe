"""Every test runs against a throwaway state dir: daemon.py reads CLAUDE_VOICE_STATE once, at import,
and a test that imports it first must never point it at the live ~/.claude-voice."""

import os
import tempfile
from pathlib import Path

_STATE = Path(tempfile.mkdtemp(prefix="cv-test-state-"))
(_STATE / "token").write_text("test-token")
(_STATE / "first-hello").write_text("")  # a Mac set up already: tests of the first call remove it (test_first_hello.py)
os.environ["CLAUDE_VOICE_STATE"] = str(_STATE)
os.environ["POINTE_LINK_DIR"] = str(_STATE / "link")  # a daemon a test starts never rewrites ~/.local/bin/pointe
os.environ["POINTE_SYSTEM_APPLICATIONS"] = str(_STATE / "Applications")  # an uninstall a test runs never reaches /Applications
os.environ["CLAUDE_VOICE_SKIP_KEY_CHECK"] = "1"  # no test reaches a vendor with its synthetic keys (doctor.check_keys)

import sys  # noqa: E402

import pytest  # noqa: E402

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
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


def pytest_runtest_teardown(item):
    """vendors keeps a key read from the Keychain in memory, not in os.environ, so monkeypatch's restore of the
    environment does not reach it: one test's fake Keychain key must not answer the next test's lookup."""
    vendors = sys.modules.get("vendors")
    if vendors is not None:
        vendors._found.clear()


@pytest.fixture
def on_a_mac(monkeypatch):
    """A test of the macOS Keychain path: keys.py, vendors.py and uninstall.py take the login keyring's path on Linux,
    where CI runs (tests/test_linux_keys.py tests that one)."""
    monkeypatch.setattr(sys, "platform", "darwin")


def pytest_addoption(parser):
    parser.addoption("--runslow", action="store_true", help="run the tests marked slow too (CI and the release gate do)")


@pytest.hookimpl(tryfirst=True)  # before -m deselects, so `-m chrome` sees the marks added here
def pytest_collection_modifyitems(config, items):
    """A test marked slow (a real daemon, a long wait) runs in CI and at a release, not in the inner loop
    (tools/test-changed): without --runslow it is skipped and says why. Every test that skips without headless Chrome
    is marked chrome and slow (each starts a browser): CI runs those in a job of their own (test.yml, `page`)."""
    for item in items:
        if any("headless Chrome" in str(m.kwargs.get("reason", "")) for m in item.iter_markers("skipif")):
            item.add_marker(pytest.mark.chrome)
            item.add_marker(pytest.mark.slow)
    if config.getoption("--runslow"):
        return
    skip = pytest.mark.skip(reason="slow: runs in CI and at a release (--runslow)")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)
