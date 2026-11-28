"""Small things the page says or does that a person notices (launch QA, round 3).

A keyboard reaches a session's Rename and Disconnect; this Mac's own page shows no round trip; a setup says which key it
lacks before Use this setup is clicked, and a refusal shows beside the click; the setup in use shows its cost; a
read-back reads as a sentence; the night shift sheet takes the focus; meeting notes say nothing for "not stated"; a
machine invite can be copied; the phone route in use is called so; a Wi-Fi route's hint asks about the Wi-Fi; and in
forced colours the controls keep their edges. The page runs in a headless Chrome against the stub Mac
(tests/page_rig.py); skipped where that Chrome is not installed.
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

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "pointe" / "ui.html").read_text()
LIVE = "call.state = 'live'; call.rtt = 23; render();"


class Refusing(StubMac):
    refuse: dict = {}

    async def _post(self, request):
        if request.path in self.refuse:
            code, detail = self.refuse[request.path]
            self.posts.append((request.path, {}, 0.0))
            return web.json_response({"detail": detail}, status=code)
        return await super()._post(request)


def _page(status, script, refuse=None, media=None):
    async def run():
        stub = await Refusing().start()
        stub.refuse = refuse or {}
        stub.status = status
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                if media:
                    await page.cdp("Emulation.setEmulatedMedia", {"features": media})
                await page.eval(LIVE)
                return await script(stub, page)
        finally:
            await stub.stop()
    return asyncio.run(run())


async def _key(page, key, code=None, vk=0):
    for kind in ("keyDown", "keyUp"):
        await page.cdp("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": code or key, "windowsVirtualKeyCode": vk})


def test_a_keyboard_renames_with_f2_and_disconnects_with_delete_twice():
    async def script(stub, page):
        await page.eval("document.querySelector('#list .s .nm').focus()")
        await _key(page, "F2", vk=113)
        await asyncio.sleep(0.3)
        renaming = await page.eval("document.activeElement.tagName === 'INPUT' && !!document.activeElement.closest('#list .s')")
        await _key(page, "Escape", vk=27)
        await asyncio.sleep(0.5)
        await page.eval("document.querySelector('#list .s .nm').focus()")
        await _key(page, "Delete", vk=46)
        await asyncio.sleep(0.4)
        asked = await page.eval("document.querySelector('#list .s .edit.sure')?.textContent || ''")
        await page.eval("document.querySelector('#list .s .nm').focus()")
        await _key(page, "Delete", vk=46)
        await asyncio.sleep(0.6)
        return renaming, asked, [p for p, _, _ in stub.posts], await page.eval("document.querySelector('#list .s .nm').getAttribute('aria-keyshortcuts')")
    renaming, asked, posts, shortcuts = _page(fixture(sessions=3, talk=2, connected=True), script)
    assert renaming and asked == "disconnect?" and "/voice/disconnect" in posts and shortcuts == "F2 Delete"


def test_this_macs_own_page_shows_no_round_trip():
    async def script(stub, page):
        return await page.eval("document.getElementById('sub').textContent")
    sub = _page(fixture(sessions=2, talk=2, connected=True), script)
    assert "ms" not in sub and sub.startswith("Orchestrating 2 sessions"), sub


KEYS = {"line": "Setup: Free start. Every role is filled.", "setup": "free",
        "keys": {"gemini": "in use", "openai": "optional", "anthropic": "not used", "soniox": "optional", "elevenlabs": "optional"},
        "uses": {"gemini": ["brain", "reader", "checker", "ears", "mouth"]},
        "setups": [{"id": "free", "name": "Free start", "short": "One Gemini key.", "pick_for": "trying Pointe at no cost",
                    "cost": "$0 until the free quota ends", "keys": ["gemini"]},
                   {"id": "openai", "name": "One OpenAI key", "short": "One OpenAI key.", "pick_for": "people who already pay for OpenAI",
                    "cost": "about $0.95", "keys": ["openai"]},
                   {"id": "voice-local", "name": "Voice stays on your Mac", "short": "One Anthropic key.", "pick_for": "confidential work",
                    "cost": "about $0.40", "keys": ["anthropic"]}]}
SETUPS = """[...document.querySelectorAll('#pref-setups .r')].map(r => ({head: r.querySelector('.shead2').textContent + r.querySelector('.cost').textContent,
  note: r.querySelector('.snote').textContent, buttons: [...r.querySelectorAll('button')].map(b => b.textContent)}))"""


def test_a_setup_names_its_missing_key_before_the_click_and_a_refusal_shows_beside_it():
    async def script(stub, page):
        await page.eval("openSettings()")
        await asyncio.sleep(0.4)
        before = await page.eval(SETUPS)
        await page.eval("[...document.querySelectorAll('#pref-setups .r')][2].querySelector('button').click()")
        await asyncio.sleep(0.6)
        return before, await page.eval(SETUPS)
    refused = "Not switched, Pointe keeps running as it is. Voice stays on your Mac needs headphones."
    before, after = _page({**fixture(sessions=2, connected=True), "keys": KEYS}, script, refuse={"/voice/setup": (409, refused)})
    free, openai, local = before
    assert free["head"] == "Free startIn use$0 until the free quota ends" and free["buttons"] == []  # the cost, and In use beside the name
    assert openai["note"] == "Needs the OpenAI key: not saved yet." and openai["buttons"] == ["Add the OpenAI key…"]
    assert local["note"] == "" and local["buttons"] == ["Use this setup"]  # its key is saved, though this setup does not use it
    assert after[2]["note"] == refused  # in view, by the button, not on the keys line above


def test_a_read_back_reads_as_a_sentence_not_a_code_box():
    async def script(stub, page):
        await asyncio.sleep(0.4)
        return await page.eval("""(() => { const e = document.querySelector('#startask .need'), c = getComputedStyle(e);
          return [e.textContent, c.fontFamily.includes('mono'), c.backgroundColor]; })()""")
    status = {**fixture(sessions=2, connected=True), "start_pending": {"id": "p1", "line": "Start a Codex session in shop? Say yes or tap.",
                                                                        "expires_in": 40}}
    line, mono, background = _page(status, script)
    assert line.startswith("Start a Codex session") and not mono and background == "rgba(0, 0, 0, 0)"


def test_the_night_shift_sheet_takes_the_focus_and_its_title_shows_no_ring():
    async def script(stub, page):
        await page.eval("document.getElementById('m-night').focus(); openNightShift()")
        await asyncio.sleep(0.5)
        return await page.eval("""[!!document.activeElement.closest('#nightsheet'), document.activeElement.id,
          getComputedStyle(document.activeElement).outlineStyle]""")
    inside, focused, outline = _page(fixture(sessions=2, connected=True), script)
    assert inside and focused == "night-h" and outline == "none"


def test_meeting_notes_drop_not_stated_and_never_nest_brackets():
    async def script(stub, page):
        await page.eval("""showEnd({summary: 'Short.', action_items: [
          {what: 'Check the retry limit', owner: 'unassigned', due: 'not stated'},
          {what: 'Raise the limit to 8', owner: "Sam (Speaker 3 said 'I will')", due: 'Friday'},
          {what: 'Update the runbook', owner: 'Dana', due: 'Not stated'}]})""")
        await asyncio.sleep(0.3)
        return await page.eval("[...document.querySelectorAll('#endbody ul.items li')].map(li => li.textContent)")
    items = _page(fixture(sessions=2, connected=True), script)
    assert items == ["Check the retry limit", "Raise the limit to 8 · Sam (Speaker 3 said 'I will') · by Friday", "Update the runbook · Dana"]


def test_a_machine_invite_has_copy_and_the_phone_route_in_use_says_in_use():
    async def script(stub, page):
        await page.eval("""invite = {code: 'ABCD-1234', link: 'pointe://hub?v=1&code=x', made: Date.now(), until: Date.now() + 60000};
          openSettings(); showInvite();""")
        await asyncio.sleep(0.3)
        return await page.eval("[document.getElementById('mach-copy').textContent, !!document.getElementById('mach-copy').offsetParent]")
    label, shown = _page(fixture(sessions=2, machines=2, connected=True), script)
    assert label == "Copy command" and shown  # the pill every small action in Settings is (round 4)
    assert "'set up now'" not in PAGE and "title.append(el('span', 'now', 'in use'))" in PAGE


def test_a_wifi_route_that_does_not_answer_asks_about_the_wifi():
    async def script(stub, page):
        return await page.eval("[CONNECT_COPY.unreachable('192.168.1.20:7443'), CONNECT_COPY.unreachable('studio.tail1234.ts.net:7443')]")
    wifi, vpn = _page(fixture(sessions=1), script)
    assert "same Wi-Fi" in wifi and "Twingate" not in wifi
    assert "Twingate or Tailscale" in vpn


def test_in_forced_colours_buttons_keep_an_edge_and_the_choice_is_marked():
    async def script(stub, page):
        return await page.eval("""(() => { const c = s => getComputedStyle(document.querySelector(s));
          return {deny: c('#attention .deny').borderTopWidth, on: c('#micmode-always').backgroundColor, off: c('#micmode-ptt').backgroundColor,
                  dot: c('#list .s .st.working').borderTopWidth}; })()""")
    got = _page(fixture(sessions=3, talk=2, approval=True, connected=True), script, media=[{"name": "forced-colors", "value": "active"}])
    assert got["deny"] == "1px" and got["dot"] == "1px" and got["on"] != got["off"], got
