"""Three misfires from one call, as specs: a request the user aimed at a session by what it works on, refused as "off
the thread" again and again; the answer to "which session?" refused as "not what the user just said"; and the wake
word alone, which reached the brain and set off a re-send, beside a sentence about the top bar read as "add a
session" and answered with closed sessions. Then "Approved." over Pointe's own line asking for it, taken for "only
listening", and the line said again. Invented sessions and words only.

uv run --locked pytest -q tests/test_guard_misfires.py
"""

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import matching  # noqa: E402
from discovery import Found  # noqa: E402
from guards import attach_request  # noqa: E402
from test_orchestrator import Params, add, d, fake_conn, no_classifier, open_gates, record_dispatch, spoken  # noqa: E402,F401

VOICE_NAME = "Lattice voice layer addon"
VENDOR_NAME = "Vendor questionnaire and bank review"
DRAFT = "Add a reading-speed control to the top bar design. Mockup first, no build yet."


def _two(d, monkeypatch, classifier_picks: str | None):
    """Two sessions in one folder, as on the call: the one building Pointe, and the one the user was talking with."""
    voice = add(d, "v", VOICE_NAME, cwd="/w/monorepo")
    voice.brief = {"goal": "Launch Pointe, the open-source voice layer for coding agents, with the Mac app at parity."}
    vendor = add(d, "q", VENDOR_NAME, cwd="/w/monorepo")
    vendor.brief = {"goal": "Deliver the Northwind due-diligence package and keep up with the Contoso vendor assessment."}
    d.REGISTRY.active_id = vendor.id
    d.state.thread = (vendor.id, time.time())  # last sent to: the topic of an unnamed follow-up
    pool = {VOICE_NAME: voice, VENDOR_NAME: vendor, None: None}
    no_classifier(d, monkeypatch, answer=pool[classifier_picks])
    return voice, vendor, record_dispatch(d, monkeypatch)


async def _send(d, message: str, session: str | None = None) -> dict:
    p = Params(message=message, **({"session": session} if session else {}))
    await d.send_to_claude_code(p)
    return p.results[0]


# ---------- guard 1: off the thread ----------

def test_words_that_name_what_a_session_works_on_send_there_with_no_question(d, monkeypatch):
    voice, vendor, sent = _two(d, monkeypatch, VOICE_NAME)
    open_gates(d, monkeypatch, "Another feature for the top bar is a control for reading speed. In Pointe.")
    result = asyncio.run(_send(d, DRAFT, VOICE_NAME))
    assert sent == [(VOICE_NAME, DRAFT)], result
    assert VOICE_NAME in result.get("say", "")  # it says where it went: the user did not name it outright


def test_the_wake_word_as_a_call_points_at_no_session(d, monkeypatch):
    voice, vendor, sent = _two(d, monkeypatch, VOICE_NAME)
    open_gates(d, monkeypatch, "Pointe, add a reading-speed control to the top bar")
    result = asyncio.run(_send(d, DRAFT, VOICE_NAME))
    assert sent == [] and "which session" in result["error"], result


def test_a_word_both_sessions_carry_points_at_neither(d, monkeypatch):
    voice, vendor, sent = _two(d, monkeypatch, VOICE_NAME)
    vendor.brief = {"goal": "Answer the Pointe launch questions from the Northwind security team."}
    open_gates(d, monkeypatch, "Another feature for the top bar is a control for reading speed. In Pointe.")
    result = asyncio.run(_send(d, DRAFT, VOICE_NAME))
    assert sent == [] and "which session" in result["error"], result


# ---------- guard 2: the answer to "which session?" ----------

def _asked_which(d, monkeypatch):
    voice, vendor, sent = _two(d, monkeypatch, VOICE_NAME)
    open_gates(d, monkeypatch, "Another feature for the top bar is a control for reading speed.")
    first = asyncio.run(_send(d, DRAFT, VOICE_NAME))
    assert sent == [] and "which session" in first["error"], first
    d.state.conversation.append(("assistant", "Which session is it for: the Pointe one, or the vendor review?"))
    return voice, vendor, sent


@pytest.mark.parametrize("answer", ["Pointe.", "The Pointe one."])
def test_naming_what_the_session_works_on_answers_which_and_sends_the_words_waiting(d, monkeypatch, answer):
    voice, vendor, sent = _asked_which(d, monkeypatch)
    open_gates(d, monkeypatch, answer, relevant=False)  # the words alone do not carry the request: the check must not run
    result = asyncio.run(_send(d, DRAFT, VOICE_NAME))
    assert sent == [(VOICE_NAME, DRAFT)], result


def test_the_answer_sends_only_the_words_that_waited(d, monkeypatch):
    voice, vendor, sent = _asked_which(d, monkeypatch)
    open_gates(d, monkeypatch, "Pointe.", relevant=False)
    asyncio.run(_send(d, DRAFT + " Also delete the old settings page.", VOICE_NAME))
    assert sent == [(VOICE_NAME, DRAFT)]  # the answer picks where; what goes is what the user asked, never the brain's addition


def test_an_answer_that_says_something_new_is_a_new_request(d, monkeypatch):
    voice, vendor, sent = _asked_which(d, monkeypatch)
    open_gates(d, monkeypatch, "Pointe, and delete the old settings page.", relevant=False)
    result = asyncio.run(_send(d, DRAFT + " Also delete the old settings page.", VOICE_NAME))
    assert sent == [] and "error" in result, result


def test_naming_the_other_session_answers_which_for_it(d, monkeypatch):
    voice, vendor, sent = _asked_which(d, monkeypatch)
    open_gates(d, monkeypatch, "The Northwind one.", relevant=False)
    result = asyncio.run(_send(d, DRAFT, VENDOR_NAME))
    assert sent == [(VENDOR_NAME, DRAFT)], result


# ---------- the wake word alone ----------

def _ears(d, monkeypatch):
    d.state.conn = fake_conn()
    ears = d.SonioxEars()
    pushed = []

    async def push(frame, *a):
        pushed.append(frame)

    monkeypatch.setattr(ears, "push_frame", push)
    return ears, pushed


@pytest.mark.parametrize("said", ["Point.", "Pointe?", "Hey Pointe."])
def test_the_wake_word_alone_is_answered_yes_and_never_reaches_the_brain(d, monkeypatch, said):
    voice, vendor, sent = _two(d, monkeypatch, VOICE_NAME)
    d.state.blocked = [DRAFT]  # a refused send the brain is told to raise: the wake word must not set off a re-send
    ears, pushed = _ears(d, monkeypatch)
    before = d.state.last_user_speech_at
    asyncio.run(ears._take(said))
    assert pushed == []  # the brain is not given the turn
    assert d.state.last_user_speech_at == before  # and nothing counts as a new request for a send
    assert "Yes?" in spoken(d.state.conn)
    assert d.state.pending_attach is None and sent == []


@pytest.mark.parametrize("said", ["Point taken, go on.", "Pointe, what is the vendor review doing?"])
def test_the_wake_word_with_words_is_a_turn(d, monkeypatch, said):
    _two(d, monkeypatch, None)
    ears, pushed = _ears(d, monkeypatch)
    asyncio.run(ears._take(said))
    assert pushed and "Yes?" not in spoken(d.state.conn)


# ---------- "add ... to Pointe" is not a request to add a session ----------

@pytest.mark.parametrize("said", [
    "Add reading speed to the top bar of Pointe, and also tell Claude to find out what is going on with the blocking.",
    "Also, another issue: I can see a component saying add session to Pointe, and it lists some sessions.",
    "Add a speed control to the top bar, and ask Codex to review it.",
])
def test_a_sentence_about_adding_something_else_is_not_an_add_session_request(said):
    assert attach_request(said) is None, said


# ---------- the picker offers open sessions; closed ones only when asked back ----------

NOW = time.mktime((2026, 11, 23, 15, 0, 0, 0, 0, -1))


def F(name, cwd, state="open", when=NOW - 600, **kw):
    return Found(harness="claude-code", id=name, name=name, cwd=f"/w/{cwd}", state=state, when=when, **kw)


FOUND = [
    F("ledger", "ledger", first="Fix the retry tests", keywords=["retry"]),
    F("ledger-migration", "ledger", state="recent", when=NOW - 86400, first="Move invoices to the new table",
      keywords=["migration", "invoices"]),
    F("lighthouse", "lighthouse", state="recent", when=NOW - 2 * 86400, first="Profile the renderer"),
]


def test_a_connect_never_offers_a_closed_session():
    assert matching.pick(FOUND, attach_request("connect to the session about invoices"), NOW).kind == "none"
    p = matching.pick(FOUND, attach_request("connect to a session"), NOW)
    assert all(f.state == "open" for f in p.items) and p.items, p


@pytest.mark.parametrize("said", ["reopen the session about invoices", "bring back the invoices session",
                                  "connect to yesterday's session about invoices"])
def test_asking_for_a_closed_one_back_offers_it(said):
    p = matching.pick(FOUND, attach_request(said), NOW)
    assert p.kind == "one" and p.items[0].name == "ledger-migration", (said, p)


def test_one_open_session_named_takes_the_send_with_no_question_beside_a_closed_twin(d, monkeypatch):
    ledger = add(d, "l", "ledger", cwd="/w/ledger")
    add(d, "o", "orchard", cwd="/w/orchard")
    gone = add(d, "lm", "ledger-migration", cwd="/w/ledger")
    d.REGISTRY.remove(gone.id)  # it left the voice: a closed session
    seen = no_classifier(d, monkeypatch)
    sent = record_dispatch(d, monkeypatch)
    open_gates(d, monkeypatch, "tell ledger to rerun the retry tests")
    result = asyncio.run(_send(d, "Rerun the retry tests."))
    assert sent == [("ledger", "Rerun the retry tests.")] and seen == [], result
    assert ledger.name in result["sent_to"]


# ---------- "Approved." over Pointe's own line that asks for it ----------

from test_reply_resumes import _hear, _rig  # noqa: E402

ASKS = ("Vendor review still needs your answer on group two, rows 4, 6 and 9. Say approve rows 4, 6 and 9, or name the "
        "row to change.")


async def _cut(d, front, spoken, line: str, heard_secs: float):
    d.state.last_utterance, d.state.last_user_speech_at = "What is next?", time.time() - 10
    await front._speak(line)
    front._speaking = True
    front._spoke_since = time.time() - heard_secs
    front._interrupted()  # what an InterruptionFrame does here
    front._speaking = False
    del spoken[:]


def _waiting(d):
    vendor = add(d, "q", VENDOR_NAME, cwd="/w/monorepo")
    vendor.needs = {"need": "Yes to group two (rows 4, 6 and 9) or a named change"}
    return vendor


@pytest.mark.parametrize("words", ["Approved.", "Yes."])
def test_a_yes_over_a_line_that_asks_for_it_is_the_answer_not_listening(d, monkeypatch, words):
    _waiting(d)
    front, spoken, asked, tasks_done = _rig(d, monkeypatch, ["Sent the approval of all three to vendor review."])

    async def run():
        await _cut(d, front, spoken, ASKS, heard_secs=5.5)  # inside "Say approve rows ...": no question mark left
        await _hear(d, front, tasks_done, words)

    asyncio.run(run())
    assert len(asked) == 1 and not any("name the row" in line for line in spoken), spoken


def test_a_yes_after_the_question_was_heard_answers_it_though_the_cut_came_later(d, monkeypatch):
    front, spoken, asked, tasks_done = _rig(d, monkeypatch, ["Sent."])

    async def run():
        await _cut(d, front, spoken, "Group two is rows 4, 6 and 9: all advisory only. Approve all three? It is due "
                   "today, before the vendor call.", heard_secs=5.3)  # past the question mark: it was heard
        await _hear(d, front, tasks_done, "Approved.")

    asyncio.run(run())
    assert len(asked) == 1 and not any("vendor call" in line for line in spoken), spoken


def test_okay_over_that_line_is_still_only_listening(d, monkeypatch):
    _waiting(d)
    front, spoken, asked, tasks_done = _rig(d, monkeypatch, [])

    async def run():
        await _cut(d, front, spoken, ASKS, heard_secs=5.5)
        await _hear(d, front, tasks_done, "Okay.")

    asyncio.run(run())
    assert asked == [] and spoken and "name the row" in spoken[0], spoken
