"""Two sessions share a word ("orchid-api", "orchid-web") and the user says only that word: ask, never guess.

From the routing benchmark: Pointe asked first on 4 of 14 ambiguous turns ("in the orchid one"), the plain router on
10. The routing rules already call such a tie ambiguous; the brain's own pick of one of them was taken as the user's
choice because the user's words did name it, among others. A pick inside a tie of the user's words is a guess.

uv run pytest -q tests/test_shared_word_asks.py
"""

import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

from test_orchestrator import add, d  # noqa: E402,F401  (d is the daemon fixture)


def _two(d):  # noqa: F811
    add(d, "a", "orchid-api")
    add(d, "w", "orchid-web")
    d.REGISTRY.mode = "orchestrator"


def test_the_brains_pick_inside_a_tie_is_not_the_users_choice(d):  # noqa: F811
    _two(d)
    d.state.brain_target = "orchid-api"
    assert d._brain_named("In the orchid one, bump the version.") is None


def test_a_name_that_tells_them_apart_still_goes(d):  # noqa: F811
    _two(d)
    d.state.brain_target = "orchid-api"
    assert d._brain_named("In orchid api, bump the version.").name == "orchid-api"


def test_a_question_about_the_shared_word_asks_which(d):  # noqa: F811
    _two(d)
    d.state.last_utterance = "What version is orchid on?"
    target, ask = d._resolve_target("orchid-api")
    assert target is None and "orchid-api" in ask and "orchid-web" in ask
    d.state.last_utterance = "What version is orchid web on?"
    target, ask = d._resolve_target("orchid-web")
    assert target.name == "orchid-web" and ask is None


def test_the_question_back_is_said_at_once_and_names_the_options(d, monkeypatch):  # noqa: F811
    """From the suite: "What version is orchid on?" got "I didn't send that. Do you mean orchid API or orchid web?"
    after a model step. The question is the whole reply: the daemon says it, naming the options, and a name in the
    user's answer sends the request held for it."""
    import asyncio

    from test_orchestrator import open_gates, record_dispatch, send

    _two(d)
    sent = record_dispatch(d, monkeypatch)
    open_gates(d, monkeypatch, "In the orchid one, bump the version.")
    async def unclear(*_a, **_k):
        return None
    monkeypatch.setattr(d, "_classify_target", unclear)
    result = asyncio.run(send(d, "Bump the version."))
    assert sent == [] and result["ask"] == "orchid api or orchid web?"
    assert d._quick_ack({"message": "Bump the version."}, result, "In the orchid one, bump the version.") == "orchid api or orchid web?"


def test_a_tie_is_broken_from_the_users_words_not_from_the_brains_message(d, monkeypatch):  # noqa: F811
    """From the suite: the brain wrote "Bump the version in the orchid-api project." and the tie-breaker read the name
    it had guessed into the message. A tie of the user's words is broken, or not, from the user's words."""
    import asyncio

    _two(d)
    d.state.last_utterance = "In the orchid one, bump the version."
    seen = []

    async def classify(message, sessions, tie=False):
        seen.append((message, tie))
        return None
    monkeypatch.setattr(d, "_classify_target", classify)
    targets, how = asyncio.run(d._route("Bump the version in the orchid-api project.", d.state.last_utterance))
    assert how == "ambiguous" and seen == [("In the orchid one, bump the version.", True)]
