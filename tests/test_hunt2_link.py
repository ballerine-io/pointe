"""Second bug hunt, link/hub/node protocol: each test here is written to FAIL on 8b7dba0 and names the defect."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import harnesses  # noqa: E402
import hub_nodes  # noqa: E402
import nodelink  # noqa: E402
import sessions  # noqa: E402
from sessions import Session  # noqa: E402
from test_hub_nodes import FakeNode, _request, entry, paired, real, run, settle  # noqa: E402,F401  (real is a fixture)
from test_hub_nodes import world  # noqa: E402,F401
import test_node  # noqa: E402
from test_node import FakeHub, _body  # noqa: E402
from test_orchestrator import d, fake_conn  # noqa: E402,F401


# ---------- 3. the node never gets past a transcript line longer than READ_MAX ----------

def test_a_line_longer_than_one_read_does_not_stall_shipping_for_good(tmp_path, monkeypatch):
    monkeypatch.setattr(test_node.node, "READ_MAX", 4096)  # the real cap is 4 MB: a pasted screenshot is bigger
    big = json.dumps({"type": "user", "image": "x" * 5000}) + "\n"  # one line over READ_MAX
    small = json.dumps({"type": "assistant", "message": {"content": "done"}}) + "\n"

    async def scenario(hub, n):
        body = _body(tmp_path)
        Path(body["transcript"]).write_text(big + small)
        await n.register(body)
        await hub.next("transcript.repointed")
        try:
            frame = await hub.next("transcript", timeout=2)
        except asyncio.TimeoutError:
            pytest.fail("nothing shipped: the node re-reads the same READ_MAX bytes every poll and never advances")
        assert frame["next_offset"] == len((big + small).encode())
        assert frame["entries"] == [small]  # the oversize line is skipped, its bytes counted, the rest ships

    test_node.run(scenario, tmp_path)
