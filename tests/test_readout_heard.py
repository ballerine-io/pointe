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


def test_the_reminder_of_a_request_already_read_is_one_short_line(d, monkeypatch):  # noqa: F811
    """"Billing is still waiting for your yes or no. Say, read it to hear it again." ended about ten dialogues of tester
    round 4's first sample. A yes already brings the request again before anything is approved, so the hint is not
    needed: the line says only that it waits."""
    active, posts, said = _read_out_setup(d, monkeypatch)
    active.permission_read_at = d.time.time() - 60
    fixed = []

    async def say_fixed(text, *a, **k):
        fixed.append(text)

    monkeypatch.setattr(d, "_say_fixed", say_fixed)
    monkeypatch.setattr(d, "pick_nudge", lambda *a: active)
    monkeypatch.setattr(d.state, "connected_at", 0.0)
    real_sleep = asyncio.sleep

    async def one_round(seconds):
        if fixed:
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(d.asyncio, "sleep", one_round)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(d._nudger())
    assert fixed == [f"{d._spoken_names(active.name)}'s still waiting on your yes or no."]


def test_a_sibling_project_is_said_by_its_name_next_to_the_project(tmp_path):
    """amb-01: "also in the folder above the project, /tmp/pccb/dlg-…/amb-01-shared-word-pointe/toll-api", 25 seconds
    of path for the project next door. Its name and where it sits say the same place."""
    (tmp_path / "toll-web").mkdir()
    (tmp_path / "toll-api").mkdir()
    cwd = str(tmp_path / "toll-web")
    out = readout.looking(f"cd {tmp_path}/toll-api && ls && git status && cat NOTES.md", cwd)
    assert out == "look around, read only: ls, git status and cat, also in toll-api, next to the project"
    assert readout.looking(f"cat {tmp_path}/toll-api/NOTES.md", cwd) == \
        "look around, read only: cat, also in toll-api/NOTES.md, next to the project"
    hidden = readout.looking(f"cat {tmp_path}/toll-api/.env.example", cwd)
    assert hidden is None or "next to the project" not in hidden  # hidden or secret-looking: never shortened
    assert readout.place(f"{tmp_path}/toll-api/build", cwd).endswith("/toll-api/build")  # what an action reaches: whole


def test_a_place_inside_the_project_is_still_not_said(tmp_path):
    (tmp_path / "toll-web" / "src").mkdir(parents=True)
    cwd = str(tmp_path / "toll-web")
    assert readout.looking(f"ls {tmp_path}/toll-web/src; cat src/app.py", cwd) == "look around, read only: ls and cat"
