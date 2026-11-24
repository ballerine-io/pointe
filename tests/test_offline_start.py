"""An installed Pointe starts without internet: bin/* sync the environment from uv's cache first (bin/uv-sync), because a
plain `uv sync --locked` asks GitHub about the spaCy model wheel again and fails offline with every package on disk."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _fake_uv(tmp_path: Path, offline_works: bool) -> tuple[dict, Path]:
    calls = tmp_path / "calls"
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "uv").write_text("#!/bin/bash\n"
                             f"echo \"$*\" >> {calls}\n"
                             f"case \" $* \" in *' --offline '*) exit {0 if offline_works else 2} ;; esac\n"
                             "exit 0\n")
    (fake / "uv").chmod(0o755)
    return {"PATH": f"{fake}:/usr/bin:/bin"}, calls


def test_with_everything_cached_the_sync_never_goes_out(tmp_path):
    env, calls = _fake_uv(tmp_path, offline_works=True)
    got = subprocess.run([str(ROOT / "bin" / "uv-sync"), "--quiet", "--project", "x"], env=env, capture_output=True)
    assert got.returncode == 0
    assert calls.read_text().splitlines() == ["sync --locked --offline --quiet --project x"]


def test_a_sync_the_cache_cannot_satisfy_goes_out_with_the_same_lockfile(tmp_path):
    env, calls = _fake_uv(tmp_path, offline_works=False)
    got = subprocess.run([str(ROOT / "bin" / "uv-sync"), "--quiet", "--extra", "local"], env=env, capture_output=True)
    assert got.returncode == 0
    assert calls.read_text().splitlines() == ["sync --locked --offline --quiet --extra local",
                                              "sync --locked --quiet --extra local"]


def test_no_command_pointe_runs_syncs_online_first():
    """`uv run --locked` and `uv sync --locked` sync online; every one in bin/ goes through bin/uv-sync instead. The node's
    own environment (bin/voice-node, `pointe node`) has no direct-URL package and is left as it is."""
    found = []
    for path in sorted((ROOT / "bin").iterdir()):
        if path.name in ("uv-sync", "voice-node"):
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"\buv (run|sync)\b[^#]*--locked", line) and "--only-group node" not in line:
                found.append(f"{path.name}:{n}: {line.strip()}")
    assert not found, found
