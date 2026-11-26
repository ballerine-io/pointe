"""`pointe <command> --help` says what the command does and runs nothing. From QA round 2: `pointe local --help` started
the 19 GB fully local install and switched the setup, `pointe stop --help` ended the call, `open --help` opened the page."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
import local  # noqa: E402

COMMANDS = ["start", "attach", "open", "talk", "doctor", "status", "log", "context", "stop", "restart", "uninstall",
            "hub", "people", "share", "machine", "machines", "key", "setup", "join", "leave", "local", "apps"]


@pytest.fixture
def pointe(tmp_path):
    """bin/pointe beside scripts that only write down that they ran, and a uv that does the same."""
    bin_ = tmp_path / "plugin" / "bin"
    bin_.mkdir(parents=True)
    shutil.copy(ROOT / "bin" / "pointe", bin_ / "pointe")
    calls = tmp_path / "calls"
    recorder = f'#!/bin/bash\necho "$(basename "$0") $*" >> {calls}\nexit 0\n'
    fake = tmp_path / "fake"
    fake.mkdir()
    for name in [p.name for p in (ROOT / "bin").iterdir() if p.name != "pointe"]:
        (bin_ / name).write_text(recorder)
    (fake / "uv").write_text(recorder)
    (fake / "python3").write_text(recorder)
    for f in (*bin_.iterdir(), *fake.iterdir()):
        f.chmod(0o755)
    env = {"PATH": f"{fake}:/usr/bin:/bin", "HOME": str(tmp_path)}
    return bin_ / "pointe", calls, env


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_on_a_command_says_what_it_does_and_runs_nothing(pointe, command, flag):
    script, calls, env = pointe
    got = subprocess.run([str(script), command, flag], env=env, capture_output=True, text=True)
    assert got.returncode == 0, got.stderr
    assert got.stdout.startswith(f"pointe {command}"), got.stdout
    assert not calls.exists(), calls.read_text()


def test_help_after_a_subcommand_runs_nothing_either(pointe):
    script, calls, env = pointe
    got = subprocess.run([str(script), "local", "voice", "--help"], env=env, capture_output=True, text=True)
    assert got.returncode == 0 and "19 GB" in got.stdout and not calls.exists()


def test_pair_and_node_still_read_their_own_help(pointe):
    script, calls, env = pointe
    subprocess.run([str(script), "pair", "--help"], env=env, capture_output=True, text=True)
    assert "pair.py --help" in calls.read_text()


def test_local_py_never_installs_on_a_flag(monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(local, "install", lambda *a: ran.append(a) or 0)
    assert local.main(["--help"]) == 0 and local.main(["-h"]) == 0
    assert local.main(["--yes"]) == 2
    assert not ran and "pointe local status" in capsys.readouterr().out
