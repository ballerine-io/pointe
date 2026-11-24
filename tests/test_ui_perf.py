"""The page stays responsive: what it does on its own every 700 ms, and what a click waits for.

The page runs in a headless Chrome against a stub Mac (tests/page_rig.py) with twenty sessions on three machines. A poll
that brings the same status must touch no DOM in the lists (a list rebuilt under the pointer swallows the click whose
press and release land on different elements, and drops the keyboard focus); a poll that changes one session touches
that row only; the idle page runs no long task even on a slow CPU; and a session row, the mode switch, the microphone
switch and Settings change on the click, not after the Mac's answer. Skipped where that Chrome is not installed.
"""

import asyncio
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_rig import CHROME, PROBES, ROOT, Browser, StubMac, fixture, free_port  # noqa: E402

PAGE = (ROOT / "pointe" / "ui.html").read_text()
needs_chrome = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")

# A row is found by the session name its title starts with (ui.html row(): `x.name + ' — …'`, `x.name + ' (focused)'`,
# `x.name + ': offline …'`); the fixture's names hold no spaces.
ROW_NAME = "b => b.title.split(/[ :]/)[0]"
ROW_NAMES = f"[...document.querySelectorAll('#list .s')].map({ROW_NAME})"
TAG_ROWS = "(() => { [...document.querySelectorAll('#list .s, #list .mh')].forEach((b, i) => b.__tag = i); return true; })()"
TAGS_KEPT = "[...document.querySelectorAll('#list .s, #list .mh')].map(b => b.__tag)"
# Every mutation in #list, as the row (session name) it touched; a record on #list itself names its added and removed rows.
WATCH_LIST = """(() => {
  window.__touched = [];
  const name = n => n.nodeType === 1 && n.classList.contains('s') ? n.title.split(/[ :]/)[0] : n.nodeType === 1 && n.classList.contains('mh') ? '@' + n.querySelector('.mn').textContent : '?' + (n.nodeName || '');
  window.__mo = new MutationObserver(ms => { for (const m of ms) {
    if (m.target.id === 'list') { for (const n of [...m.addedNodes, ...m.removedNodes]) __touched.push(name(n)); }
    else { const row = m.target.nodeType === 1 ? m.target.closest('.s, .mh') : m.target.parentElement.closest('.s, .mh'); __touched.push(row ? name(row) : '?' + m.type); }
  } });
  __mo.observe(document.getElementById('list'), {childList: true, subtree: true, attributes: true, characterData: true});
  return true; })()"""


async def _page(status, throttle: int = 1):
    """The page on the stub, probes installed, settled after its first polls."""
    stub = await StubMac(free_port()).start()
    stub.status = status
    browser = Browser()
    await browser.__aenter__()
    page = await browser.open(stub.url)
    await page.cdp("Performance.enable")
    if throttle > 1:
        await page.cdp("Emulation.setCPUThrottlingRate", {"rate": throttle})
    await page.eval(PROBES)
    await asyncio.sleep(1.6)
    return stub, browser, page


async def _close(stub, browser):
    await browser.__aexit__(None, None, None)
    await stub.stop()


def test_no_keyframe_animates_a_layout_or_paint_property():
    """A height or box-shadow keyframe runs layout or paint on the main thread 60 times a second for as long as it plays;
    the caption's wave did so while hidden (it keeps display:flex for its fade). Only opacity and transform animate."""
    for name, body in re.findall(r"@keyframes\s+([\w-]+)\s*\{((?:[^{}]*\{[^{}]*\})*)\s*\}", PAGE):
        props = set(re.findall(r"([\w-]+)\s*:", body))
        assert props <= {"opacity", "transform"}, (name, props)
    assert re.search(r"#caption\[hidden\] \.wave i \{ animation: none; \}", PAGE)
    assert "backdrop-filter" not in re.search(r"\.top \{[^}]*\}", PAGE).group(0)
    assert "backdrop-filter" not in re.search(r"\n  \.dock \{[^}]*\}", PAGE).group(0)


@needs_chrome
def test_a_poll_with_the_same_status_touches_no_list():
    async def run():
        stub, browser, page = await _page(fixture(sessions=20, machines=3, talk=200, approval=True))
        try:
            await page.eval("__reset()")
            await page.eval(TAG_ROWS)
            await page.eval("(async () => { await refresh(); await refresh(); return true; })()")
            muts = await page.eval("JSON.stringify(__probe.muts)")
            tags = await page.eval(TAGS_KEPT)
            return muts, tags, stub.status_hits
        finally:
            await _close(stub, browser)

    muts, tags, hits = asyncio.run(run())
    assert hits >= 3
    assert muts == '{"list":0,"recent":0,"talk":0}'
    assert tags == list(range(len(tags))) and len(tags) == 23  # 20 rows and 3 machine headers, the same elements


@needs_chrome
def test_a_poll_that_changes_one_session_touches_that_row_only():
    async def run():
        stub, browser, page = await _page(fixture(sessions=20, machines=3, talk=200, approval=True))
        try:
            await page.eval(WATCH_LIST)
            changed = next(x for x in stub.status["sessions"] if x["needs"])
            changed["needs"] = "which port should it use?"  # the same urgency: the row stays where it is
            await page.eval("(async () => { await refresh(); return true; })()")
            in_place = await page.eval("__touched.slice()")
            await page.eval("__touched = []")
            moved = next(x for x in stub.status["sessions"] if x["working"] and x is not changed)
            moved["working"] = False  # idle now: sorted after the working ones
            await page.eval("(async () => { await refresh(); return true; })()")
            after_move = await page.eval("__touched.slice()")
            names = await page.eval(ROW_NAMES)
            return changed["name"], set(in_place), moved["name"], set(after_move), names
        finally:
            await _close(stub, browser)

    changed, in_place, moved, after_move, names = asyncio.run(run())
    assert in_place == {changed}
    assert after_move == {moved}
    assert len(names) == 20 and len(set(names)) == 20


@needs_chrome
def test_idle_on_a_slow_cpu_runs_no_long_task():
    async def run():
        stub, browser, page = await _page(fixture(sessions=20, machines=3, talk=200, approval=True), throttle=4)
        try:
            await page.eval("__reset()")
            m0 = {m["name"]: m["value"] for m in (await page.cdp("Performance.getMetrics"))["metrics"]}
            await asyncio.sleep(10)
            m1 = {m["name"]: m["value"] for m in (await page.cdp("Performance.getMetrics"))["metrics"]}
            longtasks = await page.eval("JSON.stringify(__probe.longtasks)")
            ticks = await page.eval("__probe.ticks.length")
            return longtasks, ticks, m1["LayoutCount"] - m0["LayoutCount"]
        finally:
            await _close(stub, browser)

    longtasks, ticks, layouts = asyncio.run(run())
    assert ticks >= 10
    assert longtasks == "[]"
    assert layouts <= 3, layouts  # nothing changed on screen: the polls must not lay the page out


@needs_chrome
def test_controls_change_on_the_click_not_after_the_mac_answers():
    """The Mac stalls 2 s on every request: the row, the mode switch, the microphone switch and Settings still move
    within a frame, and the Mac's status, once it arrives, agrees with what was shown."""
    async def run():
        stub, browser, page = await _page(fixture(sessions=20, machines=3, talk=200, approval=True))
        try:
            stub.delay = 2.0
            await asyncio.sleep(0.2)
            got = {}
            got["row"] = await page.eval(f"""(() => {{ const b = document.querySelectorAll('#list .s')[6];
                window.__picked = ({ROW_NAME})(b); b.click();
                return __until(() => [...document.querySelectorAll('#list .s.on')].some({ROW_NAME.replace('b =>', 'x =>').replace('b.title', 'x.title')} === __picked), 1500); }})()""")
            got["posts_answered_at_click"] = len(stub.posts)
            got["mode"] = await page.eval("""(() => { document.getElementById('m-orchestrator').click();
                return __until(() => document.getElementById('m-orchestrator').className === 'on', 1500); })()""")
            got["mic"] = await page.eval("""(() => { document.getElementById('micmode-ptt').click();
                return __until(() => document.getElementById('micmode-ptt').classList.contains('on') && document.body.dataset.state === 'off', 1500); })()""")
            got["settings"] = await page.eval("""(() => { document.getElementById('settingsbtn').click();
                return __until(() => document.getElementById('settingssheet').classList.contains('open'), 1500); })()""")
            await asyncio.sleep(5)  # every request answered, and polls started after that arrived
            stub.delay = 0
            got["mac"] = (stub.status["mode"], stub.status["ptt"]["mode"])
            got["shown"] = await page.eval("[document.getElementById('m-orchestrator').className, document.getElementById('micmode-ptt').classList.contains('on'), document.getElementById('pref-mic').value]")
            got["posts"] = [p[0] for p in stub.posts]
            return got
        finally:
            await _close(stub, browser)

    got = asyncio.run(run())
    for key in ("row", "mode", "mic", "settings"):
        assert got[key]["ms"] is not None and got[key]["frames"] <= 1, (key, got[key])
    assert got["posts_answered_at_click"] == 0  # the row changed before the Mac answered anything
    assert got["mac"] == ("orchestrator", "ptt")
    assert got["shown"] == ["on", True, "ptt"]
    assert ["/voice/switch", "/voice/mode", "/voice/prefs"] == [p for p in got["posts"] if p != "/voice/page-event"][:3]


@needs_chrome
def test_a_press_that_spans_a_poll_still_clicks_the_row():
    """Mouse down on a row, a poll lands, mouse up: the row is the same element, so the click reaches it."""
    async def run():
        stub, browser, page = await _page(fixture(sessions=20, machines=3, talk=200, approval=True))
        try:
            x, y = await page.eval("(() => { const r = document.querySelectorAll('#list .s')[2].getBoundingClientRect(); return [r.x + 40, r.y + r.height / 2]; })()")
            await page.cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
            await page.cdp("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
            pressed = await page.eval(f"({ROW_NAME})(document.querySelectorAll('#list .s')[2])")
            other = next(x for x in stub.status["sessions"] if x["needs"] and x["name"] != pressed)
            other["needs"] = "which port should it use?"  # another row changes under the press; the order stays
            await page.eval("(async () => { while (inflight) await new Promise(r => setTimeout(r, 20)); await refresh(); return true; })()")
            under = await page.eval(f"({ROW_NAME})(document.elementFromPoint({x}, {y}).closest('.s'))")
            await page.cdp("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})
            await asyncio.sleep(0.5)
            return pressed, under, [p for p in stub.posts if p[0] == "/voice/switch"]
        finally:
            await _close(stub, browser)

    pressed, under, switches = asyncio.run(run())
    assert under == pressed
    assert [p[1] for p in switches] == [{"name": pressed}]


@needs_chrome
def test_a_row_click_stays_in_session_mode_after_the_next_poll():
    """In orchestrator mode a click on a row focuses that session, as a tap in the phone app does: the page shows session
    mode at once, and the Mac's status, polled after it answered, keeps it there."""
    async def run():
        stub, browser, page = await _page(fixture(sessions=4))
        try:
            assert stub.status["mode"] == "orchestrator"
            name = await page.eval(f"""(() => {{ const b = document.querySelectorAll('#list .s')[2]; b.click(); return ({ROW_NAME})(b); }})()""")
            await asyncio.sleep(0.3)
            polled = stub.status_hits
            while stub.status_hits < polled + 2:  # two polls after the switch was answered
                await asyncio.sleep(0.1)
            shown = await page.eval("[document.getElementById('m-session').className, document.getElementById('m-orchestrator').className]")
            return name, shown, stub.status["mode"], stub.status["active"]
        finally:
            await _close(stub, browser)

    name, shown, mode, active = asyncio.run(run())
    assert (mode, active) == ("session", name)
    assert shown == ["on", ""]
