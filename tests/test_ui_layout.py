"""The page's layout rules that a restyle can break without any test of behaviour noticing (docs/design/ux-review-web.md).

The page runs in a headless Chrome against the stub Mac (tests/page_rig.py) at a desktop, a small-laptop and a phone
width: a session's name is never cut while it fits in two lines, nothing runs off a phone's screen, every control a
finger can reach is at least 44 px, the sessions sheet is out of the way while closed, the Showing pane is on screen at
every width and leaves the call its room, and the conversation stays on its newest turn when a card takes room from it.
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
