"""A path inside the project is read out by its name even when the path and the project folder are spelled through
different links (/tmp and /private/tmp on a Mac).

From the first tester round: "billing wants to run: python3 unittest discover -s tests -t
/tmp/pccb/<run>/<dialogue>/billing ..." read the session's own folder aloud in full, because the session's folder was
recorded as /private/tmp/... and the command said /tmp/...; every read-out of such a request was 20 words of path.

uv run pytest -q tests/test_readout_symlinked_cwd.py
"""

import os
import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import readout  # noqa: E402


def test_the_same_folder_through_a_link_is_inside(tmp_path):
    real = os.path.realpath(tmp_path)
    linked = os.path.join(tmp_path.parent, "linked")
    os.symlink(real, linked)
    (Path(real) / "tests").mkdir()
    assert readout.place(f"{linked}/tests", real) == "tests"
    assert readout.place(f"{real}/tests", linked) == "tests"
    assert readout.place(real, linked) == real  # the project itself is said whole (test_readout_discover.py)


def test_a_folder_outside_is_still_whole(tmp_path):
    real = os.path.realpath(tmp_path)
    (Path(real) / "proj").mkdir()
    assert readout.place(f"{real}/other", f"{real}/proj") == f"{real}/other"
