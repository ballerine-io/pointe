"""A command that only looks is read out as that, in a few words; anything that could change something is not.

From the sprint's measured round (apr-03, apr-04, apr-05 before the change): a session exploring its project asked for
"pwd; cd … && pwd && ls -la && git status --short; grep -ril … | head -20; find . -path ./.git -prune …", and the
word-for-word read-out took 38 seconds, path part by path part. Now: "look around, read only: pwd, ls, git status,
grep, head and find". Every program is said, and every place outside the project or file that may hold a secret. The
list of what only looks is narrow, and each way around it found in review is a test below: those are read word for word.

uv run pytest -q tests/test_readout_looking.py
"""

import os
import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import guards  # noqa: E402
import readout  # noqa: E402


@pytest.fixture
def cwd(tmp_path):
    path = str(tmp_path / "atlas")
    os.makedirs(path)
    return path


def said(command: str, cwd: str) -> str:
    return guards.spoken_request("Bash", {"command": command}, cwd)


def test_a_session_exploring_its_project_is_read_in_a_few_words(cwd):
    command = (f'pwd; cd {cwd} && pwd && ls -la && git status --short; grep -ril "unirest" --exclude-dir=.git . '
               f'2>/dev/null | head -20; find . -path ./.git -prune -o -name "*.py" -print')
    out = said(command, cwd)
    assert out == "look around, read only: pwd, ls, git status, grep, head and find"
    assert len(out.split()) <= 14  # about six seconds, against 38 word for word


def test_a_place_outside_the_project_is_said(cwd):
    out = said("pwd && ls -la /tmp | head -50 && find /tmp -maxdepth 3 -name 'scratch.txt' 2>/dev/null", cwd)
    assert out == "look around, read only: pwd, ls, head and find, also in /tmp"
    assert said("cd /etc; ls; cat hosts | wc -l", cwd).endswith("also in /etc")


def test_the_projects_own_folder_by_its_full_path_is_not_a_place_to_name(cwd):
    assert said(f'ls -la {cwd}; echo "exit=$?"; git -C {cwd} status --short', cwd) == "look around, read only: ls and git status"
    assert said('find "$PWD" -maxdepth 2 -name "*.toml" | sort | head', cwd) == "look around, read only: find, sort and head"


def test_a_hidden_file_or_one_that_may_hold_a_secret_is_said(cwd):
    assert said("find . -name '*.json'; cat config/credentials.json | head -5", cwd).endswith("also in config/credentials.json")
    assert said("find . -name '*.yml'; wc -l .github/workflows/ci.yml", cwd).endswith("also in .github/workflows/ci.yml")
    assert "~/.ssh" in said("find . -name x; cat ~/.ssh/config; pwd", cwd)


@pytest.mark.parametrize("command", [
    "ls && rm -rf build",  # a program that changes something
    "find . -name '*.pyc' -delete", "find . -exec rm {} \;", "find . -name x -ok rm {} \;", "find . -fprint out.txt",
    "ls > out.txt", "ls >> out.txt", "cat a | sort -o a", "cat a | sort --output=a", "cat < /etc/passwd",
    "ls $(rm x)", "ls `id`", "cat <(rm x)", "ls & rm x", "FOO=1 ls", "cat $HOME/.netrc", "ls ${HOME}",
    "git branch newone", "git diff --output=x", "git log -o x", "git stash", "git checkout .", "git -C /tmp reset --hard",
    "grep -r key . | xargs rm", "ls; python3 x.py", "python3 -c 'import os'", "ls; sh x.sh", "ls | tee out.txt; pwd; pwd; x",
    "pwd\nrm -rf x", "date -s 2020-01-01", "env", "printenv", "sed -n 1p a", "awk '{print}' a", "tree -o out.txt",
    "ls 2> errors.txt", "ls &> all.txt", "cat a <<EOF\nx\nEOF", "ls; curl https://example.org",
])
def test_anything_that_could_change_something_is_never_called_looking(cwd, command):
    assert readout.looking(command, cwd) is None
    out = said(command, cwd)
    assert out is None or not out.startswith(readout.LOOK)


def test_too_many_places_or_programs_is_read_word_for_word(cwd):
    assert readout.looking("ls /a; ls /b; ls /c; ls /d", cwd) is None
    assert readout.looking("pwd; ls; cat a; head a; tail a; wc a; grep x a; file a; stat a", cwd) is None


def test_a_single_readable_command_keeps_its_own_short_form(cwd):
    assert said("git status", cwd) == "run: git status"
    assert said("ls -la", cwd) == "run: ls"
