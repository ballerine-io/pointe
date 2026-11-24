"""CLI polish: `pointe pair` subcommands print no Pipecat log banner, and `pointe --version` says the version."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pointe_pair_help_prints_only_the_help(tmp_path):
    got = subprocess.run([sys.executable, "-I", str(ROOT / "pointe" / "pair.py"), "--help"], capture_output=True, text=True,
                         env={"CLAUDE_VOICE_STATE": str(tmp_path), "PATH": "/usr/bin:/bin"}, timeout=60)
    assert got.returncode == 0 and got.stdout.startswith("Pair the Pointe phone app")
    assert "pipecat" not in (got.stdout + got.stderr).lower()


def test_pointe_version():
    want = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    for flag in ("--version", "version"):
        got = subprocess.run([str(ROOT / "bin" / "pointe"), flag], capture_output=True, text=True, timeout=10)
        assert got.returncode == 0 and got.stdout == f"Pointe {want}\n"
