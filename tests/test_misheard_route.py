"""A send the brain addresses to a session the ears misheard ("Dox" for docs) goes there, not to the one session the
utterance names correctly in another sentence. QA round 2: three tasks for billing, docs and shop all went to billing,
and the voice said they went to all three."""

import asyncio

from test_orchestrator import Params, add, d, no_classifier, open_gates, record_dispatch  # noqa: F401

SAID = ("Billing adds an empty file called marker to its folder with the touch command. Dox checks which version the "
        "changelog and the README each state and reports both, without editing anything. Sharp decides which checkout "
        "timeout the support page should state and says why, without editing anything.")
BILLING = "Add an empty file called marker to the folder using the touch command."
DOCS = "Check which version the changelog and the README each state and report both. Do not edit anything."
SHOP = "Decide which checkout timeout the support page should state and explain why. Do not edit anything."


def _three(d, monkeypatch):
    add(d, "a", "billing/main"), add(d, "b", "docs/main"), add(d, "c", "shop/main")
    seen = no_classifier(d, monkeypatch)
    sent = record_dispatch(d, monkeypatch)
    open_gates(d, monkeypatch, SAID)
    return seen, sent


async def _send(d, message, session=None):
    p = Params(message=message, **({"session": session} if session else {}))
    await d.send_to_claude_code(p)
    return p.results[0]


def test_each_sentence_goes_where_the_brain_addressed_it(d, monkeypatch):
    _, sent = _three(d, monkeypatch)

    async def scenario():
        await _send(d, BILLING, "billing/main")
        await _send(d, DOCS, "docs/main")
        await _send(d, SHOP, "shop/main")

    asyncio.run(scenario())
    assert [name for name, _ in sent] == ["billing/main", "docs/main", "shop/main"]


def test_a_sentence_that_names_no_session_never_goes_to_the_one_another_sentence_names(d, monkeypatch):
    seen, sent = _three(d, monkeypatch)
    result = asyncio.run(_send(d, DOCS))  # no target from the brain: the classifier decides, and here it cannot
    assert ("billing/main", DOCS) not in sent and seen and "billing/main" not in result.get("sent_to", [])


def test_the_brain_cannot_send_an_unnamed_sentence_to_the_session_another_sentence_names(d, monkeypatch):
    _, sent = _three(d, monkeypatch)
    asyncio.run(_send(d, DOCS, "billing/main"))
    assert ("billing/main", DOCS) not in sent


def test_a_named_sentence_still_routes_by_its_name(d, monkeypatch):
    _, sent = _three(d, monkeypatch)
    asyncio.run(_send(d, BILLING, "docs/main"))  # the brain is wrong; the words name billing for this sentence
    assert sent == [("billing/main", BILLING)]
