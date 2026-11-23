"""The page under its own script policy (guards.page_csp), in headless Chrome: everything it ships may run, and a script
or handler that reaches the page later may not. The stub serves the policy as daemon.py does, so every page test runs
under it."""

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_rig import CHROME, Browser, StubMac, fixture, free_port  # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")

WATCH = """window.__csp = []; document.addEventListener('securitypolicyviolation',
  e => window.__csp.push(e.violatedDirective + ' ' + (e.sample || '')));"""

# The browser's own view: each handler's attribute value and each inline script's text, hashed in the page.
HASHED_HERE = """(async () => {
  const sha = async t => btoa(String.fromCharCode(...new Uint8Array(await crypto.subtle.digest('SHA-256',
                                                                     new TextEncoder().encode(t)))));
  const out = [];
  for (const e of document.querySelectorAll('*'))
    for (const a of e.attributes) if (a.name.startsWith('on')) out.push(await sha(a.value));
  for (const s of document.querySelectorAll('script')) out.push(await sha(s.textContent));
  return out;
})()"""

INJECT = """(async () => {
  window.__pwned = 0;
  const b = document.createElement('button'); b.setAttribute('onclick', 'window.__pwned = 1');
  document.body.append(b); b.click();
  const s = document.createElement('script'); s.textContent = 'window.__pwned = 2'; document.body.append(s);
  const d = document.createElement('div'); d.innerHTML = '<img src="data:," onerror="window.__pwned = 3">';
  document.body.append(d);
  await new Promise(r => setTimeout(r, 300));
  return window.__pwned;
})()"""


def test_the_page_runs_under_its_policy_and_an_injected_script_does_not():
    async def run():
        stub = await StubMac(free_port()).start()
        stub.status = fixture(sessions=3, talk=4, connected=True)
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                await page.cdp("Page.addScriptToEvaluateOnNewDocument", {"source": WATCH})
                await page.cdp("Page.reload")
                await asyncio.sleep(0.5)
                await page.wait_for_page()
                policy = await page.eval("fetch('/voice').then(r => r.headers.get('content-security-policy'))")
                hashed = await page.eval(HASHED_HERE)
                await page.eval("(async () => { openSettings && openSettings(); await refresh(); return true; })()")
                await asyncio.sleep(0.5)
                loaded = await page.eval("window.__csp.slice()")
                injected = await page.eval(INJECT)
                blocked = await page.eval("window.__csp.slice()")
        finally:
            await stub.stop()
        return policy, hashed, loaded, injected, blocked

    policy, hashed, loaded, injected, blocked = asyncio.run(run())
    assert policy and "script-src" in policy
    missing = [h for h in hashed if f"'sha256-{h}'" not in policy]
    assert not missing, f"{len(missing)} inline scripts or handlers the policy does not allow"
    assert loaded == [], loaded  # the page itself, its first status, and Settings: nothing refused
    assert injected == 0 and len(blocked) >= 3, blocked


SINKS = """(async () => {
  await refresh(); await new Promise(r => setTimeout(r, 300));
  const sub = document.getElementById('sub');
  await loadCtx();
  const ctx = document.getElementById('ctx-total');
  return {sub: sub.textContent, subTags: [...sub.querySelectorAll('*')].map(e => e.localName),
          ctx: ctx.textContent, ctxTags: [...ctx.querySelectorAll('*')].map(e => e.localName),
          qr: qrNodes(QR).map(n => n.localName + ':' + n.namespaceURI + ':' + n.querySelectorAll('path').length),
          refused: [qrNodes('<svg onload="window.__pwned = 4"><path d="M0 0"/></svg>').length,
                    qrNodes('<svg><script>window.__pwned = 5</script></svg>').length,
                    qrNodes('<svg><a href="https://evil.example"><path d="M0 0"/></a></svg>').length,
                    qrNodes('<img src=x onerror="window.__pwned = 6">').length, qrNodes(undefined).length],
          pwned: window.__pwned || 0};
})()"""


def test_names_and_the_qr_code_reach_the_page_as_text_and_shapes_never_as_markup():
    import json

    from phone_pairing import _svg

    marked = '<img src=x onerror="window.__pwned=7">shop'

    async def run():
        stub = await StubMac(free_port()).start()
        stub.status = fixture(sessions=2, talk=2, connected=True)
        stub.status["sessions"][0]["name"] = marked
        stub.status["active"], stub.status["mode"] = marked, "session"
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                await page.eval(f"window.QR = {json.dumps(_svg('pointe://pair?v=2&host=h.example&port=7443&code=AB'))}; true")
                return await page.eval(SINKS)
        finally:
            await stub.stop()

    got = asyncio.run(run())
    assert "Focused on" in got["sub"] and '__pwned=7">shop' in got["sub"] and got["subTags"] == ["b"]  # text, in bold
    assert got["ctx"] == "—no call connected" and got["ctxTags"] == ["small"]
    assert got["qr"] == ["svg:http://www.w3.org/2000/svg:2"]  # segno's drawing, as SVG
    assert got["refused"] == [0, 0, 0, 0, 0] and got["pwned"] == 0


CALL = """(async () => {
  await startCall();
  for (let i = 0; i < 50 && call.state === 'connecting'; i++) await new Promise(r => setTimeout(r, 100));
  try { await silence.play(); } catch (e) {}
  await new Promise(r => setTimeout(r, 500));
  return {state: call.state, worklet: !!call.player, csp: window.__csp.slice()};
})()"""


def test_the_call_runs_under_the_policy():
    """The microphone's AudioWorklet (from blob:), the call's WebSocket and the media-keys clip (a blob: wav): the
    policy refuses none of them, so a stricter directive cannot silently break the call."""
    async def run():
        stub = await StubMac(free_port()).start()
        stub.status = fixture(sessions=1)
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                await page.cdp("Page.addScriptToEvaluateOnNewDocument", {"source": WATCH})
                await page.cdp("Page.reload")
                await asyncio.sleep(0.5)
                await page.wait_for_page()
                return await page.eval(CALL)
        finally:
            await stub.stop()

    got = asyncio.run(run())
    assert got["csp"] == [] and got["worklet"], got
    assert got["state"] not in ("off", "connecting"), got
