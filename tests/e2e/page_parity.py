"""What the iPhone app did and the page did not, in a real (headless) Chrome against a real daemon. No call, no paid API.

- Ending a meeting and discarding its notes each take two clicks: the first asks, the second does it.
- Settings → Meetings offers "Ask again before the next meeting" once the consent step was accepted, and it resets it.
- Settings shows the local mode line from the daemon's status.
- Right-to-left text (Hebrew, Arabic) reads from the right in the conversation, the caption, cards and lists: a final
  full stop sits at the left end. English is unchanged. Each element takes its direction from its own first strong
  letter (dir="auto"), not the page's.
- Machines (docs/design/multi-machine.md, "Page"), on a status recorded from this daemon with the design's machine
  fields added: one machine looks as before; with several, filter chips (client-side, nothing sent), a group per machine
  with this Mac first, a machine tag on each row, offline dimming with no Approve or Deny, "shop · devbox" on the card
  and the desktop alert, and Settings → Machines with an invite code counting down and Revoke in two clicks.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-par CLAUDE_VOICE_DAEMON_PORT=7960 CLAUDE_VOICE_TLS_PORT=7560 POINTE_CHROME_PORT=7963 \
     uv run python -u -I tests/e2e/page_parity.py
Screenshots go to $POINTE_SHOTS. POINTE_LIVE_MACHINES=1 skips the fixture and checks the daemon's own machine fields.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from websockets.asyncio.client import connect

os.environ.setdefault("POINTE_SHOTS", tempfile.mkdtemp(prefix="pointe-parity-shots-"))  # before page_meeting reads it
sys.path.insert(0, str(Path(__file__).parent))
from page_meeting import CHROME, Page, call  # noqa: E402
from rig import DAEMON, ROOT, STATE, fresh_state, stop_daemon  # noqa: E402
from scenarios import check, results  # noqa: E402

DEBUG_PORT = int(os.environ.get("POINTE_CHROME_PORT", "7963"))
SHOTS = Path(os.environ["POINTE_SHOTS"])


async def two_clicks(page: Page) -> None:
    await page.js("window.__posted = []; meetPost = async body => { window.__posted.push(body.action); return {}; };"
                  "showEnd = () => {}; closeEnd = () => {}; true")
    await page.js("endMeeting()")
    asked = await page.js("document.getElementById('meetend').textContent")
    check("the first click on End meeting asks, and ends nothing", await page.js("window.__posted.length") == 0
          and asked == "End the meeting?", label=asked)
    await page.js("endMeeting()")
    check("the second click ends the meeting", await page.js("window.__posted") == ["end"])
    await asyncio.sleep(4.5)
    await page.js("window.__posted = []; endMeeting()")
    check("a click after the question lapsed asks again", await page.js("window.__posted.length") == 0)

    await page.js("window.__posted = []; discardMeeting()")
    asked = await page.js("document.getElementById('enddiscard').textContent")
    check("the first click on Discard asks, and keeps the notes", await page.js("window.__posted.length") == 0
          and asked == "Discard the notes?", label=asked)
    await page.js("discardMeeting()")
    check("the second click discards", await page.js("window.__posted") == ["discard"])


async def settings(page: Page) -> None:
    call("/voice/prefs", {"meeting.consented": True})
    await page.js("openSettings()")
    await page.until("!document.getElementById('pref-consent').hidden", 5)
    check("Settings → Meetings offers to ask again once consent was accepted",
          await page.js("!document.getElementById('pref-consent').hidden"))
    await page.shot("settings-consent")
    await page.js("document.getElementById('pref-consent-again').click()")
    await page.until("document.getElementById('pref-consent').hidden", 5)
    check("Ask again resets the consent step on the Mac", call("/voice/status") is not None
          and json.loads(urllib.request.urlopen(urllib.request.Request(
              f"{DAEMON}/voice/prefs", headers={"Authorization": f"Bearer {(STATE / 'token').read_text().strip()}"})).read())
          .get("meeting.consented") is False)

    line = await page.until("document.getElementById('pref-local').textContent", 5)
    check("Settings shows the local mode line from the daemon", line == call("/voice/status")["local"]["line"], line=line)
    await page.shot("settings-local")
    await page.js("closeSheet('settingssheet')")


# The first and last character of an element's text, on screen: where a sentence starts and where its full stop sits.
EDGES = """(e => {
  const walk = document.createTreeWalker(e, NodeFilter.SHOW_TEXT); let first = null, last = null, n;
  while ((n = walk.nextNode())) if (n.textContent.trim()) { first = first || n; last = n; }
  const box = (node, i) => { const r = document.createRange(); r.setStart(node, i); r.setEnd(node, i + 1); return r.getBoundingClientRect(); };
  const end = last.textContent.replace(/\\s+$/, '').length - 1;
  return {start: box(first, first.textContent.search(/\\S/)).left, stop: box(last, end).left, dir: getComputedStyle(e).direction};
})"""
LINES = {"Hebrew": "שלחתי את התיקון לבדיקה.", "Arabic": "أرسلت الإصلاح للمراجعة.",
         "Hebrew with English inside": "פתחתי PR חדש ל-billing.", "English": "Billing is opening the PR.",
         "English with Hebrew inside": "Send it to the תור team.", "digits first, then Hebrew": "42 בדיקות עברו."}
RTL = {"Hebrew", "Arabic", "Hebrew with English inside", "digits first, then Hebrew"}


async def rtl(page: Page) -> None:
    for name, text in LINES.items():
        places = {
            "your bubble": f"turnItem({{id: -1, who: 'user', text: {json.dumps(text)}}}, false)",
            "the bot's bubble": f"turnItem({{id: -2, who: 'assistant', text: {json.dumps(text)}}}, false)",
            "a recent request": f"el('div', 'said', {json.dumps('“' + text + '”')})",
        }
        for where, make in places.items():
            got = await page.js(f"(() => {{ const e = {make}; e.style.maxWidth = '600px'; $('talk').append(e);"
                                f" const r = {EDGES}(e); e.remove(); return r; }})()")
            ok = got["stop"] < got["start"] if name in RTL else got["stop"] > got["start"]
            check(f"{name} in {where}: the full stop is at the {'left' if name in RTL else 'right'} end", ok, **got)
        got = await page.js(f"(() => {{ $('caption-text').textContent = {json.dumps(text)}; $('caption').hidden = false;"
                            f" const r = {EDGES}($('caption-text')); $('caption').hidden = true; return r; }})()")
        ok = got["stop"] < got["start"] if name in RTL else got["stop"] > got["start"]
        check(f"{name} in the caption: the full stop is at the {'left' if name in RTL else 'right'} end", ok, **got)
    await page.js("$('talk').append(turnItem({id: -3, who: 'user', text: " + json.dumps(LINES["Hebrew"]) + "}, false),"
                  " turnItem({id: -4, who: 'assistant', text: " + json.dumps(LINES["Arabic"]) + "}, false),"
                  " turnItem({id: -5, who: 'user', text: " + json.dumps(LINES["English"]) + "}, false)); true")
    await page.shot("rtl-conversation")
    await page.js("[...$('talk').querySelectorAll('li')].filter(li => +li.dataset.id < 0 || !li.dataset.id).forEach(li => li.remove()); true")


# The machine fields as the design defines them ("UI" in docs/design/multi-machine.md). Built on a status recorded from
# the running daemon, so every other field is the real shape. Names are invented.
def machines_fixture(recorded: dict, now: float, *, offline_request: bool = False, invite: dict | None = None) -> dict:
    def session(name, machine="studio", working=False, waiting=False, needs=None, request=None, request_id=None, online=True, harness="claude-code"):
        return {"name": name, "harness": harness, "capabilities": {"approvals": True, "side_questions": machine == "studio",
                                                                   "attach": True, "spawn": machine == "studio"},
                "working": working, "waiting": waiting, "request": request, "request_id": request_id,
                "voice_can_approve": bool(request_id) and online, "needs": needs, "mode": "inbox", "machine": machine, "online": online}
    tests = 'Bash: Run the tests\n{"command": "uv run pytest -q"}'
    sessions = [session("billing/main", working=True), session("shop"),
                session("shop devbox", "devbox", working=True, waiting=not offline_request, request=None if offline_request else tests,
                        request_id=None if offline_request else "r-dev-1"),
                session("api", "devbox", needs="which retry budget to use"), session("חנות", "devbox"),
                session("notes", "laptop", online=False, waiting=offline_request,
                        request=tests if offline_request else None, request_id="r-lap-1" if offline_request else None)]
    return {**recorded, "mode": "orchestrator", "active": "billing/main", "sessions": sessions, "attention": [
                {"id": "permission:r-dev-1", "kind": "permission", "session": "shop devbox", "request_id": "r-dev-1",
                 "title": "shop devbox needs approval", "body": "run the tests", "approvable": True, "at": now}],
            "machines": [
                {"id": "hub", "name": "studio", "here": True, "os": "macos", "online": True, "sessions": 3, "need": 0},
                {"id": "n3f2a1", "name": "devbox", "here": False, "os": "linux", "online": True, "sessions": 3, "need": 2,
                 "rtt_ms": 23, "key_fp": "3f2a9c41d07be215"},
                {"id": "n91c0de", "name": "laptop", "here": False, "os": "macos", "online": False, "since": now - 1800,
                 "sessions": 1, "need": 0, "rtt_ms": None, "key_fp": "91c0de77aa013b42"}],
            "invite": invite}


FAKE = r"""(() => {  // the status comes from the fixture; hub, approve and switch requests are recorded, not sent
  window.__posts = []; window.__invite = null;
  if (!window.__realFetch) window.__realFetch = window.fetch;
  window.fetch = async (url, opts) => {
    const u = String(url), body = opts && opts.body ? JSON.parse(opts.body) : null;
    if (u.startsWith('/voice/status') && window.__fixture) {  // a code made here counts down, as the Mac's would
      const f = {...window.__fixture}, i = window.__invite;
      if (i) f.invite = {code: i.code, expires_in: Math.max(0, Math.round((i.until - Date.now()) / 1000))};
      return new Response(JSON.stringify(f));
    }
    if (/^\/voice\/(hub\/|approve|switch|mode)/.test(u)) {
      window.__posts.push({url: u, body});
      const make = u === '/voice/hub/invite' && body.action === 'make';
      if (u === '/voice/hub/invite') window.__invite = make ? {code: 'K7PQ-2MXD', until: Date.now() + 600000} : null;
      return new Response(JSON.stringify(make ? {code: 'K7PQ-2MXD', expires_in: 600} : {}));
    }
    return window.__realFetch(url, opts);
  };
  return true;
})()"""


async def use(page: Page, fixture: dict) -> None:
    await page.js(f"window.__fixture = {json.dumps(fixture, ensure_ascii=False)}; refresh(); true")
    await asyncio.sleep(0.9)  # a poll paints it


async def machines(page: Page) -> None:
    recorded = call("/voice/status")
    now = __import__("time").time()
    await page.js(FAKE)
    texts = "[...document.querySelectorAll('#list > .s .nm')].map(e => e.firstChild.textContent)"

    one = {**recorded, "sessions": machines_fixture(recorded, now)["sessions"][:2],
           "machines": [{"id": "hub", "name": "studio", "here": True, "os": "macos", "online": True, "sessions": 2, "need": 0}],
           "invite": None}
    await use(page, one)
    check("one machine: no chips, no machine headers, no machine tags (the page as before)",
          await page.js("!$('mchips').children.length && !document.querySelector('#list .mh, #list .machine')")
          and await page.js(texts) == ["billing/main", "shop"], rows=await page.js(texts))
    await page.shot("machines-one")

    await use(page, machines_fixture(recorded, now))
    chips = await page.js("[...$('mchips').children].map(b => b.textContent)")
    check("filter chips at the top: All, this Mac first, then each machine", chips == ["All", "studio", "devbox", "laptop"], chips=chips)
    heads = await page.js("[...document.querySelectorAll('#list .mh')].map(h => h.textContent)")
    check("a group per machine, this Mac first, with its OS, round trip, offline time and what needs you",
          len(heads) == 3 and heads[0].startswith("studiothis Mac") and heads[1] == "devboxLinux23 ms2 need you"
          and heads[2].startswith("laptopmacOSoffline since "), heads=heads)
    tags = await page.js("[...document.querySelectorAll('#list .s')].map(r => (r.querySelector('.machine') || {}).textContent)")
    check("a machine tag on every row while more than one machine has sessions", tags == ["studio", "studio", "devbox", "devbox", "devbox", "laptop"], tags=tags)
    sub = await page.js("$('sub').textContent")
    check("All: the line counts every machine", "Orchestrating 6 sessions · 2 need you" in sub, sub=sub)
    off = await page.js("(() => { const r = [...document.querySelectorAll('#list .s')].find(r => r.querySelector('.nm').firstChild.textContent === 'notes');"
                        " return {away: r.classList.contains('away'), opacity: +getComputedStyle(r).opacity, tag: r.querySelector('.tag').textContent, title: r.title}; })()")
    check("an offline session is dimmed and says offline since when, and that sends are refused",
          off["away"] and off["opacity"] < 0.6 and off["tag"] == "offline" and "offline since" in off["title"] and "sends are refused" in off["title"], **off)
    await page.js("[...document.querySelectorAll('#list .s')].find(r => r.title.startsWith('notes')).click()")
    check("a click on an offline session still focuses it (its notes can be asked about)",
          await page.until("window.__posts.some(p => p.url === '/voice/switch' && p.body.name === 'notes')", 3))
    card = await page.js("document.querySelector('#attention .what').textContent")
    check("the approval card says shop · devbox", card.startswith("shop · devbox needs approval"), card=card)
    check("an online remote request has Approve and Deny", await page.js("document.querySelectorAll('#attention .answer button').length") == 2)
    await page.shot("machines-all")

    await page.js("window.__posts = []; [...$('mchips').children].find(b => b.textContent === 'devbox').click(); true")
    await asyncio.sleep(0.9)
    rows = await page.js(texts)
    check("the devbox chip shows only devbox's sessions", sorted(rows) == ["api", "shop devbox", "חנות"], rows=rows)
    check("filtered to one machine: no machine tags (they would all say the same)", await page.js("!document.querySelector('#list .machine')"))
    sub = await page.js("$('sub').textContent")
    check("the Orchestrating line is filtered too", "Orchestrating 3 sessions on devbox · 2 need you" in sub, sub=sub)
    check("a chip sends nothing and changes no mode", await page.js("window.__posts.length") == 0
          and await page.js("$('m-orchestrator').className") == "on", posts=await page.js("window.__posts"))
    await page.shot("machines-filter-devbox")
    await page.js("[...$('mchips').children].find(b => b.textContent === 'All').click(); true")
    await asyncio.sleep(0.9)
    check("All brings every machine back", len(await page.js(texts)) == 6)

    await page.js("[...document.querySelectorAll('#list .mh')][1].click(); true")
    await asyncio.sleep(0.9)
    check("a header click folds its group, remembered in localStorage",
          sorted(await page.js(texts)) == ["billing/main", "notes", "shop"]
          and await page.js("JSON.parse(localStorage.getItem('pointe.machinesFolded'))") == ["devbox"])
    await page.shot("machines-folded")
    await page.js("[...document.querySelectorAll('#list .mh')][1].click(); true")
    await asyncio.sleep(0.9)
    check("a second click unfolds it", len(await page.js(texts)) == 6)

    await page.js("document.querySelector('#attention .answer button.allow').click(); true")
    posted = await page.until("window.__posts.find(p => p.url === '/voice/approve')", 3)
    check("Approve on a remote card answers that request by id", posted and posted["body"] == {
        "session": "shop devbox", "request_id": "r-dev-1", "decision": "allow"}, posted=posted)

    await use(page, machines_fixture(recorded, now, offline_request=True))
    card = await page.js("document.querySelector('#attention').textContent")
    check("an offline request: no Approve or Deny, and where to answer it",
          await page.js("!document.querySelector('#attention .answer')") and "offline: answer it in its terminal" in card
          and card.startswith("notes · laptop"), card=card)
    await page.shot("machines-offline-request")

    await use(page, machines_fixture(recorded, now))

    got = await page.js("(() => { const nm = [...document.querySelectorAll('#list .s .nm')].find(e => e.firstChild.textContent === 'חנות');"
                        " return {dir: getComputedStyle(nm).direction, tag: getComputedStyle(nm.querySelector('.machine')).direction}; })()")
    check("a Hebrew session name on a machine reads from the right, its English machine tag from the left",
          got == {"dir": "rtl", "tag": "ltr"}, **got)

    await page.js("openSettings()")
    await page.until("!$('machines').hidden", 5)
    items = await page.js("[...$('mach-list').children].map(li => li.textContent)")
    check("Settings → Machines lists each machine with its state, round trip and key",
          len(items) == 3 and items[0].startswith("studio (this Mac)") and "online · 23 ms" in items[1] and "key 3f2a9c41d07be215" in items[1]
          and "offline since" in items[2] and items[1].endswith("Revoke") and not items[0].endswith("Revoke"), items=items)
    await page.shot("settings-machines")

    await page.js("window.__posts = []; $('mach-invitebtn').click(); true")
    code = await page.until("!$('mach-invite').hidden && $('mach-code').textContent", 3)
    check("Invite a machine shows the one-time code as text", code == "K7PQ-2MXD", code=code,
          posts=await page.js("window.__posts"))
    check("the invite asks the Mac for a code", await page.js("window.__posts[0]") == {"url": "/voice/hub/invite", "body": {"action": "make"}})
    first = await page.js("$('mach-left').textContent")
    await asyncio.sleep(2.2)
    later = await page.js("$('mach-left').textContent")
    check("with a 10-minute countdown", first in ("Expires in 10:00", "Expires in 9:59") and later in ("Expires in 9:58", "Expires in 9:57"),
          first=first, later=later)
    await page.shot("settings-machines-invite")
    await page.js("window.__invite = null; true")
    await use(page, machines_fixture(recorded, now, invite={"code": "K7PQ-2MXD", "expires_in": 540,
                                                             "link": "pointe://hub?v=1&host=studio.example.ts.net&port=7443&fp=3b1c&code=K7PQ-2MXD"}))
    left = await page.js("$('mach-left').textContent")
    check("the countdown follows the Mac's expires_in", left in ("Expires in 9:00", "Expires in 8:59"), left=left)
    check("with the full join line when the Mac sends it",
          (await page.js("$('mach-link').textContent")).startswith("pointe node join 'pointe://hub?v=1&host="))
    await page.js("window.__posts = []; $('mach-cancel').click(); true")
    posted = await page.until("window.__posts[0]", 3)
    await use(page, machines_fixture(recorded, now))
    check("Cancel withdraws the code", posted == {"url": "/voice/hub/invite", "body": {"action": "cancel"}}
          and await page.js("$('mach-invite').hidden && !$('mach-invitebtn').hidden"), posted=posted)

    await page.js("window.__posts = []; [...$('mach-list').querySelectorAll('button')][0].click(); true")
    await asyncio.sleep(0.9)
    asked = await page.js("[...$('mach-list').querySelectorAll('button')][0].textContent")
    check("the first click on Revoke asks, and revokes nothing", asked == "Revoke devbox?" and await page.js("window.__posts.length") == 0, asked=asked)
    await page.shot("settings-machines-revoke")
    await page.js("[...$('mach-list').querySelectorAll('button')][0].click(); true")
    posted = await page.until("window.__posts[0]", 3)
    check("the second click revokes it", posted == {"url": "/voice/hub/revoke", "body": {"name": "devbox"}}, posted=posted)
    await page.js("closeSheet('settingssheet')")
    await page.js("window.__fixture = null; window.fetch = window.__realFetch; localStorage.removeItem('pointe.machinesFolded'); refresh(); true")
    await asyncio.sleep(0.9)


async def live_machines(page: Page) -> None:
    """Against a hub with nodes: the daemon's own fields render (run after integration)."""
    s = call("/voice/status")
    check("the daemon sends machines", isinstance(s.get("machines"), list) and any(m.get("here") for m in s["machines"]),
          machines=s.get("machines"))
    await page.js("openSettings()")
    shown = await page.until("!$('machines').hidden && $('mach-list').children.length", 5)
    check("Settings → Machines lists the daemon's machines", shown == len(s.get("machines") or []), shown=shown)
    await page.shot("live-settings-machines")
    await page.js("closeSheet('settingssheet')")


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    fresh_state()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    profile = tempfile.mkdtemp(prefix="pointe-chrome-")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}",
                               "--window-size=1440,900", "--no-first-run",
                               f"{DAEMON}/voice?key={(STATE / 'page_key').read_text().strip()}"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json").read())
                target = next(t for t in tabs if t.get("type") == "page")
                break
            except Exception:
                await asyncio.sleep(0.5)
        async with connect(target["webSocketDebuggerUrl"], max_size=50_000_000) as socket:
            page = Page(socket)
            await page.cdp("Runtime.enable")
            await page.until("typeof meetPost === 'function' && !!status && !!status.sessions", 20)
            await two_clicks(page)
            await settings(page)
            await (live_machines(page) if os.environ.get("POINTE_LIVE_MACHINES") else machines(page))
            await page.js("for (let i = 1; i < 5000; i++) clearInterval(i); true")  # no poll redraws under the measurements
            await rtl(page)
    finally:
        chrome.terminate()
        stop_daemon()
    print(f"screenshots: {SHOTS}")
    failed = [r for r in results if not r["ok"]]
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
