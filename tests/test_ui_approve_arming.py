"""A card for a request that was not on screen ignores Approve for a moment, so a double-click on one card never
approves the next, unread. The page runs in a headless Chrome against the stub Mac (tests/page_rig.py); skipped where
that Chrome is not installed."""

import asyncio
import os
import sys
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_rig import CHROME, Browser, StubMac, fixture, free_port  # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")

APPROVE = "document.querySelector('#attention .ask .answer button.allow')"
SHOWN = f"[document.querySelector('#attention .ask .exact')?.textContent, {APPROVE}?.disabled]"


class Answering(StubMac):
    """The stub Mac, clearing an approved request at once as the daemon's _apply_answer does: the next one is first."""

    async def _post(self, request):
        if request.path == "/voice/approve":
            body = await request.json()
            self.posts.append((request.path, body, 0.0))
            for row in self.status["sessions"]:
                if row.get("request_id") == body.get("request_id"):
                    row.update(waiting=False, request=None, request_id=None)
            return web.json_response({"ok": True})
        return await super()._post(request)


def _waiting(status, i, request, request_id):
    status["sessions"][i].update(waiting=True, request=request, request_id=request_id, voice_can_approve=False, working=False)


def _run(script, waiting=True):
    async def run():
        stub = await Answering(free_port()).start()
        stub.status = fixture(sessions=3, connected=True)
        if waiting:
            _waiting(stub.status, 1, "Bash\n{\"command\": \"git status\"}", "perm-a")
            _waiting(stub.status, 2, "Bash\n{\"command\": \"rm -rf ~/work\"}", "perm-b")
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                await page.eval("call.state = 'live'; call.rtt = 23; render();")
                return await script(stub, page)
        finally:
            await stub.stop()
    return asyncio.run(run())


def test_a_double_click_on_approve_does_not_approve_the_next_request():
    async def script(stub, page):
        await asyncio.sleep(1.2)  # the first card has been on screen a while
        first = await page.eval(SHOWN)
        await page.eval(f"{APPROVE}.click()")
        for _ in range(40):  # the refresh after the click draws the next request's card
            await asyncio.sleep(0.02)
            if "rm -rf" in ((await page.eval(SHOWN))[0] or ""):
                break
        second = await page.eval(SHOWN)
        await page.eval(f"{APPROVE}.click()")  # the double-click's second click lands on the new card
        await asyncio.sleep(1.0)
        later = await page.eval(SHOWN)
        return first, second, later, [b.get("request_id") for p, b, _ in stub.posts if p == "/voice/approve"]
    first, second, later, approved = _run(script)
    assert "git status" in first[0] and first[1] is False
    assert "rm -rf" in second[0] and second[1] is True  # shown as not yet active
    assert approved == ["perm-a"]
    assert "rm -rf" in later[0] and later[1] is False  # armed after the pause: a deliberate click works


def test_a_card_that_lands_on_an_open_page_ignores_approve_at_first():
    async def script(stub, page):
        await asyncio.sleep(1.0)
        _waiting(stub.status, 1, "Bash\n{\"command\": \"rm -rf ~/work\"}", "perm-c")
        for _ in range(100):
            await asyncio.sleep(0.02)
            if (await page.eval(SHOWN))[0]:
                break
        landed = await page.eval(SHOWN)
        await page.eval(f"{APPROVE}.click()")
        await asyncio.sleep(1.0)
        return landed, await page.eval(SHOWN), [p for p, _, _ in stub.posts]
    landed, later, posts = _run(script, waiting=False)
    assert "rm -rf" in landed[0] and landed[1] is True
    assert later[1] is False and "/voice/approve" not in posts
