"""A click the Mac refused, or that never reached it, is said on the page and can be tried again.

The page runs in a headless Chrome against the stub Mac (tests/page_rig.py). A refusal (an HTTP error with a reason)
stays on the problem line through the refresh that follows the click; a request that never arrived (the network gone)
gives its button back and says so; typed words that were not sent stay in the box. Skipped where that Chrome is not
installed.
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_rig import CHROME, Browser, StubMac, fixture  # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")

LIVE = "call.state = 'live'; call.rtt = 23; render();"
STATE = """[[document.getElementById('problem'), document.querySelector('#attention .ask .need.err'), document.getElementById('typed-err')]
    .map(e => e ? e.textContent : '').join(' '),
  [...document.querySelectorAll('#attention .ask .answer button')].map(b => b.disabled),
  document.getElementById('typed').value]"""


class Refusing(StubMac):
    """The stub Mac, refusing the paths in `refuse` with (status, reason)."""

    refuse: dict = {}

    async def _post(self, request):
        if request.path in self.refuse:
            code, detail = self.refuse[request.path]
            self.posts.append((request.path, {}, 0.0))
            return web.json_response({"detail": detail}, status=code)
        return await super()._post(request)


def _run(script):
    async def run():
        stub = await Refusing().start()
        stub.refuse = {}
        stub.status = fixture(sessions=4, talk=4, approval=True, connected=True)
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                await page.cdp("Network.enable")
                await page.eval(LIVE)
                return await script(stub, page)
        finally:
            await stub.stop()
    return asyncio.run(run())


async def _offline(page, off: bool):
    await page.cdp("Network.emulateNetworkConditions", {"offline": off, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})


def test_a_refused_approve_says_why_after_the_refresh():
    async def script(stub, page):
        stub.refuse = {"/voice/approve": (409, "that request is no longer pending")}
        await page.eval("document.querySelector('#attention .ask .allow').click()")
        await asyncio.sleep(1.5)  # a poll or two later: the refresh after the click must not have wiped it
        return await page.eval(STATE)
    problem, disabled, _ = _run(script)
    assert "that request is no longer pending" in problem
    assert disabled == [False, False]


def test_an_approve_that_never_reached_the_mac_can_be_tried_again():
    async def script(stub, page):
        await _offline(page, True)
        await page.eval("document.querySelector('#attention .ask .allow').click()")
        await asyncio.sleep(1.0)
        offline = await page.eval(STATE)
        await _offline(page, False)
        await asyncio.sleep(1.0)
        await page.eval("document.querySelector('#attention .ask .allow').click()")
        await asyncio.sleep(1.0)
        return offline, [p for p, _, _ in stub.posts]
    (problem, disabled, _), posts = _run(script)
    assert "did not answer" in problem
    assert disabled == [False, False]  # given back: a second click is not a dead button
    assert posts.count("/voice/approve") == 1  # the second click, once the network was back


def test_typed_words_that_were_not_sent_stay_in_the_box_with_the_reason():
    async def script(stub, page):
        stub.refuse = {"/voice/say": (409, "no call is up")}
        await page.eval("document.getElementById('typed').value = 'tell billing to raise the timeout'; "
                        "document.getElementById('compose').requestSubmit()")
        await asyncio.sleep(1.5)
        refused = await page.eval(STATE)
        stub.refuse = {}
        await _offline(page, True)
        await page.eval("document.getElementById('typed').value = 'and docs too'; document.getElementById('compose').requestSubmit()")
        await asyncio.sleep(1.0)
        return refused, await page.eval(STATE)
    (problem, _, box), (problem2, _, box2) = _run(script)
    assert box == "tell billing to raise the timeout" and "Not sent" in problem  # a 409 reads as "Connect first."
    assert box2 == "and docs too" and "did not answer" in problem2


def test_a_refused_drive_key_or_microphone_change_says_why_after_the_refresh():
    """QA round 3: these wrote their refusal on the problem line and the refresh that followed the click wiped it."""
    async def script(stub, page):
        out = []
        for path, call in (("/voice/drive", "setDrive(true)"), ("/voice/prefs", "setMicMode('ptt')"), ("/voice/key", "fixKey()")):
            stub.refuse = {path: (409, f"refused at {path}")}
            if path == "/voice/key":
                await page.eval("status.key_refused = {vendor: 'gemini'}")
            await page.eval(f"(async () => {{ await {call}; return true; }})()")
            await asyncio.sleep(1.5)
            out.append(await page.eval("document.getElementById('problem').textContent"))
        return out
    drive, mic, key = _run(script)
    assert "refused at /voice/drive" in drive, drive
    assert "microphone mode did not change" in mic, mic
    assert "refused at /voice/key" in key, key


def test_a_start_that_never_reached_the_mac_gives_its_button_back():
    async def script(stub, page):
        stub.status["start_pending"] = {"id": "p1", "line": "Start a Codex session in shop? Say yes or tap.", "expires_in": 40}
        await page.eval("(async () => { await __fresh(); return true; })()")
        await asyncio.sleep(0.4)
        await _offline(page, True)
        await page.eval("document.querySelector('#startask .allow').click()")
        await asyncio.sleep(1.0)
        got = await page.eval("[document.querySelector('#startask .allow').disabled, document.getElementById('problem').textContent]")
        await _offline(page, False)
        return got
    disabled, problem = _run(script)
    assert disabled is False and ("did not answer" in problem or "not answering" in problem), (disabled, problem)  # the poll may say it first
