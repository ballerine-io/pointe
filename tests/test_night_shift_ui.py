"""The night shift on the page: the start sheet, the strip while one runs, the read-back's card and the ledger
(docs/design/night-shift.md), and its words on every surface. The page runs in a headless Chrome against the stub Mac;
the apps' words are read from their source (apps/PointeKit NightShiftCopy.swift) and must be the page's.

uv run --locked pytest -q tests/test_night_shift_ui.py
"""

import asyncio
import os
import re
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_rig import CHROME, Browser, StubMac, fixture, free_port  # noqa: E402
from test_new_session_ui import page_dict, swift_enum  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "pointe" / "ui.html").read_text()
KEYS = ("title", "lede", "rule", "session", "task", "taskPlaceholder", "addTask", "newSession", "hours", "messages", "notify",
        "start", "cancel", "stop", "confirmTitle", "ledger", "decided", "asked", "done", "blocked", "inFlight", "notStarted",
        "exact", "empty", "noSessions", "history", "running")


def test_the_page_the_iphone_and_the_mac_say_the_same_words():
    page = page_dict("NIGHT_SHIFT_COPY")
    assert tuple(page) == KEYS
    apps = swift_enum(ROOT / "apps" / "PointeKit" / "Sources" / "PointeKit" / "NightShiftCopy.swift", "NightShiftCopy")
    for key in KEYS:
        assert apps[key] == page[key], f"{key}: the apps and the page differ"
    ui = ROOT / "apps" / "PointeKit" / "Sources" / "PointeUI"
    for source in [*ui.glob("*.swift"), *(ROOT / "apps" / "macos" / "PointeMac").glob("*.swift"), *(ROOT / "apps" / "ios" / "Pointe").glob("*.swift")]:
        assert "enum NightShiftCopy" not in source.read_text(), source.name


def test_every_surface_says_the_approval_rule_and_none_offers_a_way_around_it():
    """The sheet says that Pointe approves nothing, and no screen has an auto-approve or a skip-prompts switch."""
    sheet = PAGE[PAGE.index('id="nightsheet"'):PAGE.index('id="rowsheet"')]
    script = PAGE[PAGE.index("const NIGHT_SHIFT_COPY"):PAGE.index("function approvalCard")]
    assert 'id="night-rule"' in sheet and "approves nothing" in page_dict("NIGHT_SHIFT_COPY")["rule"]
    assert "/voice/approve" not in script  # nothing in the night shift's code on the page answers a request
    assert "folder.append(...o.folders.map" in script and "el('input'" not in script  # a folder is a pick from the Mac's list
    sources = [sheet, script] + [p.read_text() for p in (ROOT / "apps" / "PointeKit" / "Sources").rglob("NightShift*.swift")]
    for text in sources:
        assert not re.search(r"auto[- ]?approv|bypass|skip[- ]?permissions|dangerously", text, re.I)


def test_the_ledger_is_drawn_in_the_mornings_order():
    order = re.search(r"const NIGHT_ORDER = \[(.*?)\];", PAGE).group(1)
    assert re.findall(r"\['(\w+)', '\w+'\]", order) == ["decided", "asked", "done", "blocked", "in_flight", "not_started"]


SHEET = """(() => ({open: document.getElementById('nightsheet').classList.contains('open'),
  form: !document.getElementById('night-form').hidden, ledger: !document.getElementById('night-ledger').hidden,
  title: document.getElementById('night-title').textContent, rule: document.getElementById('night-rule').textContent,
  who: [...document.querySelectorAll('#night-rows .night-who')].map(w => [...w.options].map(o => [o.textContent, o.disabled])),
  rows: document.querySelectorAll('#night-rows .night-row').length,
  hours: document.getElementById('night-hours').value, messages: document.getElementById('night-messages').value,
  notify: document.getElementById('night-notify').checked, err: document.getElementById('night-err').textContent,
  startOff: document.getElementById('night-start').disabled, start: document.getElementById('night-start').textContent,
  head: document.getElementById('night-head').textContent,
  sections: [...document.querySelectorAll('#night-sections section')].map(s => [s.querySelector('h3').textContent,
             [...s.querySelectorAll('li')].map(li => li.textContent)]),
  request: [...document.querySelectorAll('#night-sections pre')].map(p => p.textContent),
  links: [...document.querySelectorAll('#night-sections a')].map(a => [a.textContent, a.href, a.target, a.rel]),
  stopShown: !document.getElementById('night-stop').hidden, newShown: !document.getElementById('night-new').hidden,
  history: [...document.querySelectorAll('#night-history button')].map(b => b.textContent)}))()"""
MAIN = """(() => ({strip: document.getElementById('nightstrip').textContent,
  stripButtons: [...document.querySelectorAll('#nightstrip button')].map(b => b.textContent),
  card: document.getElementById('shiftask').textContent,
  cardButtons: [...document.querySelectorAll('#shiftask button')].map(b => b.textContent),
  entry: document.getElementById('m-night').textContent}))()"""
REQUEST = 'Bash: push the branch\n{"command": "git push origin retry-work"}'


def entry(kind, session, task, **more):
    base = {"id": f"{kind}-{session}", "kind": kind, "session": session, "task": task, "at": time.time(), "text": "", "proof": "",
            "commit": "", "pr": "", "waits_on": "", "request": "", "request_id": "", "question": "", "choice": "", "otherwise": "",
            "resolved": "", "resolved_at": 0}
    return {**base, **more}


def a_night() -> dict:
    """A shift with something in every bucket, as GET /voice/night-shift answers it."""
    summary = {"on": True, "id": "n7", "at": time.time() - 7200, "ends_at": time.time() + 3600, "ended": None, "why": "", "sent": 6,
               "budget": 40, "hours": 8, "notify": False, "tasks": 5, "done": 1, "in_flight": 1, "blocked": 2, "decided": 1, "asked": 1,
               "fronts": []}
    ledger = {
        "done": [entry("done", "billing", "fix the retry tests", text="retry tests pass (42 of 42)", proof="retry tests pass (42 of 42)",
                       commit="3f2a9c1", pr="https://github.com/acme/billing/pull/12")],
        "in_flight": [{"session": "web", "task": "tidy the styles", "since": time.time() - 600, "followups": 0}],
        "blocked": [entry("blocked", "billing", "push the branch", text="Waits for your approval.", waits_on="your approval",
                          request=REQUEST, request_id="p1"),
                    entry("blocked", "shop", "fix the flaky test", text="the fixture server is down", waits_on="the fixture server is down")],
        "decided": [entry("decided", "billing", "fix the retry tests", question="cap the backoff?", choice="30 seconds",
                          otherwise="change MAX_BACKOFF if you want it longer")],
        "asked": [entry("asked", "docs", "update the changelog", question="Old format or new?", text="Old format or new?")],
        "not_started": [{"session": "docs", "task": "write the release notes"}]}
    morning = [{"kind": "headline", "title": "Night shift", "text": "Night shift, 22:10 and still running: 1 of 5 tasks done, 2 blocked."}]
    return {"summary": summary, "shift": {**summary, "how": "voice", "ledger": ledger, "morning": morning}}


@pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")
def test_the_sheet_starts_what_it_shows_and_the_strip_the_card_and_the_ledger_follow():
    async def run():
        stub = await StubMac(free_port()).start()
        stub.status = fixture(sessions=2, connected=True)
        out = {}
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                await page.wait_for_page()
                out["before"] = await page.eval(MAIN)
                await page.eval("(async () => { await openNightShift(); return true; })()")
                await asyncio.sleep(0.4)
                out["sheet"] = await page.eval(SHEET)
                await page.eval("""(() => { const rows = () => document.querySelectorAll('#night-rows .night-row');
                    rows()[0].querySelector('.night-who').value = 'billing';
                    rows()[0].querySelector('.night-task').value = 'fix the retry tests'; nightAddRow();
                    const who = rows()[1].querySelector('.night-who'); who.value = [...who.options].at(-1).value; who.onchange();
                    rows()[1].querySelector('.night-folder').value = '/Users/sam/work/shop'; nightSync(); return true; })()""")
                out["half"] = await page.eval(SHEET)  # the second row has no task yet
                await page.eval("""(() => { document.querySelectorAll('#night-rows .night-task')[1].value = 'fix the flaky test';
                    document.getElementById('night-hours').value = '2'; document.getElementById('night-messages').value = '12';
                    document.getElementById('night-notify').checked = true; nightSync(); return true; })()""")
                out["ready"] = await page.eval(SHEET)
                await page.eval("(async () => { await startShift(); await refresh(); return true; })()")
                await asyncio.sleep(0.4)
                out["started"] = await page.eval(SHEET)
                out["running"] = await page.eval(MAIN)
                night = a_night()
                stub.status["night_shift"] = night["summary"]
                stub.night = {**stub.night, "shift": night["shift"], "history": [night["summary"]]}
                stub.status["shift_pending"] = {"id": "p9", "expires_in": 50, "items": [], "line":
                                                "Night shift. docs: update the changelog. Up to 8 hours and 40 messages. I approve "
                                                "nothing: a session that needs approval waits for you. Start? Say yes or tap."}
                await page.eval("(async () => { await refresh(); await openNightShift(); return true; })()")
                await asyncio.sleep(0.4)
                out["ledger"] = await page.eval(SHEET)
                out["busy"] = await page.eval(MAIN)
                await page.eval("(() => { document.querySelector('#shiftask button.deny').click(); return true; })()")
                await asyncio.sleep(0.3)
                await page.eval("(() => { [...document.querySelectorAll('#nightstrip button')].at(-1).click(); return true; })()")
                await asyncio.sleep(0.5)
                out["stopped"] = await page.eval(MAIN)
        finally:
            await stub.stop()
        return out, [b for p, b, _ in stub.posts if p == "/voice/night-shift"]

    got, posts = asyncio.run(run())
    assert got["before"] == {"strip": "", "stripButtons": [], "card": "", "cardButtons": [], "entry": "Night shift"}
    sheet = got["sheet"]
    assert sheet["open"] and sheet["form"] and not sheet["ledger"] and sheet["title"] == "Night shift" and sheet["start"] == "Start shift"
    assert sheet["rule"] == "Pointe approves nothing: a session that needs approval waits for you."
    assert sheet["who"] == [[["shop", False], ["billing", False], ["New session…", False]]] and sheet["rows"] == 1
    assert (sheet["hours"], sheet["messages"], sheet["notify"]) == ("8", "40", False)  # the caps, and alerts off
    assert sheet["startOff"] and got["half"]["startOff"] and not got["ready"]["startOff"]  # every row needs a task
    assert posts[0] == {"action": "start", "hours": 2, "messages": 12, "notify": True, "items": [
        {"session": "billing", "task": "fix the retry tests"},
        {"start": {"harness": "claude-code", "folder": "/Users/sam/work/shop"}, "task": "fix the flaky test"}]}
    assert got["started"]["ledger"] and not got["started"]["form"] and got["started"]["stopShown"] and not got["started"]["newShown"]
    assert got["running"]["strip"].startswith("Night shift0 of 2 done · 0 blocked") and got["running"]["stripButtons"] == ["Ledger", "Stop shift"]
    ledger = got["ledger"]
    assert ledger["head"] == "Night shift, 22:10 and still running: 1 of 5 tasks done, 2 blocked."
    assert [title for title, _ in ledger["sections"]] == ["Decisions made without you", "Questions waiting on you", "Done", "Blocked",
                                                          "In flight", "Not started"]
    rows = dict(ledger["sections"])
    decided = rows["Decisions made without you"][0]  # as the iPhone app: the question, → the choice, then what else it costs
    assert "cap the backoff?→ 30 secondschange MAX_BACKOFF" in decided and "→ change" not in decided, decided
    assert "docsupdate the changelogOld format or new?" in rows["Questions waiting on you"][0]  # the task, as in the app
    assert "42 of 42" in rows["Done"][0] and "3f2a9c1 · #12" in rows["Done"][0], rows["Done"][0]
    # the pull request is a link named by its number, as on the iPhone, not a raw address
    assert ledger["links"] == [["#12", "https://github.com/acme/billing/pull/12", "_blank", "noopener noreferrer"]], ledger["links"]
    assert ledger["request"] == [REQUEST] and "The exact request" in rows["Blocked"][0]  # word for word, on the screen
    assert ledger["history"] and "1 of 5 done · 2 blocked · running" in ledger["history"][0]
    assert got["busy"]["strip"].startswith("Night shift1 of 5 done · 2 blocked")
    assert "Start this night shift?" in got["busy"]["card"] and "I approve nothing" in got["busy"]["card"]
    assert got["busy"]["cardButtons"] == ["Cancel", "Start shift"]
    assert posts[1:] == [{"action": "cancel", "id": "p9"}, {"action": "stop"}]
    assert got["stopped"]["strip"] == "" and got["stopped"]["card"] == ""
