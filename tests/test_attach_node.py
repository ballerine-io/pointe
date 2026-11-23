"""Adding sessions on another machine (docs/design/attach-by-voice.md): the node lists its own sessions for the hub,
without their paths to transcripts, sockets or accounts, and joins one when the hub asks, as /pointe:voice there
would. A recent Claude Code session is not reopened from the hub.

uv run --locked pytest -q tests/test_attach_node.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harnesses  # noqa: E402
from discovery import Found  # noqa: E402
from test_node import run  # noqa: E402


def _fake_discovery(monkeypatch, tmp_path, items):
    async def discover(since, cap, items=items):
        return list(items)

    async def nothing(since, cap):
        return []

    monkeypatch.setattr(harnesses.get("claude-code"), "discover", discover)
    for name in ("codex", "opencode"):
        monkeypatch.setattr(harnesses.get(name), "discover", nothing)


def test_the_node_lists_its_sessions_without_paths_to_secrets(tmp_path, monkeypatch):
    found = Found("claude-code", "cc-1", "pentest-recon", str(tmp_path), "open", 5.0, first="pentest the login",
                  pid=os.getpid(), socket="/tmp/secret.sock", home="/Users/mira/.claude-work",
                  transcript="/Users/mira/.claude-work/projects/x/cc-1.jsonl")
    _fake_discovery(monkeypatch, tmp_path, [found])

    async def scenario(hub, n):
        await hub.send("discover", req="r1", since=0.0, cap=40)
        got = await hub.next("discovered", req="r1")
        assert [f["id"] for f in got["found"]] == ["cc-1"] and got["found"][0]["first"] == "pentest the login"
        assert not {"socket", "home", "transcript", "pid", "data"} & set(got["found"][0])

    run(scenario, tmp_path)


def test_the_node_joins_a_listed_session_and_refuses_to_reopen_claude_code(tmp_path, monkeypatch):
    found = Found("claude-code", "cc-1", "pentest-recon", str(tmp_path), "open", 5.0, pid=os.getpid(),
                  transcript=str(tmp_path / "cc-1.jsonl"))
    recent = Found("claude-code", "cc-old", "billing-migration", str(tmp_path), "recent", 1.0)
    _fake_discovery(monkeypatch, tmp_path, [found, recent])
    bodies = []

    def attach_body(f):
        bodies.append(f.id)
        return {"id": f.id, "name": f.name, "name_given": True, "cwd": f.cwd, "pid": f.pid, "transcript": f.transcript}

    monkeypatch.setattr(harnesses.get("claude-code"), "attach_body", attach_body)

    async def scenario(hub, n):
        await hub.send("discover", req="r1", since=0.0, cap=40)
        await hub.next("discovered", req="r1")
        await hub.send("attach", req="r2", harness="claude-code", id="cc-1")
        assert (await hub.next("attach.result", req="r2"))["ok"] is True
        assert "cc-1" in n.registry.sessions and bodies == ["cc-1"]
        await hub.send("attach", req="r3", harness="claude-code", id="cc-old", reopen=True)
        refused = await hub.next("attach.result", req="r3")
        assert refused["ok"] is False and "only on the hub's Mac" in refused["why"]
        await hub.send("attach", req="r4", harness="claude-code", id="nobody")
        assert (await hub.next("attach.result", req="r4"))["ok"] is False

    run(scenario, tmp_path)
