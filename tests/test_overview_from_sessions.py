"""An overview's facts are the sessions' own, asked for this minute.

From the third independent tester (orc-01, bar-01, bar-02, t3-03): "what's going on everywhere" was answered from notes
that held only how each session joined the call: "The three sessions are all idle, attached to Pointe, and have
read the notes file." Every session named, and not one fact. Now each session is asked through a read-only copy, and the
model is given their answers and nothing else to make the reply from.

uv run pytest -q tests/test_overview_from_sessions.py
"""

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).parent))

from pipecat.frames.frames import InputTextRawFrame  # noqa: E402
from pipecat.processors.frame_processor import FrameDirection  # noqa: E402

from test_no_silent_turn import _call  # noqa: E402
from test_orchestrator import add, d  # noqa: E402,F401  (d is the daemon fixture)

ANSWERS = {"billing": "Three refund tests fail on half-cent rounding. Next is Decimal with half-even rounding.",
           "lantern": "The nightly import took 47 minutes. Next is an index on customer id.",
           "harbor": "Lighthouse is at 71. Next is converting the hero image."}


def _three(d, monkeypatch, slow: str | None = None):  # noqa: F811
    front, spoken, asked, say = _call(d, monkeypatch, ["Billing has three failing refund tests. Lantern's import took "
                                                       "47 minutes. Harbor's Lighthouse score is 71."])
    add(d, "s2", "lantern"), add(d, "s3", "harbor")
    monkeypatch.setattr(d, "COPY_SESSIONS", True)
    monkeypatch.setattr(d, "online", lambda s: True)
    monkeypatch.setattr(d, "_capabilities", lambda s: {"side_questions": True})
    monkeypatch.setattr(d, "OVERVIEW_WAIT_SECS", 0.3)
    questions = []

    async def side_question(session, prompt):
        questions.append((session.name, prompt))
        if session.name == slow:
            await asyncio.sleep(5)
        return ANSWERS[session.name]

    monkeypatch.setattr(d.harnesses, "of", lambda s: type("H", (), {"side_question": staticmethod(side_question),
                                                                    "agent": "claude", "label": "Claude Code"})())
    return front, spoken, asked, say, questions


@pytest.mark.parametrize("words", ["What's going on everywhere?", "Give me a full rundown of everything that's happening "
                                   "across all the sessions.", "What's the status of each session?", "מה קורה בכל הסשנים?",
                                   # t3-03 in tester round 4: "a detailed overview of both sessions" went to the notes
                                   "תן לי סקירה מפורטת של כל ה-sessions, כל מה שאתה יודע על כל אחד.",
                                   "Give me an overview of all of them."])
def test_a_question_about_every_session_asks_every_session(d, monkeypatch, words):  # noqa: F811
    front, spoken, asked, say, questions = _three(d, monkeypatch)
    assert [s.name for s in d._overview_sessions(words)] == ["billing", "lantern", "harbor"]


@pytest.mark.parametrize("words", ["What's billing doing?", "Tell every session to run its tests.", "Thanks, all of them work.",
                                   "What's the status of lantern?"])
def test_other_words_are_answered_as_before(d, monkeypatch, words):  # noqa: F811
    front, spoken, asked, say, questions = _three(d, monkeypatch)
    assert d._overview_sessions(words) == []


def test_the_overview_is_made_from_the_sessions_own_answers(d, monkeypatch):  # noqa: F811
    front, spoken, asked, say, questions = _three(d, monkeypatch)
    fed = d.state.conn.injector.fed

    async def run():
        d.state.last_utterance, d.state.last_user_speech_at = "What's going on everywhere?", time.time() - 1
        d.state.utterance_spent = False
        await d._overview(front, "What's going on everywhere?", d._overview_sessions("What's going on everywhere?"))

    asyncio.run(run())
    assert spoken[0] == "Asking billing, lantern and harbor."  # said at once, before any answer
    assert sorted(name for name, _ in questions) == ["billing", "harbor", "lantern"]
    text, respond = fed[-1]
    assert respond and text.startswith("[overview:")
    assert all(answer in text for answer in ANSWERS.values())  # what the model speaks from is the sessions' words
    assert "at most 50 words" in text and "joining the voice" in text


def test_a_session_that_does_not_answer_in_time_is_named_as_unreached(d, monkeypatch):  # noqa: F811
    front, spoken, asked, say, questions = _three(d, monkeypatch, slow="harbor")

    async def run():
        d.state.last_user_speech_at = time.time() - 1
        await d._overview(front, "What's going on everywhere?", d._overview_sessions("What's going on everywhere?"))

    asyncio.run(run())
    text, _ = d.state.conn.injector.fed[-1]
    assert "- harbor: gave no answer in time" in text and ANSWERS["billing"] in text


def test_asked_again_at_once_it_is_not_asked_of_the_sessions_twice(d, monkeypatch):  # noqa: F811
    front, spoken, asked, say, questions = _three(d, monkeypatch)
    assert d._overview_sessions("What's going on everywhere?")
    d.state.overview_at = time.time()
    assert d._overview_sessions("What's going on everywhere?") == []


def test_the_overview_may_say_a_sentence_for_each_session():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pointe"))
    import conversation as cv
    assert cv.limit_for("[overview: the user asked…]\n- billing: x", "What's going on everywhere?") is cv.OVERVIEW
    assert cv.OVERVIEW.sentences >= 3 and cv.OVERVIEW.words <= 60


def test_when_no_session_answers_one_plain_line_is_said_not_one_failure_per_session(d, monkeypatch):  # noqa: F811
    """Tester round 4's first sample (orc-01, bar-02): "Billing. I couldn't reach it in time. Lantern. Couldn't reach it
    either. Atlas. Same. No answer in time." Three failures read out one by one, and no model step is needed to say so."""
    front, spoken, asked, say, questions = _three(d, monkeypatch)

    async def nothing(session, prompt):
        return None

    monkeypatch.setattr(d.harnesses, "of", lambda s: type("H", (), {"side_question": staticmethod(nothing),
                                                                    "agent": "claude", "label": "Claude Code"})())
    fed = d.state.conn.injector.fed
    before = len(fed)

    async def run():
        d.state.last_user_speech_at = time.time() - 1
        await d._overview(front, "What's going on everywhere?", d._overview_sessions("What's going on everywhere?"))

    asyncio.run(run())
    assert len(fed) == before  # no model step
    assert spoken[-1] == "None of them answered just now. Ask one by name, or ask again in a minute."


@pytest.mark.parametrize("words,said", [("Mm-hm.", True), ("Okay.", True), ("Wait, just tell me about lantern.", False)])
def test_a_backchannel_while_the_sessions_answer_does_not_drop_the_overview(d, monkeypatch, words, said):  # noqa: F811
    """Tester round 4's first sample, bar-02: "Mm-hm." over "Asking billing, lantern and atlas." counted as the user
    speaking again, so the answers were kept as news and never said. Only new words do that."""
    front, spoken, asked, say, questions = _three(d, monkeypatch)

    async def answers_after_a_word(session, prompt):
        d.state.last_utterance, d.state.last_user_speech_at = words, d.state.overview_at + 2
        return ANSWERS[session.name]

    monkeypatch.setattr(d.harnesses, "of", lambda s: type("H", (), {"side_question": staticmethod(answers_after_a_word),
                                                                    "agent": "claude", "label": "Claude Code"})())
    fed = d.state.conn.injector.fed

    async def run():
        d.state.last_user_speech_at = time.time() - 1
        await d._overview(front, "What's going on everywhere?", d._overview_sessions("What's going on everywhere?"))

    asyncio.run(run())
    assert bool(fed and fed[-1][0].startswith("[overview:")) is said


@pytest.mark.parametrize("words", ["Wait, wait. Just tell me about lantern.", "Only lantern.", "What about lantern?"])
def test_narrowed_to_one_session_while_they_answer_that_session_is_said(d, monkeypatch, words):  # noqa: F811
    """bar-01: "Wait, wait. Just tell me about lantern." over "Asking billing, lantern and atlas." kept every answer as
    news, and the model answered from notes that held only how lantern joined: "It joined Pointe, read its notes file,
    and replied ready." The words are taken by the overview, which then says that session's own answer alone."""
    front, spoken, asked, say, questions = _three(d, monkeypatch)
    fed = d.state.conn.injector.fed
    spent = []

    async def answers_after_a_redirect(session, prompt):
        if session.name == "billing":
            d.state.utterance_spent = False
            d.state.last_utterance, d.state.last_user_speech_at = words, d.state.overview_at + 2
            await d._on_user_utterance(words)
            spent.append(d.state.utterance_spent)
        return ANSWERS[session.name]

    monkeypatch.setattr(d.harnesses, "of", lambda s: type("H", (), {"side_question": staticmethod(answers_after_a_redirect),
                                                                    "agent": "claude", "label": "Claude Code"})())

    async def run():
        d.state.last_user_speech_at = time.time() - 1
        await d._overview(front, "What's going on everywhere?", d._overview_sessions("What's going on everywhere?"))

    asyncio.run(run())
    assert spent == [True]  # the model does not answer it from notes meanwhile
    text, respond = fed[-1]
    assert respond and ANSWERS["lantern"] in text and ANSWERS["billing"] not in text and ANSWERS["harbor"] not in text


def test_when_the_user_moved_on_no_failure_line_is_said_either(d, monkeypatch):  # noqa: F811
    """adv-06 in tester round 4: "Stop. Tell lantern to…" over the rundown, and the failed rundown was said anyway."""
    front, spoken, asked, say, questions = _three(d, monkeypatch)

    async def nothing_after_new_words(session, prompt):
        d.state.last_utterance, d.state.last_user_speech_at = "Stop. Tell lantern to add the index.", d.state.overview_at + 2
        return None

    monkeypatch.setattr(d.harnesses, "of", lambda s: type("H", (), {"side_question": staticmethod(nothing_after_new_words),
                                                                    "agent": "claude", "label": "Claude Code"})())

    async def run():
        d.state.last_user_speech_at = time.time() - 1
        await d._overview(front, "What's going on everywhere?", d._overview_sessions("What's going on everywhere?"))

    asyncio.run(run())
    assert not any("answered just now" in s for s in spoken)


@pytest.mark.parametrize("words", ["Give me a rundown of both sessions.", "תן לי סקירה של שני ה-sessions."])
def test_both_of_two_sessions_is_every_session(d, monkeypatch, words):  # noqa: F811
    front, spoken, asked, say, questions = _three(d, monkeypatch)
    d.REGISTRY.sessions.pop("s3")
    assert [s.name for s in d._overview_sessions(words)] == ["billing", "lantern"]


def test_a_redirect_still_being_said_when_the_answers_come_narrows_it_too(d, monkeypatch):  # noqa: F811
    """Tester round 5's bar-01: the three answers came 0.2 s before "Wait, wait, just tell me about quarry." was taken;
    the whole overview was said, and the model also answered the redirect from notes ("Quarry has joined Pointe")."""
    front, spoken, asked, say, questions = _three(d, monkeypatch)
    fed = d.state.conn.injector.fed

    async def answers_while_the_user_talks(session, prompt):
        d.state.hearing = (time.time(), "wait wait just tell me")
        return ANSWERS[session.name]

    monkeypatch.setattr(d.harnesses, "of", lambda s: type("H", (), {"side_question": staticmethod(answers_while_the_user_talks),
                                                                    "agent": "claude", "label": "Claude Code"})())

    async def the_redirect_is_taken():
        await asyncio.sleep(0.3)
        d.state.hearing, d.state.final_at = (0.0, ""), time.time()  # the final transcript; the turn is taken later
        await asyncio.sleep(0.5)
        d.state.final_at = 0.0
        words = "Wait, wait, just tell me about lantern."
        d.state.utterance_spent = False
        d.state.last_utterance, d.state.last_user_speech_at = words, time.time()
        await d._on_user_utterance(words)

    async def run():
        d.state.last_user_speech_at = time.time() - 1
        await asyncio.gather(d._overview(front, "What's going on everywhere?",
                                         d._overview_sessions("What's going on everywhere?")), the_redirect_is_taken())

    asyncio.run(run())
    text, respond = fed[-1]
    assert respond and ANSWERS["lantern"] in text and ANSWERS["billing"] not in text
