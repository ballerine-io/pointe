"""A send never carries an absolute path the user did not say and that is not inside the session's own folder.

From the first tester round (apr-04): "delete the file scratch dot txt in the tmp folder" was sent as "the /tmp folder
(/tmp/scratch.txt)", pointing a delete outside the repository at a folder the user never named; a spoken "yes" then
approved a command on /tmp. The brain digests the user's words into a brief; a path outside the project is not a
digest of "the tmp folder". Such a send is refused with the reason, and the brain sends the user's words instead.

uv run pytest -q tests/test_no_invented_paths.py
"""

import asyncio
import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import add, d, open_gates, record_dispatch  # noqa: E402,F401  (d is the daemon fixture)


def test_a_path_outside_the_project_the_user_never_said_is_refused(d, monkeypatch, tmp_path):  # noqa: F811
    add(d, "g", "granary", cwd=str(tmp_path))
    sent = record_dispatch(d, monkeypatch)
    open_gates(d, monkeypatch, "Tell granary to delete the file scratch dot txt in the tmp folder.")
    d.state.brain_target = "granary"
    result = asyncio.run(d._send("Delete scratch.txt in the /tmp folder (/tmp/scratch.txt)."))
    assert sent == [] and "path" in result["error"]


def test_a_path_the_user_said_or_one_inside_the_project_goes(d, monkeypatch, tmp_path):  # noqa: F811
    add(d, "g", "granary", cwd=str(tmp_path))
    sent = record_dispatch(d, monkeypatch)
    open_gates(d, monkeypatch, "Tell granary to read /etc/hosts and the tmp folder.")
    d.state.brain_target = "granary"
    asyncio.run(d._send(f"Read /etc/hosts, and list {tmp_path}/tmp."))
    assert len(sent) == 1
