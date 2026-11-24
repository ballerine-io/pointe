""""Hold the reports, I need to think": nothing unasked is said until the user speaks again.

From the conversation suite: after "Hold all reports for now, I need to think", the voice said "Okay, I'll hold
reports" and eight seconds later "Atlas has one update, held as you asked." The words were the model's; nothing held
anything. Now the daemon holds session news from those words until the user's next turn; the answer to a question they
asked still comes, and a permission request is still read out. On their next words the held news goes to the model
as background, so "what happened with atlas?" is answered from it, and is not said again after.

uv run pytest -q tests/test_hold_reports.py
"""

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).parent))

import conversation as cv  # noqa: E402
from test_conversation_flow import QUICK_ANSWER, REPORT_DOCS, call  # noqa: E402,F401
from test_orchestrator import d  # noqa: E402,F401


@pytest.mark.parametrize("said", ["Hold all reports for now, I need to think.", "No updates for a bit.",
                                  "Hold the reports.", "Pause the updates, I need a minute.", "בלי עדכונים כרגע"])
def test_these_hold_the_news(said):
    assert cv.hold_news_intent(said)


@pytest.mark.parametrize("said", ["Hold on, let me finish.", "Tell billing to hold the deploy.", "What's the update on billing?"])
def test_these_do_not(said):
    assert not cv.hold_news_intent(said)


def test_held_news_waits_for_the_users_next_words_and_an_answer_they_asked_for_does_not(call):  # noqa: F811
    d = call.d  # noqa: F811

    async def run():
        injector = call.start()
        d.state.news_held = True
        await injector.inject(REPORT_DOCS, True)
        await asyncio.sleep(0.6)  # past the quiet gap
        assert call.asked == [] and injector.queued == 1
        await injector.inject(QUICK_ANSWER, True)
        await asyncio.sleep(0.2)
        assert [t for _, t in call.asked] == [QUICK_ANSWER]
        assert injector.queued == 1, [t for _, t in injector._updates.items]
        news = []
        d.state.front = type("F", (), {"brain": type("B", (), {"add_news": staticmethod(news.append)})()})()
        d._release_news()
        assert d.state.news_held is False and injector.queued == 0 and news == [REPORT_DOCS]

    asyncio.run(run())
