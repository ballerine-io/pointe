""""Rename it to X" renames the session "it" means, and asks when it means none. QA round 2: a start that did not happen,
then "Rename it to shop-tests.", renamed billing, which the user never named."""

import asyncio
import time

from test_orchestrator import _rename, add, d  # noqa: F401


def test_with_nothing_in_the_conversation_it_asks_which(d):
    add(d, "a", "billing/main"), add(d, "b", "docs/main"), add(d, "c", "shop/main")
    d.REGISTRY.set_active("a")
    d.state.thread = None
    result = asyncio.run(_rename(d, "Rename it to shop-tests.", "shop-tests"))
    assert "error" in result and "Ask which session" in result["error"]
    assert [s.name for s in d.REGISTRY.sessions.values()] == ["billing/main", "docs/main", "shop/main"]


def test_it_is_the_session_the_conversation_is_about(d):
    add(d, "a", "billing/main"), add(d, "b", "docs/main")
    d.REGISTRY.set_active("a")
    d.state.thread = ("b", time.time())
    assert asyncio.run(_rename(d, "Rename it to handbook.", "handbook")) == {"renamed": "docs/main", "to": "handbook"}


def test_this_session_is_the_one_in_focus(d):
    add(d, "a", "billing/main"), add(d, "b", "docs/main")
    d.REGISTRY.set_active("a")
    d.state.thread = None
    assert asyncio.run(_rename(d, "Rename this session to invoices.", "invoices")) == {"renamed": "billing/main",
                                                                                         "to": "invoices"}


def test_with_one_session_it_is_that_one(d):
    add(d, "a", "billing/main")
    d.state.thread = None
    assert asyncio.run(_rename(d, "Rename it to invoices.", "invoices"))["renamed"] == "billing/main"
