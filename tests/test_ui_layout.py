"""The page's layout rules that a restyle can break without any test of behaviour noticing (docs/design/ux-review-web.md).

The page runs in a headless Chrome against the stub Mac (tests/page_rig.py) at a desktop, a small-laptop and a phone
width: a session's name is never cut while it fits in two lines, nothing runs off a phone's screen, every control a
finger can reach is at least 44 px, the sessions sheet is out of the way while closed, the Showing pane is on screen at
every width and leaves the call its room, the conversation stays on its newest turn when a card takes room from it, a
session's Rename and Disconnect are a finger's reach on touch, and the dock keeps its labels where they fit.
Skipped where that Chrome is not installed.
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_rig import CHROME, Browser, StubMac, fixture, free_port  # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")

LIVE = "call.state = 'live'; call.rtt = 23; render();"
LONG = ("Bash(cd /srv/shop && uv run pytest -q tests/integration/test_checkout_flow.py::test_coupon_applies_before_tax --maxfail=1 && "
        "curl -sS https://deploy.example.test/hooks/" + "a" * 120 + ")")


def _run(steps, status=None):
    """`steps` is a list of (width, js-before, expression); returns the expression's value for each, from one page."""
    async def run():
        stub = await StubMac(free_port()).start()
        stub.status = status or fixture(sessions=4, talk=8, connected=True)
        out = []
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                for width, before, expr in steps:
                    await page.cdp("Emulation.setDeviceMetricsOverride", {"width": width, "height": 844 if width < 500 else 800,
                                                                           "deviceScaleFactor": 1, "mobile": False})
                    await page.eval(f"(async () => {{ {before} await refresh(); return true; }})()")
                    await asyncio.sleep(0.6)
                    out.append(await page.eval(expr))
        finally:
            await stub.stop()
        return out
    return asyncio.run(run())


def _named(names):
    status = fixture(sessions=len(names), talk=4, connected=True)
    for row, name in zip(status["sessions"], names):
        row["name"] = name
    status["sessions"][1].update(waiting=True, working=False, request="Bash(make deploy)", request_id="perm-1", voice_can_approve=True)
    status["sessions"][2].update(needs="which branch should it target?", working=False)
    status["active"] = names[0]
    return status


NAMES = ["checkout", "orders-gateway-refactor-2026", "בדיקות-התשלום-של-החנות", "infra-terraform-production", "a", "payments-service-migration"]
ROWS = """[...document.querySelectorAll('#list .s')].map(r => { const n = r.querySelector('.nm'), t = r.querySelector('.tag');
  return {name: n.textContent, cut: n.scrollWidth > n.clientWidth + 1 || n.scrollHeight > n.clientHeight + 1,
          tagHeight: Math.round(t.getBoundingClientRect().height),
          overlap: !!r.querySelector('.why') && n.getBoundingClientRect().bottom > r.querySelector('.why').getBoundingClientRect().top + 1}; })"""


def test_a_session_name_is_whole_and_its_state_is_one_line_at_every_width():
    """Names win: a name up to 28 characters (what short() lets through) shows whole in the sessions column, on two lines
    at most, and "needs you" never breaks into two."""
    assert all(len(n) <= 28 for n in NAMES)
    got = _run([(1440, LIVE, ROWS), (1024, "", ROWS), (390, "toggleSessions(true);", ROWS)], _named(NAMES))
    for rows in got:
        assert sorted(r["name"] for r in rows) == sorted(NAMES)
        assert not [r for r in rows if r["cut"]], rows
        assert not [r for r in rows if r["overlap"]], rows  # a two-line name never runs into the reason under it
        assert not [r for r in rows if r["tagHeight"] > 20], rows  # one line of 11.5 px


OVERFLOW = """(() => { const off = [];
  for (const e of document.querySelectorAll('main *, #attention *, .sheetbg.open *')) {
    if (e.closest('#show-body, pre, .snav, #speakers, .filters, .arts')) continue;  // these scroll sideways on purpose
    const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
    if (!r.width || cs.visibility === 'hidden' || e.closest('[hidden]')) continue;
    if (r.right > innerWidth + 1 || r.left < -1) off.push((e.id || e.className || e.tagName) + ' ' + Math.round(r.left) + '..' + Math.round(r.right)); }
  return {page: document.documentElement.scrollWidth - innerWidth, off: off.slice(0, 8)}; })()"""


def test_nothing_runs_off_a_phone_screen():
    status = fixture(sessions=6, machines=3, talk=8, approval=True, connected=True)
    status["sessions"][1]["request"] = LONG
    status["conflicts"] = [{"id": "k1", "a": "s0-shop", "b": "s1-api", "at_a": 1, "at_b": 2, "asked": ["a"], "claim_a": "The old price column stays until Friday.",
                            "claim_b": "The old price column was dropped yesterday.", "why": "Both are about the orders table."}]
    got = _run([(390, LIVE, OVERFLOW), (390, "openSettings();", OVERFLOW), (390, "closeSheet('settingssheet'); openSheet('moresheet');", OVERFLOW),
                (360, "closeSheet('moresheet');", OVERFLOW)], status)
    for r in got:
        assert r["page"] <= 0 and not r["off"], r


# A control's target is what a finger hits: the element, something inside it, or the label that wraps it. Probed 21 px
# each way from its middle, so a small mark with room around it (a chip, a close button) counts for the room it takes.
TARGETS = """(() => { const small = [];
  const sel = 'button, [role=button], select, input:not([type=hidden]), textarea, summary';
  for (const e of document.querySelectorAll(sel)) {
    const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
    if (!r.width || !r.height || cs.visibility === 'hidden' || e.disabled || e.closest('[hidden]')) continue;
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const top = document.elementFromPoint(cx, cy);
    const mine = t => !!t && (e.contains(t) || t.contains(e) && !!t.closest('label') || (e.closest('label') || e).contains(t));
    if (!mine(top)) continue;  // under a sheet, or scrolled out of its list
    const box = (e.closest('.snav, #speakers, .filters, .arts, #list, #recent, .spanel, .sheetbox, #talk, #notelist') || document.body).getBoundingClientRect();
    for (const [dx, dy] of [[-21, 0], [21, 0], [0, -21], [0, 21]]) {
      const x = cx + dx, y = cy + dy;
      if (x < box.left || x > box.right || y < box.top || y > box.bottom || x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) continue;  // a scroller's edge
      if (!mine(document.elementFromPoint(x, y))) { small.push((e.id || e.className || e.tagName) + ' "' + (e.textContent || '').trim().slice(0, 16) + '" '
                                                              + Math.round(r.width) + 'x' + Math.round(r.height) + ' @' + dx + ',' + dy); break; }
    } }
  return small; })()"""


def test_every_control_on_a_phone_is_44_px_to_the_finger():
    status = fixture(sessions=6, machines=3, talk=8, approval=True, connected=True)
    status["phones"] = {"paired": [{"id": "p1", "name": "Dana's iPhone", "online": True, "paired_at": 1.0, "last_seen": 2.0}]}
    got = _run([
        (390, LIVE, TARGETS),                                                    # the call, an approval card, the dock
        (390, "toggleSessions(true);", TARGETS),                                 # the sessions sheet: chips, rows, footer
        (390, "toggleSessions(false); openSettings();", TARGETS),                # Settings: the strip, switches, selects
        (390, "closeSheet('settingssheet'); openSheet('moresheet');", TARGETS),  # More
        (390, "closeSheet('moresheet'); openBriefing();", TARGETS),
        (390, "closeSheet('briefsheet'); toggleSessions(true); openRowSheet('s0-shop');", TARGETS),  # a session's Rename and Disconnect
    ], status)
    for small in got:
        # a session row's rename and disconnect marks are a pointer's (they show on hover), not a finger's
        assert not [s for s in small if not s.startswith("edit")], small


SIDE = """(() => { const s = document.getElementById('side'), r = s.getBoundingClientRect(), cs = getComputedStyle(s);
  return {visible: cs.visibility === 'visible', onScreen: r.right > 1, shadow: cs.boxShadow !== 'none', open: document.body.classList.contains('sheet'),
          sessbtn: getComputedStyle(document.getElementById('sessbtn')).display !== 'none', focus: document.activeElement.id,
          scrim: getComputedStyle(document.body, '::before').content !== 'none'}; })()"""


def test_the_sessions_sheet_is_out_of_the_way_closed_and_closes_with_escape():
    esc = "document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));"
    desk, closed, opened, escaped = _run([(1440, LIVE, SIDE), (390, "", SIDE), (390, "toggleSessions(true);", SIDE), (390, esc, SIDE)])
    assert desk["visible"] and desk["onScreen"] and not desk["sessbtn"], desk  # a column: no button that opens nothing
    assert not closed["visible"] and not closed["onScreen"] and not closed["shadow"] and closed["sessbtn"], closed
    assert opened["visible"] and opened["onScreen"] and opened["scrim"] and opened["focus"] == "sideclose", opened
    assert not escaped["open"] and not escaped["visible"], escaped


SHOW = """(() => { const r = id => document.querySelector(id).getBoundingClientRect();
  const show = r('#show'), dock = r('.dock'), main = r('main'), top = r('.top'), btns = [...document.querySelectorAll('.dock-side .btn')].filter(b => b.offsetParent);
  return {shown: show.width > 200 && show.height > 150 && show.left >= -1 && show.right <= innerWidth + 1 && show.top >= 0 && show.bottom <= innerHeight + 1,
          overDock: show.bottom > dock.top + 1 && show.top < dock.bottom && show.left < dock.right && show.right > dock.left,
          overTop: show.top < top.bottom - 1 && show.left < top.right && show.right > top.left, main: Math.round(main.width),
          dockRows: new Set(btns.map(b => Math.round(b.getBoundingClientRect().top))).size,
          subLines: Math.round(r('#sub').height / parseFloat(getComputedStyle(document.getElementById('sub')).lineHeight))}; })()"""


def test_the_showing_pane_is_on_screen_and_leaves_the_call_its_room():
    status = fixture(sessions=3, talk=8, connected=True)
    status["showing"] = {"id": "sh1", "session": "s0-shop", "summary": "the coupon fix and its test", "current": "a1", "at": 1.0,
                         "artifacts": [{"id": "a1", "kind": "edit", "name": "checkout.py", "path": "shop/checkout.py"}]}
    got = _run([(1440, LIVE, SHOW), (1280, "", SHOW), (1024, "", SHOW), (390, "", SHOW)], status)
    for r in got:
        assert r["shown"] and not r["overDock"] and not r["overTop"], r
    for r in got[:3]:  # beside the call: the call keeps a usable column, its dock in one row, its status line whole
        assert r["main"] >= 540 and r["dockRows"] == 1 and r["subLines"] == 1, r


def test_the_newest_turn_stays_in_view_when_a_card_takes_room():
    status = fixture(sessions=4, talk=30, connected=True)
    gap = "(() => { const t = document.getElementById('talk'); return Math.round(t.scrollHeight - t.scrollTop - t.clientHeight); })()"
    card = ("window.__s = window.__s || 1; const f = window.fetch; window.fetch = async (u, o) => { const r = await f(u, o); "
            "if (String(u).startsWith('/voice/status') && !(o && o.method)) { const j = await r.json(); j.sessions[1] = {...j.sessions[1], waiting: true, working: false, "
            "request: 'Bash(make deploy)\\nline two\\nline three', request_id: 'perm-9', voice_can_approve: true}; return new Response(JSON.stringify(j)); } return r; };")
    before, after = _run([(1440, LIVE, gap), (1440, card, gap + " + (document.querySelector('#attention .ask') ? 0 : 9999)")], status)
    assert before <= 2 and after <= 2, (before, after)


MIC = """(() => { const m = document.getElementById('mic').getBoundingClientRect(), l = document.getElementById('miclabel').getBoundingClientRect();
  const ring = parseFloat((getComputedStyle(document.getElementById('mic')).boxShadow.match(/(\\d+)px(?=\\s*$|\\s*,)/) || [0, 0])[1]) || 0;
  const cap = document.getElementById('caption').getBoundingClientRect();
  return {state: document.body.dataset.state, clear: l.top - m.bottom, ring: (getComputedStyle(document.getElementById('mic')).boxShadow.match(/0px 0px 0px (\\d+)px/) || [0, 0])[1] | 0,
          hiddenCaption: document.getElementById('caption').hidden ? Math.round(cap.height) : -1}; })()"""


def test_the_talking_ring_clears_the_label_and_a_hidden_caption_takes_no_room():
    status = fixture(sessions=3, talk=4, connected=True)
    status["ptt"] = {"mode": "ptt", "open": True, "sent_bytes": 0, "room_heard": False}
    status["whisper"] = {"on": True, "held": None, "suggest_ptt": False, "lock_note": None}
    talking = LIVE + "ptt.held.add('key'); ptt.sent = true; render();"
    for r in _run([(1440, talking, MIC), (390, "", MIC)], status):
        assert r["state"] == "talking" and r["ring"] > 0 and r["ring"] < r["clear"], r
        assert r["hiddenCaption"] == 0, r  # whisper mode's larger caption must not pad the hidden one


MORE = """(() => [...document.querySelectorAll('#list .s')].map(r => { const b = r.querySelector('.more'), rect = b.getBoundingClientRect();
  return {shown: getComputedStyle(b).display !== 'none' && rect.width > 0, w: Math.round(rect.width), h: Math.round(rect.height),
          label: b.getAttribute('aria-label')}; }))()"""


def test_a_sessions_rename_and_disconnect_are_behind_a_44_px_button_on_touch():
    """On a phone, or a touch screen of any width, a row has no hover to show its Rename and Disconnect marks: a ⋯
    button does, 44 px square. With a mouse on a wide screen the row keeps its hover marks and no ⋯."""
    async def run():
        stub = await StubMac(free_port()).start()
        stub.status = fixture(sessions=4, talk=4, connected=True)
        out = {}
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                for name, width, touch in (("desk", 1440, False), ("phone", 390, False), ("touchDesk", 1440, True)):
                    await page.cdp("Emulation.setTouchEmulationEnabled", {"enabled": touch, "maxTouchPoints": 5 if touch else 1})
                    await page.cdp("Emulation.setDeviceMetricsOverride", {"width": width, "height": 844 if width < 500 else 900,
                                                                           "deviceScaleFactor": 1, "mobile": False})
                    await page.eval(f"(async () => {{ {LIVE} toggleSessions({'true' if width < 500 else 'false'}); await refresh(); return true; }})()")
                    await asyncio.sleep(0.6)
                    out[name] = await page.eval(MORE)
        finally:
            await stub.stop()
        return out
    got = asyncio.run(run())
    assert got["desk"] and not [r for r in got["desk"] if r["shown"]], got["desk"]
    for rows in (got["phone"], got["touchDesk"]):
        assert len(rows) == 4 and all(r["shown"] and r["w"] >= 44 and r["h"] >= 44 for r in rows), rows
    assert sorted(r["label"] for r in got["phone"]) == [f"Rename or disconnect {n}" for n in ("s0-shop", "s1-api", "s2-mobile", "s3-infra")]


SHEET = """(() => ({open: document.getElementById('rowsheet').classList.contains('open'), name: document.getElementById('row-name').textContent,
  focus: document.activeElement.id, cut: document.getElementById('row-cut').textContent,
  renaming: [...document.querySelectorAll('#list .s input')].map(i => i.value)}))()"""


def test_the_rows_sheet_renames_and_disconnects_with_two_taps():
    async def run():
        stub = await StubMac(free_port()).start()
        stub.status = fixture(sessions=4, talk=4, connected=True)
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                await page.cdp("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": False})
                await page.eval(f"(async () => {{ {LIVE} toggleSessions(true); await refresh(); return true; }})()")
                await asyncio.sleep(0.6)
                tap = "[...document.querySelectorAll('#list .s')].find(r => r.querySelector('.nm').textContent === 's1-api').querySelector('.more').click();"
                await page.eval(f"(() => {{ {tap} return true; }})()")
                await asyncio.sleep(0.3)
                opened = await page.eval(SHEET)
                switched = [p for p, _, _ in stub.posts if p == "/voice/switch"]  # the tap on ⋯ is not a tap on the row
                await page.eval("document.getElementById('row-cut').click()")
                await asyncio.sleep(0.3)
                asked = await page.eval(SHEET)
                cut_after_one = [b for p, b, _ in stub.posts if p == "/voice/disconnect"]
                await page.eval("document.getElementById('row-cut').click()")
                await asyncio.sleep(0.3)
                done = await page.eval(SHEET)
                cut = [b for p, b, _ in stub.posts if p == "/voice/disconnect"]
                await page.eval(f"(() => {{ {tap} return true; }})()")
                await asyncio.sleep(0.3)
                await page.eval("document.getElementById('row-rename').click()")
                await asyncio.sleep(0.3)
                renamed = await page.eval(SHEET)
        finally:
            await stub.stop()
        return opened, switched, asked, cut_after_one, done, cut, renamed
    opened, switched, asked, cut_after_one, done, cut, renamed = asyncio.run(run())
    assert opened["open"] and opened["name"] == "s1-api" and opened["focus"] == "row-rename" and opened["cut"] == "Disconnect", opened
    assert not switched
    assert asked["open"] and asked["cut"] == "Tap again to disconnect" and not cut_after_one, asked  # the first tap only asks
    assert not done["open"] and cut == [{"name": "s1-api"}], (done, cut)
    assert not renamed["open"] and renamed["renaming"] == ["s1-api"] and renamed["focus"] == "", renamed  # the row's rename box, focused


DOCK = """(() => { const r = e => e.getBoundingClientRect();
  return [...document.querySelectorAll('.dock-side')].map(side => { const btns = [...side.children].filter(b => getComputedStyle(b).display !== 'none' && !b.hidden);
    return {rows: new Set(btns.map(b => Math.round(r(b).top))).size, inside: btns.every(b => r(b).left >= r(side).left - 1 && r(b).right <= r(side).right + 1),
            labels: btns.map(b => { const l = b.querySelector('.lb'); return r(l).width > 2 && r(l).height < 20 ? l.textContent : null; })}; }); })()"""


def test_the_dock_keeps_its_labels_where_they_fit():
    """Measured, not guessed: at 1024 px beside the sessions column (and from 1000 px, and from 761 px with no column)
    every dock button keeps its label on one row, the longest ones too; beside the column under 1000 px they are
    tooltips. A phone's dock has four buttons, labelled as the iPhone app's are."""
    status = fixture(sessions=3, talk=4, connected=True)
    long = {**status, "whisper": {"on": True, "held": None, "suggest_ptt": False, "lock_note": None},
            "challenge": {"id": "c1", "on": True, "plan": "Ship it.", "items": [], "verdict": None}}
    got = _run([(1024, LIVE, DOCK), (1000, "", DOCK), (761, "", DOCK), (999, "", DOCK), (390, "", DOCK)], status)
    longs = _run([(1024, LIVE, DOCK), (1000, "", DOCK), (761, "", DOCK)], long)
    for sides in got[:3] + longs:
        assert all(s["rows"] == 1 and s["inside"] and None not in s["labels"] for s in sides), sides
    assert [s["labels"] for s in got[0]] == [["Brain dump", "Meeting", "Briefing"], ["Challenge", "Whisper", "Type"]]
    assert [s["labels"] for s in longs[0]][1] == ["End challenge", "Whispering", "Type"]
    assert all(s["rows"] == 1 and set(s["labels"]) == {None} for s in got[3]), got[3]
    assert [s["labels"] for s in got[4]] == [["More", "Type"], ["Sessions", "Hang up"]], got[4]


def test_a_phones_dock_is_two_and_two_around_the_mic():
    """Two buttons each side, the same distance out, as the iPhone app's dock (QA round 1: one left, three right)."""
    probe = """(() => { const c = e => { const r = (e.querySelector('.ic') || e).getBoundingClientRect(); return r.left + r.width / 2; };
      const mic = c(document.getElementById('mic')), side = s => [...document.querySelector('.dock-side.' + s).children]
        .filter(b => b.offsetParent && getComputedStyle(b).visibility !== 'hidden').map(b => Math.round(Math.abs(c(b) - mic)));
      return [side('left').reverse(), side('right')]; })()"""
    for left, right in _run([(390, LIVE, probe), (360, "", probe)], fixture(sessions=3, talk=4, connected=True)):
        assert len(left) == len(right) == 2 and all(abs(a - b) <= 4 for a, b in zip(left, right)), (left, right)


OVERLAPS = """(() => { const btns = [...document.querySelectorAll('.dock button')].filter(b => b.offsetParent && getComputedStyle(b).visibility !== 'hidden');
  const box = b => (b.querySelector('.ic') || b).getBoundingClientRect(), out = [];
  for (const [i, a] of btns.entries()) for (const b of btns.slice(i + 1)) {
    if (a.contains(b) || b.contains(a)) continue;
    const p = box(a), q = box(b), x = Math.min(p.right, q.right) - Math.max(p.left, q.left), y = Math.min(p.bottom, q.bottom) - Math.max(p.top, q.top);
    if (x > 0.5 && y > 0.5) out.push(a.id + ' over ' + b.id + ' by ' + Math.round(x)); }
  return out; })()"""


def test_no_dock_button_covers_another_on_the_first_call_or_after():
    """The first call hides the mode switch and most of the dock; Hang up still has its own room beside the mic, so Type
    never slides under it (QA round 1: 16 px of overlap from 901 to 1440 px)."""
    widths = (1440, 1280, 1100, 1024, 901, 800, 600, 390, 360)
    first = fixture(sessions=1, talk=1, connected=True)
    first["first_call"] = True
    for status in (first, fixture(sessions=3, talk=4, connected=True)):
        got = _run([(w, LIVE, OVERLAPS) for w in widths], status)
        assert got == [[]] * len(widths), dict(zip(widths, got))


SHORT = """(async () => { const hit = s => { const e = document.querySelector(s); e.scrollIntoView({block: 'nearest'}); const b = e.getBoundingClientRect();
    const t = document.elementFromPoint(b.left + Math.min(12, b.width / 2), b.top + b.height / 2); return !!t && (e === t || e.contains(t)); };
  const what = document.querySelector('#attention .ask .what').getBoundingClientRect();
  const atLoad = what.top >= 0 && what.bottom <= innerHeight && hit('#attention .ask .what');
  return {atLoad, approve: hit('#attention .ask .allow'), mic: hit('#mic'), hangup: hit('#hangup')}; })()"""


def test_on_a_short_screen_the_approval_card_is_never_under_the_conversation():
    """A phone held sideways (844x390) or a laptop at 200 % zoom (720x450): the card's header, which names the session
    that asks, shows when the page opens, and the card and the dock can be reached; no bubble lies over them."""
    async def run():
        stub = await StubMac(free_port()).start()
        stub.status = fixture(sessions=4, talk=12, approval=True, connected=True)
        out = []
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                for w, h in ((844, 390), (720, 450)):
                    await page.cdp("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False})
                    await page.eval(f"(async () => {{ {LIVE} await refresh(); document.querySelector('main').scrollTop = 0; return true; }})()")
                    await asyncio.sleep(0.6)
                    out.append(await page.eval(SHORT))
        finally:
            await stub.stop()
        return out
    for r in asyncio.run(run()):
        assert r == {"atLoad": True, "approve": True, "mic": True, "hangup": True}, r


def test_the_newest_turn_is_in_view_when_the_page_opens_with_a_card_up():
    """The first paint scrolls to the newest turn and the card then takes its room in the same frame: the scroll event
    that follows is the page's own, not the user scrolling up, so the conversation stays on its newest turn."""
    async def run():
        stub = await StubMac(free_port()).start()
        stub.status = fixture(sessions=4, talk=30, approval=True, connected=True)
        out = []
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                for w, h in ((1440, 900), (390, 844)):
                    await page.cdp("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": w < 500})
                    await page.cdp("Page.reload", {"ignoreCache": True})
                    await asyncio.sleep(0.3)
                    await page.wait_for_page()
                    await asyncio.sleep(0.8)
                    out.append(await page.eval("(() => { const t = document.getElementById('talk'); return [Math.round(t.scrollHeight - t.scrollTop - t.clientHeight),"
                                               " !!document.querySelector('#attention .ask')]; })()"))
        finally:
            await stub.stop()
        return out
    for gap, card in asyncio.run(run()):
        assert card and gap <= 2, (gap, card)


MACH = """(() => { const row = document.getElementById('mach-invitebtn').parentElement;
  return {revoke: [...document.querySelectorAll('#mach-list button')].filter(b => b.offsetParent).map(b => b.textContent),
          emptyRow: !!row.offsetParent && ![...row.children].some(c => c.offsetParent)}; })()"""


def test_a_page_that_may_not_change_machines_offers_neither_revoke_nor_an_empty_row():
    """A phone's browser over the TLS listener is refused every machine change (hub_nodes.owner): it shows the machines,
    no Revoke that always fails with "forbidden", and no empty row where Invite would be."""
    owner = fixture(sessions=3, machines=2, connected=True)
    remote = {**owner, "can_invite": False}
    (mine,), (theirs,) = (_run([(390, "openSettings();", MACH)], s) for s in (owner, remote))
    assert mine == {"revoke": ["Revoke"], "emptyRow": False}, mine
    assert theirs == {"revoke": [], "emptyRow": False}, theirs


def test_more_is_never_an_empty_sheet():
    """The first call hides everything More would hold, so on a phone it offers no More at all."""
    more = """(() => ({more: !!document.getElementById('morebtn').offsetParent,
                    items: [...document.getElementById('more-list').children].filter(c => getComputedStyle(c).display !== 'none').length}))()"""
    first = fixture(sessions=1, talk=1, connected=True)
    first["first_call"] = True
    for status in (first, fixture(sessions=3, talk=4, connected=True)):
        (r,) = _run([(390, LIVE, more)], status)
        assert not r["more"] or r["items"] > 0, r


def test_the_new_session_selects_look_like_every_other_select():
    """The Agent and Folder pickers keep the chevron every select on the page has: without it they read as text fields."""
    look = """(() => [...document.querySelectorAll('#newsheet select')].filter(e => e.offsetParent).map(e => {
      const cs = getComputedStyle(e); return {id: e.id, chevron: cs.backgroundImage.startsWith('url('), room: parseFloat(cs.paddingRight)}; }))()"""
    (got,) = _run([(1440, "await openNewSession();", look)], fixture(sessions=2, connected=True))
    assert got and all(s["chevron"] and s["room"] >= 28 for s in got), got


def test_the_typed_message_field_has_a_name_and_shows_its_focus():
    """WCAG 2.4.7 and 4.1.2: focused, the field draws the page's focus ring; its name is not only a placeholder."""
    focus = """(() => { const e = document.getElementById('typed'); e.focus(); const cs = getComputedStyle(e);
      return {ring: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) >= 2, name: e.getAttribute('aria-label') || (e.labels[0] || {}).textContent || ''}; })()"""

    async def run():
        stub = await StubMac(free_port()).start()
        stub.status = fixture(sessions=2, talk=2, connected=True)
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                await page.cdp("Emulation.setFocusEmulationEnabled", {"enabled": True})  # headless has no focused window
                await page.eval(f"(async () => {{ {LIVE} await refresh(); return true; }})()")
                await asyncio.sleep(0.5)
                return await page.eval(focus)
        finally:
            await stub.stop()
    r = asyncio.run(run())
    assert r["ring"] and r["name"].strip(), r


def test_a_screen_reader_hears_an_approval_and_the_call_changing_but_not_each_turn():
    """The approval card's region is live; the call's own changes (connected, muted) are read out, the Speaking and
    Listening of every turn are not, since they would talk over the voice."""
    say = "[document.getElementById('attention').getAttribute('aria-live'), document.getElementById('statesay').textContent]"
    status = fixture(sessions=3, talk=2, approval=True, connected=True)
    off, live, muted = _run([(1440, "", say), (1440, LIVE, say), (1440, "muted = true; render();", say)], status)
    talking = status | {"speaking": "bot"}
    _, first, turn = _run([(1440, "", say), (1440, LIVE, say), (1440, "", say)], talking)
    assert off == ["polite", ""], off
    assert live == ["polite", "Listening"] and muted[1] == "Muted", (live, muted)
    assert first[1] == turn[1] == "Speaking", (first, turn)  # said once, as the call came up


def test_the_context_panel_keeps_the_keyboard_inside_and_gives_it_back():
    """The panel is a modal dialog: focus starts on its Close, Tab never lands behind it, Escape returns to the opener."""
    where = "[document.activeElement.id, !!document.activeElement.closest('#ctxpanel')]"

    async def run():
        stub = await StubMac(free_port()).start()
        stub.status = fixture(sessions=4, talk=6, connected=True)
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                await page.cdp("Emulation.setFocusEmulationEnabled", {"enabled": True})
                await page.eval(f"(async () => {{ {LIVE} await refresh(); $('ctx').focus(); openCtx(); return true; }})()")
                await asyncio.sleep(0.4)
                stops = [await page.eval(where)]
                for _ in range(40):
                    for kind in ("keyDown", "keyUp"):
                        await page.cdp("Input.dispatchKeyEvent", {"type": kind, "key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9})
                    stops.append(await page.eval(where))
                modal = await page.eval("document.getElementById('ctxpanel').getAttribute('aria-modal')")
                for kind in ("keyDown", "keyUp"):
                    await page.cdp("Input.dispatchKeyEvent", {"type": kind, "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
                await asyncio.sleep(0.2)
                back = await page.eval("document.activeElement.id")
                return stops, modal, back
        finally:
            await stub.stop()
    stops, modal, back = asyncio.run(run())
    assert modal == "true" and stops[0][1], stops[0]
    assert all(inside for _, inside in stops), [s for s in stops if not s[1]]
    assert back == "ctx", back


def test_the_sessions_list_is_never_a_small_box_inside_the_column():
    """Nine sessions on three machines: the list shows whole and the column scrolls as one, so no row or machine header
    is cut by an inner scroll box of four rows; Settings stays at the column's foot."""
    probe = """(() => { const l = document.getElementById('list'), side = document.getElementById('side').getBoundingClientRect(),
      f = document.querySelector('#side footer').getBoundingClientRect();
      return {inner: l.scrollHeight - l.clientHeight, footer: f.bottom <= side.bottom + 1 && f.bottom >= side.bottom - 24}; })()"""
    status = fixture(sessions=9, machines=3, talk=4, approval=True, connected=True)
    for r in _run([(1440, LIVE, probe), (390, "toggleSessions(true);", probe)], status):
        assert r["inner"] <= 1 and r["footer"], r


KEYS = {"line": "Setup: Free start. Every role is filled.", "setup": "free",
        "keys": {"gemini": "in use", "openai": "optional", "anthropic": "optional", "soniox": "optional", "elevenlabs": "optional"},
        "uses": {"gemini": ["brain", "reader", "checker", "ears", "mouth"]},
        "setups": [{"id": "free", "name": "Free start", "short": "One Gemini key.", "pick_for": "trying Pointe at no cost",
                    "cost": "$0 until the free quota ends; about $0.70 to $0.95 with billing on"},
                   {"id": "openai", "name": "One OpenAI key", "short": "One OpenAI key.", "pick_for": "people who already pay for OpenAI",
                    "cost": "about $0.95"}]}
KEYROWS = """(() => { const x = e => Math.round(e.getBoundingClientRect().left), lh = e => parseFloat(getComputedStyle(e).lineHeight) || 20;
  const rows = [...document.querySelectorAll('#pref-keys .r')], heads = [...document.querySelectorAll('#pref-setups .shead2 b')];
  const use = [...document.querySelectorAll('#pref-setups .r button')], help = [...document.querySelectorAll('#pref-setups .help')];
  return {states: new Set(rows.map(r => x(r.querySelector('.kstate')))).size,
          names: heads.map(b => Math.round(b.getBoundingClientRect().height / lh(b))),
          helpIndent: help.map((h, i) => x(h) + parseFloat(getComputedStyle(h).paddingLeft) - x(heads[i])),
          use: use.map(b => Math.round(b.getBoundingClientRect().height))}; })()"""


def test_model_keys_states_line_up_and_a_setup_reads_as_a_choice():
    """The state column starts at one x; a setup's name keeps one line beside a long cost; its description lines up with
    its name; Use this setup is a button a finger hits, not a thin bar that reads as a divider."""
    status = {**fixture(sessions=2, connected=True), "keys": KEYS}
    for r in _run([(1440, "openSettings();", KEYROWS), (390, "", KEYROWS)], status):
        assert r["states"] == 1 and r["names"] == [1, 1] and all(abs(d) <= 1 for d in r["helpIndent"]), r
        assert r["use"] and all(h >= 36 for h in r["use"]), r


def test_a_first_open_offers_no_phone_errand_and_a_later_one_says_the_phone_is_optional():
    phone = "(() => { const b = document.getElementById('connect-phone'); return [!!b.offsetParent, b.textContent]; })()"
    first = {**fixture(sessions=2), "first_call": True, "phone_listener": False}
    later = {**first, "first_call": False}
    (a,), (b,) = (_run([(1440, "", phone)], s) for s in (first, later))
    assert a[0] is False, a
    assert b[0] is True and b[1].startswith("Optional:"), b


def test_an_invite_with_no_address_offers_the_pages_own_phone_step():
    fail = """const f = window.fetch; window.fetch = async (u, o) => String(u).startsWith('/voice/hub/invite') && o && o.method === 'POST'
      ? new Response('Not set up yet: run `pointe pair wifi`.', {status: 409, headers: {'x-pointe-fix': 'phone'}}) : f(u, o);
      openSettings(); await inviteMachine(); window.fetch = f;"""
    said = "(() => { const e = document.getElementById('mach-err'); return [e.textContent, !!e.querySelector('button')]; })()"
    (r,) = _run([(1440, fail, said)], fixture(sessions=2, machines=2, connected=True))
    assert "`" not in r[0] and "pointe pair" not in r[0] and "Phone" in r[0] and r[1], r


def test_fix_the_key_shows_only_beside_the_refused_key():
    """With a key refused, Fix the key goes with Cannot hear you; not with Pointe not answering, nor with a call that is
    up on another device. The not-answering line names no internal host."""
    probe = "(() => [!!document.getElementById('fixkey').offsetParent, (document.getElementById('connect-why')?.textContent || '') + ' ' + document.getElementById('problem').textContent, location.host])()"
    refused = {**fixture(sessions=2, talk=2, connected=True), "key_refused": {"vendor": "gemini", "ears": True}}
    down = "window.fetch = async () => { throw new TypeError('Failed to fetch'); }; await refresh(); await refresh();"
    mine, elsewhere, dead = _run([(1440, LIVE, probe), (1440, "call.state = 'off'; render();", probe), (1440, down, probe)], refused)
    assert mine[0] is True, mine
    assert elsewhere[0] is False, elsewhere
    assert dead[0] is False and "not answering" in dead[1] and dead[2] not in dead[1], dead


def test_a_gone_artifact_is_named_not_led_by_a_colon():
    status = fixture(sessions=2, talk=4, connected=True)
    status["showing"] = {"id": "sh1", "session": "s0-shop", "summary": "the coupon fix", "current": "a1", "at": 1.0,
                         "artifacts": [{"id": "a1", "kind": "file", "name": "checkout.py", "path": "shop/checkout.py"}]}
    (msg,) = _run([(1440, LIVE, "(document.querySelector('#show-body .msg') || {}).textContent")], status)
    assert msg and not msg.startswith(":") and msg.startswith("checkout.py: "), msg


def test_space_on_a_session_row_switches_as_enter_does():
    """A row is role=button: Space presses it, as it presses every button (WAI-ARIA button pattern)."""
    async def run():
        stub = await StubMac(free_port()).start()
        stub.status = fixture(sessions=3, talk=2, connected=True)
        try:
            async with Browser() as browser:
                page = await browser.open(stub.url)
                await page.cdp("Emulation.setFocusEmulationEnabled", {"enabled": True})
                await page.eval(f"(async () => {{ {LIVE} await refresh(); [...document.querySelectorAll('#list .s')]"
                                ".find(r => r.querySelector('.nm').textContent === 's2-mobile').focus(); return true; })()")
                for kind in ("keyDown", "keyUp"):
                    await page.cdp("Input.dispatchKeyEvent", {"type": kind, "key": " ", "code": "Space", "windowsVirtualKeyCode": 32,
                                                             **({"text": " "} if kind == "keyDown" else {})})
                await asyncio.sleep(0.4)
                return [b for p, b, _ in stub.posts if p == "/voice/switch"], await page.eval("muted")
        finally:
            await stub.stop()
    switched, muted = asyncio.run(run())
    assert switched == [{"name": "s2-mobile"}] and muted is False, (switched, muted)


def test_mode_settings_nav_and_the_page_title_carry_their_roles():
    """The Mode switch is a radio group whose choice is checked; the Settings section in view is aria-current; the page
    has one h1."""
    probe = """(() => ({group: document.querySelector('#modesec .seg').getAttribute('role'),
      modes: [...document.querySelectorAll('#modesec .seg button')].map(b => [b.getAttribute('role'), b.getAttribute('aria-checked')]),
      current: [...document.querySelectorAll('#set-nav button')].filter(b => b.getAttribute('aria-current') === 'true').map(b => b.textContent),
      h1: [...document.querySelectorAll('h1')].map(h => h.textContent.trim())}))()"""
    (r,) = _run([(1440, "openSettings(); settingsJump('machines');", probe)], fixture(sessions=2, machines=2, connected=True))
    assert r["group"] == "radiogroup" and r["modes"] == [["radio", "true"], ["radio", "false"]], r
    assert r["current"] == ["Machines"] and r["h1"] == ["Pointe"], r


def test_the_folders_field_lines_up_with_the_other_settings_rows():
    probe = """(() => { const f = document.getElementById('pref-folders').closest('.field'), t = document.getElementById('pref-folders');
      const text = document.createRange(); text.selectNodeContents(f.firstChild); const row = document.getElementById('pref-conflicts').closest('label, .tick, .r, .field');
      const inset = e => Math.round(e.getBoundingClientRect().left + parseFloat(getComputedStyle(e).paddingLeft));
      return [Math.round(text.getBoundingClientRect().left), inset(row), Math.round(t.getBoundingClientRect().left) - Math.round(f.getBoundingClientRect().left)]; })()"""
    for label, row, box in _run([(1440, "openSettings();", probe), (390, "", probe)], fixture(sessions=2, connected=True)):
        assert abs(label - row) <= 1 and box >= 13, (label, row, box)
