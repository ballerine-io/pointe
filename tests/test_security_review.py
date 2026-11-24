"""tools/security_review.sh runs the published security reviews: it must review a clean checkout of one commit, give
the model read tools only, and cover the five areas docs/security/reviews/ names."""

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "security_review.sh"
AREAS = ["network-pairing", "approvals-voice", "secrets-supply", "web-page", "apple-apps"]
READ_ONLY = ["Read", "Grep", "Glob", "Bash(git log:*)", "Bash(git show:*)", "Bash(rg:*)", "Bash(ls:*)"]


def _run(tmp_path, *args):
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "claude").write_text('#!/bin/bash\necho "cwd=$(pwd)"\nprintf "arg=%s\\n" "$@"\n')
    (stub / "claude").chmod(0o755)
    out = tmp_path / "out"
    env = {**os.environ, "PATH": f"{stub}:{os.environ['PATH']}"}
    env.pop("POINTE_REVIEW_MODEL", None)
    done = subprocess.run([str(SCRIPT), "--out", str(out), *args], capture_output=True, text=True, env=env, timeout=120)
    assert done.returncode == 0, done.stderr
    return out


def test_every_area_runs_read_only_on_a_clean_checkout(tmp_path):
    out = _run(tmp_path)
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    for area in AREAS:
        text = (out / f"{area}.md").read_text()
        assert f"{area} review of {head} by claude-mythos-5-2" in text
        args = re.findall(r"^arg=(.*)$", text, re.M)
        tools = args[args.index("--allowedTools") + 1:args.index("--output-format")]
        assert tools == READ_ONLY
        assert args[args.index("--permission-mode") + 1] == "default"
        cwd = re.search(r"^cwd=(.*)$", text, re.M).group(1)
        assert Path(cwd).resolve() != ROOT
    listed = subprocess.run(["git", "-C", str(ROOT), "worktree", "list"], capture_output=True, text=True).stdout
    assert "pointe-review." not in listed


def test_model_and_area_can_be_chosen(tmp_path):
    out = _run(tmp_path, "--model", "some-model", "web-page")
    assert [p.name for p in out.glob("*.md")] == ["web-page.md"]
    assert "arg=some-model" in (out / "web-page.md").read_text()


def test_unknown_area_is_refused(tmp_path):
    done = subprocess.run([str(SCRIPT), "--out", str(tmp_path), "everything"], capture_output=True, text=True)
    assert done.returncode == 2 and "unknown area" in done.stderr


def test_since_scopes_each_pass_to_the_changes(tmp_path):
    out = _run(tmp_path, "--since", "HEAD", "web-page")  # HEAD: CI's checkout is shallow, with no parent to name
    text = (out / "web-page.md").read_text()
    base = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert "changes since HEAD to" in text and f"SCOPE: review only what changed from {base} to" in text
