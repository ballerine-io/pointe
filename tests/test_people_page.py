"""People and machines on the page (docs/design/people-and-machines.md), in a headless Chrome against a stub Mac
(tests/page_rig.py) that answers the contract's routes and status fields.

- Settings → Machines → Add a machine: paste the line and it is added; the daemon's refusal is said next to the field,
  which keeps the line; a name is asked only when the daemon says the machine's own is taken (409).
- The one-time card says which services the voice sends that machine's transcripts to, until OK.
- People: an invite with a grant, the line to copy, the person in the list once they pair, their grant in one click,
  Remove in two.
- Whose a session or a machine is shows only when the status says so; a machine I may only watch offers no send.
- Private on a session I own, on a machine that has people.
- With machines of my own and no people, none of it shows.

Every name here is made up.

uv run --locked --group test-tools pytest -q tests/test_people_page.py --runslow -p no:testmon
"""

import asyncio
import copy
import os
import re
import sys
import time
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_rig import CHROME, ROOT, Browser, StubMac, fixture, free_port  # noqa: E402

pytestmark = [pytest.mark.slow, pytest.mark.chrome]
needs_chrome = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")
PAGE = (ROOT / "pointe" / "ui.html").read_text()
LINE = "pointe://machine?v=1&host=avi-box.example&port=7443&fp=" + "ab" * 32 + "&code=K7PQ-2MXD&name=avi-box"
QR = '<svg viewBox="0 0 4 4" class="segno"><path class="qrline" stroke="#000" d="M0 0h4"/></svg>'


# ---------- the statuses ----------

def session(name: str, **more) -> dict:
    return {"name": name, "harness": "claude-code", "capabilities": {"approvals": True}, "working": False, "waiting": False,
            "machine": "", "online": True, "request": None, "request_id": None, "voice_can_approve": False, "needs": None,
            "mode": "channel", **more}


def machine(name: str, **more) -> dict:
    return {"id": name, "name": name, "here": False, "os": "linux", "online": True, "since": time.time() - 600, "sessions": 0,
            "need": 0, "rtt_ms": 31, "key_fp": None, **more}


def mine() -> dict:
    """Two machines of my own and nobody invited: a status with none of the new fields."""
    s = fixture(sessions=4, machines=2)
    s["machines"][1]["sessions"] = 2
    return s


def with_avi(grant: str = "send") -> dict:
    """My Mac (studio) with two sessions, and avi-box, a machine Avi invited this voice to, with two of his."""
    s = fixture(sessions=2, machines=1)
    s["machines"].append(machine("avi-box", owner="Avi", grant=grant, sessions=2))
    s["sessions"] += [session("billing", machine="avi-box", owner="Avi", working=True),
                      session("search", machine="avi-box", owner="Avi", working=True, by={"name": "Dana", "since": time.time() - 120})]
    return s


def with_people() -> dict:
    """My Mac, which Dana (can talk) and Noor (watch only, away) were invited to."""
    s = fixture(sessions=2, machines=1)
    s["account"] = "sam"
    s["people"] = [{"name": "Dana", "grant": "send", "online": True, "since": time.time() - 900},
                   {"name": "Noor", "grant": "watch", "online": False, "since": time.time() - 7200}]
    s["people_invite"] = None
    return s


# ---------- the stub Mac, with the contract's routes ----------

class PeopleMac(StubMac):
    """Answers the routes of people-and-machines.md the way the daemon will, and changes the status as it would."""

    def __init__(self, port: int):
        super().__init__(port)
        self.add_answers: list[tuple[int, object]] = []  # the next answers of /voice/machines/add; none left: it is added
        self.add_delay = 0.0
        self.added = {"name": "avi-box", "owner": "Avi", "grant": "send", "vendors": ["Soniox", "ElevenLabs", "OpenAI"]}
        self.pinvite: dict | None = None
        self.vendors = {"Dana": ["Soniox", "ElevenLabs"], "Noor": []}
        self.invite_svg = ""

    def routes(self, app) -> None:
        app.router.add_get("/voice/people/invite", self._people_invite)
        app.router.add_get("/voice/people", self._people)

    async def _people_invite(self, request):
        return web.json_response(self.pinvite or {"code": None, "expires_in": 0, "link": None, "name": None, "paired": None, "ended": None})

    async def _people(self, request):
        return web.json_response({"people": [{**p, "id": p["name"].lower(), "vendors": self.vendors.get(p["name"], []), "address": "10.0.0.7",
                                              "key_fp": "c0ffee", "added": 0} for p in self.status.get("people") or []]})

    def pair(self) -> None:
        """The invited person's voice traded the code: they are in the list, and the invite is over."""
        name, grant = self.pinvite["name"], self.pinvite["grant"]
        self.status["people"] = [*(self.status.get("people") or []), {"name": name, "grant": grant, "online": True, "since": time.time()}]
        self.vendors[name] = ["Deepgram", "Cartesia"]
        self.status["people_invite"] = None
        self.pinvite = {"code": None, "expires_in": 0, "link": None, "name": name, "paired": {"name": name}, "ended": None}

    async def _post(self, request):
        path, s = request.path, self.status
        if not path.startswith(("/voice/machines/", "/voice/people/", "/voice/share", "/voice/hub/revoke")):
            return await super()._post(request)
        body = await request.json()
        self.posts.append((path, body, time.time()))
        if path == "/voice/machines/add":
            if "seen" in body:
                if (s.get("disclosure") or {}).get("machine") == body["seen"]:
                    s["disclosure"] = None
                return web.json_response({"ok": True})
            await asyncio.sleep(self.add_delay)
            if self.add_answers:
                code, said = self.add_answers.pop(0)
                return web.Response(status=code, text=said) if isinstance(said, str) else web.json_response(said, status=code)
            made = {**self.added, "name": body.get("name") or self.added["name"]}
            s["machines"].append(machine(made["name"], owner=made["owner"], grant=made["grant"], sessions=2))
            s["sessions"] += [session("billing", machine=made["name"], owner=made["owner"]),
                              session("search", machine=made["name"], owner=made["owner"])]
            s["disclosure"] = {"machine": made["name"], "vendors": made["vendors"]}
            return web.json_response(made)
        if path == "/voice/people/invite":
            if body.get("cancel"):
                self.pinvite, s["people_invite"] = None, None
                return web.json_response({"ok": True})
            if any(p["name"].lower() == body["name"].lower() for p in s.get("people") or []):
                return web.json_response({"detail": f"Somebody called {body['name']} is here already. Give this person another name."}, status=409)
            made = {"code": "K7PQ-2MXD", "link": LINE, "expires_in": 600, "name": body["name"], "grant": body.get("grant", "send")}
            self.pinvite = {**made, "paired": None, "ended": None}
            s["people_invite"] = {"code": made["code"], "expires_in": 600}
            return web.json_response({**made, **({"svg": self.invite_svg} if self.invite_svg else {})})
        people = s.get("people") or []
        if path == "/voice/people/grant":
            next(p for p in people if p["name"] == body["name"])["grant"] = body["grant"]
        elif path == "/voice/people/remove":
            s["people"] = [p for p in people if p["name"] != body["name"]] or None
            if s["people"] is None:
                del s["people"]
        elif path == "/voice/share":
            row = next(x for x in s["sessions"] if x["name"] == body["session"])
            row["private"] = bool(body["private"])
            return web.json_response({"ok": True, "private": row["private"]})
        elif path == "/voice/hub/revoke":
            s["machines"] = [m for m in s["machines"] if m["name"] != body["name"]]
            s["sessions"] = [x for x in s["sessions"] if x["machine"] != body["name"]]
        return web.json_response({"ok": True})


async def on_page(status: dict, steps, width: int | None = None, settings: bool = False, prepare=None):
    """Open the page on `status`, run `steps(page, stub)`, and hand back what it returns."""
    stub = PeopleMac(free_port())
    stub.status = copy.deepcopy(status)
    if prepare:
        prepare(stub)
    await stub.start()
    try:
        async with Browser() as browser:
            page = await browser.open(stub.url)
            if width:
                await page.cdp("Emulation.setDeviceMetricsOverride", {"width": width, "height": 844, "deviceScaleFactor": 1, "mobile": False})
                await page.cdp("Page.navigate", {"url": stub.url})
                await asyncio.sleep(0.4)
                await page.wait_for_page()
            if settings:
                await open_machines(page)
            return await steps(page, stub)
    finally:
        await stub.stop()


async def open_machines(page) -> None:
    await page.eval("(async () => { await openSettings(); settingsJump('machines'); return true; })()")
    await asyncio.sleep(0.5)


async def until(page, condition: str, secs: float = 6.0) -> bool:
    for _ in range(int(secs / 0.1)):
        if await page.eval(f"!!({condition})"):
            return True
        await asyncio.sleep(0.1)
    return False


def posts(stub, path: str) -> list[dict]:
    return [body for p, body, _ in stub.posts if p == path]


SEEN = "(id => { const e = document.getElementById(id); return !!e && !e.hidden && e.getClientRects().length > 0; })"
TEXT = "(id => document.getElementById(id).textContent.trim())"
ROWS = """(() => [...document.querySelectorAll('#list .s')].map(r => ({
  name: r.querySelector('.nm').textContent, own: r.querySelector('.own')?.textContent ?? null, lock: !!r.querySelector('.marks .lock'),
  by: r.querySelector('.by')?.textContent ?? null, button: r.querySelector('.nm').getAttribute('role') === 'button',
  tab: r.querySelector('.nm').tabIndex, tools: [...r.querySelectorAll('.tools .edit, .tools .more')].length,
  label: r.querySelector('.nm').getAttribute('aria-label') })))()"""
HEADERS = """(() => [...document.querySelectorAll('#list .mh')].map(h => ({
  name: h.querySelector('.mn').textContent, own: h.querySelector('.own')?.textContent ?? null,
  said: [...h.querySelectorAll('span:not(.ml):not(.mn):not(.own)')].map(e => e.textContent) })))()"""
MACHINES = "[...document.querySelectorAll('#mach-list li')].map(li => [...li.children].map(c => c.textContent))"
PEOPLE = """[...document.querySelectorAll('#people-list li')].map(li => ({name: li.querySelector('.mn').textContent,
  meta: [...li.querySelectorAll('.mmeta')].map(m => m.textContent), buttons: [...li.querySelectorAll('button')].map(b => b.textContent)}))"""
NEW_MARKS = "document.querySelectorAll('#list .own, #list .lock, #list .lockedit, #list .by, #list .mnote, #list .marks, #list .s.watch').length"


# ---------- nothing new for a person with machines of their own and no people ----------

@needs_chrome
def test_with_my_own_machines_and_no_people_nothing_new_shows():
    """A status without the new fields draws the sessions as before: no owner, no lock, no "Mine", no card; Settings →
    Machines gains the two ways in (the line to paste, Invite a person) and no heading, list or trust line."""
    async def steps(page, stub):
        out = {"marks": await page.eval(NEW_MARKS), "chips": await page.eval("[...document.querySelectorAll('#mchips button')].map(b => b.textContent)"),
               "rows": await page.eval(ROWS), "headers": await page.eval(HEADERS),
               "card": await page.eval("document.getElementById('disclosure').childElementCount")}
        await page.eval("openRowSheet('s0-shop')")
        out["sheet"] = await page.eval("[...document.querySelectorAll('#row-acts button')].filter(b => !b.hidden).map(b => b.textContent)")
        await page.eval("closeSheet('rowsheet')")
        await open_machines(page)
        out["machines"] = await page.eval(MACHINES)
        out["settings"] = {i: await page.eval(f"{SEEN}('{i}')") for i in
                           ("mach-add", "mach-name-f", "mach-disclosure", "people-h", "people-list", "people-form", "people-invite",
                            "people-invitebtn", "people-trust")}
        return out
    got = asyncio.run(on_page(mine(), steps))
    assert got["marks"] == 0 and got["card"] == 0
    assert got["chips"] == ["All", "studio", "devbox"]
    assert all(r["own"] is None and not r["lock"] and r["by"] is None and r["button"] and r["tools"] == 3 for r in got["rows"]), got["rows"]
    assert all(h["own"] is None and "watch only" not in h["said"] for h in got["headers"]), got["headers"]
    assert got["sheet"] == ["Rename", "Disconnect"]
    assert [m[0] for m in got["machines"]] == ["studio (this Mac)", "devbox"] and got["machines"][1][-1] == "Revoke"
    assert got["settings"] == {"mach-add": True, "mach-name-f": False, "mach-disclosure": False, "people-h": False, "people-list": False,
                               "people-form": False, "people-invite": False, "people-invitebtn": True, "people-trust": False}


# ---------- add a machine ----------

@needs_chrome
def test_a_pasted_line_adds_the_machine_and_says_once_where_its_transcripts_go():
    """Paste, and nothing else: the line alone is sent (out of a pasted command too), a quiet line says it is working,
    the machine is in the list with whose it is, and the card names the services until OK."""
    async def steps(page, stub):
        stub.add_delay = 0.6
        out = {"label": await page.eval("document.getElementById('mach-line').labels[0].textContent"), "button": await page.eval(f"{TEXT}('mach-addbtn')")}
        await page.eval(f"""(() => {{ const f = document.getElementById('mach-line'); f.focus(); f.value = "pointe machine add '{LINE}'";
                                     f.dispatchEvent(new Event('paste', {{bubbles: true}})); return true; }})()""")
        assert await until(page, f"{TEXT}('mach-adding')")
        out["working"] = [await page.eval(f"{TEXT}('mach-adding')"), await page.eval("document.getElementById('mach-addbtn').disabled")]
        assert await until(page, "document.querySelectorAll('#mach-list li').length === 2")
        out["sent"] = posts(stub, "/voice/machines/add")
        out["machines"] = await page.eval(MACHINES)
        out["field"] = [await page.eval("document.getElementById('mach-line').value"), await page.eval(f"{TEXT}('mach-adding')"), await page.eval(f"{TEXT}('mach-adderr')")]
        assert await until(page, "document.querySelector('#mach-disclosure .ask')")
        out["card"] = await page.eval("[...document.querySelectorAll('#mach-disclosure .ask > div')].map(d => d.textContent)")
        out["talk"] = await page.eval("document.querySelector('#disclosure .need').textContent")
        await asyncio.sleep(1.3)  # the next poll carries the same card: it is not drawn twice, nor dropped
        out["cards"] = await page.eval("document.querySelectorAll('#mach-disclosure .ask').length")
        await page.eval("document.querySelector('#mach-disclosure button').click()")
        assert await until(page, "!document.querySelector('#mach-disclosure .ask') && !document.querySelector('#disclosure .ask')")
        await asyncio.sleep(1.3)
        out["after"] = [await page.eval("document.querySelectorAll('.ask').length"), posts(stub, "/voice/machines/add")[-1], stub.status["disclosure"]]
        return out
    got = asyncio.run(on_page(fixture(sessions=2), steps, settings=True))
    assert got["label"] == "Paste the line the machine's owner sent you" and got["button"] == "Add"
    assert got["working"] == ["Adding the machine…", True]
    assert got["sent"] == [{"line": LINE}]
    assert got["machines"][1][0] == "avi-box · Avi's" and "2 sessions" in got["machines"][1][1] and got["machines"][1][-1] == "Remove", got["machines"]
    assert got["field"] == ["", "", ""]
    said = "Your voice sends the transcripts of the sessions on avi-box, with credentials masked, to: Soniox, ElevenLabs, OpenAI. Avi sees this list next to your name."
    assert got["card"] == ["avi-box · Avi's", said, "OK"] and got["talk"] == said and got["cards"] == 1
    assert got["after"] == [0, {"seen": "avi-box"}, None]


@needs_chrome
def test_a_machine_added_elsewhere_shows_its_card_in_the_conversation():
    """Added from the command line or the phone: the status carries the disclosure, and the page shows it without Settings."""
    status = with_avi()
    status["disclosure"] = {"machine": "avi-box", "vendors": []}
    async def steps(page, stub):
        assert await until(page, "document.querySelector('#disclosure .ask')")
        said = await page.eval("document.querySelector('#disclosure .need').textContent")
        await page.eval("document.querySelector('#disclosure button').focus()")
        await page.cdp("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"})
        await page.cdp("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
        assert await until(page, "!document.querySelector('#disclosure .ask')")
        return said, posts(stub, "/voice/machines/add")
    said, sent = asyncio.run(on_page(status, steps))
    assert said == "Your voice sends the transcripts of the sessions on avi-box to no outside service. Avi sees this list next to your name."
    assert sent == [{"seen": "avi-box"}]


@needs_chrome
def test_a_refused_line_says_the_daemons_sentence_next_to_the_field_and_keeps_the_line():
    async def steps(page, stub):
        stub.add_answers = [(400, {"detail": "That code was used already. Ask Avi for a new line."}), (403, "forbidden")]
        out = []
        for _ in range(2):
            await page.eval(f"(() => {{ document.getElementById('mach-line').value = '{LINE}'; document.getElementById('mach-add').requestSubmit(); return true; }})()")
            assert await until(page, f"{TEXT}('mach-adderr')")
            out.append({"said": await page.eval(f"{TEXT}('mach-adderr')"), "line": await page.eval("document.getElementById('mach-line').value"),
                        "name": await page.eval(f"{SEEN}('mach-name-f')"), "alert": await page.eval("document.getElementById('mach-adderr').getAttribute('role')"),
                        "busy": await page.eval("document.getElementById('mach-addbtn').disabled"), "list": await page.eval("document.querySelectorAll('#mach-list li').length")})
            await page.eval("document.getElementById('mach-adderr').textContent = ''")
        return out
    first, second = asyncio.run(on_page(fixture(sessions=2), steps, settings=True))
    assert first == {"said": "That code was used already. Ask Avi for a new line.", "line": LINE, "name": False, "alert": "alert", "busy": False, "list": 1}
    assert second["said"] == "Only the Mac's own page or the app can do this." and second["line"] == LINE


@needs_chrome
def test_a_name_is_asked_for_only_when_the_daemon_says_it_is_taken():
    """No name up front. A 409 shows "Call it" beside the daemon's sentence, with the focus in it; the next Add sends both."""
    status = fixture(sessions=2, machines=2)
    status["machines"][1]["name"] = status["machines"][1]["id"] = "avi-box"
    async def steps(page, stub):
        stub.add_answers = [(409, "You have a machine called avi-box already. Give this one another name.")]
        before = await page.eval(f"{SEEN}('mach-name-f')")
        await page.eval(f"(() => {{ document.getElementById('mach-line').value = '{LINE}'; document.getElementById('mach-add').requestSubmit(); return true; }})()")
        assert await until(page, f"{SEEN}('mach-name-f')")
        asked = {"said": await page.eval(f"{TEXT}('mach-adderr')"), "label": await page.eval("document.getElementById('mach-name').labels[0].textContent"),
                 "focus": await page.eval("document.activeElement.id"), "line": await page.eval("document.getElementById('mach-line').value")}
        await page.eval("(() => { document.getElementById('mach-name').value = 'avi-lab'; document.getElementById('mach-add').requestSubmit(); return true; })()")
        assert await until(page, "document.querySelectorAll('#mach-list li').length === 3")
        return before, asked, posts(stub, "/voice/machines/add"), await page.eval(MACHINES), await page.eval(f"{SEEN}('mach-name-f')")
    before, asked, sent, machines, after = asyncio.run(on_page(status, steps, settings=True))
    assert before is False and after is False
    assert asked == {"said": "You have a machine called avi-box already. Give this one another name.", "label": "Call it", "focus": "mach-name", "line": LINE}
    assert sent == [{"line": LINE}, {"line": LINE, "name": "avi-lab"}]
    assert machines[2][0] == "avi-lab · Avi's"


# ---------- people ----------

@needs_chrome
def test_inviting_a_person_shows_the_line_and_lists_them_once_they_pair():
    """Invite a person: a name and "Can talk to the sessions" (the default). The line, Copy, the Mac's QR drawing and the
    countdown show until the person's voice pairs; then the invite closes and they are in the list with their services."""
    async def steps(page, stub):
        out = {"before": [await page.eval(f"{SEEN}('{i}')") for i in ("people-h", "people-trust", "people-form")]}
        await page.eval("document.getElementById('people-invitebtn').click()")
        out["form"] = {"focus": await page.eval("document.activeElement.id"), "trust": await page.eval(f"{TEXT}('people-trust')"),
                       "name": await page.eval("document.getElementById('people-name').labels[0].textContent.trim()"),
                       "group": await page.eval("document.getElementById('people-grant').getAttribute('aria-label')"),
                       "choices": await page.eval("[...document.querySelectorAll('#people-grant button')].map(b => [b.textContent, b.getAttribute('aria-checked')])")}
        await page.eval("window.__copied = null; navigator.clipboard.writeText = async t => { window.__copied = t; }; true")
        await page.eval("(() => { document.getElementById('people-name').value = 'Dana'; document.getElementById('people-form').requestSubmit(); return true; })()")
        assert await until(page, f"{SEEN}('people-invite')")
        await page.eval("document.getElementById('people-copy').click()")
        await asyncio.sleep(0.2)
        out["invite"] = {"help": await page.eval(f"{TEXT}('people-help')"), "line": await page.eval(f"{TEXT}('people-link')"),
                         "dir": await page.eval("document.getElementById('people-link').dir"), "copied": await page.eval("window.__copied"),
                         "copy": await page.eval(f"{TEXT}('people-copy')"), "left": await page.eval(f"{TEXT}('people-left')"),
                         "qr": await page.eval("document.querySelectorAll('#people-qr svg path').length"),
                         "shown": [await page.eval(f"{SEEN}('{i}')") for i in ("people-qrtile", "people-form", "people-invitebtn", "people-cancel")]}
        await asyncio.sleep(1.5)  # the code still waits: the polls keep the invite up
        out["waiting"] = await page.eval(f"{SEEN}('people-invite')")
        stub.pair()
        assert await until(page, f"!{SEEN}('people-invite') && document.querySelectorAll('#people-list li').length === 1")
        assert await until(page, "document.querySelector('#people-list .pv')")
        out["people"] = await page.eval(PEOPLE)
        out["after"] = [await page.eval(f"{SEEN}('{i}')") for i in ("people-h", "people-trust", "people-invitebtn", "people-cancel")]
        return out, posts(stub, "/voice/people/invite")
    status = fixture(sessions=2)
    status["account"] = "sam"
    got, sent = asyncio.run(on_page(status, steps, settings=True, prepare=lambda stub: setattr(stub, "invite_svg", QR)))
    assert got["before"] == [False, False, False]
    assert got["form"] == {"focus": "people-name", "name": "Name", "group": "What they can do",
                           "trust": "People you invite can make these agents run commands as sam. Keep a session to yourself with Private.",
                           "choices": [["Can talk to the sessions", "true"], ["Can only watch", "false"]]}
    assert sent == [{"name": "Dana", "grant": "send"}]
    assert got["invite"]["help"] == "Send this line to Dana. It works once." and got["invite"]["line"] == got["invite"]["copied"] == LINE
    assert got["invite"]["dir"] == "ltr" and got["invite"]["copy"] == "Copied" and re.fullmatch(r"Expires in \d+:\d\d", got["invite"]["left"])
    assert got["invite"]["qr"] == 1 and got["invite"]["shown"] == [True, False, False, True]
    assert got["waiting"] is True
    assert got["people"] == [{"name": "Dana", "meta": ["online", "Their voice uses: Deepgram, Cartesia"], "buttons": ["Can talk", "Remove"]}]
    assert got["after"] == [True, True, True, False]


@needs_chrome
def test_a_watch_only_invite_can_be_cancelled_and_a_taken_name_keeps_the_form():
    async def steps(page, stub):
        await page.eval("document.getElementById('people-invitebtn').click()")
        await page.eval("(() => { document.getElementById('people-name').value = 'dana'; document.getElementById('people-form').requestSubmit(); return true; })()")
        assert await until(page, f"{TEXT}('people-err')")
        taken = [await page.eval(f"{TEXT}('people-err')"), await page.eval(f"{SEEN}('people-form')"), await page.eval("document.getElementById('people-name').value")]
        await page.eval("""(() => { document.querySelector('#people-grant [data-grant=watch]').click(); document.getElementById('people-name').value = 'Omar';
                                   document.getElementById('people-form').requestSubmit(); return true; })()""")
        assert await until(page, f"{SEEN}('people-invite')")
        qr = await page.eval(f"{SEEN}('people-qrtile')")  # this Mac drew none: no empty tile
        await page.eval("document.getElementById('people-cancel').click()")
        assert await until(page, f"!{SEEN}('people-invite')")
        await asyncio.sleep(1.3)
        return taken, qr, await page.eval(f"{SEEN}('people-invite')"), await page.eval(f"{SEEN}('people-invitebtn')"), posts(stub, "/voice/people/invite")
    taken, qr, still, button, sent = asyncio.run(on_page(with_people(), steps, settings=True))
    assert taken == ["Somebody called dana is here already. Give this person another name.", True, "dana"]
    assert qr is False and still is False and button is True
    assert sent == [{"name": "dana", "grant": "send"}, {"name": "Omar", "grant": "watch"}, {"cancel": True}]


@needs_chrome
def test_a_persons_grant_changes_in_one_click_each_way():
    async def steps(page, stub):
        assert await until(page, "document.querySelector('#people-list .pv')")
        out = [await page.eval(PEOPLE)]
        grant = "document.querySelectorAll('#people-list li')[0].querySelector('button')"
        out.append(await page.eval(f"{grant}.getAttribute('aria-label')"))
        for want in ("Watch only", "Can talk"):
            await page.eval(f"{grant}.click()")
            assert await until(page, f"{grant}.textContent === '{want}'", 1.0)  # at once, before the Mac's next status
            await asyncio.sleep(1.4)
            out.append(await page.eval(f"{grant}.textContent"))
        return out, posts(stub, "/voice/people/grant")
    (people, label, first, second), sent = asyncio.run(on_page(with_people(), steps, settings=True))
    assert people[0] == {"name": "Dana", "meta": ["online", "Their voice uses: Soniox, ElevenLabs"], "buttons": ["Can talk", "Remove"]}
    assert people[1]["name"] == "Noor" and re.fullmatch(r"last here (\w{3} )?\d\d:\d\d", people[1]["meta"][0]) and people[1]["buttons"] == ["Watch only", "Remove"]
    assert label == "Dana can talk to the sessions. Click to make it watch only."
    assert (first, second) == ("Watch only", "Can talk")
    assert sent == [{"name": "Dana", "grant": "watch"}, {"name": "Dana", "grant": "send"}]


@needs_chrome
def test_a_person_is_removed_in_two_clicks():
    async def steps(page, stub):
        cut = "document.querySelectorAll('#people-list li')[0].querySelectorAll('button')[1]"
        await page.eval(f"{cut}.click()")
        await asyncio.sleep(0.3)
        asked = [await page.eval(f"{cut}.textContent"), await page.eval(f"{cut}.className"), len(posts(stub, "/voice/people/remove"))]
        await page.eval(f"{cut}.click()")
        assert await until(page, "document.querySelectorAll('#people-list li').length === 1")
        return asked, posts(stub, "/voice/people/remove"), await page.eval(PEOPLE)
    asked, sent, people = asyncio.run(on_page(with_people(), steps, settings=True))
    assert asked == ["Remove Dana?", "sure", 0]
    assert sent == [{"name": "Dana"}] and [p["name"] for p in people] == ["Noor"]


def test_people_are_managed_only_where_an_invite_can_be_made():
    """Over the phone's listener the Mac refuses the owner's routes: no People there, and no line to paste."""
    assert "const here = canInvite && !remotePage && Array.isArray(s.machines);" in PAGE
    assert "$('mach-add').hidden = !canInvite || remotePage;" in PAGE


# ---------- whose it is ----------

@needs_chrome
@pytest.mark.parametrize("width", [1440, 390])
def test_an_owner_shows_on_a_session_and_a_machine_only_when_the_status_names_one(width):
    """Avi's machine and its sessions say "Avi's"; mine say nothing. "Dana is using it" is on the one session that is
    working on her request. "Mine" joins the filter while somebody else's session is here."""
    async def steps(page, stub):
        if width < 900:
            await page.eval("toggleSessions(true)")
            await asyncio.sleep(0.3)
        out = {"rows": await page.eval(ROWS), "headers": await page.eval(HEADERS),
               "chips": await page.eval("[...document.querySelectorAll('#mchips button')].map(b => b.textContent)"),
               "wide": await page.eval("document.getElementById('list').scrollWidth <= document.getElementById('list').clientWidth + 1")}
        await page.eval("[...document.querySelectorAll('#mchips button')].find(b => b.textContent === 'Mine').click()")
        await asyncio.sleep(0.3)
        out["mine"] = [await page.eval("[...document.querySelectorAll('#list .s .nm')].map(n => n.textContent)"),
                       await page.eval("[...document.querySelectorAll('#list .mh .mn')].map(n => n.textContent)"), await page.eval(f"{TEXT}('sub')")]
        stub.status["sessions"] = [x for x in stub.status["sessions"] if not x.get("owner")]  # Avi's sessions left
        assert await until(page, "![...document.querySelectorAll('#mchips button')].some(b => b.textContent === 'Mine')")
        out["left"] = await page.eval("[...document.querySelectorAll('#list .mh .mn')].map(n => n.textContent)")
        return out
    got = asyncio.run(on_page(with_avi(), steps, width=width))
    rows = {r["name"]: r for r in got["rows"]}
    assert [rows[n]["own"] for n in ("s0-shop", "s1-api", "billing", "search")] == [None, None, "Avi's", "Avi's"]
    assert [rows[n]["by"] for n in ("s0-shop", "s1-api", "billing", "search")] == [None, None, None, "Dana is using it"]
    assert rows["search"]["label"] == "search, Claude, working, Avi's, Dana is using it" and rows["s0-shop"]["label"] == "s0-shop, Claude, working"
    assert all(r["button"] and r["tools"] == 3 and not r["lock"] for r in got["rows"])  # a send grant: as my own
    assert [(h["name"], h["own"]) for h in got["headers"]] == [("studio", None), ("avi-box", "Avi's")]
    assert got["chips"] == ["All", "Mine", "studio", "avi-box"] and got["wide"]
    assert got["mine"][0] == ["s0-shop", "s1-api"] and got["mine"][1] == ["studio"] and "2 sessions of yours" in got["mine"][2]
    assert got["left"] == ["studio", "avi-box"]  # the filter fell back to All with its chip


@needs_chrome
def test_a_machine_i_may_only_watch_offers_no_way_to_send():
    """"watch only" on the machine; its sessions are read, not pressed: no Rename, Disconnect or ⋯, a click switches
    nothing, and a prompt waiting there shows no Approve. My own sessions keep all of it."""
    status = with_avi("watch")
    status["sessions"][2].update(waiting=True, working=False, request="Bash(make deploy)", request_id="perm-9", voice_can_approve=True)
    async def steps(page, stub):
        out = {"rows": await page.eval(ROWS), "headers": await page.eval(HEADERS),
               "card": await page.eval("document.getElementById('attention').childElementCount"),
               "title": await page.eval("[...document.querySelectorAll('#list .s')].find(r => r.textContent.includes('billing')).title"),
               "machines": None}
        await page.eval("[...document.querySelectorAll('#list .s')].find(r => r.textContent.includes('billing')).click()")
        await page.eval("[...document.querySelectorAll('#list .s')].find(r => r.textContent.includes('s1-api')).click()")
        assert await until(page, "document.querySelector('#list .s.on')")
        out["switched"] = posts(stub, "/voice/switch")
        await open_machines(page)
        out["machines"] = await page.eval(MACHINES)
        return out
    got = asyncio.run(on_page(status, steps))
    rows = {r["name"]: r for r in got["rows"]}
    for name in ("billing", "search"):
        assert rows[name]["button"] is False and rows[name]["tab"] == -1 and rows[name]["tools"] == 0, rows[name]
    assert rows["billing"]["label"] == "billing, Claude, needs approval, Avi's, watch only"
    assert rows["s0-shop"]["button"] and rows["s0-shop"]["tools"] == 3
    assert got["headers"][1]["own"] == "Avi's" and "watch only" in got["headers"][1]["said"] and "watch only" not in got["headers"][0]["said"]
    assert got["card"] == 0 and got["title"] == "billing: watch only. You see and hear it. Its machine refuses a request from you."
    assert got["switched"] == [{"name": "s1-api"}]
    assert "watch only" in got["machines"][1][1]


@needs_chrome
def test_what_a_machine_says_shows_under_it_with_remove_next_to_removed_you():
    """"avi-box removed you" sits under the machine in the sessions and in Settings, with Remove in two clicks (the
    existing revoke route). The older-Pointe line is said the same way and offers no Remove beside it. A dialed
    machine that is offline reads as any offline machine."""
    status = with_avi()
    since = time.time() - 1800
    status["machines"][1].update(online=False, since=since, notice="avi-box removed you")
    for x in status["sessions"][2:]:
        x.update(online=False, working=False, by=None)
    old = "lab runs an older Pointe (0.9.0). Update it there: pointe update"
    status["machines"].append(machine("lab", owner="Noor", grant="send", online=False, since=since, notice=old))
    async def steps(page, stub):
        notes = "[...document.querySelectorAll('#list .mnote')].map(n => [n.querySelector('span').textContent, [...n.querySelectorAll('button')].map(b => b.textContent)])"
        out = {"notes": await page.eval(notes), "headers": await page.eval(HEADERS), "role": await page.eval("document.querySelector('#list .mnote').getAttribute('role')"),
               "rows": await page.eval("[...document.querySelectorAll('#list .s')].map(r => [r.querySelector('.nm').textContent, r.classList.contains('away'), r.querySelector('.tag').textContent])")}
        await open_machines(page)
        out["machines"] = await page.eval(MACHINES)
        await page.eval("closeSheet('settingssheet')")
        await page.eval("document.querySelector('#list .mnote button').click()")
        await asyncio.sleep(0.3)
        out["asked"] = [await page.eval(notes), len(posts(stub, "/voice/hub/revoke"))]
        await page.eval("document.querySelector('#list .mnote button').click()")
        assert await until(page, "document.querySelectorAll('#list .mnote').length === 1")
        out["after"] = [posts(stub, "/voice/hub/revoke"), await page.eval("[...document.querySelectorAll('#list .mh .mn')].map(n => n.textContent)")]
        return out
    got = asyncio.run(on_page(status, steps))
    assert got["notes"] == [["avi-box removed you", ["Remove"]], [old, []]] and got["role"] == "status"
    assert re.fullmatch(r"offline since \d\d:\d\d", got["headers"][1]["said"][-1]) and got["headers"][1]["own"] == "Avi's"
    assert got["rows"][2:] == [["billing", True, "offline"], ["search", True, "offline"]]
    assert got["machines"][1][0] == "avi-box · Avi's" and got["machines"][1][2:] == ["avi-box removed you", "Remove"]
    assert re.search(r"offline since \d\d:\d\d", got["machines"][1][1])
    assert got["asked"] == [[["avi-box removed you", ["Remove avi-box?"]], [old, []]], 0]
    assert got["after"] == [[{"name": "avi-box"}], ["studio", "lab"]]


# ---------- private ----------

@needs_chrome
def test_a_session_i_own_goes_private_and_back_on_a_machine_that_has_people():
    """The row's lock under the pointer, P on its name, and Private in the ⋯ sheet: each posts /voice/share. A private
    session shows a small lock. A session that is not mine, and any session while nobody is invited, has none of it."""
    status = with_people()
    status["machines"].append(machine("avi-box", owner="Avi", grant="send", sessions=1))
    status["sessions"].append(session("billing", machine="avi-box", owner="Avi"))
    async def steps(page, stub):
        row = "[...document.querySelectorAll('#list .s')].find(r => r.querySelector('.nm').textContent === '%s')"
        out = {"keys": [await page.eval(f"{row % n}.querySelector('.nm').getAttribute('aria-keyshortcuts')") for n in ("s0-shop", "billing")],
               "marks": [await page.eval(f"{row % n}.querySelectorAll('.tools .edit').length") for n in ("s0-shop", "billing")]}
        await page.eval(f"{row % 's0-shop'}.querySelector('.nm').focus()")
        await page.cdp("Input.dispatchKeyEvent", {"type": "keyDown", "key": "p", "code": "KeyP", "windowsVirtualKeyCode": 80, "text": "p"})
        await page.cdp("Input.dispatchKeyEvent", {"type": "keyUp", "key": "p", "code": "KeyP", "windowsVirtualKeyCode": 80})
        assert await until(page, f"{row % 's0-shop'}.querySelector('.marks .lock')", 1.0)  # at once
        await asyncio.sleep(1.3)
        out["private"] = [await page.eval(ROWS), await page.eval(f"{row % 's0-shop'}.querySelector('.marks .lock').getAttribute('aria-label')"),
                          await page.eval("document.activeElement.classList.contains('nm')")]
        sheet = "[...document.querySelectorAll('#row-acts button')].filter(b => !b.hidden).map(b => b.textContent)"
        await page.eval("openRowSheet('s0-shop')")
        out["sheet"] = await page.eval(sheet)
        await page.eval("document.getElementById('row-private').click()")
        assert await until(page, f"!{row % 's0-shop'}.querySelector('.marks .lock')")
        await asyncio.sleep(1.3)
        out["shared"] = [await page.eval(f"!!{row % 's0-shop'}.querySelector('.marks .lock')"), await page.eval("document.getElementById('rowsheet').classList.contains('open')")]
        await page.eval("openRowSheet('s1-api')")
        out["sheet2"] = await page.eval(sheet)
        await page.eval("closeSheet('rowsheet'); openRowSheet('billing')")
        out["theirs"] = await page.eval(sheet)
        await page.eval("closeSheet('rowsheet')")
        await page.eval(f"{row % 's1-api'}.querySelector('.tools .lockedit').click()")
        assert await until(page, f"{row % 's1-api'}.querySelector('.marks .lock')")
        return out, posts(stub, "/voice/share"), posts(stub, "/voice/switch")
    got, sent, switched = asyncio.run(on_page(status, steps))
    assert got["keys"] == ["F2 Delete P", "F2 Delete"] and got["marks"] == [3, 2]
    rows = {r["name"]: r for r in got["private"][0]}
    assert rows["s0-shop"]["lock"] and not rows["s1-api"]["lock"] and rows["s0-shop"]["label"] == "s0-shop, Claude, working, private"
    assert got["private"][1:] == ["private", True]  # the focus stayed on the row that was redrawn
    assert got["sheet"] == ["Rename", "Shared with people", "Disconnect"] and got["shared"] == [False, False]
    assert got["sheet2"] == ["Rename", "Private", "Disconnect"] and got["theirs"] == ["Rename", "Disconnect"]
    assert sent == [{"session": "s0-shop", "private": True}, {"session": "s0-shop", "private": False}, {"session": "s1-api", "private": True}]
    assert switched == []  # the lock's click is not the row's


@needs_chrome
def test_a_share_the_mac_refuses_is_said_and_undone():
    async def steps(page, stub):
        stub.status["sessions"] = [x for x in stub.status["sessions"] if x["name"] != "s0-shop"] + [session("s0-shop")]
        stub.status["sessions"][-1]["name"] = "gone"  # the session left between the status and the click
        await page.eval("setPrivate('s0-shop', true)")
        assert await until(page, f"{TEXT}('renameproblem')")
        return await page.eval(f"{TEXT}('renameproblem')"), await page.eval("document.getElementById('renameproblem').getAttribute('role')")
    assert asyncio.run(on_page(with_people(), steps)) == ("The Mac did not change it.", "alert")


# ---------- layout, names, words ----------

@needs_chrome
@pytest.mark.parametrize("width,dark", [(1440, False), (390, True)])
def test_machines_and_people_fit_and_every_control_has_a_name(width, dark):
    """Settings → Machines with a machine of Avi's, two people, the add field asking for a name and an invite open: no
    control is unnamed or cut off, nothing scrolls sideways, and a tap target on a phone is 36 px or more."""
    status = with_people()
    status["machines"].append(machine("avi-box", owner="Avi", grant="watch", sessions=2))
    async def steps(page, stub):
        if dark:
            await page.cdp("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": "dark"}]})
        stub.add_answers = [(409, "You have a machine called avi-box already. Give this one another name.")]
        await open_machines(page)
        await page.eval(f"(() => {{ document.getElementById('mach-line').value = '{LINE}'; document.getElementById('mach-add').requestSubmit(); return true; }})()")
        assert await until(page, f"{SEEN}('mach-name-f')")
        await page.eval("document.getElementById('people-invitebtn').click()")
        form = await page.eval(CONTROLS)
        await page.eval("(() => { document.getElementById('people-name').value = 'Omar'; document.getElementById('people-form').requestSubmit(); return true; })()")
        assert await until(page, f"{SEEN}('people-invite')")
        return form, await page.eval(CONTROLS), await page.eval("getComputedStyle(document.getElementById('people-link')).direction")
    form, invite, direction = asyncio.run(on_page(status, steps, width=width))
    for got in (form, invite):
        assert got["unnamed"] == [] and got["cut"] == [] and got["sideways"] is False, got
        assert got["small"] == [] if width < 600 else True, got
    assert direction == "ltr"
    assert {"Add", "Call it", "Dana can talk to the sessions. Click to make it watch only.", "Noor can only watch. Click to let them talk to the sessions.",
            "Remove Dana", "Remove Noor", "Can talk to the sessions", "Can only watch", "Show the invite", "Cancel"} <= set(form["names"])
    assert {"Copy the line", "Cancel the invite"} <= set(invite["names"])


CONTROLS = """(() => {
  const box = document.getElementById('machines'), panel = document.getElementById('set-panel').getBoundingClientRect();
  const shown = [...box.querySelectorAll('button, input')].filter(e => e.getClientRects().length && !e.closest('[hidden]'));
  const name = e => (e.getAttribute('aria-label') || (e.labels && e.labels[0] && e.labels[0].textContent) || e.textContent || '').trim();
  return {names: shown.map(name), unnamed: shown.filter(e => !name(e)).map(e => e.id || e.outerHTML.slice(0, 60)),
          cut: shown.filter(e => { const r = e.getBoundingClientRect(); return r.left < panel.left - 1 || r.right > panel.right + 1; }).map(name),
          small: shown.filter(e => e.getBoundingClientRect().height < 36).map(name),
          sideways: document.getElementById('set-panel').scrollWidth > document.getElementById('set-panel').clientWidth + 1};
})()"""


def _copy() -> dict:
    block = PAGE[PAGE.index("const PEOPLE_COPY = {"):]
    return {k: v.replace("\\'", "'") for k, v in re.findall(r"(\w+): '((?:[^'\\]|\\.)*)'", block[:block.index("};")])}


def test_the_words_say_your_voice_machines_and_people():
    """Never "hub", "node" or "guest" on screen; no em-dash. A command to copy keeps its real name."""
    words = _copy()
    says = PAGE[PAGE.index("const PEOPLE_SAYS = {"):]
    says = says[:says.index("};")]
    assert words["addLabel"] == "Paste the line the machine's owner sent you" and words["invite"] == "Invite a person"
    assert (words["send"], words["watch"]) == ("Can talk to the sessions", "Can only watch")
    assert (words["makePrivate"], words["makeShared"], words["mine"], words["watchOnly"]) == ("Private", "Shared with people", "Mine", "watch only")
    for text in [*words.values(), says]:
        assert not re.search(r"\b(hub|node|guest)s?\b", text, re.I) and "—" not in text, text
    section = PAGE[PAGE.index('<section id="machines"'):PAGE.index('<section id="phone"')]
    prose = re.sub(r"<b>pointe node join</b>", "", re.sub(r"<[^>]+>", " ", section).replace("pointe node join", ""))
    assert not re.search(r"\b(hub|node|guest)s?\b", prose, re.I), prose


def test_the_apps_say_the_same_words_once_they_have_them():
    """The iPhone and Mac apps mirror PEOPLE_COPY as `enum PeopleCopy` (the same keys, as MachinesCopy mirrors Machines)."""
    sources = [f for f in (ROOT / "apps" / "PointeKit" / "Sources").rglob("*.swift") if "enum PeopleCopy" in f.read_text()]
    if not sources:
        pytest.skip("the apps have no PeopleCopy yet")
    swift = sources[0].read_text()
    block = swift[swift.index("enum PeopleCopy"):]
    app = dict(re.findall(r'static let (\w+) = "((?:[^"\\]|\\.)*)"', block[:block.index("\n}\n")]))
    page = _copy()
    shared = {"people", "invite", "name", "send", "watch", "copy", "cancelInvite", "remove", "ok", "add", "adding",
              "callIt", "mine", "makePrivate", "makeShared", "watchOnly", "privateMark", "noAnswer"}
    assert shared <= set(app) and shared <= set(page), (shared - set(app), shared - set(page))
    assert {k: page[k] for k in app if k in page} == {k: v for k, v in app.items() if k in page}  # a key both have says the same
