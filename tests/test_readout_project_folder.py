"""A read-out says the session's own folder as "the project folder", not as its full path.

From the independent tester's second round (apr-06): "python3 unittest discover -s tests -t /private/tmp/…/billing" was
read for 23.5 seconds, path part by path part, three times. A path inside the project was already said by its name; the
project folder itself, given by its full path, was not. Nothing else is shortened: one folder up, a neighbour whose
name starts the same, and any place outside are still said whole.

uv run pytest -q tests/test_readout_project_folder.py
"""

import os
import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import guards  # noqa: E402


def _said(command: str, cwd: str) -> str:
    return guards.spoken_request("Bash", {"command": command}, cwd)


def test_the_project_folder_by_its_full_path_is_said_in_three_words(tmp_path):
    cwd = str(tmp_path / "billing")
    os.makedirs(cwd + "/tests")
    said = _said(f"python3 -m unittest discover -v -s {cwd}/tests -t {cwd} > test_output.txt 2>&1", cwd)
    assert said == "run: python3 unittest discover -s tests -t the project folder writing to test_output.txt"
    assert len(said.split()) <= 14  # about six seconds of speech


def test_a_delete_of_the_project_folder_says_so(tmp_path):
    cwd = str(tmp_path / "billing")
    os.makedirs(cwd)
    assert _said(f"rm -rf {cwd}", cwd) == "run: rm -rf the project folder"
    assert _said(f"rm -rf {cwd}/", cwd) == "run: rm -rf the project folder"


def test_anything_that_is_not_exactly_the_project_folder_is_still_said_whole(tmp_path):
    cwd = str(tmp_path / "billing")
    os.makedirs(cwd)
    assert _said(f"rm -rf {cwd}/..", cwd) == f"run: rm -rf {tmp_path}"  # one folder up
    assert _said(f"rm -rf {cwd}x", cwd) == f"run: rm -rf {cwd}x"  # a neighbour whose name starts the same
    assert _said("rm -rf /etc", cwd) == "run: rm -rf /etc"


def test_a_file_tee_writes_is_said(tmp_path):
    cwd = str(tmp_path / "billing")
    os.makedirs(cwd)
    assert _said("pytest -q 2>&1 | tee test_output.txt", cwd) == "run: pytest into tee test_output.txt"
    assert _said("pytest -q | tee -a /etc/out.txt", cwd) == "run: pytest into tee -a /etc/out.txt"
