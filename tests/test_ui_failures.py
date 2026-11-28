"""What the page says when a tap or a typed line does not reach the Mac (ui.html, against the stub Mac in
tests/page_rig.py): Approve after a network drop says it was not sent and works on the next tap, a refusal's reason
stays on the card, and a typed line that was not sent stays in the box with the reason under it. Skipped where that
Chrome is not installed.
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_rig import CHROME, Browser, StubMac, fixture  # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")

LIVE = "call.state = 'live'; call.rtt = 23; render();"
# The next POST to `path` fails as a dropped network does (`drop`), or is answered with `status` and `detail`.
FAIL = """window.__fail = {}; window.__rejections = 0; addEventListener('unhandledrejection', () => window.__rejections++);
  const real = window.fetch;
  window.fetch = async (u, o) => { const f = window.__fail[String(u)];
    if (f && o && o.method === 'POST') { delete window.__fail[String(u)];
      if (f.drop) throw new TypeError('Failed to fetch');
      return new Response(JSON.stringify({detail: f.detail}), {status: f.status, headers: {'content-type': 'application/json'}}); }
    return real(u, o); };"""
CARD = """(() => { const c = document.querySelector('#attention .ask'); const b = c && c.querySelector('button.allow');
  return {card: !!c, text: c ? c.textContent : '', disabled: b ? b.disabled : null, rejections: window.__rejections}; })()"""


async def _page(status):
    stub = await StubMac().start()
    stub.status = status
    browser = Browser()
    await browser.__aenter__()
    page = await browser.open(stub.url)
    await page.eval(f"(async () => {{ {FAIL} {LIVE} await __fresh(); return true; }})()")
    await asyncio.sleep(0.8)
    return stub, browser, page


def test_approve_after_a_network_drop_says_so_and_the_next_tap_is_sent():
    async def run():
        stub, browser, page = await _page(fixture(sessions=3, approval=True, connected=True))
        try:
            await page.eval("window.__fail['/voice/approve'] = {drop: true}; document.querySelector('#attention .ask button.allow').click(); true")
            await asyncio.sleep(1.6)  # two polls: the card is not rebuilt, the line must stay
            dropped = await page.eval(CARD)
            await page.eval("document.querySelector('#attention .ask button.allow').click(); true")
            await asyncio.sleep(0.6)
            sent = [b for p, b, _ in stub.posts if p == "/voice/approve"]
            return dropped, sent
        finally:
            await browser.__aexit__(None, None, None)
            await stub.stop()
    dropped, sent = asyncio.run(run())
    assert dropped["card"] and dropped["disabled"] is False and dropped["rejections"] == 0, dropped
    assert "Not sent" in dropped["text"], dropped
    assert sent == [{"session": "s1-api", "request_id": "perm-1", "decision": "allow"}], sent


def test_a_refused_approve_keeps_the_macs_reason_on_the_card():
    async def run():
        stub, browser, page = await _page(fixture(sessions=3, approval=True, connected=True))
        try:
            await page.eval("window.__fail['/voice/approve'] = {status: 409, detail: 'studio is offline: answer it in its terminal'};"
                            "document.querySelector('#attention .ask button.allow').click(); true")
            await asyncio.sleep(0.3)
            soon = await page.eval(CARD)
            await asyncio.sleep(6)
            later = await page.eval(CARD)
            return soon, later
        finally:
            await browser.__aexit__(None, None, None)
            await stub.stop()
    for got in asyncio.run(run()):
        assert "studio is offline: answer it in its terminal" in got["text"] and got["disabled"] is False, got


TYPED = """(() => ({value: document.getElementById('typed').value, err: document.getElementById('typed-err').textContent,
  rejections: window.__rejections}))()"""


def test_a_typed_line_that_was_not_sent_stays_in_the_box_with_the_reason():
    async def run():
        stub, browser, page = await _page(fixture(sessions=2, talk=2, connected=True))
        out = []
        try:
            for fail in ("{drop: true}", "{status: 503, detail: 'The voice is restarting.'}"):
                await page.eval(f"{{ window.__fail['/voice/say'] = {fail}; const t = document.getElementById('typed'); t.disabled = false;"
                                "t.value = 'check the coupon test'; document.getElementById('compose').requestSubmit(); } true")
                await asyncio.sleep(0.5)
                out.append(await page.eval(TYPED))
            await page.eval("document.getElementById('compose').requestSubmit(); true")
            await asyncio.sleep(0.5)
            out.append(await page.eval(TYPED))
        finally:
            await browser.__aexit__(None, None, None)
            await stub.stop()
        return out, [b for p, b, _ in stub.posts if p == "/voice/say"]
    (dropped, refused, sent), posts = asyncio.run(run())
    assert dropped["value"] == "check the coupon test" and "Not sent" in dropped["err"] and dropped["rejections"] == 0, dropped
    assert refused["value"] == "check the coupon test" and "The voice is restarting." in refused["err"], refused
    assert sent["value"] == "" and sent["err"] == "" and posts == [{"text": "check the coupon test"}], (sent, posts)


KEY = """(() => { const m = getComputedStyle(document.getElementById('mic')), f = document.getElementById('fixkey').getBoundingClientRect();
  return {state: document.body.dataset.state, micBg: m.backgroundColor, fix: [Math.round(f.width), Math.round(f.height)],
          readbacks: ['#shiftask', '#startask'].map(id => { const e = document.querySelector(id + ' .ask > .need'), cs = e && getComputedStyle(e);
            return cs ? [cs.fontFamily.toLowerCase().includes('mono') || cs.fontFamily.toLowerCase().includes('menlo'), cs.backgroundColor] : null; })}; })()"""


def test_a_refused_key_does_not_look_like_a_live_mic_and_its_fix_is_a_button_and_a_read_back_is_prose():
    status = fixture(sessions=2, talk=2, connected=True)
    status["key_refused"] = {"vendor": "gemini", "ears": True}
    status["shift_pending"] = {"id": "p9", "expires_in": 50, "items": [], "line": "Night shift. docs: update the changelog. Start? Say yes or tap."}
    status["start_pending"] = {"id": "n3", "line": "Claude Code in shop, on studio. Start it? Say yes or tap."}

    async def run():
        stub, browser, page = await _page(status)
        try:
            return await page.eval(KEY), await page.eval("getComputedStyle(document.body).getPropertyValue('--orange').trim()")
        finally:
            await browser.__aexit__(None, None, None)
            await stub.stop()
    got, orange = asyncio.run(run())
    assert got["state"] == "broken", got
    assert got["micBg"] not in ("rgb(255, 90, 1)",), got  # the live orange
    assert got["fix"][1] >= 36, got
    # both read-backs are sentences, alike, as the app's StartCard: no monospace, no code box (QA round 5)
    assert got["readbacks"] == [[False, "rgba(0, 0, 0, 0)"]] * 2, got
