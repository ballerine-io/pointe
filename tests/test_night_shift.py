"""Night shift (docs/design/night-shift.md).

What the user's words ask for, the read-back and the yes it is bound to, the loop against fake sessions that finish,
stall, ask and block, the caps and the stop, the safety rails (an approval is never answered by Pointe: it is held and
written down word for word), the ledger on disk, and the order of the morning briefing. Nothing here starts a real
agent, calls a model or opens a window.

uv run --locked pytest -q tests/test_night_shift.py
"""

import asyncio
import inspect
import json
import os
import re
import stat
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import briefing  # noqa: E402
import harnesses  # noqa: E402
import nightshift as ns  # noqa: E402
from sessions import Session  # noqa: E402
from test_new_session import _folder, home  # noqa: E402,F401
from test_orchestrator import Params, add, client_for, d, fake_conn, model_says, record_channel, verdicts  # noqa: E402,F401

ROOT = Path(__file__).resolve().parents[1]
BILLING = Session(id="b", name="billing", cwd="/w/billing")
DOCS = Session(id="c", name="docs", cwd="/w/docs")
SHOP = Session(id="s", name="shop", cwd="/w/shop")
FAR = Session(id="r", name="ledger", cwd="/w/ledger", machine="devbox")
SESSIONS = [BILLING, DOCS, SHOP]
PLACES = [("shop", "/w/shop"), ("billing", "/w/billing"), ("docs", "/w/docs")]
EVENING = ("Tonight: billing finishes the retry work and opens a PR; docs updates the changelog; start a Codex session "
           "in shop to fix the flaky test.")


# ---------- what counts as asking ----------

@pytest.mark.parametrize("said", [
    EVENING, "Night shift: have billing fix the retry tests.", "ok Pointe, for tonight, billing fixes the retry tests",
    "Overnight, docs updates the changelog", "start a night shift: billing fixes the tests",
    "הלילה: billing יסיים את ה-retry"])
def test_these_words_ask_for_a_night_shift(said):
    assert ns.shift_intent(said) is not None, said


@pytest.mark.parametrize("said", [
    "what did the night shift do?", "brief me on the night", "tell billing to work tonight", "yes",
    "is the night shift still running", "billing, fix the retry tests", "stop the night shift"])
def test_these_words_do_not(said):
    assert ns.shift_intent(said) is None and ns.plan_request(said, SESSIONS, PLACES) is None, said


# ---------- the plan comes from the words ----------

def test_each_session_gets_the_words_said_after_its_name():
    plan = ns.plan_request(EVENING, SESSIONS, PLACES)
    assert not plan.problem
    assert [(i.name, i.task) for i in plan.items[:2]] == [
        ("billing", "finishes the retry work and opens a PR"), ("docs", "updates the changelog")]
    new = plan.items[2]
    assert new.start == {"harness": "codex", "folder": "/w/shop", "name": None} and new.task == "fix the flaky test"


def test_every_task_is_a_span_of_what_the_user_said():
    for said in (EVENING, "Night shift: have billing fix the retry tests, then docs should update the changelog."):
        for item in ns.plan_request(said, SESSIONS, PLACES).items:
            assert item.task in said, (item.task, said)


def test_tell_ask_and_should_are_not_part_of_the_task():
    plan = ns.plan_request("for tonight, tell billing to fix the retry tests and docs should update the changelog",
                           SESSIONS, PLACES)
    assert [(i.name, i.task) for i in plan.items] == [("billing", "fix the retry tests"), ("docs", "update the changelog")]


def test_a_second_item_for_a_session_is_a_second_task():
    plan = ns.plan_request("tonight billing fixes the tests, docs updates the changelog, and billing opens a PR", SESSIONS, PLACES)
    assert [(i.name, i.task) for i in plan.items] == [
        ("billing", "fixes the tests"), ("docs", "updates the changelog"), ("billing", "opens a PR")]


def test_a_name_inside_a_task_is_not_a_new_item():
    plan = ns.plan_request("tonight billing updates the docs folder index", SESSIONS, PLACES)
    assert [(i.name, i.task) for i in plan.items] == [("billing", "updates the docs folder index")]


@pytest.mark.parametrize("said, asks", [
    ("tonight I am going out", "named no session"),
    ("tonight billing", "what billing should do"),
    ("overnight, start a codex session in shop", "what the new session should do"),
    ("tonight, start a codex session to fix the tests", "where the new session should start"),
    ("tonight ledger reconciles the accounts", "another machine")])
def test_anything_unclear_is_a_question_never_a_guess(said, asks):
    plan = ns.plan_request(said, SESSIONS + [FAR], PLACES)
    assert plan is not None and not plan.items and asks in plan.problem and plan.problem.startswith("Not started"), plan


def test_a_name_two_sessions_answer_to_is_a_tie():
    twin = Session(id="b2", name="billing", cwd="/x/billing")
    plan = ns.plan_request("tonight billing fixes the tests", SESSIONS + [twin], PLACES)
    assert not plan.items and "more than one session" in plan.problem


def test_a_session_is_named_by_the_words_that_tell_it_apart_never_its_branch():
    main, feature = Session(id="m", name="billing/main", cwd="/w/billing"), Session(id="f", name="docs/fix-links", cwd="/w/docs")
    plan = ns.plan_request("tonight: billing fixes the retry tests; docs fix links updates the changelog", [main, feature], PLACES)
    assert [(i.name, i.task) for i in plan.items] == [("billing/main", "fixes the retry tests"), ("docs/fix-links", "updates the changelog")]
    two = [main, Session(id="d", name="billing/dev", cwd="/x/billing")]
    assert "more than one session" in ns.plan_request("tonight billing fixes the tests", two, PLACES).problem
    assert ns.release_intent("approve billing's push", [main]) is main and ns.release_intent("approve billing", two) is None


def test_a_plan_has_limits():
    many = [ns.Item(task="x", session_id="b", name="billing") for _ in range(ns.MAX_TASKS + 1)]
    assert "at most" in ns.limits_problem(many)
    wide = [ns.Item(task="x", session_id=str(i), name=f"s{i}") for i in range(ns.MAX_FRONTS + 1)]
    assert "at most" in ns.limits_problem(wide)
    assert ns.limits_problem([]) and ns.limits_problem([ns.Item(task="   ", session_id="b")])
    assert ns.limits_problem([ns.Item(task="x" * (ns.MAX_TASK_CHARS + 1), session_id="b")])
    assert ns.limits_problem([ns.Item(task="fix it", session_id="b")]) is None


def test_the_read_back_says_the_plan_the_caps_and_the_approval_rule():
    line = ns.read_back([{"session": "billing", "task": "fix the retry tests"},
                         {"session": "shop-2", "task": "fix the flaky test", "new": True, "agent": "Codex", "folder": "shop"}],
                        8, 40)
    assert line == ("Night shift. billing: fix the retry tests. A new Codex session in shop, named shop-2: fix the flaky "
                    "test. Up to 8 hours and 40 messages. I approve nothing: a session that needs approval waits for you. "
                    "Start?")


@pytest.mark.parametrize("said", ["stop the night shift", "Pointe, cancel the night shift please.", "end the shift",
                                  "call off the night shift", "עצור את משמרת הלילה"])
def test_these_words_stop_a_shift(said):
    assert ns.stop_intent(said), said


@pytest.mark.parametrize("said", ["stop", "don't stop the night shift", "should I stop the night shift?",
                                  "stop the night shift from touching billing", "tell billing to stop"])
def test_these_do_not_stop_it(said):
    assert not ns.stop_intent(said), said


def test_approve_billings_push_names_the_waiting_session_and_a_send_does_not():
    assert ns.release_intent("approve billing's push", [BILLING, DOCS]) is BILLING
    assert ns.release_intent("ok, let docs do it", [BILLING, DOCS]) is DOCS
    assert ns.release_intent("tell billing to approve the PR", [BILLING]) is None
    assert ns.release_intent("approve it", [BILLING]) is None
    assert ns.release_intent("approve billing and docs", [BILLING, DOCS]) is None  # two names: ask, never guess
    assert ns.release_intent("billing looks good", [BILLING]) is None


# ---------- the only messages a shift sends ----------

def test_a_message_is_a_fixed_template_around_the_users_task():
    for kind in ns.TEMPLATES:
        text = ns.message(kind, "fix the retry tests")
        assert text == ns.TEMPLATES[kind].replace("{task}", "fix the retry tests") and "fix the retry tests" in text
        assert text.startswith("[Night shift.") and "NIGHT REPORT" in text
    with pytest.raises(KeyError):
        ns.message("anything else", "x")


def test_every_template_repeats_the_limits_and_none_grants_anything():
    for kind, text in ns.TEMPLATES.items():
        assert "Do nothing destructive or outward-facing that the task does not ask for" in text, kind
        assert "do not work around it" in text and "BLOCKED" in text, kind
        assert not re.search(r"\b(?:approved|you may|you are allowed|permission granted|go ahead and (?:push|merge|delete))\b",
                             text, re.I), kind


def test_a_task_with_braces_is_sent_as_said():
    assert "render {name} in the template" in ns.message("task", "render {name} in the template")


# ---------- what a report says ----------

REPORT = """Fixed the retry tests.

NIGHT REPORT
STATUS: done
DONE: retry tests pass (42 of 42), commit 3f2a9c1, PR https://github.com/acme/billing/pull/12
BLOCKED: none
DECIDED: cap the backoff? -> 30 seconds -> change MAX_BACKOFF if you want it longer
"""


def test_the_sessions_own_block_decides():
    out = ns.read_report(REPORT)
    assert out.status == "done" and out.blocked == []
    assert out.done == ["retry tests pass (42 of 42), commit 3f2a9c1, PR https://github.com/acme/billing/pull/12"]
    assert out.decided == [("cap the backoff?", "30 seconds", "change MAX_BACKOFF if you want it longer")]
    assert out.commit == "3f2a9c1" and out.pr == "https://github.com/acme/billing/pull/12"


def test_markdown_and_bullets_around_the_labels_are_read():
    out = ns.read_report("## NIGHT REPORT\n**STATUS:** blocked\n- **BLOCKED:** the push needs your approval\n"
                         "**DECIDED:**\n  - old or new format? → old → regenerate if you want new\n")
    assert out.status == "blocked" and out.blocked == ["the push needs your approval"]
    assert out.decided == [("old or new format?", "old", "regenerate if you want new")]


def test_nothing_blocked_is_not_a_blocker():
    out = ns.read_report("NIGHT REPORT\nSTATUS: done\nDONE: versions reported\nBLOCKED: Nothing blocked. Aligning them is your call.\n"
                         "DECIDED: none")
    assert out.status == "done" and out.blocked == [] and out.decided == []
    assert ns.read_report("NIGHT REPORT\nSTATUS: blocked\nBLOCKED: no access to the staging bucket").blocked


def test_a_commit_or_pr_comes_from_the_message_never_from_thin_air():
    out = ns.read_report("NIGHT REPORT\nSTATUS: done\nDONE: changelog updated and pushed")
    assert out.status == "done" and out.commit == "" and out.pr == ""
    assert ns.read_report("NIGHT REPORT\nSTATUS: done\nDONE: opened PR #48").pr == "#48"


def test_a_question_with_no_block_is_asks_and_silence_is_unclear():
    out = ns.read_report("I can keep the old format or move to the new one.\nWhich do you want?")
    assert out.status == "asks" and out.question == "Which do you want?"
    out = ns.read_report("Waiting on you.", {"waiting": True, "need": "pick the changelog format"})
    assert out.status == "asks" and out.question == "pick the changelog format"
    assert ns.read_report("I looked at the tests.").status == "unclear"
    assert ns.read_report("NIGHT REPORT\nSTATUS: working\nDONE: two of five files").status == "working"


# ---------- the loop, against fake sessions ----------

def shift_of(*fronts, hours=8.0, messages=40, now=1000.0) -> ns.Shift:
    made = [ns.Front(session=name, session_id=name, tasks=[ns.Task(text=t) for t in tasks]) for name, tasks in fronts]
    return ns.new_shift(made, hours, messages, False, "voice", now)


def started(shift: ns.Shift, now=1000.0) -> list:
    """Every front given its first task, as begin_shift does."""
    for f in shift.fronts:
        kind = shift.next_task(f, now)
        assert kind == "task"
        shift.sent_to(f, kind, now)
    return shift.fronts


def test_a_session_that_finishes_gets_its_next_task_and_the_proof_is_kept():
    shift = shift_of(("billing", ["fix the retry tests", "open a PR"]))
    (front,) = started(shift)
    assert shift.report(front, ns.read_report(REPORT), 1100.0) == "task"
    assert front.task().text == "open a PR" and front.tasks[0].state == "done"
    done = shift.ledger()["done"][0]
    assert done["session"] == "billing" and done["task"] == "fix the retry tests"
    assert done["commit"] == "3f2a9c1" and done["pr"].endswith("/pull/12") and "42 of 42" in done["proof"]
    assert shift.ledger()["decided"][0]["choice"] == "30 seconds"


def test_the_last_task_done_finishes_the_front_and_then_the_shift():
    shift = shift_of(("billing", ["fix the retry tests"]))
    (front,) = started(shift)
    assert shift.report(front, ns.read_report(REPORT), 1100.0) is None
    assert front.state == "finished" and shift.over(1101.0) == "complete"


def test_a_blocked_task_is_parked_and_the_session_jumps_to_its_next_one():
    shift = shift_of(("billing", ["push the branch", "write the release notes"]), ("docs", ["update the changelog"]))
    billing, docs = started(shift)
    out = ns.read_report("NIGHT REPORT\nSTATUS: blocked\nBLOCKED: the push needs credentials only you have")
    assert shift.report(billing, out, 1100.0) == "task"
    assert billing.tasks[0].state == "blocked" and billing.task().text == "write the release notes"
    blocked = shift.ledger()["blocked"][0]
    assert blocked["session"] == "billing" and "credentials only you have" in blocked["waits_on"]
    assert docs.state == "working" and shift.over(1101.0) is None  # one blocked front never stops the others


def test_a_question_is_recorded_and_the_session_is_told_to_decide_never_answered_by_pointe():
    shift = shift_of(("docs", ["update the changelog"]))
    (front,) = started(shift)
    asks = ns.read_report("Old format or new?")
    assert shift.report(front, asks, 1100.0) == "decide"
    asked = shift.ledger()["asked"]
    assert [a["question"] for a in asked] == ["Old format or new?"] and asked[0]["choice"] == ""
    shift.sent_to(front, "decide", 1101.0)
    answer = ns.read_report("NIGHT REPORT\nSTATUS: done\nDONE: changelog updated\n"
                            "DECIDED: old format or new? -> old -> regenerate with --new if you want the new one")
    assert shift.report(front, answer, 1200.0) is None
    ledger = shift.ledger()
    assert ledger["asked"] == [] and ledger["decided"][0]["otherwise"] == "regenerate with --new if you want the new one"


def test_a_question_nobody_decided_stays_as_a_question_waiting():
    shift = shift_of(("docs", ["update the changelog"]))
    (front,) = started(shift)
    shift.report(front, ns.read_report("Old format or new?"), 1100.0)
    shift.report(front, ns.read_report("NIGHT REPORT\nSTATUS: blocked\nBLOCKED: only you can pick the format"), 1200.0)
    assert [a["question"] for a in shift.ledger()["asked"]] == ["Old format or new?"]


def test_working_gets_continue_and_no_block_gets_report():
    shift = shift_of(("billing", ["fix the retry tests"]))
    (front,) = started(shift)
    assert shift.report(front, ns.read_report("NIGHT REPORT\nSTATUS: working\nDONE: 2 of 5"), 1100.0) == "continue"
    assert shift.report(front, ns.read_report("I read the tests."), 1200.0) == "report"
    assert front.task().followups == 2


def test_followups_are_capped_then_the_task_is_parked_as_blocked():
    shift = shift_of(("billing", ["fix the retry tests", "open a PR"]))
    (front,) = started(shift)
    unclear = ns.read_report("I read the tests.")
    kinds = [shift.report(front, unclear, 1100.0 + i) for i in range(ns.FOLLOWUPS)]
    assert kinds == ["report"] * ns.FOLLOWUPS
    assert shift.report(front, unclear, 1200.0) == "task"  # the cap: parked, and on to the next task
    assert front.tasks[0].state == "parked" and front.task().text == "open a PR"
    assert f"Did not finish in {ns.FOLLOWUPS} follow-ups" in shift.ledger()["blocked"][0]["text"]


def test_a_stalled_session_gets_one_status_message_per_stall():
    shift = shift_of(("billing", ["fix the retry tests"]))
    (front,) = started(shift)
    look = dict(present=True, busy=False, stall_secs=600)
    assert shift.tick(front, 1000.0 + 599, **look) is None
    assert shift.tick(front, 1000.0 + 600, **look) == "status"
    assert shift.tick(front, 1000.0 + 700, **look) is None  # asked once; again only after another stall
    assert shift.tick(front, 1000.0 + 1200, **look) == "status"


def test_a_busy_session_is_never_nudged():
    shift = shift_of(("billing", ["fix the retry tests"]))
    (front,) = started(shift)
    assert shift.tick(front, 1000.0 + 5000, present=True, busy=True, stall_secs=600) is None


def test_a_session_that_closed_is_blocked_and_its_queue_is_parked():
    shift = shift_of(("billing", ["fix the retry tests", "open a PR"]))
    (front,) = started(shift)
    assert shift.tick(front, 1100.0, present=False) is None
    assert front.state == "parked" and [t.state for t in front.tasks] == ["blocked", "parked"]
    assert shift.ledger()["blocked"][0]["text"] == "The session closed." and shift.over(1101.0) == "complete"


def test_a_message_that_did_not_arrive_parks_the_front():
    shift = shift_of(("billing", ["fix the retry tests"]))
    front = shift.fronts[0]
    shift.next_task(front, 1000.0)
    shift.not_delivered(front, "Its Claude Code held the message.", 1001.0)
    assert front.state == "parked" and "did not reach it" in shift.ledger()["blocked"][0]["text"] and shift.sent == 0


def test_a_new_session_that_never_starts_is_blocked():
    shift = ns.new_shift([ns.Front(session="shop-2", state="starting", start_id="x", tasks=[ns.Task(text="fix the flaky test")])],
                         8, 40, False, "voice", 1000.0)
    shift.not_started(shift.fronts[0], "Codex's daemon is not running.", 1100.0)
    assert shift.fronts[0].state == "parked" and "did not start. Codex's daemon is not running." in shift.ledger()["blocked"][0]["text"]
    assert shift.over(1101.0) == "complete"


# ---------- the caps and the stop ----------

def test_past_the_message_budget_nothing_more_is_sent():
    shift = shift_of(("billing", ["a", "b", "c"]), messages=2)
    (front,) = started(shift)
    assert shift.report(front, ns.read_report("NIGHT REPORT\nSTATUS: done\nDONE: a"), 1100.0) == "task"
    shift.sent_to(front, "task", 1100.0)
    assert shift.sent == 2 and not shift.can_send()
    assert shift.report(front, ns.read_report("NIGHT REPORT\nSTATUS: done\nDONE: b"), 1200.0) is None
    assert front.tasks[2].state == "queued" and shift.ledger()["not_started"] == [{"session": "billing", "task": "c"}]
    assert shift.over(1201.0) in ("complete", "messages")


def test_the_budget_also_stops_followups():
    shift = shift_of(("billing", ["a"]), messages=1)
    (front,) = started(shift)
    assert shift.report(front, ns.read_report("still going?"), 1100.0) is None
    assert shift.tick(front, 1000.0 + 9999, present=True, busy=False, stall_secs=600) is None


def test_a_shift_ends_at_its_hours():
    shift = shift_of(("billing", ["a"]), hours=2)
    started(shift)
    assert shift.over(1000.0 + 2 * 3600 - 1) is None and shift.over(1000.0 + 2 * 3600) == "hours"
    shift.end("hours", 1000.0 + 7200)
    assert not shift.on and shift.over(9e9) is None and not shift.can_send()


def test_after_a_stop_nothing_is_sent_whatever_the_session_reports():
    shift = shift_of(("billing", ["a", "b"]))
    (front,) = started(shift)
    shift.end("stopped", 1050.0)
    assert shift.report(front, ns.read_report("NIGHT REPORT\nSTATUS: done\nDONE: a"), 1100.0) is None
    assert shift.followup(front, "status", 1100.0) is None and shift.why == "stopped"


def test_caps_have_bounds():
    assert ns.valid_hours(8) and ns.valid_hours(0.1) and ns.valid_hours(12)
    assert not ns.valid_hours(0) and not ns.valid_hours(12.5) and not ns.valid_hours(True) and not ns.valid_hours("8")
    assert ns.valid_messages(1) and ns.valid_messages(200)
    assert not ns.valid_messages(0) and not ns.valid_messages(201) and not ns.valid_messages(2.5)


# ---------- approvals: recorded word for word, never answered ----------

REQUEST = "Bash: push the branch\n{\"command\": \"git push origin retry-work\"}"


def test_a_pending_approval_parks_the_front_with_the_exact_request_and_sends_nothing():
    shift = shift_of(("billing", ["fix the retry work and open a PR", "write the notes"]))
    (front,) = started(shift)
    for now in (1100.0, 1110.0, 5000.0):  # however long it waits: one entry, and no nudge
        assert shift.tick(front, now, present=True, busy=True, request_id="p1", request=REQUEST) is None
    assert front.state == "waiting" and front.task().text == "fix the retry work and open a PR"  # no jump past it
    (entry,) = shift.ledger()["blocked"]
    assert entry["request"] == REQUEST and entry["request_id"] == "p1" and entry["waits_on"] == "your approval"
    assert shift.over(5001.0) is None  # it still waits on the user: not complete


def test_the_users_answer_marks_the_entry_and_the_front_works_again():
    shift = shift_of(("billing", ["fix the retry work"]))
    (front,) = started(shift)
    shift.tick(front, 1100.0, present=True, request_id="p1", request=REQUEST)
    assert shift.answered("billing", "p1", "allow", 2000.0)
    (entry,) = shift.ledger()["blocked"]
    assert entry["resolved"] == "approved by you" and front.state == "working" and front.waiting_on == ""
    assert not shift.answered("billing", "p1", "allow", 2001.0)  # only once


def test_a_denial_and_an_answer_at_the_terminal_are_told_apart():
    shift = shift_of(("billing", ["a"]), ("docs", ["b"]))
    billing, docs = started(shift)
    shift.tick(billing, 1100.0, present=True, request_id="p1", request=REQUEST)
    shift.tick(docs, 1100.0, present=True, terminal_wait="a permission prompt in its terminal")
    shift.answered("billing", "p1", "deny", 1200.0)
    shift.tick(docs, 1300.0, present=True, busy=True)  # the prompt in its terminal is gone
    resolved = {e["session"]: e["resolved"] for e in shift.ledger()["blocked"]}
    assert resolved == {"billing": "denied by you", "docs": "answered at its own prompt"}
    assert shift.ledger()["blocked"][1]["request"] == ""  # Pointe never saw what the terminal asked


def test_nothing_in_the_rules_can_answer_a_request():
    """nightshift.py holds no way to allow or deny: it has no verdict to give and nowhere to send one."""
    source = (ROOT / "nightshift.py").read_text()
    for forbidden in ("_apply_answer", "_deliver_verdict", "permission_answer", "set_result", "post_channel", "/verdict"):
        assert forbidden not in source, forbidden


# ---------- the ledger on disk ----------

def test_the_ledger_survives_a_restart_as_it_was(tmp_path):
    store = ns.Store(tmp_path / "night-shifts.json")
    shift = shift_of(("billing", ["fix the retry tests", "open a PR"]), ("docs", ["update the changelog"]))
    billing, docs = started(shift)
    shift.report(billing, ns.read_report(REPORT), 1100.0)
    shift.tick(docs, 1100.0, present=True, request_id="p9", request=REQUEST)
    store.add(shift)
    again = ns.Store(tmp_path / "night-shifts.json")
    assert again.current is not None and again.current.to_dict() == shift.to_dict()
    assert again.current.front_of("docs").waiting_on == "p9" and again.current.ledger() == shift.ledger()
    assert stat.S_IMODE(os.stat(tmp_path / "night-shifts.json").st_mode) == 0o600


def test_the_store_keeps_seven_and_a_damaged_file_is_an_empty_history(tmp_path):
    store = ns.Store(tmp_path / "n.json")
    for i in range(ns.HISTORY + 3):
        s = shift_of(("billing", ["a"]), now=1000.0 + i)
        s.end("stopped", 1001.0 + i)
        store.add(s)
    assert len(ns.Store(tmp_path / "n.json").items) == ns.HISTORY and store.current is None and store.latest is not None
    (tmp_path / "bad.json").write_text("{not json")
    assert ns.Store(tmp_path / "bad.json").items == []


def test_a_secret_in_a_report_never_reaches_the_ledger():
    import fake_secrets

    key = fake_secrets.GITHUB_TOKEN if hasattr(fake_secrets, "GITHUB_TOKEN") else "ghp_" + "a1B2" * 9
    shift = shift_of(("billing", ["rotate the token"]))
    (front,) = started(shift)
    shift.report(front, ns.read_report(f"NIGHT REPORT\nSTATUS: done\nDONE: rotated, the new token is {key}"), 1100.0)
    shift.tick(front, 1100.0, present=True)
    assert key not in json.dumps(shift.to_dict()) and key not in ns.written(shift)


def test_since_picks_the_shift_a_briefing_leads_with(tmp_path):
    store = ns.Store(tmp_path / "n.json")
    old = shift_of(("billing", ["a"]), now=1000.0)
    old.end("complete", 2000.0)
    store.add(old)
    assert store.since(1500.0) is old and store.since(2500.0) is None
    running = shift_of(("docs", ["b"]), now=3000.0)
    store.add(running)
    assert store.since(9e9) is running


# ---------- the morning ----------

def night_with_everything() -> ns.Shift:
    shift = shift_of(("billing", ["fix the retry tests", "push the branch"]), ("docs", ["update the changelog"]),
                     ("shop", ["fix the flaky test"]), ("web", ["tidy the styles"]))
    billing, docs, shop, _web = started(shift)
    shift.report(billing, ns.read_report(REPORT), 1100.0)
    shift.sent_to(billing, "task", 1100.0)
    shift.tick(billing, 1200.0, present=True, request_id="p1", request=REQUEST)
    shift.report(docs, ns.read_report("Old format or new?"), 1300.0)
    shift.report(shop, ns.read_report("NIGHT REPORT\nSTATUS: blocked\nBLOCKED: the fixture server is down"), 1400.0)
    return shift


def test_the_morning_leads_with_decisions_then_questions_then_done_then_blocked():
    shift = night_with_everything()
    shift.end("hours", 30000.0)
    parts = ns.morning(shift)
    assert [p["kind"] for p in parts] == ["headline", "decided", "asked", "done", "blocked", "in_flight"]
    head = parts[0]["text"]
    assert "1 of 5 tasks done" in head and "2 blocked" in head and "it ran out of hours" in head
    assert "1 decision made without you, 1 question waiting on you" in head
    assert "cap the backoff?" in parts[1]["text"] and "It chose: 30 seconds." in parts[1]["text"]
    assert "?." not in ns.written(shift) and ".." not in ns.written(shift)
    assert "If you want otherwise: change MAX_BACKOFF" in parts[1]["text"]
    assert "docs asks: Old format or new?" in parts[2]["text"]
    assert "42 of 42" in parts[3]["text"]
    assert "the fixture server is down" in parts[4]["text"]


def test_a_spoken_approval_is_named_never_quoted():
    shift = night_with_everything()
    said = ns.written(shift)
    assert "billing waits for your approval; say \"approve billing\" to hear the request." in said
    assert "git push" not in said and "retry-work" not in said  # the exact request is on the screen and in the read-out
    assert shift.ledger()["blocked"][0]["request"] == REQUEST


def test_a_quiet_shift_says_so_plainly():
    shift = shift_of(("billing", ["a"]))
    started(shift)
    (only,) = [p for p in ns.morning(shift) if p["kind"] == "headline"]
    assert "0 of 1 task done, 0 blocked; it is still running. 0 decisions made without you, 0 questions" in only["text"]


def test_a_briefing_speaks_the_nights_report_before_any_session():
    lead = [p["text"] for p in ns.morning(night_with_everything())]
    other = briefing.Section(session="lantern", status="done", text="lantern: merged the importer.")
    b = briefing.assemble([other], "overnight", "normal", 0.0, 100.0, lead=lead, night="abc")
    parts = b.parts()
    assert parts[:len(lead)] == lead and parts[len(lead)].endswith("lantern: merged the importer.")
    assert parts[1].startswith("Decisions made without you.") and parts[2].startswith("Questions waiting on you.")
    assert b.written().index("Decisions made without you") < b.written().index("lantern: merged")
    assert briefing.Briefing.from_dict(b.to_dict()).parts() == parts and b.night == "abc" and not b.empty


def test_with_a_nights_report_a_quiet_rest_is_not_called_a_quiet_night():
    lead = [p["text"] for p in ns.morning(night_with_everything())]
    quiet = briefing.Section(session="lantern", status="quiet", text="lantern: nothing new.")
    for sections in ([], [quiet]):
        b = briefing.assemble(sections, "overnight", "normal", 0.0, 100.0, lead=lead)
        assert b.parts() == lead and "Quiet night" not in b.written() and not b.empty
    assert briefing.assemble([], "overnight", "normal", 0.0, 100.0).parts() == ["Quiet night. Nothing waits on you."]


def test_an_older_briefing_on_disk_still_loads():
    b = briefing.assemble([], "overnight", "normal", 0.0, 100.0)
    old = {k: v for k, v in b.to_dict().items() if k not in ("lead", "night")}
    assert briefing.Briefing.from_dict(old).parts() == b.parts()


# ---------- the daemon: read-back, yes, the loop, approvals ----------

@pytest.fixture
def night(home, monkeypatch):  # noqa: F811
    """`home` (shop and billing on the voice, in real folders) plus docs, and a night store of its own."""
    d = home.d  # noqa: F811
    monkeypatch.setattr(d, "NIGHT", ns.Store(home.tmp / "night-shifts.json"))
    monkeypatch.setattr(d, "_NIGHT_WATCH", {})
    monkeypatch.setattr(d, "_NIGHT_SEEN", set())
    monkeypatch.setattr(d, "BRIEFINGS", briefing.Store(home.tmp / "briefings.json"))
    home.docs = _folder(home.tmp, "docs")
    add(d, "s3", "docs", cwd=home.docs)
    d.REGISTRY.set_active("s1")
    return home


async def _say(d, said: str | None, heard_own_words: bool = False, spoken: bool = True) -> dict:  # noqa: F811
    """The user said `said` (None: nothing new), then the model called night_shift; a read-back is then said (unless
    `spoken` is False), as the model's reply would say it on a call."""
    if said is not None:
        await d.on_user_utterance(said)
        d.state.heard_own_words = heard_own_words
    p = Params(tasks="whatever the model wrote")
    await d.night_shift(p)
    if spoken and "confirm_first" in p.results[0]:
        await model_says(d)
    return p.results[0]


async def _settle(d, secs: float = 0.5) -> None:  # noqa: F811
    deadline = time.time() + secs
    while time.time() < deadline and any(s.state == "starting" for s in d.STARTS.values()):
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)


TWO = "Tonight: billing finishes the retry work and opens a PR; docs updates the changelog."
TWO_LINE = ("Night shift. billing: finishes the retry work and opens a PR. docs: updates the changelog. Up to 8 hours and "
            "40 messages. I approve nothing: a session that needs approval waits for you. Start?")


def test_the_plan_is_read_back_exactly_and_nothing_is_sent(night):
    result = asyncio.run(_say(night.d, TWO))
    assert result["confirm_first"] == TWO_LINE, result
    assert night.sent == [] and night.d.NIGHT.current is None


def test_a_new_session_in_the_plan_is_read_back_with_its_final_name(night):
    result = asyncio.run(_say(night.d, EVENING))
    assert "A new Codex session in shop, named shop-2: fix the flaky test." in result["confirm_first"], result
    assert night.started == [] and night.sent == []


@pytest.mark.parametrize("yes", ["Yes.", "go ahead", "כן"])
def test_a_plain_yes_starts_the_shift_and_each_session_gets_its_task_in_the_night_brief(night, yes):
    d = night.d  # noqa: F811

    async def scenario():
        await _say(d, TWO)
        return await _say(d, yes)

    done = asyncio.run(scenario())
    assert done["started"] is True and done["sessions"] == ["billing", "docs"], done
    assert night.sent == [("billing", ns.message("task", "finishes the retry work and opens a PR")),
                          ("docs", ns.message("task", "updates the changelog"))]
    shift = d.NIGHT.current
    assert shift.sent == 2 and shift.how == "voice" and [f.state for f in shift.fronts] == ["working", "working"]
    assert json.loads((night.tmp / "night-shifts.json").read_text())["items"][0]["id"] == shift.id


@pytest.mark.parametrize("answer", ["no", "wait, not docs", "what is billing doing?", "hmm"])
def test_anything_but_a_plain_yes_starts_nothing(night, answer):
    async def scenario():
        await _say(night.d, TWO)
        return await _say(night.d, answer)

    result = asyncio.run(scenario())
    assert "error" in result and night.sent == [] and night.d.NIGHT.current is None and night.d.state.pending_shift is None


def test_the_read_back_heard_back_and_typed_words_are_not_a_yes(night):
    async def scenario():
        await _say(night.d, TWO)
        return await _say(night.d, "yes", heard_own_words=True)

    assert "error" in asyncio.run(scenario()) and night.sent == [] and night.d.NIGHT.current is None


def test_a_yes_long_after_the_read_back_starts_nothing(night):
    d = night.d  # noqa: F811

    async def scenario():
        await _say(d, TWO)
        d.state.pending_shift = (d.state.pending_shift[0] - ns.CONFIRM_SECS - 60, d.state.pending_shift[1])
        return await _say(d, "yes")

    assert "error" in asyncio.run(scenario()) and night.sent == []


def test_the_model_calling_again_before_the_answer_starts_nothing(night):
    async def scenario():
        await _say(night.d, TWO)
        return await _say(night.d, None)

    result = asyncio.run(scenario())
    assert "Nothing started yet" in result["error"] and night.sent == [] and night.d.state.pending_shift is not None


def test_the_models_arguments_start_nothing_the_user_did_not_ask_for(night):
    result = asyncio.run(_say(night.d, "what is billing doing?"))
    assert "did not ask for a night shift" in result["error"] and night.d.state.pending_shift is None and night.sent == []


def test_with_the_voice_lock_on_only_the_owners_yes_starts(night, monkeypatch):
    d = night.d  # noqa: F811
    monkeypatch.setattr(d, "lock_level", lambda: "approvals")
    monkeypatch.setattr(d.VOICE, "confident", lambda verdict: False)

    async def scenario():
        await _say(d, TWO)
        return await _say(d, "yes")

    assert "not clearly the owner's voice" in asyncio.run(scenario())["error"] and night.sent == []


def test_the_yes_that_starts_a_shift_never_approves_a_waiting_prompt(night, monkeypatch):
    d = night.d  # noqa: F811
    posts = record_channel(d, monkeypatch)
    shop = d.REGISTRY.sessions["s1"]
    shop.channel_url = "http://127.0.0.1:1/ch"
    shop.permission_id, shop.permission_delivered_at, shop.permission_spoken = "p1", 1.0, "run the tests"
    d.state.conn = fake_conn(bot_started_at=2.0)

    async def scenario():
        await _say(d, TWO)
        d.state.conn.injector.bot_started_at = time.time()  # the read-back is spoken
        return await _say(d, "yes")

    assert asyncio.run(scenario())["started"] is True
    assert verdicts(posts) == [] and shop.permission_id == "p1"


@pytest.mark.parametrize("mode", ["meeting", "challenge", "running"])
def test_a_shift_cannot_start_in_a_read_only_mode_or_on_top_of_another(night, mode):
    d = night.d  # noqa: F811
    if mode == "meeting":
        d.state.meeting = SimpleNamespace(status=lambda: {}, mode="listening", hand=None)
    elif mode == "challenge":
        d.state.challenge = SimpleNamespace()
    else:
        asyncio.run(d.begin_shift(d._check_shift([ns.Item(task="a", session_id="s2", name="billing")]),
                                  d._shift_caps(), "page"))
        night.sent.clear()
    assert d._night_refusal()
    client = client_for(d)
    r = client.post("/voice/night-shift", json={"action": "start", "items": [{"session": "docs", "task": "update the changelog"}]})
    assert r.status_code == 409 and night.sent == []
    assert "night_shift" not in d.modes.READ_ONLY_TOOLS


def test_a_session_on_another_machine_is_refused(night):
    d = night.d  # noqa: F811
    add(d, "s4", "ledger", cwd="/tmp", machine="devbox")
    result = asyncio.run(_say(d, "tonight ledger reconciles the accounts"))
    assert "another machine" in result["error"] and night.sent == []
    with pytest.raises(d.StartRefused):
        d._check_shift([ns.Item(task="x", session_id="s4", name="ledger")])


def _begin(night, items, **caps):
    d = night.d  # noqa: F811
    return asyncio.run(d.begin_shift(d._check_shift(items), d._shift_caps(**caps), "page"))


def _finished(d, session, final: str, digest: dict | None = None):  # noqa: F811
    """The session ended a turn with this final message: what daemon.feed does after the report digest."""
    return d._night_report(session, {**(digest or {}), "final": final})


def test_a_report_moves_the_session_to_its_next_task_with_no_call_up(night, monkeypatch):
    d = night.d  # noqa: F811
    billing = d.REGISTRY.sessions["s2"]
    _begin(night, [ns.Item(task="fix the retry tests", session_id="s2"), ns.Item(task="open a PR", session_id="s2")])
    assert d.state.conn is None

    async def digest(session, text):
        return {"final": text.split(d.FINAL_MARK, 1)[-1]}

    monkeypatch.setattr(d, "_digest_turn", digest)
    asyncio.run(d.feed(billing, f"[claude-code {d.FINISHED_MARK} {d.FINAL_MARK}{REPORT}", True))
    assert [m for _, m in night.sent] == [ns.message("task", "fix the retry tests"), ns.message("task", "open a PR")]
    ledger = d.NIGHT.current.ledger()
    assert ledger["done"][0]["commit"] == "3f2a9c1" and ledger["in_flight"][0]["task"] == "open a PR"


def test_everything_a_shift_sends_is_one_of_the_templates(night):
    d = night.d  # noqa: F811
    billing, docs = d.REGISTRY.sessions["s2"], d.REGISTRY.sessions["s3"]
    _begin(night, [ns.Item(task="fix the retry tests", session_id="s2"), ns.Item(task="update the changelog", session_id="s3")])

    async def scenario():
        await _finished(d, docs, "Old format or new?", {"waiting": True, "questions": ["Old format or new?"]})
        await _finished(d, billing, "I read the tests.")
        await _finished(d, billing, "NIGHT REPORT\nSTATUS: working\nDONE: 2 of 5")
        task = d.NIGHT.current.fronts[0].task()  # billing goes quiet
        task.sent_at, task.reported_at = task.sent_at - 9999, task.reported_at - 9999
        billing.busy = False
        await d._night_tick(time.time())

    asyncio.run(scenario())
    allowed = {ns.message(k, t) for k in ns.TEMPLATES for t in ("fix the retry tests", "update the changelog")}
    assert len(night.sent) == 6 and all(text in allowed for _, text in night.sent)
    kinds = [next(k for k in ns.TEMPLATES if text == ns.message(k, "fix the retry tests") or text == ns.message(k, "update the changelog"))
             for _, text in night.sent]
    assert kinds == ["task", "task", "decide", "report", "continue", "status"]


def test_a_turn_that_answered_the_user_is_not_taken_for_the_nights_report(night):
    d = night.d  # noqa: F811
    billing = d.REGISTRY.sessions["s2"]
    _begin(night, [ns.Item(task="fix the retry tests", session_id="s2")])
    billing.last_delegation_at = time.time() + 1  # the user sent it something themselves since
    asyncio.run(_finished(d, billing, "The answer to your question is 42."))
    assert len(night.sent) == 1 and d.NIGHT.current.fronts[0].task().followups == 0


def test_a_new_session_gets_its_task_when_it_joins(night):
    d = night.d  # noqa: F811

    async def scenario():
        await d.begin_shift(d._check_shift([ns.Item(task="fix the flaky test", start={"harness": "codex", "folder": night.shop})]),
                            d._shift_caps(), "page")
        await _settle(d)

    asyncio.run(scenario())
    assert [(h, cwd, name) for h, cwd, name, _ in night.started] == [("codex", night.shop, "shop-2")]
    assert night.sent == [("shop-2", ns.message("task", "fix the flaky test"))]
    front = d.NIGHT.current.fronts[0]
    assert front.state == "working" and front.session == "shop-2" and front.session_id in d.REGISTRY.sessions


def test_a_new_session_is_checked_exactly_as_new_session_checks_it(night):
    d = night.d  # noqa: F811
    with pytest.raises(d.StartRefused, match="not one you already work in"):
        d._check_shift([ns.Item(task="x", start={"harness": "codex", "folder": "/etc"})])
    with pytest.raises(d.StartRefused, match="same name"):
        d._check_shift([ns.Item(task="x", start={"harness": "codex", "folder": night.shop}),
                        ns.Item(task="y", start={"harness": "codex", "folder": night.shop})])


def test_a_message_claude_code_held_parks_the_front(night, monkeypatch):
    d = night.d  # noqa: F811
    billing = d.REGISTRY.sessions["s2"]

    async def deliver(session, text):
        session.held_at = time.time() + 1
        return True

    monkeypatch.setattr(d, "deliver", deliver)
    _begin(night, [ns.Item(task="fix the retry tests", session_id="s2")])
    shift = d.NIGHT.latest
    assert shift.sent == 0 and shift.fronts[0].state == "parked" and billing.held_at
    assert "crossSessionInbound" in shift.ledger()["blocked"][0]["text"]


# ----- the safety rails, in the daemon -----

def _hook(d, session, command="git push origin retry-work"):  # noqa: F811
    return d._harness_permission(session, "Bash", {"command": command, "description": "push the branch"})


def test_a_request_from_a_shift_session_is_held_unanswered_and_written_down_word_for_word(night, monkeypatch):
    d = night.d  # noqa: F811
    billing = d.REGISTRY.sessions["s2"]
    _begin(night, [ns.Item(task="fix the retry work and open a PR", session_id="s2")])
    night.sent.clear()
    answered = []
    monkeypatch.setattr(d, "_apply_answer", lambda *a, **k: answered.append(a))
    monkeypatch.setattr(d, "_deliver_verdict", lambda *a, **k: answered.append(a))

    async def scenario():
        held = asyncio.create_task(_hook(d, billing))
        await asyncio.sleep(0.2)
        state = (held.done(), billing.permission_id, billing.permission_until - time.time())
        await d._night_tick(time.time())
        await d._night_tick(time.time())
        held.cancel()
        return state

    done, request_id, left = asyncio.run(scenario())
    assert not done and request_id and answered == []  # no call is up, and it was neither allowed nor denied
    assert left > ns.PARK_SECS - 60  # held for the night, not for 280 seconds
    (entry,) = d.NIGHT.current.ledger()["blocked"]
    assert entry["request_id"] == request_id and entry["waits_on"] == "your approval"
    assert entry["request"] == 'Bash\n{"command": "git push origin retry-work"}'  # what runs; never the model's description
    assert night.sent == [] and d.NIGHT.current.fronts[0].state == "waiting"


def test_a_session_that_is_not_on_a_shift_still_goes_to_its_terminal_with_no_call(night):
    d = night.d  # noqa: F811
    _begin(night, [ns.Item(task="a", session_id="s2")])
    shop = d.REGISTRY.sessions["s1"]
    assert asyncio.run(_hook(d, shop)) is None and shop.permission_id is None


def test_the_end_of_a_call_does_not_hand_a_shifts_request_back(night):
    d = night.d  # noqa: F811
    billing, shop = d.REGISTRY.sessions["s2"], d.REGISTRY.sessions["s1"]
    _begin(night, [ns.Item(task="a", session_id="s2")])

    async def scenario():
        loop = asyncio.get_running_loop()
        billing.permission_answer, shop.permission_answer = loop.create_future(), loop.create_future()
        d._hand_prompts_back()
        return billing.permission_answer.done(), shop.permission_answer.done()

    assert asyncio.run(scenario()) == (False, True)


def test_the_users_tap_in_the_morning_answers_it_through_the_normal_route(night):
    d = night.d  # noqa: F811
    billing = d.REGISTRY.sessions["s2"]
    _begin(night, [ns.Item(task="fix the retry work and open a PR", session_id="s2")])

    async def scenario():
        held = asyncio.create_task(_hook(d, billing))
        await asyncio.sleep(0.2)
        request_id = billing.permission_id
        d.NIGHT.current.end("hours", time.time())  # the shift is over; the request still waits
        d.NIGHT.save()
        assert await d._apply_answer(billing, request_id, "allow", "tapped")  # what /voice/approve calls
        return await asyncio.wait_for(held, 3)

    assert asyncio.run(scenario()) == "allow"
    (entry,) = d.NIGHT.latest.ledger()["blocked"]
    assert entry["resolved"] == "approved by you" and billing.permission_id is None


def test_approve_billings_push_reads_the_request_out_and_approves_nothing(night, monkeypatch):
    d = night.d  # noqa: F811
    billing = d.REGISTRY.sessions["s2"]
    _begin(night, [ns.Item(task="fix the retry work and open a PR", session_id="s2")])
    asked = []

    async def ask(session):
        asked.append(session.name)

    monkeypatch.setattr(d, "_ask_permission", ask)

    async def scenario():
        held = asyncio.create_task(_hook(d, billing))
        await asyncio.sleep(0.2)
        d.state.conn = fake_conn(bot_started_at=time.time())
        waits = d._night_release("approve billing's push")
        assert waits is billing and d._night_release("tell billing to approve the PR") is None
        await d.activate(waits)
        await d.on_user_utterance("approve billing's push")  # the same words, as a turn: they answer nothing
        state = (held.done(), billing.permission_id is not None)
        held.cancel()
        return state

    assert asyncio.run(scenario()) == (False, True)
    assert asked == ["billing"] and d.REGISTRY.active is billing


def test_no_night_shift_code_in_the_daemon_can_answer_a_request(d):  # noqa: F811
    """The shift's functions never reach the code that delivers a verdict. `_night_answered` is called by it, after the
    user's own answer, and only writes the ledger."""
    night_code = {name: inspect.getsource(fn) for name, fn in vars(d).items()
                  if inspect.isfunction(fn) and fn.__module__ == d.__name__
                  and re.match(r"_?night_|_shift_|begin_shift|stop_shift|_check_shift|_begin_pending", name)}
    assert len(night_code) >= 20, sorted(night_code)
    for name, source in night_code.items():
        for forbidden in ("_apply_answer", "_deliver_verdict", "_deliver_remote", "permission_answer.set_result",
                          "/verdict", "/voice/approve", "behavior"):
            assert forbidden not in source, (name, forbidden)
    callers = [n for n, fn in vars(d).items() if inspect.isfunction(fn) and fn.__module__ == d.__name__
               and "_apply_answer(" in inspect.getsource(fn) and n != "_apply_answer"]
    assert sorted(callers) == sorted(c for c in callers if not re.match(r"_?night|_shift|begin_shift", c))


def test_the_hook_waits_as_long_as_a_night(tmp_path):
    hook = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]["PermissionRequest"][0]["hooks"][0]
    script = (ROOT / "bin" / "voice-permission-hook").read_text()
    waits = int(re.search(r"--max-time (\d+)", script).group(1))
    assert hook["timeout"] >= ns.PARK_SECS and ns.PARK_SECS <= waits < hook["timeout"]
    assert harnesses.get("claude-code").permission_deadline == 280.0  # an ordinary request is let go as before


def test_a_shifts_blockers_are_quiet_until_morning_unless_asked_for(night):
    d = night.d  # noqa: F811
    billing, shop = d.REGISTRY.sessions["s2"], d.REGISTRY.sessions["s1"]
    for s in (billing, shop):
        s.permission_id, s.permission_since = f"p-{s.name}", time.time()
    _begin(night, [ns.Item(task="a", session_id="s2")])
    quiet = {i["session"]: i["quiet"] for i in d._attention()}
    assert quiet == {"billing": True, "shop": False}  # still listed for the screens, with no notification
    d.NIGHT.current.notify = True
    assert {i["session"]: i["quiet"] for i in d._attention()} == {"billing": False, "shop": False}
    d.NIGHT.current.notify = False
    d.state.conn = fake_conn()  # the user is on a call: they are there to be told
    assert not d._night_quiet(billing)
    d.state.conn = None
    client_for(d).post("/voice/night-shift", json={"action": "stop"})
    assert not d._night_quiet(billing)  # they came back to it
    assert d.PREFS.get("nightshift.notify") is False and d.PREFS.all()["nightshift.hours"] == ns.HOURS


def test_stop_by_voice_needs_no_read_back_and_nothing_is_sent_after(night):
    d = night.d  # noqa: F811
    billing = d.REGISTRY.sessions["s2"]
    _begin(night, [ns.Item(task="a", session_id="s2"), ns.Item(task="b", session_id="s2")])
    d.state.conn = fake_conn()

    async def scenario():
        assert not await d._night_stop_words("stop")
        assert await d._night_stop_words("stop the night shift")
        await _finished(d, billing, "NIGHT REPORT\nSTATUS: done\nDONE: a")
        await d._night_tick(time.time() + 99999)

    asyncio.run(scenario())
    shift = d.NIGHT.latest
    assert not shift.on and shift.why == "stopped" and len(night.sent) == 1
    assert "stopped the night shift" in d.state.conn.injector.fed[-1][0]


def test_stop_and_start_from_a_screen(night):
    d = night.d  # noqa: F811
    client = client_for(d)
    assert client.post("/voice/night-shift", json={"action": "stop"}).status_code == 409
    r = client.post("/voice/night-shift", json={"action": "start", "hours": 2, "messages": 5, "notify": True, "items": [
        {"session": "billing", "task": "fix the retry tests"}, {"session": "docs", "task": "  update the changelog  "},
        {"start": {"harness": "codex", "folder": night.shop}, "task": "fix the flaky test"}]})
    assert r.status_code == 200 and r.json()["shift"]["tasks"] == 3, r.text
    shift = d.NIGHT.current
    assert (shift.hours, shift.messages, shift.notify, shift.how) == (2, 5, True, "page")
    assert ("docs", ns.message("task", "update the changelog")) in night.sent
    status = client.get("/voice/status").json()
    assert status["night_shift"]["on"] and status["night_shift"]["tasks"] == 3 and status["shift_pending"] is None
    view = client.get("/voice/night-shift").json()
    assert view["shift"]["id"] == shift.id and set(view["shift"]["ledger"]) == {"done", "in_flight", "blocked", "decided", "asked", "not_started"}
    assert view["caps"] == {"hours": 2, "messages": 5, "notify": True} and view["rule"] == ns.RULE  # the sheet's caps are kept
    assert [s["name"] for s in view["sessions"]] == ["shop", "billing", "docs", "shop-2"]
    stopped = client.post("/voice/night-shift", json={"action": "stop"})
    assert stopped.status_code == 200 and not d.NIGHT.latest.on and d.NIGHT.latest.why == "stopped"
    assert client.get(f"/voice/night-shift?id={shift.id}").json()["shift"]["why"] == "stopped"


@pytest.mark.parametrize("body", [
    {"action": "start"}, {"action": "start", "items": []}, {"action": "start", "items": [{"session": "billing"}]},
    {"action": "start", "items": [{"session": "billing", "task": "x"}], "hours": 99},
    {"action": "start", "items": [{"session": "billing", "task": "x"}], "messages": 0},
    {"action": "start", "items": [{"session": "nobody", "task": "x"}]},
    {"action": "start", "items": [{"start": {"harness": "codex", "folder": "/etc"}, "task": "x"}]},
    {"action": "approve"}, {"action": "confirm", "id": "nope"}])
def test_a_bad_request_starts_nothing(night, body):
    r = client_for(night.d).post("/voice/night-shift", json=body)
    assert r.status_code in (400, 403, 409) and night.d.NIGHT.current is None and night.sent == [], r.text


def test_a_tap_on_the_read_backs_card_starts_or_drops_it(night):
    d = night.d  # noqa: F811
    client = client_for(d)
    asyncio.run(_say(d, TWO))
    card = client.get("/voice/status").json()["shift_pending"]
    assert card["line"] == TWO_LINE and [i["session"] for i in card["items"]] == ["billing", "docs"]
    assert client.post("/voice/night-shift", json={"action": "cancel", "id": card["id"]}).json() == {"cancelled": True}
    assert d.NIGHT.current is None and night.sent == []
    asyncio.run(_say(d, TWO))
    card = client.get("/voice/status").json()["shift_pending"]
    assert client.post("/voice/night-shift", json={"action": "confirm", "id": card["id"]}).status_code == 200
    assert d.NIGHT.current.how == "page" and len(night.sent) == 2


def test_the_phones_key_reaches_the_night_shift_and_nothing_new(night):
    from guards import _PHONE_PATHS

    assert "/voice/night-shift" in _PHONE_PATHS


def test_the_caps_come_from_settings(night):
    d = night.d  # noqa: F811
    d.PREFS.update({"nightshift.hours": 2, "nightshift.messages": 12})
    assert "Up to 2 hours and 12 messages." in asyncio.run(_say(d, TWO))["confirm_first"]
    for bad in ({"nightshift.hours": 13}, {"nightshift.messages": 0}, {"nightshift.notify": "yes"}):
        with pytest.raises(ValueError):
            d.PREFS.update(bad)


def test_with_no_call_the_keeper_follows_the_shifts_sessions_and_a_call_takes_over(night, monkeypatch):
    d = night.d  # noqa: F811
    watched = []

    def watch(session, feed):
        async def follow():
            watched.append(session.name)
            await asyncio.sleep(3600)
        return [follow()]

    monkeypatch.setattr(harnesses.get("claude-code"), "watch", watch)

    async def scenario():
        await d.begin_shift(d._check_shift([ns.Item(task="a", session_id="s2")]), d._shift_caps(), "page")
        await d._night_tick(time.time())
        await asyncio.sleep(0.01)
        first = (list(watched), set(d._NIGHT_WATCH))
        d.state.conn = fake_conn()
        await d._night_tick(time.time())
        return first, set(d._NIGHT_WATCH)

    (names, during), after = asyncio.run(scenario())
    assert names == ["billing"] and during == {"s2"} and after == set()  # shop and docs are not on the shift


def test_the_keeper_ends_a_shift_at_its_hours_and_sends_nothing_after(night):
    d = night.d  # noqa: F811
    _begin(night, [ns.Item(task="a", session_id="s2")], hours=1)
    asyncio.run(d._night_tick(time.time() + 3601))
    assert not d.NIGHT.latest.on and d.NIGHT.latest.why == "hours" and len(night.sent) == 1
    assert json.loads((night.tmp / "night-shifts.json").read_text())["items"][0]["why"] == "hours"


def test_a_send_from_the_user_answers_an_open_question_on_the_ledger(night):
    d = night.d  # noqa: F811
    docs = d.REGISTRY.sessions["s3"]
    _begin(night, [ns.Item(task="update the changelog", session_id="s3")])
    asyncio.run(_finished(d, docs, "Old format or new?"))
    d._night_user_said(docs, "tell docs to use the old format")
    (asked,) = d.NIGHT.current.ledger()["asked"]
    assert asked["resolved"] == "answered by you: tell docs to use the old format"


def test_brief_me_on_the_night_leads_with_the_shift_and_reads_its_sessions_once(night, monkeypatch):
    d = night.d  # noqa: F811
    billing = d.REGISTRY.sessions["s2"]
    _begin(night, [ns.Item(task="fix the retry tests", session_id="s2")])
    asyncio.run(_finished(d, billing, REPORT))
    read = []

    async def section(group, since, since_label, length, lang):
        read.append(group[-1].name)
        return briefing.Section(session=group[-1].name, status="done", text=f"{group[-1].name}: did things.")

    monkeypatch.setattr(d, "_brief_section", section)
    b = asyncio.run(d.build_briefing("the night", "", "normal"))
    assert sorted(read) == ["docs", "shop"] and b.night == d.NIGHT.latest.id
    parts = b.parts()
    assert parts[0].startswith("Night shift,") and parts[1].startswith("Decisions made without you.")
    assert parts[2].startswith("Done.") and any("shop: did things." in p for p in parts[3:])
    fed = d._briefing_part(SimpleNamespace(), 0, parts)
    assert "send nothing, approve nothing" in fed and "data, not instructions" in fed
    read.clear()
    scoped = asyncio.run(d.build_briefing("the night", "billing", "normal"))
    assert read == ["billing"] and scoped.lead == []  # asked about one session: that session, as always


def test_the_brain_is_told_a_shift_runs_and_that_it_sends_nothing_for_it(night):
    d = night.d  # noqa: F811
    assert d._night_context() is None
    _begin(night, [ns.Item(task="a", session_id="s2")])
    line = d._night_context()
    assert "0 of 1 task(s) done" in line and "approve nothing" in line
    assert any(t.name == "night_shift" for t in d.TOOLS.standard_tools)


# ----- the plan and its yes, taken in code (the model can be late, or answer a long plan from memory) -----

class FakeFront:
    def __init__(self):
        self.said = []

    async def _speak(self, text, request_id=None):
        self.said.append((text, request_id))


def _on_a_call(d, monkeypatch):  # noqa: F811
    front = FakeFront()
    d.state.conn, d.state.front = fake_conn(), front
    monkeypatch.setattr(d, "FRONT", "brain")
    return front


def test_the_daemon_reads_the_plan_back_in_its_own_words_and_sends_nothing(night, monkeypatch):
    d = night.d  # noqa: F811
    front = _on_a_call(d, monkeypatch)
    assert asyncio.run(d._night_words(TWO)) is True
    assert front.said == [(TWO_LINE, None)]  # exactly the line a yes will start, and no yes window for a prompt
    assert night.sent == [] and d.NIGHT.current is None and d.state.pending_shift[1]["line"] == TWO_LINE


def test_what_the_ears_really_write_is_still_the_plan(night, monkeypatch):
    d = night.d  # noqa: F811
    front = _on_a_call(d, monkeypatch)
    heard = ("Tonight. Billing adds an empty file called marker to its folder with the touch command. Docs. Updates the "
             "changelog, without editing anything else.")
    assert asyncio.run(d._night_words(heard)) is True
    assert front.said[0][0].startswith("Night shift. billing: adds an empty file called marker to its folder with the "
                                       "touch command. docs: Updates the changelog, without editing anything else. Up to")


@pytest.mark.parametrize("answer, starts", [("Yes.", True), ("no", False), ("stop, not that", False)])
def test_the_yes_or_no_after_it_is_taken_in_code_too(night, monkeypatch, answer, starts):
    d = night.d  # noqa: F811
    _on_a_call(d, monkeypatch)

    async def scenario():
        await d._night_words(TWO)
        return await d._night_words(answer)

    assert asyncio.run(scenario()) is True
    assert (d.NIGHT.current is not None) == starts and len(night.sent) == (2 if starts else 0)
    assert d.state.pending_shift is None
    told = d.state.conn.injector.fed[-1][0]
    assert told.startswith("[night shift started]" if starts else "[night shift not started]")


def test_words_that_are_not_a_plan_or_its_answer_go_to_the_model(night, monkeypatch):
    d = night.d  # noqa: F811
    front = _on_a_call(d, monkeypatch)

    async def scenario():
        first = [await d._night_words(w) for w in ("tonight I am going out", "what is billing doing?", "yes")]
        await d._night_words(TWO)
        return first, await d._night_words("what is billing doing?")

    first, question = asyncio.run(scenario())
    assert first == [False, False, False] and question is False  # a question after the read-back: the model answers
    assert len(front.said) == 1 and night.sent == [] and d.NIGHT.current is None


def test_the_yes_taken_in_code_keeps_the_owner_rule_and_the_echo_rule(night, monkeypatch):
    d = night.d  # noqa: F811
    _on_a_call(d, monkeypatch)
    monkeypatch.setattr(d, "lock_level", lambda: "approvals")
    monkeypatch.setattr(d.VOICE, "confident", lambda verdict: False)

    async def scenario():
        await d._night_words(TWO)
        await d._night_words("yes")
        d.lock_level = lambda: "off"
        await d._night_words(TWO)
        monkeypatch.setattr(d.ECHO, "repeats_bot", lambda text: True)  # the read-back, heard back through the speakers
        return await d._night_words("yes")

    asyncio.run(scenario())
    assert night.sent == [] and d.NIGHT.current is None


def test_a_refused_plan_is_said_and_nothing_waits(night, monkeypatch):
    d = night.d  # noqa: F811
    _on_a_call(d, monkeypatch)
    assert asyncio.run(d._night_words("tonight billing")) is True
    assert "Ask what billing should do tonight" in d.state.conn.injector.fed[-1][0] and d.state.pending_shift is None


def test_the_minute_for_a_yes_starts_when_a_long_read_back_ends(night, monkeypatch):
    d = night.d  # noqa: F811
    _on_a_call(d, monkeypatch)
    asyncio.run(d._night_words(TWO))
    at, plan = d.state.pending_shift
    assert plan["say_secs"] == pytest.approx(len(plan["line"].split()) / ns.WORDS_PER_SEC)
    d.state.pending_shift = (at - ns.CONFIRM_SECS - 1, plan)  # a minute after it began to be said: it had not ended yet
    assert d._shift_pending() is not None and d._shift_pending_view()["expires_in"] > 0
    d.state.pending_shift = (at - ns.CONFIRM_SECS - plan["say_secs"] - 1, plan)
    assert d._shift_pending() is None


def test_the_spoken_report_cuts_a_long_answer_and_the_ledger_keeps_all_of_it():
    shift = shift_of(("docs", ["update the changelog"]))
    (front,) = started(shift)
    long = " ".join(f"w{i}" for i in range(60))
    shift.report(front, ns.read_report(f"NIGHT REPORT\nSTATUS: done\nDONE: {long}\nDECIDED: which? -> {long} -> {long}"), 1100.0)
    for part in ns.morning(shift)[1:]:
        assert "w59" not in part["text"] and len(part["text"].split()) < 3 * ns.SAID_WORDS + 20, part["kind"]
    assert "w59" in shift.ledger()["decided"][0]["choice"] and "w59" in shift.ledger()["done"][0]["proof"]


# ----- the yes to the plan keeps a permission prompt's rules (Mythos review AV-3, AV-5) -----

async def _answer(d, words: str) -> None:  # noqa: F811
    """The words after the read-back: taken in code, or, when not, given to the model, which calls night_shift."""
    if not await d._night_words(words):
        await _say(d, words)


@pytest.mark.parametrize("answer", ["yes, but skip the deploy", "okay, except billing"])
def test_a_yes_with_a_condition_starts_no_shift(night, monkeypatch, answer):
    """The plan read back has billing's deploy in it: "yes, but skip the deploy" would start all of it."""
    d = night.d  # noqa: F811
    _on_a_call(d, monkeypatch)

    async def scenario():
        await d._night_words(TWO)
        await _answer(d, answer)

    asyncio.run(scenario())
    assert night.sent == [] and d.NIGHT.current is None


def test_a_yes_after_the_bot_said_something_else_starts_no_shift(night, monkeypatch):
    d = night.d  # noqa: F811
    _on_a_call(d, monkeypatch)

    async def scenario():
        await d._night_words(TWO)
        assert await d._night_words("what is billing doing?") is False
        await d.on_user_utterance("what is billing doing?")
        await model_says(d, "Billing is running its tests. Want me to check docs too?")
        await _answer(d, "yes")

    asyncio.run(scenario())
    assert night.sent == [] and d.NIGHT.current is None


def test_a_yes_said_over_the_read_back_starts_no_shift(night, monkeypatch):
    d = night.d  # noqa: F811
    _on_a_call(d, monkeypatch)

    async def scenario():
        await d._night_words(TWO)
        monkeypatch.setattr(d.ECHO, "speaking", True)  # the read-back is still playing
        await _answer(d, "yes")

    asyncio.run(scenario())
    assert night.sent == [] and d.NIGHT.current is None


def test_a_typed_yes_starts_no_shift(night, monkeypatch):
    d = night.d  # noqa: F811
    _on_a_call(d, monkeypatch)

    async def push(frame, direction=None):
        pass

    d.state.conn.injector.push_frame = push
    asyncio.run(d._night_words(TWO))
    assert client_for(d).post("/voice/say", json={"text": "yes"}).status_code == 200
    p = Params(tasks="whatever the model wrote")
    asyncio.run(d.night_shift(p))  # the brain answers the typed words with the tool
    assert "error" in p.results[0] and night.sent == [] and d.NIGHT.current is None, p.results
