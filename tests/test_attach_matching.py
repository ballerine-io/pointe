"""Which sessions a spoken description means (docs/design/attach-by-voice.md): what counts as asking, the local match,
the short list the brain may order (titles and keywords only), answers to "which one?", and the read-backs word for
word. Invented sessions only.

uv run --locked pytest -q tests/test_attach_matching.py
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import matching  # noqa: E402
from discovery import Found  # noqa: E402
from guards import attach_request, close_request, disconnect_intent, start_request  # noqa: E402
from sessions import Session  # noqa: E402

NOW = time.mktime((2026, 11, 23, 15, 0, 0, 0, 0, -1))


def F(name, cwd, state="open", when=NOW - 600, harness="claude-code", **kw):
    return Found(harness=harness, id=kw.pop("id", name), name=name, cwd=f"/w/{cwd}", state=state, when=when, **kw)


SESSIONS = [
    F("pentest-recon", "pentest-notes", first="Plan the pentest of the login service", keywords=["pentest", "login"]),
    F("billing", "billing", first="Fix the retry tests", keywords=["retry", "tests"]),
    F("docs", "docs", harness="codex", first="Update the changelog"),
    F("billing-migration", "billing", state="recent", when=NOW - 86400, title="billing-migration",
      first="Write the migration that moves invoices to the new table", keywords=["migration", "invoices"]),
    F("lantern", "lantern", state="recent", when=NOW - 3 * 86400, first="Profile the renderer"),
]


# ---------- what counts as asking ----------

@pytest.mark.parametrize("said, verb, every, harness, when, about", [
    ("hey Pointe, connect to the session about the recent pentest", "join", False, None, None, ["pentest"]),
    ("Hey Pointe, connect to all open Claude Code sessions", "join", True, "claude-code", None, []),
    ("reopen yesterday's session about the billing migration", "reopen", False, None, "yesterday", ["billing", "migration"]),
    ("join the codex thread about the changelog", "join", False, "codex", None, ["changelog"]),
    ("listen to the docs agent", "join", False, None, None, ["docs"]),
    ("resume the session from this morning", "reopen", False, None, "this morning", []),
    ("bring back the last session", "reopen", False, None, "latest", []),
    ("open yesterday's session about billing", "reopen", False, None, "yesterday", ["billing"]),
    ("add all opencode sessions", "join", True, "opencode", None, []),
])
def test_these_words_ask_to_add_sessions(said, verb, every, harness, when, about):
    ask = attach_request(said)
    assert ask is not None, said
    assert (ask.verb, ask.all, ask.harness, ask.when, ask.about) == (verb, every, harness, when, about), ask


@pytest.mark.parametrize("said", [
    "connect to the database", "add a test to billing", "tell billing to resume the job", "join the two tables",
    "start a new session in shop", "add a new session in billing", "ask docs to connect to staging", "what is billing doing?",
])
def test_these_words_do_not(said):
    assert attach_request(said) is None, said


def test_a_machine_is_read_from_on_and_never_left_as_a_description():
    ask = attach_request("join the pentest session on devbox", ["devbox"], "studio")
    assert ask.machine == "devbox" and ask.about == ["pentest"]
    assert attach_request("connect to all sessions on this mac", ["devbox"], "studio").machine == ""


def test_a_reopen_is_never_read_as_a_new_session():
    assert start_request("open yesterday's session about billing", [("billing", "/w/billing")]) is None
    assert start_request("open a new session in billing", [("billing", "/w/billing")]) is not None


@pytest.mark.parametrize("said", ["leave the pentest session", "hey Pointe, leave the pentest session",
                                  "Leave the pen test session.",  # how the ears wrote it, live
                                  "disconnect from the pentest session", "detach from pentest recon"])
def test_leaving_a_session_takes_it_off_the_voice(said):
    sessions = [Session(id="a", name="pentest-recon", cwd="/w/pentest-notes"), Session(id="b", name="billing", cwd="/w/billing")]
    assert disconnect_intent(said)
    assert [s.name for s in close_request(said, sessions).close] == ["pentest-recon"]


@pytest.mark.parametrize("said", ["leave the billing session running", "leave billing alone"])
def test_leaving_a_session_alone_is_not_leaving_it(said):
    sessions = [Session(id="b", name="billing", cwd="/w/billing")]
    ask = close_request(said, sessions)
    assert ask is None or not ask.close


def test_close_all_leave_billing_still_keeps_billing():
    sessions = [Session(id="a", name="pentest-recon", cwd="/w/p"), Session(id="b", name="billing", cwd="/w/billing")]
    ask = close_request("close all, leave billing", sessions)
    assert [s.name for s in ask.close] == ["pentest-recon"] and [s.name for s in ask.keep] == ["billing"]


# ---------- the local match ----------

def _pick(said, found=SESSIONS):
    return matching.pick(found, attach_request(said), NOW)


@pytest.mark.parametrize("said", ["connect to the session about the recent pentest",
                                  "Connect to the session about the recent pen test."])  # how the ears wrote it, live
def test_a_description_picks_the_one_session_it_fits(said):
    p = _pick(said)
    assert p.kind == "one" and [f.name for f in p.items] == ["pentest-recon"]


def test_all_open_claude_code_sessions_are_every_open_one_of_that_harness():
    p = _pick("connect to all open Claude Code sessions")
    assert p.kind == "all" and sorted(f.name for f in p.items) == ["billing", "pentest-recon"]


def test_yesterdays_session_about_the_billing_migration_is_the_closed_one():
    p = _pick("reopen yesterday's session about the billing migration")
    assert p.kind == "one" and p.items[0].name == "billing-migration" and p.items[0].state == "recent"


def test_a_connect_offers_a_closed_one_only_when_no_open_one_fits():
    p = _pick("connect to the session about invoices")
    assert p.kind == "one" and p.items[0].name == "billing-migration"
    p = _pick("connect to the billing session")
    assert p.items[0].name == "billing" and p.items[0].state == "open"


def test_a_reopen_of_a_session_that_is_open_joins_it():
    p = _pick("resume the pentest session")
    assert p.items[0].name == "pentest-recon" and p.items[0].state == "open"


def test_close_scores_go_to_the_brain_and_never_join_by_themselves():
    twins = [F("recon-a", "scanner", first="pentest the api"), F("recon-b", "scanner2", first="pentest the web app")]
    p = matching.pick(twins, attach_request("connect to the pentest session"), NOW)
    assert p.kind == "rank" and len(p.items) == 2


def test_nothing_that_cannot_join_is_ever_picked():
    blocked = [F("pentest-recon", "pentest-notes", joinable=False, why="no socket")]
    assert matching.pick(blocked, attach_request("connect to the pentest session"), NOW).kind == "none"


def test_a_harness_or_a_time_said_filters_before_any_score():
    assert _pick("connect to the codex session about billing").kind == "none"
    p = _pick("reopen the session from yesterday")
    assert p.kind == "one" and p.items[0].name == "billing-migration"


def test_no_description_and_several_sessions_is_a_question():
    p = _pick("connect to a session")
    assert p.kind == "choose" and len(p.items) == matching.MOST_CHOICES


# ---------- the brain sees titles and keywords only ----------

def test_the_ranking_prompt_holds_no_path_and_no_request_text():
    secret = F("recon-a", "scanner", first="the staging password is in vault/item-42", keywords=["pentest", "api"])
    prompt = matching.rank_prompt("the pentest one", [secret, F("recon-b", "scanner2")], NOW)
    assert "recon-a" in prompt and "pentest" in prompt and "scanner" in prompt
    assert "/w/" not in prompt and "password" not in prompt and "vault" not in prompt
    assert all(len(line) <= 210 for line in prompt.splitlines())


@pytest.mark.parametrize("reply, n, expected", [("2", 3, 1), ("Session 1.", 3, 0), ("unclear", 3, None), ("7", 3, None),
                                                ("1 or 2", 3, None)])
def test_the_ranking_answer_is_a_number_in_the_list_or_nothing(reply, n, expected):
    assert matching.parse_rank(reply, n) == expected


# ---------- "which one?" ----------

ITEMS = [F("pentest-recon", "pentest-notes"), F("recon", "scanner", state="recent", when=NOW - 86400)]


@pytest.mark.parametrize("said, names", [("the first one", ["pentest-recon"]), ("number two", ["recon"]),
                                         ("the second", ["recon"]), ("the second one", ["recon"]), ("the last one", ["recon"]),
                                         ("both", ["pentest-recon", "recon"]), ("all of them", ["pentest-recon", "recon"]),
                                         ("the one in scanner", ["recon"]), ("pentest recon", ["pentest-recon"]),
                                         ("neither", []), ("no", [])])
def test_an_answer_picks_from_the_list_read_back(said, names):
    assert [f.name for f in matching.choice(said, ITEMS)] == names


@pytest.mark.parametrize("said", ["hmm", "what is billing doing?", "wait"])
def test_words_that_do_not_answer_pick_nothing(said):
    assert matching.choice(said, ITEMS) is None


# ---------- the read-backs, word for word ----------

def test_one_open_session_is_read_back_as_a_join():
    assert matching.line_one(SESSIONS[0], "studio", NOW) == \
        "Join pentest-recon, the Claude Code session in pentest-notes on studio? Say yes or tap."


def test_approvals_that_stay_in_the_terminal_are_said():
    f = F("pentest-recon", "pentest-notes", approvals=False)
    assert matching.line_one(f, "studio", NOW) == ("Join pentest-recon, the Claude Code session in pentest-notes on "
                                                    "studio? Its approvals stay in its terminal. Say yes or tap.")


def test_a_reopen_says_the_terminal_window_for_claude_code_only():
    assert matching.line_one(SESSIONS[3], "studio", NOW) == ("Reopen billing-migration, the Claude Code session in billing "
                                                             "from yesterday, in a new terminal window on studio? Say yes or tap.")
    codex = F("invoices", "billing", state="recent", when=NOW - 86400, harness="codex")
    assert matching.line_one(codex, "studio", NOW) == \
        "Reopen invoices, the Codex session in billing from yesterday, on studio? Say yes or tap."


def test_all_is_read_back_with_the_count_and_the_names():
    items = [F("pentest-recon", "p"), F("billing", "b"), F("docs", "d")]
    assert matching.line_all(items, "studio", "claude-code") == \
        "Join 3 open Claude Code sessions on studio: pentest-recon, billing and docs? Say yes or tap."
    assert matching.line_all(items[:1], "studio", "claude-code") == \
        "Join the one open Claude Code session on studio, pentest-recon? Say yes or tap."
    many = [F(f"s{i}", "x") for i in range(9)]
    assert "and 3 more?" in matching.line_all(many, "studio", None)


def test_several_that_fit_are_read_back_and_asked_about():
    assert matching.line_choose(ITEMS, "studio", NOW) == ("Two sessions fit: one, pentest-recon in pentest-notes, open; two, "
                                                          "recon in scanner, from yesterday. Which one? A closed one reopens.")


def test_sessions_on_another_machine_say_where():
    remote = F("pentest-recon", "pentest-notes", machine="devbox")
    assert "on devbox?" in matching.line_one(remote, "studio", NOW)
