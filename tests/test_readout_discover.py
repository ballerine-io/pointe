"""`python3 -m unittest discover -s tests -t .` is read out: its folders are said, so a spoken yes can approve it.

From the conversation suite: after two requests sent back for plain commands, Claude ran
`python3 -m unittest discover -s <project>/tests -t <project>`, still tap-only because -s and -t were not known flags
of unittest. They name folders, which the read-out says (inside the project, by name; the project itself and anything
outside it, whole). A glob pattern (-p 'test_*.py') stays tap-only, as every glob does.

uv run pytest -q tests/test_readout_discover.py
"""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import readout  # noqa: E402

CWD = "/tmp/project/ledgerline"


@pytest.mark.parametrize("command,said", [
    (f"python3 -m unittest discover -s {CWD}/tests -t {CWD}", "python3 unittest discover -s tests -t the project folder"),
    ("python3 -m unittest discover -s tests -v", "python3 unittest discover -s tests"),
])
def test_discover_with_its_folders_is_read_out(command, said):
    assert readout.spoken(command, CWD) == said


def test_a_folder_outside_the_project_is_said_whole():
    assert readout.spoken("python3 -m unittest discover -s /etc/tests", CWD) == "python3 unittest discover -s /etc/tests"
