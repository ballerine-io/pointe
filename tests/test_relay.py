"""A misheard name reaches the agent as heard, and a short answer to the user's question is said without the reader.

From the Spoken Identifiers benchmark: the brain wrote misheard words as code names that do not exist, and the agent
changed nothing; the words as heard led it to the real name. From the barge-in benchmark: a short answer to a status
question waited for the reader's pass before the voice said it.

uv run pytest -q tests/test_relay.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import relay  # noqa: E402
from test_orchestrator import _gates_open, add, d, fake_conn, record_dispatch  # noqa: E402,F401  (d is a fixture)


def test_a_code_name_built_from_the_users_words_carries_the_words_as_heard():
    out = relay.as_heard('Add a comment above "loadHarborFee" (camelCase).',
                         "Add a comment above load harbor fee, camel case.")
    assert '"loadHarborFee" (heard as "load harbor fee")' in out
    assert 'The speech recognizer heard: "Add a comment above load harbor fee, camel case."' in out


def test_a_new_name_the_user_asked_for_stays_and_is_marked():
    out = relay.as_heard("Rename fee_total to harbor_total.", "Rename fee underscore total to harbor total.")
    assert out.startswith('Rename fee_total to harbor_total (heard as "harbor total").')


def test_a_name_the_user_said_or_this_session_knows_is_left_alone():
    assert relay.as_heard("Use harbor_total.", "use harbor_total") == "Use harbor_total."
    out = relay.as_heard("Fix loadHarborFee.", "fix load harbor fee", known={"loadHarborFee"})
    assert out == "Fix loadHarborFee."


def test_a_plain_request_is_sent_as_written():
    message = 'Add a line containing the word "violet" to the notes file.'
    assert relay.as_heard(message, "Add a line with the word violet to the notes file.") == message


def test_a_homophone_hint_is_resolved_here_with_the_sessions_own_names():
    said = "Add a comment above right ledger, right as in writing, singular."
    assert relay.homophone_hints(said) == [("right", "write", "writing")]
    out = relay.as_heard('Add a comment above the "right ledger".', said, known={"write_ledger", "right_margin"})
    assert '"right, as in writing" means the word "write". This session\'s names with it: write_ledger.' in out
    assert relay.homophone_hints("peek, as in peeking at it") == []  # heard as meant: nothing to say
    assert relay.homophone_hints("turn left as in leaving") == []  # no such pair


def test_the_send_carries_the_words_as_heard(d, monkeypatch):
    add(d, "m", "marsh")
    d.REGISTRY.active_id = "m"
    sent = record_dispatch(d, monkeypatch)
    _gates_open(d, monkeypatch, "Add a comment above load harbor fee, camel case.")
    d.state.brain_target = "marsh"
    asyncio.run(d._send('Add a comment above "loadHarborFee".'))
    assert sent and '(heard as "load harbor fee")' in sent[0][1]
    assert d.state.last_message == sent[0][1]


def _finished(d, text):
    return f"[claude-code {d.FINISHED_MARK} {d.FINAL_MARK}{text}"


def test_a_short_answer_to_the_users_question_is_said_before_the_reader(d, monkeypatch):
    s = add(d, "m", "marsh")
    d.REGISTRY.active_id = "m"
    d.state.conn = fake_conn()
    d.state.unconfirmed["m"] = ["How many tests failed in the last run?"]
    digested = []

    async def digest(session, text):
        digested.append(time.time())
        return {}

    monkeypatch.setattr(d, "_digest_turn", digest)

    async def scenario():
        await d.feed(s, _finished(d, "Seven tests failed, four of them in the harbor tests."), True)
        spoken = list(d.state.conn.injector.fed)
        await asyncio.sleep(0.05)
        return spoken

    spoken = asyncio.run(scenario())
    assert spoken[-1][1] is True and "Seven tests failed" in spoken[-1][0] and "answered the question" in spoken[-1][0]
    assert digested  # the notes still get the reader's pass


def test_a_long_turn_or_one_that_answers_no_question_goes_through_the_reader(d, monkeypatch):
    s = add(d, "m", "marsh")
    d.REGISTRY.active_id = "m"
    d.state.conn = fake_conn()
    d.state.unconfirmed["m"] = ["Fix the flaky harbor test."]
    assert d._quick_answer(s, _finished(d, "Fixed it.")) is None
    d.state.unconfirmed["m"] = ["Why did it fail?"]
    assert d._quick_answer(s, _finished(d, "x" * 2000)) is None
    assert d._quick_answer(s, _finished(d, "A timeout in the harbor client.")) is not None


def test_a_short_answer_from_a_session_that_is_not_active_is_said_before_the_reader_too(d, monkeypatch):
    """From the conversation suite: with two sessions, a question to the one not in focus ("how long did the import take
    in granary?") went through the reader and came back as a one-line "not the active session" report, seconds later.
    The user asked it: its answer is said from Claude's own words, as for the active session."""
    add(d, "b", "billing")
    s = add(d, "q", "granary")
    d.REGISTRY.active_id = "b"
    d.REGISTRY.mode = "orchestrator"
    d.state.conn = fake_conn()
    d.state.unconfirmed["q"] = ["How long did the nightly import take?"]
    out = d._quick_answer(s, _finished(d, "It took 47 minutes."))
    assert out is not None and "47 minutes" in out and "granary" in out


def test_session_mode_keeps_other_sessions_answers_for_the_screens(d, monkeypatch):
    add(d, "b", "billing")
    s = add(d, "q", "granary")
    d.REGISTRY.active_id = "b"
    d.REGISTRY.mode = "session"
    d.state.conn = fake_conn()
    d.state.unconfirmed["q"] = ["How long did the nightly import take?"]
    assert d._quick_answer(s, _finished(d, "It took 47 minutes.")) is None
