"""The New session sheet on the page, its words on every surface, and the row and card a start shows
(docs/design/new-session.md). The page runs in a headless Chrome against the stub Mac; the apps' words are read from
their sources (apps/PointeKit/Sources/PointeUI/NewSession.swift, apps/PointeKit NewSessionCopy.swift) and must be the page's.

uv run --locked pytest -q tests/test_new_session_ui.py
"""

import asyncio
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_rig import CHROME, Browser, StubMac, fixture  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "pointe" / "ui.html").read_text()
KEYS = ("title", "lede", "agent", "machine", "folder", "name", "namePlaceholder", "prompt", "promptPlaceholder", "start",
        "cancel", "noFolders", "claudeNote", "starting", "failed", "confirmTitle", "foldersTitle", "foldersHelp",
        "permissionsSetting", "permissionsSkip", "permissionsAsk", "permissionsHint", "skipNotice")


def page_dict(name: str) -> dict:
    block = PAGE[PAGE.index(f"const {name} = {{"):]
    block = block[:block.index("};")]
    return {k: v.replace("\\'", "'") for k, v in re.findall(r"(\w+): '((?:[^'\\]|\\.)*)'", block)}


def swift_enum(path: Path, name: str) -> dict:
    text = path.read_text()
    block = text[re.search(rf"\benum {name}\b", text).start():]
    block = block[:block.index("\n}\n")]
    return dict(re.findall(r'static let (\w+) = "((?:[^"\\]|\\.)*)"', block))


def test_the_page_the_iphone_and_the_mac_say_the_same_words():
    page = page_dict("NEW_SESSION_COPY")
    assert tuple(page) == KEYS
    apps = swift_enum(ROOT / "apps" / "PointeKit" / "Sources" / "PointeKit" / "NewSessionCopy.swift", "NewSessionCopy")
    for key in KEYS:
        assert apps[key] == page[key], f"{key}: the apps and the page differ"
    # one dictionary: the screens both apps draw take it from the package, and neither carries a copy of its own
    ui = ROOT / "apps" / "PointeKit" / "Sources" / "PointeUI"
    assert "typealias NewSessionCopy = PointeKit.NewSessionCopy" in (ui / "Shared.swift").read_text()
    for source in [*ui.glob("*.swift"), *(ROOT / "apps" / "macos" / "PointeMac").glob("*.swift"), *(ROOT / "apps" / "ios" / "Pointe").glob("*.swift")]:
        assert "enum NewSessionCopy" not in source.read_text(), source.name


def test_no_surface_offers_a_free_path_or_a_way_to_skip_prompts_from_the_sheet():
    """The folder is a pick from the daemon's list on every surface. Whether a session skips its prompts is the setting
    in Settings (SECURITY.md, the owner's default), never a switch on the sheet, and no screen names Claude Code's flag."""
    sheet = PAGE[PAGE.index('id="newsheet"'):PAGE.index('id="rowsheet"')]
    assert '<select id="new-folder"' in sheet and 'id="new-path"' in sheet
    assert not re.search(r'<input[^>]*id="new-(?:folder|path)"', sheet)
    views = [sheet] + [p.read_text() for p in [*(ROOT / "apps" / "PointeKit" / "Sources" / "PointeUI").glob("NewSession*.swift"),
                                               *(ROOT / "apps" / "macos" / "PointeMac").glob("NewSession*.swift")]]
    for text in views:
        assert not re.search(r"bypass|skip|dangerously|permissions", text, re.I)
    copy = (ROOT / "apps" / "PointeKit" / "Sources" / "PointeKit" / "NewSessionCopy.swift").read_text()
    assert not re.search(r"bypass|dangerously", copy + " ".join(page_dict("NEW_SESSION_COPY").values()), re.I)


def test_the_setting_and_the_risk_are_the_daemons_words():
    import sys
    sys.path.insert(0, str(ROOT / "pointe"))
    import newsession

    page = page_dict("NEW_SESSION_COPY")
    assert dict(newsession.PERMISSIONS) == {"skip": page["permissionsSkip"], "ask": page["permissionsAsk"]}
    assert newsession.PERMISSIONS_SETTING == page["permissionsSetting"]
    assert newsession.PERMISSIONS_HINT == page["permissionsHint"] and "without asking" in page["permissionsHint"]
    assert newsession.SKIP_NOTICE == page["skipNotice"]
    markup = PAGE[PAGE.index('id="pref-permissions-card"'):]
    markup = markup[:markup.index("</div>\n          </div>")]
    assert f'class="field">{page["permissionsSetting"]}<select id="pref-permissions">' in markup
    assert f'<option value="skip">{page["permissionsSkip"]}</option><option value="ask">{page["permissionsAsk"]}</option>' in markup


SHEET = """(() => ({open: document.getElementById('newsheet').classList.contains('open'),
  title: document.getElementById('new-title').textContent,
  agents: [...document.getElementById('new-agent').options].map(o => [o.value, o.textContent, o.disabled]),
  folders: [...document.getElementById('new-folder').options].map(o => [o.value, o.textContent]),
  path: document.getElementById('new-path').textContent, machineShown: !document.getElementById('new-machine-f').hidden,
  note: document.getElementById('new-note').textContent, err: document.getElementById('new-err').textContent,
  startOff: document.getElementById('new-start').disabled, start: document.getElementById('new-start').textContent}))()"""
LIST = """(() => ({rows: [...document.querySelectorAll('#list .s.starting')].map(r => r.textContent),
  card: document.getElementById('startask').textContent,
  buttons: [...document.querySelectorAll('#startask button')].map(b => b.textContent)}))()"""


@pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")
def test_the_sheet_starts_what_it_shows_and_the_row_and_the_card_follow():
    async def run():
        stub = await StubMac().start()
        stub.status = fixture(sessions=2, connected=True)
        out = {}
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                await page.wait_for_page()
                await page.eval("(async () => { await openNewSession(); return true; })()")
                await asyncio.sleep(0.3)
                out["sheet"] = await page.eval(SHEET)
                await page.eval("""(() => { document.getElementById('new-agent').value = 'opencode'; newSessionSync();
                    document.getElementById('new-folder').value = '/Users/sam/work/billing'; newSessionSync();
                    document.getElementById('new-name').value = 'invoices';
                    document.getElementById('new-prompt').value = 'List the open invoices.'; return true; })()""")
                out["picked"] = await page.eval(SHEET)
                await page.eval("(async () => { await startNewSession(); await __fresh(); return true; })()")
                await asyncio.sleep(0.4)
                out["after"] = await page.eval(SHEET)
                out["list"] = await page.eval(LIST)
                stub.status["starting"][0].update(state="failed", detail="OpenCode's service is not running.")
                stub.status["start_pending"] = {"id": "p1", "line": "Start a Codex session in shop on studio, named shop-2? Say yes or tap.",
                                                "harness": "codex", "name": "shop-2", "folder": "shop", "expires_in": 55}
                await page.eval("(async () => { await __fresh(); return true; })()")
                await asyncio.sleep(0.3)
                out["failed"] = await page.eval(LIST)
                await page.eval("(() => { document.querySelector('#startask button.allow').click(); return true; })()")
                await asyncio.sleep(0.4)
                out["tapped"] = await page.eval(LIST)
                stub.new_session = {**stub.new_session, "folders": []}
                await page.eval("(async () => { await openNewSession(); return true; })()")
                await asyncio.sleep(0.3)
                out["empty"] = await page.eval(SHEET)
        finally:
            await stub.stop()
        return out, [(p, b) for p, b, _ in stub.posts if p == "/voice/new-session"]

    got, posts = asyncio.run(run())
    sheet = got["sheet"]
    assert sheet["open"] and sheet["title"] == "New session" and sheet["start"] == "Start"
    assert sheet["agents"] == [["claude-code", "Claude Code", False], ["opencode", "OpenCode", False],
                               ["codex", "Codex (not available)", True]]
    assert sheet["folders"] == [["/Users/sam/work/shop", "shop"], ["/Users/sam/work/billing", "billing"]]
    assert sheet["path"] == "/Users/sam/work/shop" and not sheet["machineShown"] and not sheet["startOff"]
    assert "Claude Code opens in a new terminal window on the Mac." in sheet["note"] and "Codex is not installed" in sheet["note"]
    assert got["picked"]["path"] == "/Users/sam/work/billing" and "new terminal window" not in got["picked"]["note"]
    assert posts[0] == ("/voice/new-session", {"harness": "opencode", "folder": "/Users/sam/work/billing", "name": "invoices",
                                               "prompt": "List the open invoices."})
    assert not got["after"]["open"]  # it closed on the Mac's yes
    assert len(got["list"]["rows"]) == 1 and "invoices" in got["list"]["rows"][0] and "starting" in got["list"]["rows"][0]
    assert "did not start" in got["failed"]["rows"][0] and "service is not running" in got["failed"]["rows"][0]
    assert "Start this session?" in got["failed"]["card"] and "named shop-2? Say yes or tap." in got["failed"]["card"]
    assert got["failed"]["buttons"] == ["Cancel", "Start"]
    assert posts[1] == ("/voice/new-session", {"confirm": "p1"}) and got["tapped"]["card"] == ""
    assert got["empty"]["startOff"] and "No folder yet." in got["empty"]["note"]
