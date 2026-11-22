"""Starting a new coding-agent session from Pointe (docs/design/new-session.md).

What the user's words ask for, where a session may start, the read-back and the yes it is bound to, what is never
started (a session that skips its permission prompts, a folder the user does not work in, another machine), and each
harness's starter against a fake at its process or API seam. Nothing here starts a real agent or opens a window.

uv run --locked pytest -q tests/test_new_session.py
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harnesses  # noqa: E402
import harnesses.claude_code as claude_code  # noqa: E402
import newsession  # noqa: E402
from guards import start_intent, start_request  # noqa: E402
from harnesses.base import StartError, refuse_bypass  # noqa: E402
from harnesses.codex import Codex, bypasses  # noqa: E402
from harnesses.opencode import OpenCode  # noqa: E402
from test_orchestrator import (Params, _consent_setup, add, client_for, d, fake_conn, verdicts)  # noqa: E402,F401

ROOT = Path(__file__).resolve().parents[1]
PLACES = [("shop", "/w/shop"), ("billing", "/w/billing"), ("codex-tools", "/w/codex-tools"), ("pricing", "/w/shop")]


# ---------- what counts as asking ----------

@pytest.mark.parametrize("said", [
    "Start a new Claude Code session in shop.", "open a codex session in billing", "launch another agent here",
    "start an open code session in the billing folder", "run codex in billing", "create a new session",
    "new session in shop", "spin up a session for billing", "start claude code in shop",
    "תפתח סשן חדש של קודקס ב billing", "תתחיל סשן ב shop"])
def test_these_words_ask_for_a_new_session(said):
    assert start_intent(said), said


@pytest.mark.parametrize("said", [
    "Tell shop to start a new session.", "Ask billing to open a new agent thread for the importer.", "start session mode",
    "start a meeting", "start the server in shop", "What is shop doing?", "open the sessions panel", "yes",
    "close the shop session", "run the agent tests in billing"])
def test_these_words_do_not(said):
    assert not start_intent(said), said
    assert start_request(said, PLACES) is None


# ---------- what the words pick ----------

def test_the_agent_the_folder_and_the_name_come_from_the_words():
    ask = start_request("open a codex session in billing called invoices", PLACES)
    assert (ask.harness, ask.folder, ask.name, ask.machine) == ("codex", "/w/billing", "invoices", None)
    ask = start_request("Start a new Claude Code session in shop.", PLACES)
    assert (ask.harness, ask.folder, ask.name) == ("claude-code", "/w/shop", None)
    ask = start_request("start an open code session in the billing folder", PLACES)
    assert (ask.harness, ask.folder) == ("opencode", "/w/billing")


def test_a_session_on_the_voice_names_its_folder():
    assert start_request("start a session where pricing is", PLACES).folder == "/w/shop"


def test_no_agent_said_is_none_and_two_agents_is_a_question():
    assert start_request("start a session in shop", PLACES).harness is None
    two = start_request("start a claude session and a codex session in shop", PLACES)
    assert two.harness is None and set(two.harnesses) == {"claude-code", "codex"}


def test_an_agents_name_inside_a_folders_name_is_the_folder():
    ask = start_request("start a session in codex-tools", PLACES)
    assert ask.folder == "/w/codex-tools" and ask.harness is None


def test_a_name_two_folders_answer_to_is_a_tie_never_a_guess():
    ask = start_request("start a session in shop", PLACES + [("shop", "/x/elsewhere/shop")])
    assert ask.folder is None and set(ask.ties) == {"/w/shop", "/x/elsewhere/shop"}


def test_a_folder_that_is_not_in_the_list_cannot_be_said():
    for said in ("start a session in /etc", "start a claude code session in slash users slash root", "open a session in payroll"):
        ask = start_request(said, PLACES)
        assert ask is not None and ask.folder is None and not ask.ties, said


def test_here_means_the_active_sessions_folder_only_when_given():
    assert start_request("launch another agent here", PLACES, here_folder="/w/billing").folder == "/w/billing"
    assert start_request("launch another agent here", PLACES).folder is None


def test_this_mac_and_another_machine_are_told_apart():
    assert start_request("start a session in shop on studio", PLACES, ["devbox"], "studio").machine == ""
    assert start_request("start a session in shop on this Mac", PLACES, ["devbox"], "studio").machine == ""
    assert start_request("run codex in billing on devbox", PLACES, ["devbox"], "studio").machine == "devbox"
    assert start_request("start a session in shop", PLACES, ["devbox"], "studio").machine is None


def test_a_given_name_ends_where_the_folder_begins():
    ask = start_request("new session named fix login in billing", PLACES)
    assert ask.name == "fix login" and ask.folder == "/w/billing"


# ---------- where a session may start ----------

def _folder(tmp_path, name: str) -> str:
    path = tmp_path / name
    path.mkdir(parents=True, exist_ok=True)
    return newsession.real(str(path))


def test_the_list_is_current_recent_and_added_folders_that_exist(tmp_path):
    shop, billing, docs = _folder(tmp_path, "shop"), _folder(tmp_path, "billing"), _folder(tmp_path, "docs")
    recent = newsession.Recent(tmp_path / "folders.json")
    recent.note(billing)
    recent.note(str(tmp_path / "gone"))  # joined from once, deleted since
    sessions = [SimpleNamespace(cwd=shop, machine="", name="shop"), SimpleNamespace(cwd="/srv/app", machine="devbox", name="app")]
    got = newsession.allowed(sessions, recent, [docs, shop])
    assert [(f["name"], f["source"]) for f in got] == [("shop", "session"), ("billing", "recent"), ("docs", "added")]
    assert newsession.find(shop, got) and newsession.find(str(tmp_path / "gone"), got) is None
    assert newsession.find("/etc", got) is None and newsession.find("", got) is None and newsession.find(None, got) is None


def test_recent_folders_are_kept_between_runs_and_forgotten_after_a_month(tmp_path):
    billing = _folder(tmp_path, "billing")
    newsession.Recent(tmp_path / "folders.json").note(billing, now=time.time() - 40 * 24 * 3600)
    assert newsession.Recent(tmp_path / "folders.json").folders() == []
    newsession.Recent(tmp_path / "folders.json").note(billing)
    assert newsession.Recent(tmp_path / "folders.json").folders() == [billing]
    assert (tmp_path / "folders.json").stat().st_mode & 0o777 == 0o600


def test_a_path_through_a_link_is_the_folder_it_leads_to(tmp_path):
    shop = _folder(tmp_path, "shop")
    (tmp_path / "alias").symlink_to(shop)
    got = newsession.allowed([SimpleNamespace(cwd=str(tmp_path / "alias"), machine="", name="shop")],
                             newsession.Recent(tmp_path / "f.json"), [])
    assert [f["path"] for f in got] == [shop]


@pytest.mark.parametrize("value, ok", [([], True), (["/w/shop", "~/work"], True), (["relative/path"], False), (["/"], False),
                                       ("/w/shop", False), ([1], False), (["/a"] * 51, False)])
def test_the_added_folders_setting_takes_only_a_short_list_of_absolute_paths(value, ok):
    assert newsession.valid_folders(value) is ok


# ---------- never a session that skips its prompts ----------

@pytest.mark.parametrize("parts", [["claude", "--dangerously-skip-permissions"], ["--permission-mode", "bypassPermissions"],
                                   ['{"sandbox": "danger-full-access"}'], ["claude", "--allow-dangerously-skip-permissions"]])
def test_a_starter_that_would_bypass_is_refused(parts):
    with pytest.raises(StartError):
        refuse_bypass(*parts)


def test_claude_code_starts_in_its_default_mode_and_never_with_a_skip_flag(tmp_path):
    argv = claude_code.start_argv("shop-2", tmp_path / "s.json")
    assert argv[1:3] == ["--permission-mode", "default"]
    assert not any("dangerously" in a or "bypass" in a for a in argv)


def test_a_codex_thread_that_would_never_ask_outside_a_sandbox_is_a_bypass():
    assert bypasses({"approvalPolicy": "never", "sandbox": {"type": "dangerFullAccess"}})
    assert not bypasses({"approvalPolicy": "on-request", "sandbox": {"type": "dangerFullAccess"}})
    assert not bypasses({"approvalPolicy": "never", "sandbox": {"type": "workspaceWrite"}})
    assert not bypasses({"approvalPolicy": "on-request", "sandbox": {"type": "workspaceWrite"}})


# ---------- each harness's starter, against a fake ----------

def test_claude_code_opens_a_terminal_on_a_script_that_joins_by_its_hook(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(harnesses.HOST, "state_dir", tmp_path)
    monkeypatch.setattr(harnesses.HOST, "port", 7999, raising=False)
    monkeypatch.setattr(claude_code, "open_terminal", opened.append)
    monkeypatch.setattr(claude_code.sys, "platform", "darwin")
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: f"/opt/bin/{name}")
    folder = _folder(tmp_path, "my shop")  # a space in the path must survive the shell
    assert asyncio.run(harnesses.get("claude-code").start(folder, "shop-2", "abc123")) is None  # it registers itself
    script = opened[0]
    text = script.read_text()
    assert script.suffix == ".command" and script.stat().st_mode & 0o777 == 0o700
    assert f"cd '{folder}' || exit 1" in text
    assert "exec /opt/bin/claude --permission-mode default --name shop-2 --settings " in text
    assert f"CLAUDE_VOICE_STATE={tmp_path}" in text and "CLAUDE_VOICE_DAEMON_PORT=7999" in text
    assert "dangerously" not in text and "bypass" not in text
    settings = json.loads((tmp_path / "starts" / "abc123.json").read_text())
    hook = settings["hooks"]["SessionStart"][0]
    assert hook["matcher"] == "startup"  # a /clear or /resume later never registers it again
    assert hook["hooks"][0]["command"] == f"{ROOT}/bin/register-session --quiet --name shop-2 --start abc123"
    assert subprocess.run(["sh", "-n", str(script)]).returncode == 0  # the shell can read it
    assert "token" not in text.lower() and "token" not in json.dumps(settings).lower()  # no secret in either file


def test_claude_code_is_not_started_where_no_terminal_can_open_or_it_is_missing(monkeypatch):
    adapter = harnesses.get("claude-code")
    monkeypatch.setattr(claude_code.sys, "platform", "linux")
    assert "only on a Mac" in adapter.can_start()
    monkeypatch.setattr(claude_code.sys, "platform", "darwin")
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: None)
    assert adapter.can_start() == "Claude Code is not installed on this Mac."
    with pytest.raises(StartError, match="not installed"):
        asyncio.run(adapter.start("/tmp", "shop", "x"))


def test_a_terminal_that_does_not_open_is_a_failure_with_words(tmp_path, monkeypatch):
    def fail(_script):
        raise subprocess.CalledProcessError(1, "open")

    monkeypatch.setattr(harnesses.HOST, "state_dir", tmp_path)
    monkeypatch.setattr(claude_code, "open_terminal", fail)
    monkeypatch.setattr(claude_code.sys, "platform", "darwin")
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: f"/opt/bin/{name}")
    with pytest.raises(StartError, match="could not open a terminal"):
        asyncio.run(harnesses.get("claude-code").start(_folder(tmp_path, "shop"), "shop", "x1"))


def test_the_register_script_passes_the_start_id(tmp_path):
    """bin/register-session --start: the id reaches the daemon in the body. A fake curl on PATH records what was sent."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "curl").write_text('#!/bin/sh\ncat > "$OUT"\necho \'{"name": "shop-2"}\'\n')
    (fake_bin / "curl").chmod(0o755)
    (tmp_path / "token").write_text("t")
    hook = json.dumps({"session_id": "sess-1", "transcript_path": "/tmp/none.jsonl"})
    env = {"PATH": f"{fake_bin}:/usr/bin:/bin", "HOME": str(tmp_path), "CLAUDE_VOICE_STATE": str(tmp_path),
           "OUT": str(tmp_path / "body.json"), "CLAUDE_PID": "4242", "CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/sock"}
    done = subprocess.run([str(ROOT / "bin" / "register-session"), "--quiet", "--name", "shop-2", "--start", "abc123"],
                          input=hook, text=True, capture_output=True, env=env, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    body = json.loads((tmp_path / "body.json").read_text())
    assert body["start"] == "abc123" and body["name"] == "shop-2" and body["name_given"] and body["pid"] == 4242
    assert body["id"] == "sess-1" and body["inbox_socket"] == "/tmp/sock"


class FakeService:
    def __init__(self, answer=None, error=None):
        self.calls, self.answer, self.error = [], answer, error

    async def call(self, method, path, body=None, timeout=15):
        self.calls.append((method, path, body))
        if self.error:
            raise self.error
        return self.answer

    def forget_url(self):
        pass


def test_opencode_creates_a_session_in_the_folder_with_no_permission_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(harnesses.HOST, "state_dir", tmp_path)
    service = FakeService({"data": {"id": "ses_new1", "title": "shop-2"}})
    body = asyncio.run(OpenCode(service).start("/w/shop", "shop-2", "x"))
    assert service.calls == [("POST", "/api/session", {"location": {"directory": "/w/shop"}, "title": "shop-2"})]
    assert body["id"] == "ses_new1" and body["cwd"] == "/w/shop" and body["name"] == "shop-2" and body["name_given"]
    assert body["transcript"].endswith("harness/opencode/ses_new1.jsonl")


@pytest.mark.parametrize("error, words", [(ConnectionError("down"), "service is not running"),
                                          (FileNotFoundError("opencode"), "not installed")])
def test_opencode_failures_have_words(monkeypatch, error, words):
    monkeypatch.setattr("harnesses.opencode.shutil.which", lambda name: None)
    with pytest.raises(StartError, match=words):
        asyncio.run(OpenCode(FakeService(error=error)).start("/w/shop", "shop", "x"))


class FakeLink:
    def __init__(self, started=None, error=None):
        self.calls, self.started, self.error = [], started, error
        self.listeners, self.reconnected, self.down_since, self.up = [], [], None, True

    async def ensure(self):
        if self.error:
            raise self.error

    async def request(self, method, params, timeout=30):
        self.calls.append((method, params))
        return self.started if method == "thread/start" else {}


SAFE = {"thread": {"id": "thr_new1"}, "approvalPolicy": "on-request", "sandbox": {"type": "workspaceWrite"}}


def test_codex_starts_a_thread_in_the_folder_with_no_policy_of_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(harnesses.HOST, "state_dir", tmp_path)
    link = FakeLink(SAFE)
    body = asyncio.run(Codex(link).start("/w/shop", "shop-2", "x"))
    assert link.calls == [("thread/start", {"cwd": "/w/shop"}), ("thread/name/set", {"threadId": "thr_new1", "name": "shop-2"})]
    assert body["id"] == "thr_new1" and body["cwd"] == "/w/shop" and body["name"] == "shop-2"


def test_a_codex_thread_that_bypasses_is_archived_and_never_joined():
    link = FakeLink({"thread": {"id": "thr_wild"}, "approvalPolicy": "never", "sandbox": {"type": "dangerFullAccess"}})
    with pytest.raises(StartError, match="never starts a session that skips"):
        asyncio.run(Codex(link).start("/w/shop", "shop", "x"))
    assert link.calls == [("thread/start", {"cwd": "/w/shop"}), ("thread/archive", {"threadId": "thr_wild"})]


def test_codex_with_no_daemon_says_how_to_start_it():
    with pytest.raises(StartError, match="codex app-server daemon start"):
        asyncio.run(Codex(FakeLink(error=ConnectionRefusedError())).start("/w/shop", "shop", "x"))


def test_every_harness_that_starts_says_how_to_open_it_or_is_a_terminal_already():
    s = SimpleNamespace(id="abc")
    assert harnesses.get("claude-code").open_hint(s) == ""
    assert harnesses.get("opencode").open_hint(s) == "opencode --session abc"
    assert harnesses.get("codex").open_hint(s) == "codex resume abc --remote unix://"


# ---------- the daemon: read-back, yes, start, join ----------

@pytest.fixture
def home(d, tmp_path, monkeypatch):
    """Two sessions on the voice, in folders that exist, and starters that record instead of starting."""
    monkeypatch.setattr(d, "RECENT_FOLDERS", newsession.Recent(tmp_path / "folders.json"))
    monkeypatch.setattr(d, "STARTS", {})
    monkeypatch.setattr(d, "PREFS", d.Prefs(tmp_path / "prefs.json"))
    monkeypatch.setattr(d, "_here", lambda: "studio")
    monkeypatch.setattr(d, "paired_machines", lambda: [])  # another test's machines stay in sessions.MACHINES
    shop, billing = _folder(tmp_path, "shop"), _folder(tmp_path, "billing")
    add(d, "s1", "shop", cwd=shop)
    add(d, "s2", "billing", cwd=billing)
    d.REGISTRY.set_active("s1")
    started = []

    def starter(harness, body=True):
        async def start(cwd, name, start_id):
            started.append((harness, cwd, name, start_id))
            return {"id": f"new-{len(started)}", "name": name, "name_given": True, "cwd": cwd, "pid": os.getpid(),
                    "transcript": "/tmp/none.jsonl"} if body else None
        return start

    for name in ("claude-code", "opencode", "codex"):
        adapter = harnesses.get(name)
        monkeypatch.setattr(adapter, "can_start", lambda: None)
        monkeypatch.setattr(adapter, "start", starter(name, body=name != "claude-code"))
    sent = []

    async def deliver(session, text):
        sent.append((session.name, text))
        return True

    monkeypatch.setattr(d, "deliver", deliver)
    return SimpleNamespace(d=d, shop=shop, billing=billing, started=started, sent=sent, tmp=tmp_path)


async def _ask(d, said: str | None, heard_own_words: bool = False) -> dict:
    """The user said `said` (None: nothing new), then the model called start_session."""
    if said is not None:
        await d.on_user_utterance(said)
        d.state.heard_own_words = heard_own_words
    p = Params(folder="whatever the model wrote")
    await d.start_session(p)
    return p.results[0]


async def _settle(d, secs: float = 0.5) -> None:
    deadline = time.time() + secs
    while time.time() < deadline and any(s.state == "starting" for s in d.STARTS.values()):
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.02)


def test_a_request_is_read_back_exactly_and_nothing_starts(home):
    result = asyncio.run(_ask(home.d, "Start a new Codex session in shop."))
    assert result["confirm_first"] == "Start a Codex session in shop on studio, named shop-2? Say yes or tap.", result
    assert home.started == [] and not home.d.STARTS


def test_no_agent_said_means_claude_code_and_the_read_back_says_so(home):
    result = asyncio.run(_ask(home.d, "open a new session in billing called invoices"))
    assert result["confirm_first"] == "Start a Claude Code session in billing on studio, named invoices? Say yes or tap."


def test_a_name_that_differs_only_by_a_branch_counts_as_taken(home):
    """ "shop" beside "shop/main" would get a suffix when it joins: the read-back already says the name it will have."""
    d = home.d
    d.REGISTRY.rename("s1", "shop/main")
    result = asyncio.run(_ask(d, "start a codex session in shop"))
    assert "named shop-2?" in result["confirm_first"], result

    async def scenario():
        await _ask(d, "yes")
        await _settle(d)

    asyncio.run(scenario())
    assert "shop-2" in [s.name for s in d.REGISTRY.sessions.values()]


def test_an_open_code_session_takes_an(home):
    result = asyncio.run(_ask(home.d, "start an open code session in billing"))
    assert result["confirm_first"].startswith("Start an OpenCode session in billing on studio, named billing-2?")


@pytest.mark.parametrize("yes", ["Yes.", "go ahead", "כן"])
def test_a_plain_yes_starts_what_was_read_back_and_it_joins_by_that_name(home, yes):
    d = home.d

    async def scenario():
        await _ask(d, "Start a new Codex session in shop.")
        done = await _ask(d, yes)
        await _settle(d)
        return done

    done = asyncio.run(scenario())
    assert done["starting"] == "shop-2", done
    assert [(h, cwd, name) for h, cwd, name, _ in home.started] == [("codex", home.shop, "shop-2")]
    joined = next(s for s in d.REGISTRY.sessions.values() if s.name == "shop-2")
    assert joined.harness == "codex" and joined.named_by == "user" and joined.cwd == home.shop
    assert d.REGISTRY.active.name == "shop"  # starting one does not move the conversation
    assert home.sent == []  # by voice there is no first prompt


@pytest.mark.parametrize("said", ["Start a new codec session in shop.", "start a new codecs session in shop"])
def test_codex_misheard_as_codec_is_still_codex(home, said):
    """From a live run: the ears wrote "codec" for "Codex", and the start was refused as not asked."""
    result = asyncio.run(_ask(home.d, said))
    assert result.get("confirm_first", "").startswith("Start a Codex session in shop"), result


def test_the_ears_are_told_the_agents_names(d):
    assert {"Codex", "OpenCode", "Claude Code"} <= set(d._recognition_terms({}))


def test_a_yes_to_the_voices_own_offer_to_start_is_read_back_first(home):
    """From a live run: the voice asked "Do you want a new Codex session in shop?", the user said yes, and the start was
    refused twice as not asked. The yes asks for what the voice offered; the read-back still comes before anything starts."""
    d = home.d

    async def scenario():
        await d.on_user_utterance("Can you get me another agent going?")
        d.state.conversation.append(("assistant", "Do you want a new Codex session in shop?"))
        return await _ask(d, "Yes.")

    result = asyncio.run(scenario())
    assert result.get("confirm_first", "").startswith("Start a Codex session in shop"), result
    assert home.started == []


def test_a_yes_to_anything_else_starts_nothing(home):
    d = home.d

    async def scenario():
        await d.on_user_utterance("What is shop doing?")
        d.state.conversation.append(("assistant", "Shop is running its tests. Want me to check billing too?"))
        return await _ask(d, "Yes.")

    assert "error" in asyncio.run(scenario()) and home.started == []


async def _rename(d, said: str, new_name: str) -> dict:
    await d.on_user_utterance(said)
    p = Params(new_name=new_name)
    await d.rename_session(p)
    return p.results[0]


def test_rename_it_right_after_a_start_renames_the_new_session_not_the_active_one(home):
    """"Start a new Codex session in shop", yes, then "rename it to shop-tests": "it" is the session that just started."""
    d = home.d

    async def scenario():
        await _ask(d, "Start a new Codex session in shop.")
        await _ask(d, "Yes.")
        await _settle(d)
        return await _rename(d, "Rename it to shop-tests.", "shop-tests")

    result = asyncio.run(scenario())
    assert result == {"renamed": "shop-2", "to": "shop-tests"}, result

    again = asyncio.run(_rename(d, "No, rename it to shop-e2e.", "shop-e2e"))
    assert again == {"renamed": "shop-tests", "to": "shop-e2e"}, again
    assert sorted(s.name for s in d.REGISTRY.sessions.values()) == ["billing", "shop", "shop-e2e"]
    assert d.REGISTRY.active.name == "shop"  # renaming it does not move the conversation either


def test_after_a_switch_it_is_the_session_switched_to_again(home):
    d = home.d

    async def scenario():
        await _ask(d, "Start a new Codex session in shop.")
        await _ask(d, "Yes.")
        await _settle(d)
        d.state.last_switch_at = 0.0  # the rename below must see fresh words
        await d.activate(d.REGISTRY.sessions["s2"])
        await asyncio.sleep(0.01)
        return await _rename(d, "Rename it to invoices.", "invoices")

    result = asyncio.run(scenario())
    assert result == {"renamed": "billing", "to": "invoices"}, result


@pytest.mark.parametrize("answer", ["no", "wait, not that one", "what is billing doing?", "hmm"])
def test_anything_but_a_plain_yes_starts_nothing(home, answer):
    async def scenario():
        await _ask(home.d, "Start a new Codex session in shop.")
        return await _ask(home.d, answer)

    result = asyncio.run(scenario())
    assert "error" in result and home.started == [] and home.d.state.pending_start is None


def test_the_models_arguments_start_nothing_the_user_did_not_ask_for(home):
    for said in ("What is shop doing?", "Tell shop to start a new session for the importer.", "yes"):
        result = asyncio.run(_ask(home.d, said))
        assert "error" in result and home.started == [] and home.d.state.pending_start is None, said


def test_the_read_back_heard_back_and_typed_words_are_not_a_yes(home):
    async def scenario():
        await _ask(home.d, "Start a new Codex session in shop.")
        return await _ask(home.d, "yes", heard_own_words=True)

    assert "error" in asyncio.run(scenario()) and home.started == []


def test_a_yes_long_after_the_read_back_starts_nothing(home):
    d = home.d

    async def scenario():
        await _ask(d, "Start a new Codex session in shop.")
        d.state.pending_start = (d.state.pending_start[0] - newsession.CONFIRM_SECS - 1, d.state.pending_start[1])
        return await _ask(d, "yes")

    assert "error" in asyncio.run(scenario()) and home.started == []


def test_the_model_calling_again_before_the_answer_starts_nothing(home):
    async def scenario():
        await _ask(home.d, "Start a new Codex session in shop.")
        return await _ask(home.d, None)

    result = asyncio.run(scenario())
    assert "Nothing started yet" in result["error"] and home.started == [] and home.d.state.pending_start is not None


def test_with_the_voice_lock_on_only_the_owners_yes_starts(home, monkeypatch):
    d = home.d
    monkeypatch.setattr(d, "lock_level", lambda: "approvals")
    monkeypatch.setattr(d.VOICE, "confident", lambda verdict: False)

    async def scenario():
        await _ask(d, "Start a new Codex session in shop.")
        return await _ask(d, "yes")

    result = asyncio.run(scenario())
    assert "owner's voice" in result["error"] and home.started == []


def test_the_yes_to_a_read_back_never_approves_a_waiting_prompt(d, monkeypatch, tmp_path):
    active, posts = _consent_setup(d, monkeypatch)
    monkeypatch.setattr(d, "RECENT_FOLDERS", newsession.Recent(tmp_path / "folders.json"))
    monkeypatch.setattr(d, "STARTS", {})
    shop = _folder(tmp_path, "shop")
    add(d, "s9", "shop", cwd=shop)
    started = []

    async def start(cwd, name, start_id):
        started.append(name)
        return {"id": "new-1", "name": name, "name_given": True, "cwd": cwd, "pid": os.getpid(), "transcript": "/tmp/none.jsonl"}

    monkeypatch.setattr(harnesses.get("codex"), "can_start", lambda: None)
    monkeypatch.setattr(harnesses.get("codex"), "start", start)

    async def scenario():
        await _ask(d, "start a codex session in shop")
        d.state.conn.injector.bot_started_at = time.time()  # the read-back is spoken
        await _ask(d, "yes")
        await _settle(d)

    asyncio.run(scenario())
    assert verdicts(posts) == [] and active.permission_id == "p1"
    assert started == ["shop-2"]


def test_a_folder_the_words_do_not_name_is_asked_for_from_the_list(home):
    result = asyncio.run(_ask(home.d, "start a new codex session in payroll"))
    assert "error" in result and "shop" in result["error"] and "billing" in result["error"], result
    assert home.d.state.pending_start is None


def test_another_machine_is_refused_in_one_line(home, monkeypatch):
    monkeypatch.setattr(home.d, "paired_machines", lambda: [SimpleNamespace(name="devbox", online=True)])
    result = asyncio.run(_ask(home.d, "start a codex session in shop on devbox"))
    assert "only on this Mac" in result["error"] and home.started == []


def test_a_name_that_cannot_be_used_is_refused_with_why(home):
    for said, why in (("start a codex session in shop called billing", "already called"),
                      ("start a codex session in shop called yes", "yes or no"),
                      ("start a codex session in shop called dev", "cannot be used")):
        result = asyncio.run(_ask(home.d, said))
        assert why in result["error"], (said, result)
        home.d.state.last_start_at = 0


def test_meeting_and_challenge_modes_cannot_start_a_session():
    import modes

    assert "start_session" not in modes.READ_ONLY_TOOLS
    for mode in (modes.MEETING_LISTENING, modes.MEETING_PARTICIPATING, modes.CHALLENGE):
        assert not mode.allows_tool("start_session")


def test_the_brain_has_the_tool_and_is_told_to_read_back(d):
    tool = next(t for t in d.TOOLS.standard_tools if t.name == "start_session")
    assert "confirm_first" in tool.description
    assert "start_session" in d.INSTRUCTIONS


# ---------- the sheet's Start button, the card's tap, the status ----------

def test_the_sheet_is_offered_agents_machines_and_only_the_allowed_folders(home):
    got = client_for(home.d).get("/voice/new-session").json()
    assert [h["name"] for h in got["harnesses"]] == ["claude-code", "opencode", "codex"]
    assert all(h["available"] for h in got["harnesses"]) and got["harnesses"][0]["title"] == "Claude Code"
    assert got["machines"] == [{"name": "studio", "here": True, "available": True, "why": None}]
    assert sorted(f["path"] for f in got["folders"]) == sorted([home.shop, home.billing])


def test_start_from_the_sheet_sends_the_first_prompt_only_after_it_joined(home):
    d = home.d
    order = []
    original = d._join

    async def join(body):
        order.append("joined")
        return await original(body)

    async def deliver(session, text):
        order.append("prompt")
        home.sent.append((session.name, text))
        return True

    d._join, d.deliver = join, deliver
    try:
        async def scenario():
            from httpx import ASGITransport, AsyncClient

            async with AsyncClient(transport=ASGITransport(app=d.app), base_url="http://127.0.0.1:7860",
                                   cookies={"pointe_local": d.PAGE_KEY}) as client:
                r = await client.post("/voice/new-session", json={"harness": "opencode", "folder": home.billing,
                                                                  "name": "invoices", "prompt": "List the open invoices."})
                await _settle(d)
                return r, (await client.get("/voice/status")).json()

        r, status = asyncio.run(scenario())
    finally:
        d._join = original
    assert r.status_code == 200 and r.json()["name"] == "invoices", r.text
    assert order == ["joined", "prompt"] and home.sent == [("invoices", "List the open invoices.")]
    assert status["starting"] == [] and "invoices" in [s["name"] for s in status["sessions"]]


@pytest.mark.parametrize("folder", ["/etc", "/", "", "../..", "/tmp/not-a-folder-anyone-works-in"])
def test_a_folder_outside_the_list_is_refused_whoever_asks(home, folder):
    r = client_for(home.d).post("/voice/new-session", json={"harness": "codex", "folder": folder})
    assert r.status_code == 403 and "not one you already work in" in r.json()["detail"]
    assert home.started == [] and not home.d.STARTS


def test_a_child_of_an_allowed_folder_is_not_allowed(home):
    inner = _folder(Path(home.shop), "secrets")
    assert client_for(home.d).post("/voice/new-session", json={"harness": "codex", "folder": inner}).status_code == 403


def test_bad_requests_from_the_sheet_have_reasons(home, monkeypatch):
    client = client_for(home.d)
    assert client.post("/voice/new-session", json={"harness": "gemini", "folder": home.shop}).status_code == 400
    assert client.post("/voice/new-session", json={"harness": "codex", "folder": home.shop, "machine": "devbox"}).status_code == 409
    assert client.post("/voice/new-session", json={"harness": "codex", "folder": home.shop, "name": "billing"}).status_code == 409
    assert client.post("/voice/new-session", json={"harness": "codex", "folder": home.shop, "name": "<b>"}).status_code == 400
    long = client.post("/voice/new-session", json={"harness": "codex", "folder": home.shop, "prompt": "x" * 4001})
    assert long.status_code == 400 and "too long" in long.json()["detail"]
    monkeypatch.setattr(harnesses.get("codex"), "can_start", lambda: "Codex is not installed on this Mac.")
    missing = client.post("/voice/new-session", json={"harness": "codex", "folder": home.shop})
    assert missing.status_code == 409 and missing.json()["detail"] == "Codex is not installed on this Mac."
    assert home.started == []


def test_a_start_that_fails_shows_its_reason_and_is_said_on_a_call(home, monkeypatch):
    d = home.d

    async def start(cwd, name, start_id):
        raise StartError("OpenCode's service is not running. Open OpenCode, or run `opencode service start`, and try again.")

    monkeypatch.setattr(harnesses.get("opencode"), "start", start)
    said = []

    async def say(text):
        said.append(text)

    monkeypatch.setattr(d, "say", say)
    d.state.conn = fake_conn()

    async def scenario():
        d.begin_start(d._check_start("opencode", home.shop, None), "page")
        await _settle(d)

    asyncio.run(scenario())
    row = d.newsession.shown(d.STARTS)[0].view("OpenCode")
    assert row["state"] == "failed" and "service is not running" in row["detail"] and row["name"] == "shop-2"
    assert said and "did not start" in said[0] and "service is not running" in said[0]
    assert len(d.REGISTRY.sessions) == 2


def test_a_folder_deleted_before_the_start_is_a_failure_not_a_crash(home):
    d = home.d

    async def scenario():
        what = d._check_start("codex", home.shop, None)
        os.rmdir(home.shop)
        d.begin_start(what, "page")
        await _settle(d)

    asyncio.run(scenario())
    assert [s.detail for s in d.STARTS.values()] == ["Not started: that folder is no longer there."] and home.started == []


def test_claude_code_waits_for_its_own_registration_then_gets_the_prompt(home):
    d = home.d
    client = client_for(d)

    async def scenario():
        start = d.begin_start(d._check_start("claude-code", home.shop, None, "Run the tests."), "page")
        await asyncio.sleep(0.05)
        waiting = start.state, list(home.sent)
        await d._join({"id": "cc-new", "name": "shop-2", "name_given": True, "cwd": home.shop, "pid": os.getpid(),
                       "transcript": "/tmp/none.jsonl", "inbox_socket": "/tmp/s", "start": start.id})
        await asyncio.sleep(0.4)
        return start, waiting

    start, waiting = asyncio.run(scenario())
    assert waiting == ("waiting", [])  # nothing is sent before it is on the voice
    assert start.state == "joined" and home.sent == [("shop-2", "Run the tests.")]
    joined = d.REGISTRY.sessions["cc-new"]
    assert joined.joining is False  # it joined from a hook, not inside a turn: its first turn is news
    assert client.get("/voice/status").json()["starting"] == []


def test_claude_code_that_never_joins_fails_and_says_the_prompt_was_not_sent(home, monkeypatch):
    d = home.d
    monkeypatch.setattr(d.newsession, "JOIN_SECS", 0.1)

    async def scenario():
        start = d.begin_start(d._check_start("claude-code", home.shop, None, "Run the tests."), "page")
        await asyncio.sleep(0.6)
        late = await d._join({"id": "cc-late", "name": "shop-2", "name_given": True, "cwd": home.shop, "pid": os.getpid(),
                              "transcript": "/tmp/none.jsonl", "start": start.id})
        await asyncio.sleep(0.05)
        return start, late

    start, late = asyncio.run(scenario())
    assert late["name"] == "shop-2" and start.state == "joined"  # it still joins when it comes
    assert home.sent == []  # and the prompt the user was told was not sent stays unsent


def test_a_registration_carrying_a_start_id_from_another_folder_is_not_that_start(home):
    d = home.d

    async def scenario():
        start = d.begin_start(d._check_start("claude-code", home.shop, None, "Run the tests."), "page")
        await asyncio.sleep(0.05)
        await d._join({"id": "cc-x", "name": "other", "cwd": home.billing, "pid": os.getpid(),
                       "transcript": "/tmp/none.jsonl", "start": start.id})
        await asyncio.sleep(0.05)
        return start

    assert asyncio.run(scenario()).state == "waiting" and home.sent == []


def test_a_tap_on_the_card_starts_exactly_what_was_read_back_and_cancel_drops_it(home):
    d = home.d
    client = client_for(d)

    async def read_back():
        return await _ask(d, "Start a new Codex session in shop.")

    asyncio.run(read_back())
    pending = client.get("/voice/status").json()["start_pending"]
    assert pending["line"].startswith("Start a Codex session in shop") and pending["name"] == "shop-2"
    assert client.post("/voice/new-session", json={"confirm": "not-the-id"}).status_code == 409
    assert client.post("/voice/new-session", json={"cancel": pending["id"]}).json() == {"cancelled": True}
    assert client.get("/voice/status").json()["start_pending"] is None
    assert client.post("/voice/new-session", json={"confirm": pending["id"]}).status_code == 409  # cancelled: gone
    assert home.started == []
    d.state.last_start_at = 0
    asyncio.run(read_back())
    again = client.get("/voice/status").json()["start_pending"]
    assert client.post("/voice/new-session", json={"confirm": again["id"]}).json()["name"] == "shop-2"


def test_the_folders_setting_is_changed_only_at_the_mac(home, monkeypatch):
    d = home.d
    docs = _folder(home.tmp, "docs")
    client = client_for(d)
    monkeypatch.setattr(d, "_off_the_mac", lambda request: True)
    refused = client.post("/voice/prefs", json={"sessions.folders": [docs]})
    assert refused.status_code == 403 and d.PREFS.get("sessions.folders") == []
    monkeypatch.setattr(d, "_off_the_mac", lambda request: False)
    assert client.post("/voice/prefs", json={"sessions.folders": [docs]}).status_code == 200
    assert docs in [f["path"] for f in client.get("/voice/new-session").json()["folders"]]
    assert client.post("/voice/prefs", json={"sessions.folders": ["not/absolute"]}).status_code == 400


def test_a_session_that_joins_makes_its_folder_recent(home):
    d = home.d
    docs = _folder(home.tmp, "docs")
    client_for(d).post("/voice/register", headers={"authorization": "Bearer secret"},
                       json={"id": "j1", "name": "docs", "cwd": docs, "pid": os.getpid(), "transcript": "/tmp/none.jsonl"})
    asyncio.run(d.disconnect(d.REGISTRY.sessions["j1"], "test"))
    assert docs in [f["path"] for f in d._start_folders()]  # it left the voice; its folder is still one the user works in


def test_the_phone_key_reaches_the_new_session_route():
    from guards import _PHONE_PATHS

    assert "/voice/new-session" in _PHONE_PATHS
