"""The check for facts nobody gave the voice (brief.unsupported_in) holds for the user's work and lets the world through.

From the 1.14.0 latency runs: "1,024 bytes" and "late March to late October" were sent back as made up, and a reply sent
back before any sound costs one to two seconds. A plain question about the world gets a plain answer; a number or a date
about a session, a file or what an agent did is still refused unless something the voice was told contains it.
"""

import asyncio
from types import SimpleNamespace

import pytest

from brief import unsupported_in
from test_orchestrator import add, d  # noqa: F401  (d is the daemon fixture)

TEL_AVIV_Q = "What time zone is Tel Aviv in?"
TEL_AVIV = "Tel Aviv is on Israel Standard Time; daylight time runs from late March to late October."
KILOBYTE_Q = "How many bytes are in a kilobyte?"
KILOBYTE = "A kilobyte is 1,000 bytes, or 1,024 in binary units."
KNOWN = "[right now] Active session: payments. [payments: claude-code finished its turn] The retry fix is in review."


@pytest.mark.parametrize("asked,said", [(TEL_AVIV_Q, TEL_AVIV), (KILOBYTE_Q, KILOBYTE)])
def test_general_knowledge_answering_the_users_own_question_passes(asked, said):
    assert unsupported_in(said, f"{asked} {KNOWN}", asked, {"payments"}) == []


@pytest.mark.parametrize("said,made_up", [(TEL_AVIV, ["march", "october"]), (KILOBYTE, ["1,000", "1,024"])])
def test_the_same_words_are_checked_as_before_when_they_answer_no_question_of_the_users(said, made_up):
    """`world` is None for a turn on session news, after a tool, or with no words of the user's: today's check."""
    assert unsupported_in(said, KNOWN, None, {"payments"}) == made_up


@pytest.mark.parametrize("said,made_up", [
    ("Payments' test suite has 1,024 tests.", ["1,024"]),  # an invented session result, phrased like a fact
    ("Payments handles 4,096 a minute.", ["4,096"]),  # the session's name alone makes it about the work
    ("The config file is 2,048 lines long.", ["2,048"]),  # an invented file
    ("It found 12 duplicates.", ["12"]),  # what an agent did
    ("Claude ran it on March 3rd.", ["march"]),
    ("Your build takes 40 seconds.", ["40"]),
    ("Dana signed off on it in October.", ["october"]),  # a name the session's notes keep
    ("A kilobyte is 1,024 bytes in binary units. The retry worker writes 2,048 rows.", ["2,048"]),  # each sentence on its own
])
def test_a_made_up_fact_about_the_work_is_refused_even_after_a_question_about_the_world(said, made_up):
    assert unsupported_in(said, f"{KILOBYTE_Q} {KNOWN}", KILOBYTE_Q, {"payments", "dana"}) == made_up


@pytest.mark.parametrize("asked", [
    "How many tests does payments have?",  # a word of the work
    "How big is payments?",  # a session's name
    "How long will it take?",  # pointing at something already in the conversation
    "And that one?", "How many?",  # too little of its own to be about the world
    "When did we ship?",
])
def test_a_question_about_the_work_keeps_every_sentence_of_its_answer_checked(asked):
    for said, made_up in (("About 12 minutes.", ["12"]), ("The 23rd of March.", ["23", "march"])):
        assert unsupported_in(said, f"{asked} {KNOWN}", asked, {"payments"}) == made_up


def test_a_fact_someone_gave_passes_whatever_the_question():
    known = f"{KNOWN} [payments: claude-code finished its turn] 1,024 tests pass."
    assert unsupported_in("Payments has 1,024 tests passing.", known, None, {"payments"}) == []
    assert unsupported_in("Payments has 1,024 tests passing.", known, KILOBYTE_Q, {"payments"}) == []


# ---------- the binding: Brain decides when the reply answers only the user's own words ----------

def _brain(monkeypatch, replies, tool_first=False):
    import brain as brain_module

    spoken, steps = [], []

    async def speak(text, request_id=None):
        spoken.append(text)

    async def step(choice, instructions, messages, decls, **_):
        steps.append(len(messages))
        if tool_first and len(steps) == 1:
            return SimpleNamespace(calls=[{"id": "t1", "name": "list_sessions", "args": {}}], said="", raw=None,
                                   vendor="fake", usage={})
        return SimpleNamespace(calls=[{"id": f"c{len(steps)}", "name": "speak", "args": {"text": replies.pop(0)}}],
                               said="", raw=None, vendor="fake", usage={})

    monkeypatch.setattr(brain_module.vendors, "step", step)
    tool = SimpleNamespace(name="list_sessions", description="", properties={}, required=[])
    b = brain_module.Brain("fake:model", "instructions", [tool] if tool_first else [],
                           lambda: "[right now] Active session: payments.", speak)
    b.may_stay_silent = lambda: False
    b.work_words = lambda: {"payments"}
    return b, spoken, steps


@pytest.mark.parametrize("asked,said", [(TEL_AVIV_Q, TEL_AVIV), (KILOBYTE_Q, KILOBYTE)])
def test_a_plain_answer_is_spoken_on_the_first_step(monkeypatch, asked, said):
    b, spoken, steps = _brain(monkeypatch, [said, "unused"])
    asyncio.run(b.turn(asked))
    assert spoken == [said] and len(steps) == 1


def test_an_invented_session_result_after_a_plain_question_is_still_sent_back(monkeypatch):
    b, spoken, steps = _brain(monkeypatch, ["A kilobyte is 1,024 bytes. Payments' test suite has 1,024 tests.",
                                            "A kilobyte is 1,000 bytes, or 1,024 in binary units."])
    asyncio.run(b.turn(KILOBYTE_Q))
    assert len(steps) == 2 and spoken == ["A kilobyte is 1,000 bytes, or 1,024 in binary units."]
    refusal = [m for m in b.messages if m["role"] == "tool"][0]["results"][0]["result"]["error"]
    assert "1,024" in refusal


def test_a_turn_on_session_news_checks_general_words_as_before(monkeypatch):
    b, spoken, steps = _brain(monkeypatch, [KILOBYTE, "Payments finished."])
    asyncio.run(b.turn("[payments: claude-code finished its turn] done"))
    assert len(steps) == 2 and spoken == ["Payments finished."]


def test_after_a_tool_the_answer_is_checked_as_before(monkeypatch):
    import brain as brain_module

    async def run_tool(self, call, filled):
        return {"sessions": ["payments"]}, filled

    monkeypatch.setattr(brain_module.Brain, "_tool", run_tool)
    b, spoken, steps = _brain(monkeypatch, [TEL_AVIV, "Tel Aviv is on Israel time."], tool_first=True)
    asyncio.run(b.turn(TEL_AVIV_Q))
    assert len(steps) == 3 and spoken == ["Tel Aviv is on Israel time."]


def test_the_daemon_tells_the_brain_its_sessions_names_and_the_names_their_notes_keep(d):
    s = add(d, "p1", "payments/main")
    s.brief = {"people_and_names": ["Dana (reviewer)", "BAL-77"]}
    words = d.make_brain(lambda *_a: None).work_words()
    assert {"payments", "dana", "reviewer", "bal"} <= words and "main" not in words and "77" not in words


def test_a_question_sharing_a_word_with_session_news_is_about_the_work(monkeypatch):
    b, spoken, steps = _brain(monkeypatch, ["On March 3rd.", "I do not have a date for it."])
    b.append("[payments: claude-code finished its turn] The pricing launch moved; no new date yet.")
    asyncio.run(b.turn("When is the pricing launch?"))
    assert len(steps) == 2 and spoken == ["I do not have a date for it."]


@pytest.mark.parametrize("said", ["On March 3rd.", "About 12 minutes.", "Roughly 4,000."])
def test_a_bare_figure_names_nothing_of_the_world_and_is_checked(said):
    asked = "When is the pricing launch?"  # in words no session used: the answer must still name what it is about
    assert unsupported_in(said, f"{asked} {KNOWN}", asked, {"payments"}) != []


def test_words_in_another_script_are_checked_as_before():
    """The words that mark the work are English: a Hebrew question or answer cannot be read for them."""
    assert unsupported_in("ההשקה ב-23 במרץ, אחרי בדיקת התשלומים.", "", "מתי ההשקה של התשלומים?") == ["23"]
    assert unsupported_in("The launch is on the 23rd, after בדיקה of the checkout.", "", KILOBYTE_Q) == ["23"]


def test_a_short_sentence_that_takes_up_the_world_question_passes():
    """From a latency run, 3 of 3: the docstring's own case, said as a short first sentence, was refused."""
    said = "1,000 bytes in the SI definition. Binary units count 1,024 bytes per kilobyte."
    assert unsupported_in(said, f"{KILOBYTE_Q} {KNOWN}", KILOBYTE_Q, {"lantern", "billing"}) == []


@pytest.mark.parametrize("said,made_up", [
    ("It took forty minutes and twelve failed.", ["forty", "twelve"]),
    ("Payments has a thousand rows.", ["thousand"]),
])
def test_spelled_out_figures_are_checked_like_digits(said, made_up):
    assert unsupported_in(said, KNOWN, None, {"payments"}) == made_up


def test_a_spelled_figure_the_voice_was_told_passes():
    assert unsupported_in("Payments has twelve failures.", f"{KNOWN} 12 tests failed.", None, {"payments"}) == []
    assert unsupported_in("Payments has three sessions open.", KNOWN, None, {"payments"}) == []  # a small count
