"""`pointe restart` stops a running Pointe only once the new setup can start, and `pointe setup` says when a key is
missing. From a QA run: `pointe setup openai` with no OpenAI key, then `pointe restart`, left Pointe stopped and the call gone."""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import setups  # noqa: E402
import vendors  # noqa: E402


def _bin(tmp_path, preflight_rc: int) -> tuple[Path, dict]:
    """A copy of bin/pointe and bin/uv-sync beside a fake voice-daemon that is running, and a fake uv whose preflight
    answers `preflight_rc`."""
    bin_ = tmp_path / "plugin" / "bin"
    bin_.mkdir(parents=True)
    for name in ("pointe", "uv-sync"):
        shutil.copy(ROOT / "bin" / name, bin_ / name)
    calls = tmp_path / "calls"
    (bin_ / "voice-daemon").write_text(f'#!/bin/bash\necho "daemon $*" >> {calls}\n[ "$1" = status ] && echo "running (pid 1)"\nexit 0\n')
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "uv").write_text(f'#!/bin/bash\necho "uv $*" >> {calls}\ncase "$*" in *--preflight*) echo "It needs an OpenAI key."; exit {preflight_rc} ;; esac\nexit 0\n')
    for f in (*bin_.iterdir(), fake / "uv"):
        f.chmod(0o755)
    return calls, {"PATH": f"{fake}:/usr/bin:/bin", "HOME": str(tmp_path)}


def test_a_restart_onto_a_setup_that_cannot_start_keeps_pointe_running(tmp_path):
    calls, env = _bin(tmp_path, preflight_rc=1)
    got = subprocess.run([str(tmp_path / "plugin" / "bin" / "pointe"), "restart"], env=env, capture_output=True, text=True)
    assert got.returncode == 1 and "Not restarted: Pointe keeps running" in got.stderr and "OpenAI key" in got.stderr
    assert "daemon stop" not in calls.read_text()


def test_a_restart_onto_a_setup_that_can_start_restarts(tmp_path):
    calls, env = _bin(tmp_path, preflight_rc=0)
    got = subprocess.run([str(tmp_path / "plugin" / "bin" / "pointe"), "restart"], env=env, capture_output=True, text=True)
    lines = calls.read_text().splitlines()
    assert got.returncode == 0 and lines[-2:] == ["daemon stop", "daemon ensure"]


def test_pointe_setup_says_a_missing_key_before_the_restart(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_VOICE_STATE", str(tmp_path))
    monkeypatch.setattr(vendors, "saved", lambda v: False)
    assert setups.main(["openai"]) == 0
    out = capsys.readouterr().out
    assert "Not saved yet: the OpenAI key" in out and "pointe key openai" in out and "keeps it running" in out
    monkeypatch.setattr(vendors, "saved", lambda v: True)
    setups.main(["openai"])
    assert "Not saved yet" not in capsys.readouterr().out
