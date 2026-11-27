"""The page's "<agent> replied" (docs/design/agents.md): one desktop notification while the tab is in the background,
and a click on it opens that agent's replies, read from the Mac, as text.

The page runs in a headless Chrome against the stub Mac (tests/page_rig.py), with a fake Notification. Skipped where
that Chrome is not installed.
"""

import asyncio
import os
import re
import sys
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_rig import CHROME, Browser, StubMac, fixture, free_port  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ITEM = {"id": "agent_reply:hermes:0", "kind": "agent_reply", "session": "hermes", "title": "hermes replied",
        "body": "Open Pointe to read it.", "text": "Open Pointe to read it.", "approvable": False, "quiet": False}

FAKE = """(() => {
  window.made = [];
  window.Notification = class { constructor(title, o) { Object.assign(this, o, {title}); made.push(this); }
                                close() {} static get permission() { return 'granted'; } };
  localStorage.setItem('pointe.desktopAlerts', 'on');
  Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'hidden'});
  return true;
})()"""


class Replying(StubMac):
    read: list[str] = []

    def routes(self, app) -> None:
        app.router.add_post("/voice/agents/{name}/replies", self._replies)

    async def _replies(self, request):
        self.read.append(request.match_info["name"])
        return web.json_response({"agent": "hermes", "replies": [{"text": "Friday is clear.", "at": ""},
                                                                 {"text": "<b>not markup</b>", "at": ""}]})


@pytest.mark.slow
@pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")
def test_one_notification_and_a_click_opens_the_agents_replies():
    async def run():
        stub = await Replying(free_port()).start()
        stub.read = []
        stub.status = fixture(sessions=2)
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                await page.eval(FAKE)
                stub.status = {**stub.status, "attention": [ITEM]}  # the reply comes while the tab is in the background
                await asyncio.sleep(2.5)  # polls, hidden: every 2 s
                made = await page.eval("made.map(n => [n.title, n.body, n.tag])")
                await page.eval("made[0].onclick()")
                await asyncio.sleep(0.5)
                shown = await page.eval("""[document.getElementById('replysheet').classList.contains('open'),
                    document.getElementById('reply-name').textContent,
                    [...document.querySelectorAll('#reply-list p')].map(p => p.textContent),
                    document.querySelectorAll('#reply-list b').length]""")
                return made, shown, list(stub.read)
        finally:
            await stub.stop()

    made, (opened, title, lines, markup), read = asyncio.run(run())
    assert made == [["hermes replied", "Open Pointe to read it.", "agent_reply:hermes:0"]], "once, however many polls"
    assert opened and title == "hermes replied" and read == ["hermes"]
    assert lines == ["Friday is clear.", "<b>not markup</b>"] and markup == 0, "the agent's words are text, never markup"


def test_the_page_and_the_apps_say_the_same_words():
    page = (ROOT / "pointe" / "ui.html").read_text()
    swift = (ROOT / "apps" / "PointeKit" / "Sources" / "PointeUI" / "AgentReply.swift").read_text()
    copy = page[page.index("const REPLY_COPY"):page.index("};", page.index("const REPLY_COPY"))]
    for key in ("none", "unreachable"):
        said = re.search(rf"{key}: '([^']*)'", copy).group(1)
        assert f'static let {key} = "{said}"' in swift, key
    assert "reading: 'Reading the reply\\u2026'" in copy and 'static let reading = "Reading the reply…"' in swift
    assert "title: name => `${name} replied`" in copy and '"\\(name) replied"' in swift
