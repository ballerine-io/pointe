"""The Add sessions sheet on the page, its words on every surface, and the read-back card
(docs/design/attach-by-voice.md). The page runs in a headless Chrome (a mock keychain, a throwaway profile) against
the stub Mac; the apps' words are read from apple/PointeKit AddSessionsCopy.swift and must be the page's.

uv run --locked pytest -q tests/test_attach_ui.py
"""

import asyncio
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_rig import CHROME, Browser, StubMac, fixture, free_port  # noqa: E402
from test_new_session_ui import page_dict, swift_enum  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "ui.html").read_text()
KEYS = ("title", "lede", "searchPlaceholder", "open", "recent", "join", "reopen", "cancel", "loading", "none", "noMatch",
        "approvalsTerminal", "reopenNote", "confirmTitle")


def test_the_page_the_iphone_and_the_mac_say_the_same_words():
    page = page_dict("ADD_SESSIONS_COPY")
    assert tuple(page) == KEYS
    apps = swift_enum(ROOT / "apple" / "PointeKit" / "Sources" / "PointeKit" / "AddSessionsCopy.swift", "AddSessionsCopy")
    for key in KEYS:
        assert apps[key] == page[key], f"{key}: the apps and the page differ"
    ui = ROOT / "apple" / "PointeKit" / "Sources" / "PointeUI"
    assert "typealias AddSessionsCopy = PointeKit.AddSessionsCopy" in (ui / "Shared.swift").read_text()
    for source in [*ui.glob("*.swift"), *(ROOT / "macos" / "PointeMac").glob("*.swift"), *(ROOT / "ios" / "Pointe").glob("*.swift")]:
        assert "enum AddSessionsCopy" not in source.read_text(), source.name


def test_no_surface_sends_a_path_only_a_listed_key():
    """A tap sends back the key the Mac listed: the sheet has no field a path could be typed into."""
    sheet = PAGE[PAGE.index('id="addsheet"'):PAGE.index('id="nightsheet"')]
    assert not re.search(r"<input(?![^>]*type=\"search\")", sheet)
    js = PAGE[PAGE.index("const ADD_SESSIONS_COPY"):PAGE.index("let attachAskShown")]
    assert "{reopen: x.key}" in js and "{join: [...addChecked]}" in js and "x.path" not in js
    swift = (ROOT / "apple" / "PointeKit" / "Sources" / "PointeUI" / "AddSessions.swift").read_text()
    assert "item.key" in swift and ".path" not in swift


SHEET = """(() => ({open: document.getElementById('addsheet').classList.contains('open'),
  title: document.getElementById('add-title').textContent,
  rows: [...document.querySelectorAll('#addlist .addrow')].map(r => r.textContent),
  groups: [...document.querySelectorAll('#addlist .grp')].map(g => g.textContent),
  marks: [...document.querySelectorAll('#addlist .addrow .hmark')].map(m => m.dataset.harness),
  note: document.getElementById('add-note').textContent, join: document.getElementById('add-join').textContent,
  joinOff: document.getElementById('add-join').disabled}))()"""
CARD = """(() => ({card: document.getElementById('attachask').textContent,
  buttons: [...document.querySelectorAll('#attachask button')].map(b => b.textContent)}))()"""


@pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")
def test_the_sheet_lists_searches_and_joins_by_key_and_the_card_follows():
    async def run():
        stub = await StubMac(free_port()).start()
        stub.status = fixture(sessions=2, connected=True)
        out = {}
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                await page.wait_for_page()
                await page.eval("(async () => { await openAddSessions(); return true; })()")
                await asyncio.sleep(0.3)
                out["sheet"] = await page.eval(SHEET)
                await page.eval("(() => { const s = document.getElementById('add-search'); s.value = 'invoice export'; addSessionsDraw(); return true; })()")
                out["searched"] = await page.eval(SHEET)
                await page.eval("""(() => { const s = document.getElementById('add-search'); s.value = ''; addSessionsDraw();
                    document.querySelectorAll('#addlist .addrow input[type=checkbox]').forEach(c => { if (!c.disabled) { c.checked = true; c.onchange(); } });
                    return true; })()""")
                out["ticked"] = await page.eval(SHEET)
                await page.eval("(async () => { await joinChecked(); return true; })()")
                await asyncio.sleep(0.3)
                await page.eval("(async () => { await openAddSessions(); return true; })()")
                await asyncio.sleep(0.3)
                await page.eval("(() => { document.querySelector('#addlist .addrow button').click(); return true; })()")
                await asyncio.sleep(0.3)
                stub.status["attach_pending"] = {"id": "a1", "line": "Join pentest-recon, the Claude Code session in pentest-notes on studio? Say yes or tap.",
                                                 "choose": False, "verb": "join", "items": [], "expires_in": 50}
                await page.eval("(async () => { await refresh(); return true; })()")
                await asyncio.sleep(0.3)
                out["card"] = await page.eval(CARD)
                await page.eval("(() => { document.querySelector('#attachask button.allow').click(); return true; })()")
                await asyncio.sleep(0.3)
                stub.status["attach_pending"] = {"id": "a2", "line": "Two sessions fit: one, a in x, open; two, b in y, open. Which one?",
                                                 "choose": True, "verb": "join", "items": [], "expires_in": 50}
                await page.eval("(async () => { await refresh(); return true; })()")
                await asyncio.sleep(0.3)
                out["choose"] = await page.eval(CARD)
        finally:
            await stub.stop()
        return out, [(p, b) for p, b, _ in stub.posts if p == "/voice/add-sessions"]

    got, posts = asyncio.run(run())
    sheet = got["sheet"]
    assert sheet["open"] and sheet["title"] == "Add sessions" and sheet["groups"] == ["Open now", "This week"]
    assert sheet["marks"] == ["claude-code", "codex", "claude-code"] and sheet["joinOff"]
    assert "Plan the pentest of the login service" in sheet["rows"][0] and "Its approvals stay in its terminal." in sheet["rows"][1]
    assert "Reopen" in sheet["rows"][2] and "new terminal window" in sheet["note"]
    assert len(got["searched"]["rows"]) == 1 and "invoices" in got["searched"]["rows"][0]
    assert got["ticked"]["join"] == "Join 2" and not got["ticked"]["joinOff"]
    assert posts[0] == ("/voice/add-sessions", {"join": ["-|claude-code|a1", "-|codex|t1"]})
    assert posts[1] == ("/voice/add-sessions", {"reopen": "-|claude-code|c3"})
    assert "Add these sessions?" in got["card"]["card"] and got["card"]["buttons"] == ["Cancel", "Join"]
    assert posts[2] == ("/voice/add-sessions", {"confirm": "a1"})
    assert got["choose"]["buttons"] == ["Cancel"]  # "which one?" is answered by voice or in the sheet
