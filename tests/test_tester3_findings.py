"""Four faults the third independent tester found, each as the words that showed it.

- "Yes or no, will that change any files?" after a read-out was heard as a no and denied: a question is not an answer.
- "Tell atlas to rewrite the readme from scratch. Actually no, never mind, forget it." was delivered whole.
- With two sessions, "what version is the other one on?" was refused as "sounds like it is for another session", and
  the user heard "I didn't send that." and no answer.
- "The router blocked it twice." was said aloud.

uv run pytest -q tests/test_tester3_findings.py
"""

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

import guards  # noqa: E402
from test_orchestrator import _read_out_setup, add, d, fake_conn, verdicts  # noqa: E402,F401  (d is the daemon fixture)


@pytest.mark.parametrize("words", ["Yes or no, will that change any files?", "Is that safe to run?",
                                   "No idea what that is, what does it do?", "כן או לא, זה משנה קבצים?"])
def test_a_question_about_the_request_is_not_an_answer_to_it(words):
    assert guards.permission_answer(words) is None


@pytest.mark.parametrize("words,verdict", [("No.", "deny"), ("No, don't run that.", "deny"), ("yes", "allow"),
                                           ("Yes, go ahead.", "allow"), ("no?", "deny")])
def test_plain_answers_are_still_answers(words, verdict):
    assert guards.permission_answer(words) == verdict


def test_a_question_after_the_read_out_denies_nothing(d, monkeypatch):  # noqa: F811
    active, posts, said = _read_out_setup(d, monkeypatch)
    asyncio.run(d._read_out(active))
    d.ECHO.bot_started()
    d.ECHO.bot_stopped()
    d.ECHO.stopped_at = time.time() - 5
    d.state.user_started_at = time.time() - 1
    d.state.conn.injector.bot_started_at = time.time()
    asyncio.run(d.on_user_utterance("Yes or no, will that change any files?"))
    assert verdicts(posts) == [] and active.permission_id == "p1"


@pytest.mark.parametrize("words,taken_back", [
    ("Tell atlas to rewrite the readme from scratch. Actually no, never mind, forget it.", True),
    ("Tell billing to fix it. Never mind.", True),
    ("תגיד ל-billing להריץ טסטים. בעצם לא, עזוב.", True),
    ("Never mind the tests, fix the build.", False),
    ("Tell billing to run the tests.", False),
    ("Tell atlas to forget about the old logo and use the new one.", False),
])
def test_a_request_taken_back_at_the_end_of_the_sentence(words, taken_back):
    assert guards.withdrawn(words) is taken_back


def test_a_withdrawn_request_is_not_sent_fast_or_by_the_model(d):  # noqa: F811
    add(d, "a", "atlas")
    d.REGISTRY.active_id = "a"
    d.state.conn = fake_conn()
    words = "Tell atlas to rewrite the readme from scratch. Actually no, never mind, forget it."
    assert d._fast_send(words) is None
    d.state.last_utterance, d.state.last_user_speech_at = words, time.time()
    out = asyncio.run(d._send_now("Rewrite the readme from scratch."))
    assert "error" in out and "took the request back" in out["error"]


def test_the_other_one_of_two_sessions_is_the_one_they_were_not_talking_with(d):  # noqa: F811
    web, api = add(d, "w", "ledger-web"), add(d, "p", "ledger-api")
    d.state.thread = (web.id, time.time())
    d.state.brain_target = "ledger-api"
    assert d._brain_named("And what version is the other one on?") is api
    d.state.brain_target = "ledger-web"  # the brain picking the session they were already with gets no such pass
    assert d._brain_named("And what version is the other one on?") is None
    add(d, "b", "billing")  # with three sessions "the other one" is not one session
    d.state.brain_target = "ledger-api"
    assert d._brain_named("And what version is the other one on?") is None


def test_the_voice_never_says_the_router_blocked_it():
    import brain as brain_mod
    assert brain_mod._BACKSTAGE.search("i haven't sent that yet. the router blocked it twice.")
    assert not brain_mod._BACKSTAGE.search("billing is blocked until the tests pass.")


def test_the_second_waiting_request_is_read_after_the_first_is_answered(d, monkeypatch):  # noqa: F811
    """adv-12: billing and another session were sent work in one breath and both asked; only billing's request was read,
    and the other sat on its card until the user was told to switch."""
    active, posts, said = _read_out_setup(d, monkeypatch)  # bluebell is active with request p1
    monkeypatch.setattr(d, "NEXT_REQUEST_AFTER_SECS", 0.01)
    monkeypatch.setattr(d, "online", lambda s: True)
    other = next(s for s in d.REGISTRY.sessions.values() if s is not active)
    other.permission_id, other.permission_spoken, other.permission_since = "p9", "run: pytest", time.time()
    other.permission_text, other.permission_cut = "[permission request] Bash: run the tests\npytest", False
    asked = []

    async def ask(session):
        asked.append(session.name)

    monkeypatch.setattr(d, "_ask_permission", ask)

    async def run():
        assert await d._apply_answer(active, "p1", "allow", "user said: 'yes'")
        await asyncio.sleep(0.1)

    asyncio.run(run())
    assert asked == [other.name] and d.REGISTRY.active is other


def test_a_check_with_no_verdict_gets_a_second_reading_not_say_it_again(d, monkeypatch):  # noqa: F811
    """Measured in the 0.8.5 round (bar-01): the fast checker answered "to answer this, let's analyze the user's…", which
    is neither yes nor no, and the user heard "My question didn't go through, because the check failed. Please say it
    again." A missing verdict is read once more by the slower model, as a refusal already was."""
    from test_orchestrator import _gates_open, record_dispatch
    a = add(d, "a", "alpha")
    d.REGISTRY.active_id = a.id
    sent = record_dispatch(d, monkeypatch)
    _gates_open(d, monkeypatch, "Just tell me about alpha.")

    async def no_verdict(*_a):
        return None

    async def second_reading(*_a, **_k):
        return "Yes."

    monkeypatch.setattr(d, "_is_current_request", no_verdict)
    monkeypatch.setattr(d.vendors, "text", second_reading)
    out = asyncio.run(d._send("The owner asks: tell me about alpha. Report your state."))
    assert out.get("sent_to") == ["alpha"] and sent

