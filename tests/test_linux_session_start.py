"""Starting a Claude Code session from the voice on Linux: a window in the person's own tmux session `pointe`, which they
attach to from any terminal or over SSH (`tmux attach -t pointe`). Without tmux the start is refused in words that say
how to start it themselves and join it with /pointe:voice. A fake tmux on PATH records what it was asked."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
import harnesses  # noqa: E402
from harnesses import claude_code  # noqa: E402
from harnesses.base import StartError  # noqa: E402

FAKE_TMUX = """#!/bin/sh
printf '%s\\n' "$*" >> "$TMUX_LOG"
case "$1" in
  has-session) [ -f "$TMUX_LOG.session" ] ;;
  new-session) touch "$TMUX_LOG.session" ;;
esac
"""


@pytest.fixture
def linux(tmp_path, monkeypatch):
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "tmux").write_text(FAKE_TMUX)
    (fake / "tmux").chmod(0o755)
    (fake / "claude").write_text("#!/bin/sh\n")
    (fake / "claude").chmod(0o755)
    log = tmp_path / "tmux.log"
    monkeypatch.setenv("TMUX_LOG", str(log))
    monkeypatch.setenv("PATH", f"{fake}:/usr/bin:/bin")
    monkeypatch.delenv(claude_code.OPEN_WITH_ENV, raising=False)
    monkeypatch.setattr(claude_code.sys, "platform", "linux")
    monkeypatch.setattr(harnesses.HOST, "state_dir", tmp_path / "state")
    monkeypatch.setattr(harnesses.HOST, "port", 7999, raising=False)
    return type("Linux", (), {"log": log, "fake": fake, "folder": tmp_path})


def calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def test_with_tmux_and_claude_a_session_can_start_on_linux(linux):
    assert harnesses.get("claude-code").can_start() is None


def test_without_tmux_the_start_is_refused_with_how_to_start_it_yourself(linux, monkeypatch):
    (linux.fake / "tmux").unlink()
    monkeypatch.setenv("PATH", str(linux.fake))  # CI's Ubuntu has a tmux in /usr/bin
    why = harnesses.get("claude-code").can_start()
    assert "tmux" in why and "/pointe:voice" in why and "Mac" not in why


def test_without_claude_on_linux_it_says_this_machine(linux):
    (linux.fake / "claude").unlink()
    assert harnesses.get("claude-code").can_start() == "Claude Code is not installed on this machine."


def test_the_first_start_makes_the_pointe_tmux_session_and_the_next_one_adds_a_window(linux):
    folder = linux.folder / "my shop"
    folder.mkdir()
    adapter = harnesses.get("claude-code")
    assert asyncio.run(adapter.start(str(folder), "shop", "abc1")) is None  # it registers itself, by its hook
    assert asyncio.run(adapter.start(str(folder), "shop-2", "abc2")) is None
    made, added = [c for c in calls(linux.log) if c.startswith(("new-session", "new-window"))]
    script1 = linux.folder / "state" / "starts" / "abc1.command"
    script2 = linux.folder / "state" / "starts" / "abc2.command"
    assert made.startswith("new-session -d -s pointe -n shop ") and made.endswith(f"/bin/sh {script1}")
    assert added.startswith("new-window -d -t pointe: -n shop-2 ") and added.endswith(f"/bin/sh {script2}")
    assert subprocess.run(["sh", "-n", str(script1)]).returncode == 0


def test_a_reopen_on_linux_goes_to_tmux_too(linux):
    folder = linux.folder / "repo"
    folder.mkdir()
    found = type("Found", (), {"cwd": str(folder), "name": "shop", "id": "sess-1", "home": ""})()
    assert asyncio.run(harnesses.get("claude-code").reopen(found, "abc3")) is None
    assert any(c.startswith("new-session -d -s pointe -n shop ") for c in calls(linux.log))


def test_a_tmux_that_fails_is_a_failure_with_words(linux):
    (linux.fake / "tmux").write_text("#!/bin/sh\nexit 1\n")
    folder = linux.folder / "repo"
    folder.mkdir()
    with pytest.raises(StartError, match="tmux"):
        asyncio.run(harnesses.get("claude-code").start(str(folder), "shop", "abc4"))


def test_the_test_opener_still_wins_on_linux(linux, monkeypatch):
    """The end-to-end tests name their own opener (CLAUDE_VOICE_OPEN_WITH): it is used on every system."""
    opener = linux.folder / "opener"
    opener.write_text(f"#!/bin/sh\necho \"$1\" > {linux.folder / 'opened'}\n")
    opener.chmod(0o755)
    monkeypatch.setenv(claude_code.OPEN_WITH_ENV, str(opener))
    folder = linux.folder / "repo"
    folder.mkdir()
    asyncio.run(harnesses.get("claude-code").start(str(folder), "shop", "abc5"))
    assert (linux.folder / "opened").read_text().strip().endswith("abc5.command")
    assert not calls(linux.log)


def test_the_words_say_where_it_opens(monkeypatch):
    monkeypatch.setattr(claude_code.sys, "platform", "linux")
    assert "tmux attach -t pointe" in claude_code.opens_where()
    monkeypatch.setattr(claude_code.sys, "platform", "darwin")
    assert claude_code.opens_where() == "in a new terminal window on the Mac"


def test_the_voice_says_tmux_when_it_starts_one_on_linux(monkeypatch):
    import daemon
    import newsession

    monkeypatch.setattr(claude_code.sys, "platform", "linux")
    start = newsession.Start(id="s1", harness="claude-code", folder="/tmp", name="shop")
    note = daemon._started_note(start)
    assert "tmux attach -t pointe" in note and "Mac" not in note


def test_the_new_session_sheet_gets_the_linux_note(monkeypatch):
    import daemon

    monkeypatch.setattr(claude_code.sys, "platform", "linux")
    monkeypatch.setattr(harnesses.get("claude-code"), "can_start", lambda: None)
    entry = next(h for h in daemon._start_harnesses() if h["name"] == "claude-code")
    assert "tmux attach -t pointe" in entry["note"]
    assert json.dumps(entry)  # the page reads it as it is
