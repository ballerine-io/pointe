"""Permissions for new sessions (docs/features/new-session.md, SECURITY.md): a new Claude Code session Pointe starts
skips its permission prompts by default, or asks first by the setting or for one request; the risk is said once; and
Claude Code's one-time check is asked by Pointe, never left in a terminal nobody answers. Nothing here starts a real
agent, opens a window or reads this Mac's Claude Code settings (tests/conftest.py points them at a throwaway folder).

uv run --locked pytest -q tests/test_skip_permissions.py
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harnesses  # noqa: E402
import harnesses.claude_code as claude_code  # noqa: E402
import newsession  # noqa: E402
from guards import asks_first, start_request  # noqa: E402
from harnesses.base import StartError  # noqa: E402
from test_new_session import PLACES, _ask, _folder, _settle, home  # noqa: E402,F401
from test_orchestrator import client_for, d  # noqa: E402,F401

CONFIRM_LINE = (f"Start a Claude Code session in shop, named shop-2, skipping permission prompts? "
                f"{newsession.SKIP_CONFIRM}")


@pytest.fixture
def skip_home(home, tmp_path, monkeypatch):
    """`home` with the setting at its default, and a Claude Code account of its own with nothing accepted yet."""
    home.d.PREFS.values.pop("sessions.permissions", None)
    account = tmp_path / "claude-home"
    account.mkdir()
    monkeypatch.setattr(claude_code, "DEFAULT_HOME", account)
    monkeypatch.setattr(claude_code, "MANAGED_SETTINGS", tmp_path / "managed-settings.json")
    home.account = account
    return home


def _accept_in_claude_code(home) -> None:
    (home.account / "settings.json").write_text(json.dumps({"skipDangerousModePermissionPrompt": True}))


def _sheet(d, body: dict):
    client = client_for(d)
    r = client.post("/voice/new-session", json=body)
    asyncio.run(_settle(d))
    return r, client.get("/voice/status").json()


# ---------- the flag, and nothing else that skips ----------

def test_skip_is_bypass_permissions_said_outright_and_ask_is_the_default_mode(tmp_path):
    skip = claude_code.start_argv("shop-2", tmp_path / "s.json", skip=True)
    ask = claude_code.start_argv("shop-2", tmp_path / "s.json")
    assert skip[1:3] == ["--permission-mode", "bypassPermissions"] and skip[3:] == ask[3:]
    assert ask[1:3] == ["--permission-mode", "default"]
    assert not any("dangerously" in a for a in skip)


def test_a_reopen_never_skips():
    with pytest.raises(StartError, match="default permission mode"):
        claude_code.start_argv("shop", Path("/tmp/s.json"), resume="abc", skip=True)


def test_the_rest_of_a_skipping_command_line_is_still_checked(monkeypatch):
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: "/opt/bin/claude --dangerously-skip-permissions")
    with pytest.raises(StartError, match="never starts a session that skips"):
        claude_code.start_argv("shop", Path("/tmp/s.json"), skip=True)


@pytest.mark.parametrize("name", ["codex", "opencode"])
def test_only_claude_code_skips_and_the_others_refuse_a_caller_that_asks(name):
    adapter = harnesses.get(name)
    assert adapter.skips is False and adapter.skip_check("/tmp") == "off"
    with pytest.raises(StartError, match="never starts a session that skips"):
        asyncio.run(adapter.start("/tmp", "shop", "x", skip=True))


# ---------- the start script: the session's own settings, and the fall back to asking ----------

def _script(tmp_path, monkeypatch, skip: bool, claude: str = "/opt/bin/claude") -> tuple[Path, dict]:
    monkeypatch.setattr(harnesses.HOST, "state_dir", tmp_path / "state")
    monkeypatch.setattr(harnesses.HOST, "port", 7999, raising=False)
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: claude)
    folder = _folder(tmp_path, "my shop")
    script = claude_code.start_script(folder, "shop-2", "abc123", skip=skip)
    return script, json.loads((tmp_path / "state" / "starts" / "abc123.json").read_text())


def test_a_skipping_start_carries_the_yes_and_accepts_the_voice_in_its_own_settings_only(tmp_path, monkeypatch):
    script, settings = _script(tmp_path, monkeypatch, skip=True)
    assert settings["skipDangerousModePermissionPrompt"] is True  # no check in the terminal: the yes was given already
    assert settings["crossSessionInbound"] == "accept"  # else Claude Code holds every request for approval there
    hooks = settings["hooks"]["SessionStart"][0]["hooks"]
    assert hooks[0]["command"].endswith("register-session --quiet --name shop-2 --start abc123")
    assert hooks[1]["command"] == f"touch {tmp_path / 'state' / 'starts' / 'abc123.started'}"
    text = script.read_text()
    assert "/opt/bin/claude --permission-mode bypassPermissions --name shop-2 --settings " in text
    assert "exec /opt/bin/claude --permission-mode default --name shop-2 --settings " in text  # the fall back
    assert subprocess.run(["sh", "-n", str(script)]).returncode == 0
    assert not (tmp_path / "claude-home").exists()  # nothing written to a Claude Code account


def test_an_asking_start_is_as_before(tmp_path, monkeypatch):
    script, settings = _script(tmp_path, monkeypatch, skip=False)
    assert set(settings) == {"hooks"} and len(settings["hooks"]["SessionStart"][0]["hooks"]) == 1
    text = script.read_text()
    assert "exec /opt/bin/claude --permission-mode default --name shop-2" in text and "bypass" not in text


def _fake_claude(tmp_path, starts: bool) -> Path:
    """A `claude` that records its arguments, and starts its session (the SessionStart hook's marker) or ends first."""
    log, fake = tmp_path / "ran.log", tmp_path / "bin" / "claude"
    fake.parent.mkdir(exist_ok=True)
    marker = tmp_path / "state" / "starts" / "abc123.started"
    body = f'echo "$@" >> "{log}"\n'
    if starts:
        body += f'case "$*" in *bypassPermissions*) touch "{marker}" ;; esac\nexit 0\n'
    else:
        body += 'case "$*" in *bypassPermissions*) exit 1 ;; esac\nexit 0\n'
    fake.write_text("#!/bin/sh\n" + body)
    fake.chmod(0o755)
    return fake


@pytest.mark.parametrize("starts", [True, False])
def test_claude_code_that_ends_before_its_session_starts_is_started_again_asking(tmp_path, monkeypatch, starts):
    """A policy Pointe cannot see refuses the mode, or the check came up anyway and was declined: the same terminal
    starts it asking first, at once. A session that started and ended is not started again."""
    fake = _fake_claude(tmp_path, starts)
    script, _ = _script(tmp_path, monkeypatch, skip=True, claude=str(fake))
    done = subprocess.run(["sh", str(script)], capture_output=True, text=True, timeout=20, env={"PATH": "/usr/bin:/bin"})
    runs = (tmp_path / "ran.log").read_text().splitlines()
    assert "bypassPermissions" in runs[0]
    if starts:
        assert len(runs) == 1 and done.returncode == 0
    else:
        assert len(runs) == 2 and "--permission-mode default" in runs[1], runs
        assert "Starting it to ask before actions" in done.stdout


# ---------- detecting Claude Code's one-time check ----------

def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value))


def test_with_nothing_recorded_the_yes_is_needed(skip_home):
    assert claude_code.skip_check(skip_home.account, skip_home.shop) == "confirm"


@pytest.mark.parametrize("where", ["user", "managed"])
def test_a_yes_claude_code_recorded_is_enough(skip_home, where):
    path = skip_home.account / "settings.json" if where == "user" else claude_code.MANAGED_SETTINGS
    _write(path, {"skipDangerousModePermissionPrompt": True})
    assert claude_code.skip_check(skip_home.account, skip_home.shop) == "ok"


@pytest.mark.parametrize("value", [{"skipDangerousModePermissionPrompt": False}, {"skipDangerousModePermissionPrompt": "yes"},
                                   "{not json", ["skipDangerousModePermissionPrompt"]])
def test_anything_but_a_recorded_true_needs_the_yes(skip_home, value):
    _write(skip_home.account / "settings.json", value)
    assert claude_code.skip_check(skip_home.account, skip_home.shop) == "confirm"


def test_a_repositorys_own_yes_does_not_count(skip_home):
    """Claude Code itself does not take it from an untrusted repository; Pointe asks."""
    _write(Path(skip_home.shop) / ".claude" / "settings.local.json", {"skipDangerousModePermissionPrompt": True})
    assert claude_code.skip_check(skip_home.account, skip_home.shop) == "confirm"


@pytest.mark.parametrize("where", ["managed", "user", "settings.json", "settings.local.json"])
def test_a_settings_file_that_turns_the_mode_off_wins(skip_home, where):
    _accept_in_claude_code(skip_home)
    off = {"permissions": {"disableBypassPermissionsMode": "disable"}}
    if where == "managed":
        _write(claude_code.MANAGED_SETTINGS, off)
    elif where == "user":
        _write(skip_home.account / "settings.json", {**off, "skipDangerousModePermissionPrompt": True})
    else:
        _write(Path(skip_home.shop) / ".claude" / where, off)
    assert claude_code.skip_check(skip_home.account, skip_home.shop) == "off"


# ---------- the mode a start takes ----------

def test_the_mode_follows_the_setting_the_request_and_the_harness(skip_home):
    d = skip_home.d
    assert d._start_mode("claude-code", skip_home.shop) == "confirm"
    assert d._start_mode("claude-code", skip_home.shop, ask_first=True) == "ask"
    assert d._start_mode("codex", skip_home.shop) == "ask"
    d.PREFS.update({"sessions.skip_ok": True})
    assert d._start_mode("claude-code", skip_home.shop) == "skip"  # the yes given to Pointe before
    d.PREFS.update({"sessions.permissions": "ask"})
    assert d._start_mode("claude-code", skip_home.shop) == "ask"


# ---------- by voice: the yes Claude Code needs, asked once ----------

def test_the_first_skipping_start_asks_for_claude_codes_yes_and_a_yes_starts_it_skipping(skip_home):
    d = skip_home.d

    async def scenario():
        first = await _ask(d, "start a claude code session in shop")
        done = await _ask(d, "yes")
        await _settle(d)
        d.state.last_start_at = 0
        second = await _ask(d, "start a claude code session in billing")
        return first, done, second

    first, done, second = asyncio.run(scenario())
    assert first["confirm_first"] == CONFIRM_LINE
    assert done["starting"] == "shop-2" and skip_home.skips == [True]
    assert d.PREFS.get("sessions.skip_ok") is True and d.PREFS.get("sessions.skip_told") is True
    start = next(iter(d.STARTS.values()))
    assert start.skip and start.notice == ""  # the question said the risk: not shown again
    assert second["confirm_first"] == "Start a Claude Code session in billing, named billing-2?"  # asked once, told once


@pytest.mark.parametrize("answer", ["ask first", "No, ask first.", "safe mode"])
def test_ask_first_to_the_question_starts_that_session_asking_and_keeps_no_yes(skip_home, answer):
    d = skip_home.d

    async def scenario():
        await _ask(d, "start a claude code session in shop")
        done = await _ask(d, answer)
        await _settle(d)
        return done

    done = asyncio.run(scenario())
    assert done["starting"] == "shop-2" and skip_home.skips == [False]
    assert d.PREFS.get("sessions.skip_ok") is False and d.PREFS.get("sessions.skip_told") is False


@pytest.mark.parametrize("answer", ["no", "not now", "what does that mean?"])
def test_anything_else_to_the_question_starts_nothing_and_keeps_no_yes(skip_home, answer):
    d = skip_home.d

    async def scenario():
        await _ask(d, "start a claude code session in shop")
        return await _ask(d, answer)

    done = asyncio.run(scenario())
    assert "error" in done and skip_home.started == [] and d.PREFS.get("sessions.skip_ok") is False


@pytest.mark.parametrize("line", [CONFIRM_LINE, f"Start a Claude Code session in shop, named shop-2? {newsession.SKIP_NOTICE}",
                                  newsession.SKIP_ON_LINE, newsession.ASK_ON_LINE])
def test_no_line_pointe_says_about_it_holds_a_consent_word(line):
    """Heard back through the speakers, a "say yes" would be a yes (matching.py): no tail of these lines is one."""
    from guards import consent, permission_answer

    words = line.split()
    for n in range(len(words)):
        tail = " ".join(words[n:])
        assert consent(tail) != "allow" and permission_answer(tail) != "allow", tail


def test_the_question_heard_back_is_not_an_answer(skip_home):
    """The read-back holds the words "ask first": the bot's own voice coming back must not start a session asking."""
    d = skip_home.d

    async def scenario():
        await _ask(d, "start a claude code session in shop")
        return await _ask(d, newsession.SKIP_CONFIRM, heard_own_words=True)

    done = asyncio.run(scenario())
    assert "error" in done and skip_home.started == []


def test_with_the_voice_lock_on_only_the_owners_yes_is_claude_codes_yes(skip_home, monkeypatch):
    d = skip_home.d
    monkeypatch.setattr(d, "lock_level", lambda: "approvals")
    monkeypatch.setattr(d.VOICE, "confident", lambda verdict: False)

    async def scenario():
        await _ask(d, "start a claude code session in shop")
        return await _ask(d, "yes")

    assert "owner's voice" in asyncio.run(scenario())["error"]
    assert skip_home.started == [] and d.PREFS.get("sessions.skip_ok") is False


def test_a_yes_already_in_claude_code_is_not_asked_again_and_the_risk_is_said_once(skip_home):
    _accept_in_claude_code(skip_home)
    d = skip_home.d

    async def scenario():
        first = await _ask(d, "start a claude code session in shop")
        await _ask(d, "yes")
        await _settle(d)
        d.state.last_start_at = 0
        second = await _ask(d, "start a claude code session in billing")
        return first, second

    first, second = asyncio.run(scenario())
    assert first["confirm_first"] == f"Start a Claude Code session in shop, named shop-2? {newsession.SKIP_NOTICE}"
    assert second["confirm_first"] == "Start a Claude Code session in billing, named billing-2?"
    assert skip_home.skips == [True] and d.PREFS.get("sessions.skip_ok") is False  # Claude Code's own yes, not Pointe's


# ---------- one session that asks first ----------

@pytest.mark.parametrize("said", ["start a claude code session in shop that asks first",
                                  "start a new session in shop in safe mode",
                                  "open a claude code session called invoices that asks me first in shop"])
def test_the_words_ask_for_one_session_that_asks_first(said):
    ask = start_request(said, PLACES)
    assert ask is not None and ask.ask_first and ask.folder == "/w/shop", (said, ask)
    assert ask.name in (None, "invoices")


def test_ask_first_words_are_not_a_folder_or_a_name():
    assert not asks_first("start a claude code session in shop")
    ask = start_request("start a session in billing named safe mode", PLACES)
    assert ask.ask_first and ask.folder == "/w/billing"


def test_a_request_that_asks_first_is_read_back_so_and_starts_asking(skip_home):
    d = skip_home.d

    async def scenario():
        first = await _ask(d, "start a claude code session in shop that asks first")
        done = await _ask(d, "yes")
        await _settle(d)
        return first, done

    first, done = asyncio.run(scenario())
    assert first["confirm_first"] == "Start a Claude Code session in shop, named shop-2, asking before actions?"
    assert done["starting"] == "shop-2" and skip_home.skips == [False]
    assert d.PREFS.get("sessions.skip_ok") is False and d.PREFS.get("sessions.skip_told") is False


def test_where_claude_codes_settings_forbid_it_the_session_asks_and_the_user_is_told(skip_home):
    _write(Path(skip_home.shop) / ".claude" / "settings.json", {"permissions": {"disableBypassPermissionsMode": "disable"}})
    d = skip_home.d

    async def scenario():
        first = await _ask(d, "start a claude code session in shop")
        done = await _ask(d, "yes")
        await _settle(d)
        return first, done

    first, done = asyncio.run(scenario())
    assert first["confirm_first"] == "Start a Claude Code session in shop, named shop-2?"
    assert skip_home.skips == [False] and newsession.SKIP_OFF_HERE in done["note"]


# ---------- from a screen ----------

def test_the_sheet_never_takes_claude_codes_yes_it_did_not_show(skip_home):
    r, status = _sheet(skip_home.d, {"harness": "claude-code", "folder": skip_home.shop})
    assert r.status_code == 200 and r.json()["permissions"] == "ask" and skip_home.skips == [False]
    assert skip_home.d.PREFS.get("sessions.skip_ok") is False


def test_the_sheet_skips_once_claude_code_has_the_yes_and_shows_the_risk_the_first_time(skip_home):
    _accept_in_claude_code(skip_home)
    d = skip_home.d
    r, status = _sheet(d, {"harness": "claude-code", "folder": skip_home.shop})
    assert r.json()["permissions"] == "skip" and r.json()["notice"] == newsession.SKIP_NOTICE
    row = next(x for x in status["starting"] if x["name"] == "shop-2")
    assert row["notice"] == newsession.SKIP_NOTICE and row["permissions"] == "skip"
    again, _ = _sheet(d, {"harness": "claude-code", "folder": skip_home.billing})
    assert again.json()["permissions"] == "skip" and again.json()["notice"] == ""
    assert skip_home.skips == [True, True]


def test_the_sheet_can_ask_for_one_session_and_refuses_another_value(skip_home):
    _accept_in_claude_code(skip_home)
    r, _ = _sheet(skip_home.d, {"harness": "claude-code", "folder": skip_home.shop, "permissions": "ask"})
    assert r.json()["permissions"] == "ask" and skip_home.skips == [False]
    bad, _ = _sheet(skip_home.d, {"harness": "claude-code", "folder": skip_home.shop, "permissions": "bypass"})
    assert bad.status_code == 400


def test_a_tap_on_the_card_that_showed_the_question_is_its_yes(skip_home):
    d = skip_home.d
    asyncio.run(_ask(d, "start a claude code session in shop"))
    client = client_for(d)
    pending = client.get("/voice/status").json()["start_pending"]
    assert pending["line"] == CONFIRM_LINE
    assert client.post("/voice/new-session", json={"confirm": pending["id"]}).json()["permissions"] == "skip"
    asyncio.run(_settle(d))
    assert skip_home.skips == [True] and d.PREFS.get("sessions.skip_ok") is True


# ---------- the setting ----------

def test_skip_is_the_default_and_the_setting_takes_only_its_two_values(skip_home):
    client = client_for(skip_home.d)
    assert client.get("/voice/prefs").json()["sessions.permissions"] == "skip"
    assert client.post("/voice/prefs", json={"sessions.permissions": "ask"}).json()["sessions.permissions"] == "ask"
    assert client.post("/voice/prefs", json={"sessions.permissions": "bypass"}).status_code == 400


@pytest.mark.parametrize("key", ["sessions.skip_ok", "sessions.skip_told"])
def test_the_yes_and_the_risk_said_are_never_set_by_a_request(skip_home, key):
    client = client_for(skip_home.d)
    assert client.post("/voice/prefs", json={key: True}).status_code == 400
    assert skip_home.d.PREFS.get(key) is False


@pytest.mark.parametrize("said, value", [
    ("New sessions skip permission prompts.", "skip"), ("make new sessions skip permission prompts", "skip"),
    ("skip permission prompts in new sessions", "skip"), ("Pointe, new sessions ask first", "ask"),
    ("new sessions should ask before actions please", "ask"), ("ask before actions for new sessions", "ask"),
    ("start a session that asks first", None), ("tell shop that new sessions ask first", None),
    ("skip the tests", None), ("ask first", None)])
def test_the_setting_by_voice_is_a_whole_short_sentence(said, value):
    assert newsession.permissions_intent(said) == value


def test_the_setting_by_voice_changes_it_and_skipping_needs_the_owners_voice(skip_home, monkeypatch):
    d = skip_home.d
    asyncio.run(d._permissions_by_voice("new sessions ask first", "ask"))
    assert d.PREFS.get("sessions.permissions") == "ask"
    monkeypatch.setattr(d, "lock_level", lambda: "approvals")
    monkeypatch.setattr(d.VOICE, "confident", lambda verdict: False)
    asyncio.run(d._permissions_by_voice("new sessions skip permission prompts", "skip"))
    assert d.PREFS.get("sessions.permissions") == "ask"  # not clearly the owner: unchanged
    asyncio.run(d._permissions_by_voice("new sessions skip permission prompts", "skip", typed=True))
    assert d.PREFS.get("sessions.permissions") == "skip"  # from a paired screen, as Settings is


# ---------- what does not change ----------

def test_a_night_shifts_new_session_never_skips(skip_home):
    _accept_in_claude_code(skip_home)
    d = skip_home.d
    checked = d._check_shift([d.nightshift.Item(task="Run the tests.", start={"harness": "claude-code",
                                                                                     "folder": skip_home.shop})])
    asyncio.run(d.begin_shift(checked, d._shift_caps(), "page"))
    asyncio.run(_settle(d))
    assert skip_home.skips == [False]


def test_a_reopen_still_starts_in_the_default_mode(tmp_path, monkeypatch):
    script, settings = _script(tmp_path, monkeypatch, skip=False)
    resumed = claude_code.start_script(_folder(tmp_path, "my shop"), "shop", "r1", resume="sess-1")
    assert "--resume sess-1 --permission-mode default" in resumed.read_text() and "bypass" not in resumed.read_text()
