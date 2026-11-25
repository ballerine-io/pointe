"""Finding sessions to add by voice (docs/design/attach-by-voice.md): what each harness lists, read from the shapes its
real interface prints (tests/fixtures/attach: Claude Code 2.1.330's `claude agents --json` and its session record,
scrubbed and with invented names), and what is never read or used.

uv run --locked pytest -q tests/test_attach_discovery.py
"""

import asyncio
import json
import os
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
import discovery  # noqa: E402
import harnesses.claude_code as claude_code  # noqa: E402
import nodelink  # noqa: E402
from discovery import Found  # noqa: E402
from harnesses.base import StartError  # noqa: E402
from harnesses.codex import Codex, RpcError  # noqa: E402
from harnesses.opencode import OpenCode  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "attach"
SID = "2353eaf4-fee8-4ea6-b4bc-d919b487479e"


@pytest.fixture
def sock():
    """A real Unix socket of this user, at a path short enough for macOS."""
    folder = Path(tempfile.mkdtemp(prefix="pv", dir="/tmp"))
    path = folder / "s.sock"
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(path))
    yield str(path)
    server.close()
    shutil.rmtree(folder, ignore_errors=True)


def _account(tmp_path: Path, sock: str, pid: int | None = None, cwd: str | None = None) -> tuple[Path, list]:
    """A config dir laid out as Claude Code keeps it: the session's record and its transcript; and the roster."""
    home = tmp_path / "cfg"
    pid = pid or os.getpid()
    cwd = cwd or str(tmp_path / "pentest-notes")
    Path(cwd).mkdir(exist_ok=True)
    record = json.loads((FIX / "claude_session_record.json").read_text())
    record.update(pid=pid, cwd=cwd, messagingSocketPath=sock)
    (home / "sessions").mkdir(parents=True)
    (home / "sessions" / f"{pid}.json").write_text(json.dumps(record))
    project = home / "projects" / "-x-pentest-notes"
    project.mkdir(parents=True)
    (project / f"{SID}.jsonl").write_text((FIX / "claude_transcript.jsonl").read_text().replace("/Users/mira/work/pentest-notes", cwd))
    roster = json.loads((FIX / "claude_agents.json").read_text())
    roster[0].update(pid=pid, cwd=cwd)
    return home, roster


# ---------- Claude Code ----------

def test_an_open_session_comes_from_the_roster_with_its_socket_from_its_own_record(tmp_path, sock):
    home, roster = _account(tmp_path, sock)
    found = discovery.claude_open(home, roster, "")
    assert [f.id for f in found] == [SID]  # the background one's pid is not a live process of this user
    f = found[0]
    assert (f.name, f.state, f.kind, f.status, f.socket, f.name_given) == ("pentest-recon", "open", "interactive", "idle", sock, True)
    assert f.joinable and f.transcript.endswith(f"{SID}.jsonl") and f.branch == "recon"
    assert f.first.startswith("Plan the pentest of the login service")
    assert f.last == "Write the findings into a report for the security review."
    assert "pentest" in f.keywords and "login" in f.keywords


def test_what_the_session_never_typed_is_not_its_summary(tmp_path, sock):
    """System reminders, tool results and injected caveats are not the user's words, and never reach a summary."""
    home, roster = _account(tmp_path, sock)
    f = discovery.claude_open(home, roster, "")[0]
    said = " ".join([f.first, f.last, *f.keywords]).lower()
    assert "private" not in said and "memory" not in said and "caveat" not in said and "injected" not in said


def test_a_record_that_names_another_session_gives_no_socket(tmp_path, sock):
    home, roster = _account(tmp_path, sock)
    record = json.loads((home / "sessions" / f"{os.getpid()}.json").read_text())
    record["sessionId"] = "another-session"
    (home / "sessions" / f"{os.getpid()}.json").write_text(json.dumps(record))
    f = discovery.claude_open(home, roster, "")[0]
    assert not f.joinable and f.socket == "" and "/pointe:voice" in f.why


@pytest.mark.parametrize("bad", ["a file", "a link", "missing"])
def test_a_socket_must_be_a_socket_of_this_user_and_not_a_link(tmp_path, sock, bad):
    target = tmp_path / "x.sock"
    if bad == "a file":
        target.write_text("")
    elif bad == "a link":
        target.symlink_to(sock)
    assert discovery.usable_socket(sock)
    assert not discovery.usable_socket(str(target))


def test_another_users_process_is_not_listed(tmp_path, sock, monkeypatch):
    home, roster = _account(tmp_path, sock)
    monkeypatch.setattr(discovery, "ours", lambda pid: False)
    assert discovery.claude_open(home, roster, "") == []


def test_another_users_config_dir_is_never_read(tmp_path, monkeypatch):
    mine, theirs = tmp_path / "mine", tmp_path / "theirs"
    mine.mkdir(), theirs.mkdir()
    monkeypatch.setattr(discovery, "own", lambda path: Path(path) != theirs)
    monkeypatch.delenv(discovery.HOMES_ENV, raising=False)
    assert discovery.claude_homes(tmp_path / "default", [str(mine), str(theirs), "relative/dir"]) == [str(mine)]


def test_the_override_is_the_whole_list_of_accounts(tmp_path, monkeypatch):
    a = tmp_path / "a"
    a.mkdir()
    monkeypatch.setenv(discovery.HOMES_ENV, str(a))
    assert discovery.claude_homes(tmp_path / "default", [str(tmp_path)]) == [str(a)]


def test_recent_sessions_are_closed_transcripts_newest_first_within_the_window(tmp_path, sock):
    home, _ = _account(tmp_path, sock)
    project = home / "projects" / "-x-pentest-notes"
    old, newer = project / "old.jsonl", project / "newer.jsonl"
    for path, when in ((old, time.time() - 10 * 86400), (newer, time.time() - 3600)):
        path.write_text((FIX / "claude_transcript.jsonl").read_text().replace("/Users/mira/work/pentest-notes", str(tmp_path / "pentest-notes")))
        os.utime(path, (when, when))
    (project / "agent-123.jsonl").write_text(newer.read_text())  # a sub-agent's record is not a session
    found = discovery.claude_recent(home, time.time() - 7 * 86400, {SID}, "", cap=40)
    assert [f.id for f in found] == ["newer"]
    assert found[0].state == "recent" and found[0].cwd == str(tmp_path / "pentest-notes") and found[0].joinable


def test_recent_sessions_are_capped_and_read_only_at_their_ends(tmp_path, sock, monkeypatch):
    home, _ = _account(tmp_path, sock)
    project = home / "projects" / "-x-pentest-notes"
    body = (FIX / "claude_transcript.jsonl").read_text().replace("/Users/mira/work/pentest-notes", str(tmp_path / "pentest-notes"))
    for i in range(5):
        (project / f"s{i}.jsonl").write_text(body + ("x" * 300_000) + "\n" + body)
    reads = []
    real_open = open

    def counting_open(path, mode="r", *a, **k):
        f = real_open(path, mode, *a, **k)
        if "b" in mode:
            real_read = f.read
            f.read = lambda n=-1: (reads.append(n), real_read(n))[1]
        return f

    monkeypatch.setattr("builtins.open", counting_open)
    found = discovery.claude_recent(home, 0, {SID}, "", cap=3)
    assert len(found) == 3
    assert reads and max(reads) <= discovery.TAIL_BYTES, max(reads)  # never a whole file


def test_a_recent_session_whose_folder_is_gone_is_listed_and_cannot_reopen(tmp_path, sock):
    home, _ = _account(tmp_path, sock)
    project = home / "projects" / "-x-pentest-notes"
    (project / "gone.jsonl").write_text((FIX / "claude_transcript.jsonl").read_text())  # its folder never existed here
    gone = next(f for f in discovery.claude_recent(home, 0, {SID}, "") if f.id == "gone")
    assert not gone.joinable and "no longer there" in gone.why


def test_the_hook_applies_by_settings_precedence_or_a_plugin_dir(tmp_path):
    home, folder = tmp_path / "cfg", tmp_path / "repo"
    (folder / ".claude").mkdir(parents=True)
    home.mkdir()
    managed = tmp_path / "managed.json"
    assert not discovery.hook_applies(home, str(folder), "", managed)
    (home / "settings.json").write_text(json.dumps({"enabledPlugins": {"pointe@pointe": True}}))
    assert discovery.hook_applies(home, str(folder), "", managed)
    (folder / ".claude" / "settings.local.json").write_text(json.dumps({"enabledPlugins": {"pointe@pointe": False}}))
    assert not discovery.hook_applies(home, str(folder), "", managed)
    root = Path(__file__).resolve().parents[1]
    assert discovery.hook_applies(home, str(folder), f"claude --plugin-dir {root} --name x", managed)
    managed.write_text(json.dumps({"enabledPlugins": {"pointe@corp": False}}))
    assert discovery.hook_applies(home, str(folder), f"claude --plugin-dir {root}", managed)  # loaded for this process


def test_claude_codes_discovery_reads_each_account_and_never_the_real_default(tmp_path, sock, monkeypatch):
    """The account read is always named by its path when it is not ~/.claude (tests): a test never runs the real
    `claude agents --json`, and discovery never reads the owner's sessions by accident."""
    home, roster = _account(tmp_path, sock)
    asked = []

    async def agents(key):
        asked.append(key)
        return roster

    monkeypatch.setattr(claude_code, "_agents", agents)
    monkeypatch.setattr(claude_code, "DEFAULT_HOME", tmp_path / "default")
    (tmp_path / "default").mkdir()
    monkeypatch.setenv(discovery.HOMES_ENV, os.pathsep.join([str(tmp_path / "default"), str(home)]))
    found = asyncio.run(claude_code.ClaudeCode().discover(0, 40))
    assert asked == [str(tmp_path / "default"), str(home)]
    assert [f.id for f in found if f.state == "open"] == [SID, SID]  # the same roster answered for both, in this fake
    assert {f.home for f in found} == {"", str(home)}


def test_the_register_body_is_what_pointe_voice_would_send(tmp_path, sock):
    home, roster = _account(tmp_path, sock)
    f = discovery.claude_open(home, roster, str(home))[0]
    body = claude_code.ClaudeCode().attach_body(f)
    assert body == {"id": SID, "name": "pentest-recon", "name_given": True, "cwd": f.cwd, "pid": os.getpid(),
                    "transcript": f.transcript, "inbox_socket": sock, "config_dir": str(home)}


def test_a_session_that_closed_or_lost_its_socket_does_not_join(tmp_path, sock, monkeypatch):
    home, roster = _account(tmp_path, sock)
    f = discovery.claude_open(home, roster, "")[0]
    monkeypatch.setattr(discovery, "ours", lambda pid: False)
    with pytest.raises(StartError, match="has closed"):
        claude_code.ClaudeCode().attach_body(f)
    monkeypatch.setattr(discovery, "ours", lambda pid: True)
    f.socket = str(tmp_path / "nothing.sock")
    with pytest.raises(StartError, match="/pointe:voice"):
        claude_code.ClaudeCode().attach_body(f)


def test_reopen_resumes_in_a_terminal_in_its_folder_and_account_in_the_default_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_code.HOST, "state_dir", tmp_path / "state")
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: f"/usr/local/bin/{name}")
    monkeypatch.setattr(claude_code.sys, "platform", "darwin")
    opened = []
    monkeypatch.setattr(claude_code, "open_terminal", lambda script: opened.append(script))
    folder = tmp_path / "billing"
    folder.mkdir()
    f = Found(harness="claude-code", id=SID, name="billing-migration", cwd=str(folder), state="recent", when=0,
              home="/Users/mira/.claude-work")
    assert asyncio.run(claude_code.ClaudeCode().reopen(f, "st1")) is None
    script = opened[0].read_text()
    settings = json.loads((tmp_path / "state" / "starts" / "st1.json").read_text())
    assert f"--resume {SID} --permission-mode default --settings" in script and "--name" not in script.split("exec")[1]
    assert "CLAUDE_CONFIG_DIR=/Users/mira/.claude-work" in script and f"cd {folder}" in script
    assert "dangerously" not in script and "bypass" not in script.lower()
    hook = settings["hooks"]["SessionStart"][0]
    assert hook["matcher"] == "resume" and "--start st1" in hook["hooks"][0]["command"]
    assert "--name billing-migration" in hook["hooks"][0]["command"]


def test_a_new_session_still_starts_with_the_startup_matcher_and_its_name(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_code.HOST, "state_dir", tmp_path / "state")
    script = claude_code.start_script(str(tmp_path), "shop-2", "st2")
    settings = json.loads((tmp_path / "state" / "starts" / "st2.json").read_text())
    assert settings["hooks"]["SessionStart"][0]["matcher"] == "startup"
    assert "--name shop-2" in script.read_text() and "--resume" not in script.read_text()
    assert "CLAUDE_CONFIG_DIR" not in script.read_text()


def test_reopen_refuses_a_folder_that_is_gone_and_a_machine_with_no_terminal(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: f"/usr/local/bin/{name}")
    f = Found(harness="claude-code", id=SID, name="x", cwd=str(tmp_path / "gone"), state="recent", when=0)
    monkeypatch.setattr(claude_code.sys, "platform", "darwin")
    with pytest.raises(StartError, match="no longer there"):
        asyncio.run(claude_code.ClaudeCode().reopen(f, "s"))
    monkeypatch.setattr(claude_code.sys, "platform", "linux")
    monkeypatch.delenv(claude_code.OPEN_WITH_ENV, raising=False)
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: None if name == "tmux" else f"/usr/local/bin/{name}")
    with pytest.raises(StartError, match="Reopening Claude Code here needs tmux"):
        asyncio.run(claude_code.ClaudeCode().reopen(f, "s"))


# ---------- Codex (app-server schema: thread/list, thread/loaded/list) ----------

class FakeCodexLink:
    def __init__(self, threads, loaded, resume=None, error=None):
        self.threads, self.loaded, self.resume, self.error = threads, loaded, resume or {}, error
        self.calls, self.listeners, self.reconnected, self.down_since, self.path = [], [], [], None, None

    async def ensure(self):
        if self.error:
            raise self.error

    async def request(self, method, params, timeout=30):
        self.calls.append((method, params))
        if method == "thread/loaded/list":
            return {"data": self.loaded}
        if method == "thread/list":
            return {"data": self.threads, "nextCursor": None}
        if method == "thread/resume":
            if isinstance(self.resume, Exception):
                raise self.resume
            return self.resume
        return {}


def _thread(tid, cwd, updated, **extra):
    return {"id": tid, "cwd": cwd, "name": extra.pop("name", None), "preview": extra.pop("preview", "fix the invoice export"),
            "updatedAt": updated, "createdAt": updated - 60, "status": {"type": extra.pop("status", "notLoaded")},
            "gitInfo": {"branch": "main", "sha": None, "originUrl": None}, "ephemeral": False, **extra}


def test_codex_lists_loaded_threads_as_open_and_others_as_recent(tmp_path):
    now = time.time()
    threads = [_thread("t-open", str(tmp_path), now, status="idle", name="invoices"),
               _thread("t-old", str(tmp_path), now - 86400),
               _thread("t-ancient", str(tmp_path), now - 30 * 86400),
               _thread("t-sub", str(tmp_path), now, parentThreadId="t-open")]
    link = FakeCodexLink(threads, ["t-open"])
    found = asyncio.run(Codex(link).discover(now - 7 * 86400, 40))
    assert [(f.id, f.state) for f in found] == [("t-open", "open"), ("t-old", "recent")]
    assert found[0].name == "invoices" and found[1].first == "fix the invoice export" and found[1].branch == "main"
    assert ("thread/list", {"limit": 41, "sortKey": "updated_at"}) in link.calls  # newest first, the documented key


def test_codex_with_no_shared_daemon_lists_nothing():
    found = asyncio.run(Codex(FakeCodexLink([], [], error=ConnectionError("down"))).discover(0, 40))
    assert found == []


def test_codex_reopen_resumes_the_thread_and_refuses_one_that_bypasses(tmp_path):
    f = Found(harness="codex", id="t-old", name="x", cwd=str(tmp_path), state="recent", when=0, title="invoices")
    link = FakeCodexLink([], [], resume={"approvalPolicy": "on-request", "sandbox": {"type": "workspaceWrite"}, "thread": {}})
    body = asyncio.run(Codex(link).reopen(f, ""))
    assert ("thread/resume", {"threadId": "t-old", "excludeTurns": True}) in link.calls
    assert body["id"] == "t-old" and body["harness_data"]["title"] == "invoices"
    link = FakeCodexLink([], [], resume={"approvalPolicy": "never", "sandbox": {"type": "dangerFullAccess"}})
    with pytest.raises(StartError, match="no approvals and no sandbox"):
        asyncio.run(Codex(link).reopen(f, ""))
    link = FakeCodexLink([], [], resume=RpcError("thread has an active writer"))
    with pytest.raises(StartError, match="plain `codex`"):
        asyncio.run(Codex(link).reopen(f, ""))


# ---------- OpenCode (/api/session, /api/session/active) ----------

class FakeOpenCode:
    def __init__(self, sessions, active):
        self.sessions, self.active = sessions, active

    async def call(self, method, path, body=None, timeout=15):
        if path.startswith("/api/session?"):
            return {"data": self.sessions}
        if path == "/api/session/active":
            return {"data": {sid: {} for sid in self.active}}
        raise LookupError(path)

    def forget_url(self):
        pass


def test_opencode_lists_active_and_fresh_sessions_as_open_and_older_ones_as_recent(tmp_path):
    now_ms = time.time() * 1000
    rows = [{"id": "ses_a", "title": "docs pass", "location": {"directory": str(tmp_path)}, "time": {"updated": now_ms - 3 * 86400e3}},
            {"id": "ses_b", "title": "", "location": {"directory": str(tmp_path)}, "time": {"updated": now_ms - 60e3}},
            {"id": "ses_c", "title": "old", "location": {"directory": str(tmp_path)}, "time": {"updated": now_ms - 3 * 86400e3}},
            {"id": "ses_child", "parentID": "ses_b", "location": {"directory": str(tmp_path)}, "time": {"updated": now_ms}}]
    found = asyncio.run(OpenCode(FakeOpenCode(rows, ["ses_a"])).discover(time.time() - 7 * 86400, 40))
    assert [(f.id, f.state) for f in found] == [("ses_a", "open"), ("ses_b", "open"), ("ses_c", "recent")]
    assert found[0].name == "docs pass" and found[1].name == tmp_path.name
    body = OpenCode(FakeOpenCode(rows, [])).attach_body(found[2])
    assert body["id"] == "ses_c" and body["cwd"] == str(tmp_path) and body["transcript"].endswith("ses_c.jsonl")


# ---------- across machines ----------

def test_the_link_carries_discover_and_attach_frames():
    assert nodelink.decode(nodelink.encode("discover", req="r1", since=1.0, cap=40), nodelink.HUB_FRAMES)
    assert nodelink.decode(nodelink.encode("attach", req="r1", harness="codex", id="t1", reopen=True), nodelink.HUB_FRAMES)
    assert nodelink.decode(nodelink.encode("discovered", req="r1", found=[{"id": "x"}]), nodelink.NODE_FRAMES)
    assert nodelink.decode(nodelink.encode("attach.result", req="r1", ok=False, why="gone"), nodelink.NODE_FRAMES)


def test_a_record_from_a_node_keeps_only_known_fields_cut_to_size():
    raw = {"harness": "claude-code", "id": "abc", "name": "n" * 500, "cwd": "/w/x", "state": "open", "when": 5,
           "first": "y" * 1000, "keywords": ["a", 3, "b"], "socket": "/tmp/evil.sock", "home": "/Users/other/.claude",
           "transcript": "/etc/passwd", "approvals": False}
    f = Found.from_dict(raw)
    assert len(f.name) == 80 and len(f.first) == discovery.TEXT_CHARS and f.keywords == ["a", "b"]
    assert f.socket == "" and f.home == "" and f.transcript == "" and f.approvals is False
    assert Found.from_dict({"id": "x"}) is None


def test_a_node_sends_the_hub_no_path_socket_or_account_of_a_session_off_the_voice():
    import node

    assert not {"socket", "home", "transcript", "data", "pid"} & set(node.Node._SHARED)


def test_spoken_ages():
    now = time.mktime((2026, 11, 23, 15, 0, 0, 0, 0, -1))
    assert discovery.ago(now - 30, now) == "just now"
    assert discovery.ago(now - 600, now) == "10 minutes ago"
    assert discovery.ago(now - 3 * 3600, now) == "3 hours ago"
    assert discovery.ago(now - 86400, now) == "from yesterday"
    assert discovery.ago(now - 3 * 86400, now).startswith("from ")
