"""A read-out is said as a person says it: tester round 4's first sample heard "grep calc underscore total dot then
python3 pytest test underscore refunds dot py" (acc-01) and "find and head, also in slash" (lat-04, amb-03). The words a
yes is bound to (permission_spoken) do not change, and a word-for-word read-out is still said exactly.

uv run pytest -q tests/test_readout_heard.py
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

import readout  # noqa: E402
from test_orchestrator import _read_out_setup, add, d  # noqa: E402,F401  (d is the daemon fixture)


def test_the_root_folder_is_said_as_the_whole_disk():
    assert readout.looking("find / -name 'hero.png' 2>/dev/null | head", "/tmp/p/atlas") == \
        "look around, read only: find and head, also in the whole disk"


@pytest.mark.parametrize("spoken,heard", [
    ("run: grep calc_total . then python3 pytest test_refunds.py",
     "run: grep calc total here then python3 pytest test refunds.py"),
    ("run: rm -rf build", "run: rm -rf build"),
    ("run, word for word: sh scripts/slow_check.sh 3", "run, word for word: sh scripts/slow_check.sh 3"),
])
def test_a_code_name_in_a_read_out_is_said_in_words(d, spoken, heard):  # noqa: F811
    assert d._heard_request(spoken) == heard


def test_the_read_out_speaks_the_heard_form_and_binds_the_same_request(d, monkeypatch):  # noqa: F811
    active, posts, said = _read_out_setup(d, monkeypatch)
    active.permission_spoken = "run: grep calc_total . then python3 pytest test_refunds.py"
    asyncio.run(d._read_out(active))
    assert said[-1].endswith("wants to run: grep calc total here then python3 pytest test refunds.py. Should it?")
    assert active.permission_spoken == "run: grep calc_total . then python3 pytest test_refunds.py"
