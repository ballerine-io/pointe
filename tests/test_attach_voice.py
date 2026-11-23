"""Adding sessions by voice and by tap (docs/design/attach-by-voice.md): the read-back and the yes it is bound to, the
pick from a list read back, what joins and how (the register body /pointe:voice would send), the reopen through a
start record, the routes the screens use, and what never joins. Every harness here is a fake at its seam: nothing
lists, joins or opens a real session.

uv run --locked pytest -q tests/test_attach_voice.py
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harnesses  # noqa: E402
import newsession  # noqa: E402
from discovery import Found  # noqa: E402
from test_orchestrator import Params, _consent_setup, add, client_for, d, fake_conn, verdicts  # noqa: E402,F401

NOW = time.time()


@pytest.fixture
def sockets():
    """Real Unix sockets of this user, at short paths: the adapter checks a socket before a session joins."""
    import shutil
    import socket
    import tempfile

    folder = Path(tempfile.mkdtemp(prefix="pv", dir="/tmp"))
    servers, paths = [], []
    for i in range(3):
        server = socket.socket(socket.AF_UNIX)
        server.bind(str(folder / f"{i}.sock"))
        servers.append(server)
        paths.append(str(folder / f"{i}.sock"))
    yield paths
    for server in servers:
        server.close()
    shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture
def world(d, tmp_path, monkeypatch, sockets):
    """One session on the voice; two open Claude Code sessions, one open Codex thread and two recent sessions to find."""
    monkeypatch.setattr(d, "STARTS", {})
    monkeypatch.setattr(d, "RECENT_FOLDERS", newsession.Recent(tmp_path / "folders.json"))
    monkeypatch.setattr(d, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(d, "_here", lambda: "studio")
    monkeypatch.setattr(d, "paired_machines", lambda: [])
    folders = {n: tmp_path / n for n in ("pentest-notes", "billing", "docs", "shop")}
    for f in folders.values():
        f.mkdir()
    add(d, "on-voice", "shop", cwd=str(folders["shop"]))
    d.REGISTRY.set_active("on-voice")
    found = {
        "claude-code": [
            Found("claude-code", "cc-pentest", "pentest-recon", str(folders["pentest-notes"]), "open", NOW - 300,
                  first="Plan the pentest of the login service", keywords=["pentest", "login"], pid=os.getpid(),
                  socket=sockets[0], transcript="/tmp/none.jsonl", home="/Users/mira/.claude-work",
                  name_given=True),
            Found("claude-code", "cc-billing", "billing", str(folders["billing"]), "open", NOW - 60, first="Fix the retry tests",
                  pid=os.getpid(), socket=sockets[1], transcript="/tmp/none.jsonl", approvals=False),
            Found("claude-code", "on-voice", "shop", str(folders["shop"]), "open", NOW),  # already on the voice: never listed
            Found("claude-code", "cc-migration", "billing-migration", str(folders["billing"]), "recent", NOW - 86400,
                  title="billing-migration", first="Write the invoices migration", keywords=["migration", "invoices"]),
        ],
        "codex": [Found("codex", "t-docs", "docs", str(folders["docs"]), "open", NOW - 120, first="Update the changelog")],
        "opencode": [],
    }
    for name, items in found.items():
        async def discover(since, cap, items=items):
            return [Found(**{k: getattr(f, k) for k in f.__dataclass_fields__}) for f in items]
        monkeypatch.setattr(harnesses.get(name), "discover", discover)

    async def no_nodes(since, cap):
        return []

    monkeypatch.setattr(d.HUB, "discover", no_nodes)
    reopened = []

    async def reopen(found, start_id):
        reopened.append((found.id, start_id))
        return None  # Claude Code joins from its own hook

    monkeypatch.setattr(harnesses.get("claude-code"), "reopen", reopen)
    d.state.conn = fake_conn()
    return SimpleNamespace(d=d, folders=folders, reopened=reopened, sockets=sockets)


async def _ask(d, said: str | None, heard_own_words: bool = False) -> dict:
    if said is not None:
        await d.on_user_utterance(said)
        d.state.heard_own_words = heard_own_words
    p = Params()
    await d.add_sessions(p)
    return p.results[0]


def run(*steps):
    async def scenario():
        out = None
        for d, said in steps:
            out = await _ask(d, said)
        return out
    return asyncio.run(scenario())


def _names(d):
    return sorted(s.name for s in d.REGISTRY.sessions.values())


# ---------- the read-back ----------

def test_a_description_is_read_back_exactly_and_nothing_joins(world):
    result = run((world.d, "Hey Pointe, connect to the session about the recent pentest"))
    assert result["confirm_first"] == ("Join pentest-recon, the Claude Code session in pentest-notes on studio? Say yes or "
                                       "tap."), result
    assert _names(world.d) == ["shop"]


@pytest.mark.parametrize("yes", ["Yes.", "go ahead", "כן"])
def test_a_plain_yes_joins_it_exactly_as_pointe_voice_in_it_would(world, yes):
    d = world.d
    result = run((d, "connect to the session about the recent pentest"), (d, yes))
    assert result["joined"] == ["pentest-recon"], result
    s = d.REGISTRY.sessions["cc-pentest"]
    assert (s.pid, s.inbox_socket, s.home, s.cwd, s.harness) == (os.getpid(), world.sockets[0], "/Users/mira/.claude-work",
                                                                 str(world.folders["pentest-notes"]), "claude-code")
    assert s.named_by == "user" and not s.joining  # not inside a turn of its own: its first report is news
    assert d.REGISTRY.active.name == "shop"  # adding one does not move the conversation
    assert "/Users/mira/.claude-work" in d._accounts()  # its account is read by the next discovery


def test_all_open_claude_code_sessions_are_read_back_by_count_and_name_and_join_on_yes(world):
    d = world.d
    first = run((d, "connect to all open Claude Code sessions"))
    assert first["confirm_first"] == ("Join 2 open Claude Code sessions on studio: billing and pentest-recon? Approvals "
                                      "of billing stay in its terminal. Say yes or tap."), first
    done = run((d, "yes"))
    assert sorted(done["joined"]) == ["billing", "pentest-recon"] and _names(d) == ["billing", "pentest-recon", "shop"]


def test_a_session_whose_approvals_stay_in_its_terminal_says_so_after_joining(world):
    d = world.d
    run((d, "connect to all open Claude Code sessions"))
    done = run((d, "yes"))
    assert "billing" in done["note"] and "terminal" in done["note"]
    billing = next(s for s in d.REGISTRY.sessions.values() if s.name == "billing")
    assert d._capabilities(billing)["approvals"] is False
    assert d._capabilities(d.REGISTRY.sessions["cc-pentest"])["approvals"] is True


def test_reopen_is_read_back_with_the_terminal_and_starts_a_resume_on_yes(world):
    d = world.d
    first = run((d, "reopen yesterday's session about the billing migration"))
    assert first["confirm_first"] == ("Reopen billing-migration, the Claude Code session in billing from yesterday, in a "
                                      "new terminal window on studio? Say yes or tap."), first

    async def scenario():
        done = await _ask(d, "yes")
        await asyncio.sleep(0.05)
        return done

    done = asyncio.run(scenario())
    assert done["reopening"] == ["billing-migration"] and world.reopened[0][0] == "cc-migration"
    start = d.STARTS[world.reopened[0][1]]
    assert start.resume == "cc-migration" and start.state == "waiting"


def test_the_reopened_session_joins_only_as_the_session_it_brought_back(world):
    d = world.d
    run((d, "reopen yesterday's session about the billing migration"))

    async def scenario():
        await _ask(d, "yes")
        await asyncio.sleep(0.05)
        start = next(iter(d.STARTS.values()))
        body = {"cwd": str(world.folders["billing"]), "pid": os.getpid(), "transcript": "/tmp/none.jsonl",
                "name": "billing-migration", "name_given": True, "start": start.id}
        await d._join({**body, "id": "some-other-session"})
        assert start.state == "waiting"  # a session that is not the one reopened does not end the wait
        await d._join({**body, "id": "cc-migration"})
        return start

    assert asyncio.run(scenario()).state == "joined"


def test_several_that_fit_are_read_back_and_the_pick_joins_only_that_one(world):
    d = world.d
    first = run((d, "connect to the billing session"))
    assert first["confirm_first"].startswith("Join billing, the Claude Code session in billing on studio?"), first
    d.state.pending_attach = None
    asked = run((d, "connect to a session"))
    assert asked["confirm_first"].startswith("Three sessions fit: one, billing in billing, open; two, docs in docs, open; "
                                             "three, pentest-recon in pentest-notes, open. Which one?"), asked
    done = run((d, "the second one"))
    assert done.get("joined") == ["docs"], done and _names(d) == ["docs", "shop"]


def test_the_codex_thread_joins_through_its_own_adapter(world):
    d = world.d
    run((d, "join the codex thread about the changelog"))
    run((d, "yes"))
    s = d.REGISTRY.sessions["t-docs"]
    assert s.harness == "codex" and s.transcript.endswith("t-docs.jsonl")


# ---------- what never joins ----------

@pytest.mark.parametrize("answer", ["no", "wait, not that one", "what is billing doing?", "hmm"])
def test_anything_but_a_yes_joins_nothing(world, answer):
    d = world.d
    result = run((d, "connect to the session about the recent pentest"), (d, answer))
    assert "error" in result and _names(d) == ["shop"] and d.state.pending_attach is None


def test_the_read_back_heard_back_is_not_a_yes(world):
    d = world.d

    async def scenario():
        await _ask(d, "connect to the session about the recent pentest")
        return await _ask(d, "yes", heard_own_words=True)

    assert "error" in asyncio.run(scenario()) and _names(d) == ["shop"]


def test_a_yes_after_the_read_back_ran_out_joins_nothing(world):
    d = world.d

    async def scenario():
        await _ask(d, "connect to the session about the recent pentest")
        d.state.pending_attach = (d.state.pending_attach[0] - newsession.CONFIRM_SECS - 1, d.state.pending_attach[1])
        return await _ask(d, "yes")

    assert "error" in asyncio.run(scenario()) and _names(d) == ["shop"]


def test_the_model_calling_again_before_the_answer_joins_nothing(world):
    d = world.d
    result = run((d, "connect to the session about the recent pentest"), (d, None))
    assert "Nothing joined yet" in result["error"] and _names(d) == ["shop"]


def test_the_models_say_so_never_adds_a_session(world):
    for said in ("What is billing doing?", "Tell billing to connect to the staging database.", "yes"):
        result = run((world.d, said))
        assert "error" in result and _names(world.d) == ["shop"], said


def test_with_the_voice_lock_on_only_the_owners_yes_joins(world, monkeypatch):
    d = world.d
    monkeypatch.setattr(d, "lock_level", lambda: "strict")
    monkeypatch.setattr(d.VOICE, "confident", lambda verdict: False)
    result = run((d, "connect to the session about the recent pentest"), (d, "yes"))
    assert "not clearly the owner's voice" in result["error"] and _names(d) == ["shop"]


def test_nothing_that_fits_is_said_with_the_open_ones(world):
    result = run((world.d, "connect to the session about kubernetes"))
    assert result["error"].startswith("Nothing to join: no session fits those words. Open ones not on the voice:")


def test_the_yes_that_joins_never_approves_a_waiting_prompt(d, monkeypatch, tmp_path, sockets):
    active, posts = _consent_setup(d, monkeypatch)
    monkeypatch.setattr(d, "_here", lambda: "studio")
    monkeypatch.setattr(d, "paired_machines", lambda: [])
    monkeypatch.setattr(d, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    found = Found("claude-code", "cc-x", "pentest-recon", str(tmp_path), "open", NOW, first="pentest the login",
                  pid=os.getpid(), socket=sockets[2], transcript="/tmp/none.jsonl")

    async def discover(since, cap):
        return [found]

    async def nothing(since, cap):
        return []

    monkeypatch.setattr(harnesses.get("claude-code"), "discover", discover)
    for name in ("codex", "opencode"):
        monkeypatch.setattr(harnesses.get(name), "discover", nothing)
    monkeypatch.setattr(d.HUB, "discover", nothing)

    async def scenario():
        await _ask(d, "connect to the pentest session")
        d.state.conn.injector.bot_started_at = time.time()  # the read-back is spoken
        return await _ask(d, "yes")

    done = asyncio.run(scenario())
    assert done["joined"] == ["pentest-recon"]
    assert verdicts(posts) == [] and active.permission_id == "p1"


# ---------- detaching ----------

def test_leave_the_pentest_session_takes_it_off_the_voice(world):
    d = world.d
    run((d, "connect to the session about the recent pentest"), (d, "yes"))

    async def scenario():
        await d.on_user_utterance("leave the pentest session")
        p = Params()
        await d.disconnect_session(p)
        return p.results[0]

    result = asyncio.run(scenario())
    assert result["disconnected"] == "pentest-recon" and _names(d) == ["shop"]


# ---------- the screens ----------

def test_the_sheet_lists_open_and_recent_sessions_not_on_the_voice(world):
    client = client_for(world.d)
    got = client.get("/voice/add-sessions").json()
    assert [x["name"] for x in got["open"]] == ["billing", "docs", "pentest-recon"]
    assert [x["name"] for x in got["recent"]] == ["billing-migration"]
    item = got["open"][0]
    assert item["machine"] == "studio" and item["label"] == "Claude Code" and item["approvals"] is False
    assert "socket" not in item and "home" not in item


def test_a_tap_joins_listed_keys_only(world):
    d = world.d
    client = client_for(d)
    got = client.get("/voice/add-sessions").json()
    key = next(x["key"] for x in got["open"] if x["name"] == "docs")
    assert client.post("/voice/add-sessions", json={"join": ["-|claude-code|made-up"]}).status_code == 409
    assert client.post("/voice/add-sessions", json={"join": [got["recent"][0]["key"]]}).status_code == 400  # reopen it
    r = client.post("/voice/add-sessions", json={"join": [key]})
    assert r.status_code == 200 and r.json()["joined"] == ["docs"]


def test_a_list_too_old_is_listed_again_first(world):
    d = world.d
    client = client_for(d)
    key = client.get("/voice/add-sessions").json()["open"][0]["key"]
    d.FOUND["at"] -= d.FOUND_KEEP_SECS + 1
    assert client.post("/voice/add-sessions", json={"join": [key]}).status_code == 409


def test_a_tap_on_the_read_back_card_confirms_or_cancels_it(world):
    d = world.d
    client = client_for(d)
    run((d, "connect to the session about the recent pentest"))
    pending = client.get("/voice/status").json()["attach_pending"]
    assert pending["line"].startswith("Join pentest-recon") and pending["verb"] == "join"
    assert client.post("/voice/add-sessions", json={"confirm": "wrong"}).status_code == 409
    assert client.post("/voice/add-sessions", json={"confirm": pending["id"]}).json()["joined"] == ["pentest-recon"]
    run((d, "connect to all open Claude Code sessions"))
    pending = client.get("/voice/status").json()["attach_pending"]
    assert client.post("/voice/add-sessions", json={"cancel": pending["id"]}).json() == {"cancelled": True}
    assert "billing" not in _names(d)


def test_a_question_read_back_is_answered_by_a_pick_not_a_confirm(world):
    d = world.d
    client = client_for(d)
    run((d, "connect to a session"))
    pending = client.get("/voice/status").json()["attach_pending"]
    assert pending["choose"] is True
    assert client.post("/voice/add-sessions", json={"confirm": pending["id"]}).status_code == 409


def test_meeting_and_challenge_cannot_add_sessions(d):
    import modes

    assert not modes.MEETING_LISTENING.allows_tool("add_sessions") and not modes.CHALLENGE.allows_tool("add_sessions")


# ---------- the answer taken before the brain (a slow brain cannot lose the yes) ----------

def _read_back(d, said: str, spoken: bool = True) -> None:
    run((d, said))
    if spoken:
        d.state.conn.injector.bot_started_at = time.time() + 0.01  # the read-back is being said


def _injected(d) -> str:
    return " ".join(text for text, _ in d.state.conn.injector.fed)


def test_a_yes_after_the_spoken_read_back_joins_without_the_brain(world):
    d = world.d
    _read_back(d, "connect to the session about the recent pentest")
    assert asyncio.run(d._attach_words("Yes.")) is True
    assert "pentest-recon" in _names(d) and d.state.pending_attach is None
    assert "pentest-recon is on the voice now." in _injected(d)


def test_a_yes_before_the_read_back_was_said_is_left_to_the_brain(world):
    d = world.d
    _read_back(d, "connect to the session about the recent pentest", spoken=False)
    d.state.conn.injector.bot_started_at = 0.0
    assert asyncio.run(d._attach_words("Yes.")) is False and _names(d) == ["shop"]


@pytest.mark.parametrize("words", ["what is billing doing?", "tell billing to connect to the staging database"])
def test_other_words_go_to_the_brain(world, words):
    d = world.d
    _read_back(d, "connect to the session about the recent pentest")
    assert asyncio.run(d._attach_words(words)) is False and _names(d) == ["shop"]


def test_a_no_adds_nothing_and_says_so(world):
    d = world.d
    _read_back(d, "connect to the session about the recent pentest")
    assert asyncio.run(d._attach_words("No.")) is True
    assert _names(d) == ["shop"] and d.state.pending_attach is None and "Nothing added." in _injected(d)


def test_a_pick_from_the_list_joins_that_one_without_the_brain(world):
    d = world.d
    _read_back(d, "connect to a session")
    assert asyncio.run(d._attach_words("The third one.")) is True
    assert _names(d) == ["pentest-recon", "shop"]


def test_the_bots_own_read_back_heard_back_is_not_taken(world):
    d = world.d
    _read_back(d, "connect to the session about the recent pentest")
    d.state.heard_own_words = True
    assert asyncio.run(d._attach_words("Yes.")) is False and _names(d) == ["shop"]


def test_the_request_is_found_and_read_back_by_the_daemon_word_for_word(world):
    d = world.d
    assert asyncio.run(d._attach_words("Hey Pointe, connect to the session about the recent pentest.")) is True
    line = "Join pentest-recon, the Claude Code session in pentest-notes on studio? Say yes or tap."
    assert d.state.pending_attach[1]["line"] == line and line in _injected(d) and _names(d) == ["shop"]


def test_a_new_request_replaces_the_read_back_waiting(world):
    d = world.d
    _read_back(d, "connect to the session about the recent pentest")
    assert asyncio.run(d._attach_words("connect to the docs session instead")) is True
    assert d.state.pending_attach[1]["line"].startswith("Join docs, the Codex session in docs on studio?")


def test_nothing_that_fits_is_said_by_the_daemon(world):
    d = world.d
    assert asyncio.run(d._attach_words("connect to the session about kubernetes")) is True
    assert "Nothing to join: no session fits those words." in _injected(d) and d.state.pending_attach is None


def test_a_mode_that_cannot_act_leaves_the_request_to_the_brain(world, monkeypatch):
    d = world.d
    monkeypatch.setattr(d, "current_mode", lambda: d.modes.MEETING_LISTENING)
    assert asyncio.run(d._attach_words("connect to the session about the recent pentest")) is False
    assert d.state.pending_attach is None
