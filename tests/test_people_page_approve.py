"""Phase 3 of people and machines on the page (docs/design/people-and-machines.md, "Phase 3"): people invited to a
machine answer its prompts and start sessions there. In a headless Chrome against a stub Mac (tests/page_rig.py) that
answers what pointe/daemon.py and pointe/guests.py build.

- A prompt somebody else is asked first for: the card says who and counts down, and offers Approve and Deny only when
  the status says this voice may answer. A tap the daemon refuses shows the daemon's sentence.
- Who answered, when a person did: one line, for a moment. The approvals record names the person.
- New session on a machine somebody invited this voice to: its folders, whose it is, how it starts sessions.
- Settings → Machines → People → What people can do: three controls, one route.
- "started by Dana" on the machine's own page; Private on a session a person started on somebody else's machine.
- Without the new fields, none of it shows.

Every name here is made up.

uv run --locked --group test-tools pytest -q tests/test_people_page_approve.py --runslow -p no:testmon
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
from page_rig import CHROME, ROOT, Browser, fixture, free_port  # noqa: E402
from test_people_page import (SEEN, TEXT, PeopleMac, machine, mine, open_machines, posts, session, until, with_avi,  # noqa: E402
                              with_people)

pytestmark = [pytest.mark.slow, pytest.mark.chrome]
needs_chrome = pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")
PAGE = (ROOT / "pointe" / "ui.html").read_text()
ASKED_FIRST = "Avi is asked first. You can answer in a moment."  # daemon.approve, 409
HUB_ONLY = "Pointe starts sessions only on this Mac for now. On another machine, start it there and join it."  # daemon.HUB_ONLY
WATCH = "Noor lets you watch lab, not start sessions there."  # hub_nodes.Hub.start_problem
SETTINGS = {"approve": "anyone", "start": "on", "sessions_ask": "default", "owner_first_secs": 20.0, "people_hold_secs": 45.0}  # guests.DEFAULTS
SETTING_PROBLEM = ("People's approvals are anyone or off, starts are on or off, their sessions follow default or ask, the owner-first "
                   "time is 0 to 120 seconds, and a prompt is held for people 10 to 280 seconds.")  # guests.SETTING_PROBLEM
REQUEST = 'Bash\n{"command": "npm test"}'


def asking(status: dict, name: str, first: str | None, can: bool | None) -> dict:
    """`name` waits on a permission prompt; `first` is asked first for 14 more seconds; `can`: sessions[].can_answer."""
    row = next(x for x in status["sessions"] if x["name"] == name)
    row.update(waiting=True, working=False, request=REQUEST, request_id="9f2c41aa", voice_can_approve=True)
    if first:
        row["asked"] = {"name": first, "until": time.time() + 14.4}
    if can is not None:
        row["can_answer"] = can
    return status


class ThereMac(PeopleMac):
    """PeopleMac, with phase 3's routes: /voice/approve while somebody is asked first, /voice/people/settings, a start
    on a machine somebody invited this voice to, and a share of a session there."""

    def __init__(self, port: int):
        super().__init__(port)
        self.there = {"harnesses": [{"name": "claude-code", "title": "Claude Code", "available": True, "why": None}],
                      "folders": [{"path": "/home/avi/work/ledger", "name": "ledger"}, {"path": "/home/avi/work/atlas", "name": "atlas"}],
                      "permissions": "skip", "account": "avi"}
        self.there_refusal: tuple[int, str] | None = None
        self.settings_refused = False
        self.asked: list[str] = []  # the query of each GET /voice/new-session

    def start_machines(self) -> list[dict]:  # daemon._start_machines
        return [{"name": "studio", "here": True, "available": True, "why": None},
                {"name": "avi-box", "here": False, "available": True, "why": None, "owner": "Avi"},
                {"name": "devbox", "here": False, "available": False, "why": HUB_ONLY},
                {"name": "lab", "here": False, "available": False, "why": WATCH, "owner": "Noor"}]

    async def _new_session(self, request):  # daemon.new_session_options
        self.asked.append(request.query_string)
        name = request.query.get("machine")
        if not name or name == "studio":
            return web.json_response({**self.new_session, "machines": self.start_machines()})
        if self.there_refusal:
            return web.json_response({"detail": self.there_refusal[1]}, status=self.there_refusal[0])
        return web.json_response({"harnesses": self.there["harnesses"], "machines": self.start_machines(), "max_prompt": 4000,
                                  "folders": [{**f, "source": "machine"} for f in self.there["folders"]],
                                  "machine": {"name": name, "owner": "Avi", "permissions": self.there["permissions"], "account": self.there["account"]}})

    async def _post(self, request):
        path, s = request.path, self.status
        if path not in ("/voice/approve", "/voice/people/settings", "/voice/new-session", "/voice/share"):
            return await super()._post(request)
        body = await request.json()
        if path == "/voice/approve":
            self.posts.append((path, body, time.time()))
            row = next(x for x in s["sessions"] if x["name"] == body["session"])
            if row.get("machine") and row.get("asked"):  # at their own machine the owner's tap always counts
                return web.json_response({"detail": ASKED_FIRST}, status=409)
            row.update(waiting=False, request=None, request_id=None)
            row.pop("asked", None), row.pop("can_answer", None)
            return web.json_response({"ok": True})
        if path == "/voice/people/settings":
            self.posts.append((path, body, time.time()))
            if self.settings_refused:
                return web.Response(status=409, text=SETTING_PROBLEM)
            s["people_settings"] = {**s["people_settings"], **body}
            return web.json_response(s["people_settings"])
        if path == "/voice/new-session" and body.get("machine") not in (None, "studio"):
            self.posts.append((path, body, time.time()))
            notice = "avi-box starts sessions that skip permission prompts: it can edit files and run commands as avi without asking."
            name = body.get("name") or body["folder"].rsplit("/", 1)[-1]
            s.setdefault("starting", []).append({"id": "st1", "name": name, "harness": body["harness"], "label": "Claude Code", "folder": name,
                                                 "state": "starting", "detail": "", "since": time.time(), "permissions": "ask",
                                                 "notice": notice, "machine": body["machine"]})  # newsession.Start.view
            return web.json_response({"id": "st1", "name": name, "machine": body["machine"], "notice": notice})
        if path == "/voice/share":
            row = next((x for x in s["sessions"] if x["name"] == body.get("session")), None)
            if row is not None and row.get("machine"):  # guests.install share: that machine decides
                self.posts.append((path, body, time.time()))
                if row.get("owner"):
                    return web.Response(status=403, text=f"{row['name']} is not a session you started on {row['machine']}: only its owner changes who sees it.")
                return web.json_response({"ok": True, "private": body["private"]})  # and the voice's status says nothing of it
        return await super()._post(request)  # the body is read once and kept


async def on_page(status: dict, steps, width: int | None = None, prepare=None):
    stub = ThereMac(free_port())
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
            return await steps(page, stub)
    finally:
        await stub.stop()


CARD = """(() => { const c = document.querySelector('#attention .ask:not(.done)'); return c && {
  what: c.querySelector('.what').textContent.trim(), request: c.querySelector('.exact').textContent,
  asked: c.querySelector('.asked')?.textContent ?? null, buttons: [...c.querySelectorAll('.answer button')].map(b => b.textContent),
  err: c.querySelector('.err') && !c.querySelector('.err').hidden ? c.querySelector('.err').textContent : ''}; })()"""
DONE = "[...document.querySelectorAll('#attention .ask.done')].map(d => [d.querySelector('.what').textContent, d.querySelector('.need').textContent, d.getAttribute('role')])"
ROW = "[...document.querySelectorAll('#list .s')].find(r => r.querySelector('.nm').textContent === '%s')"


# ---------- a prompt somebody else is asked first for ----------

@needs_chrome
def test_a_prompt_avi_is_asked_first_for_counts_down_and_offers_approve_only_when_this_voice_may_answer():
    """On Dana's voice: the card shows the request, "Avi is asked first" and the seconds left, and no button. It does
    not count as needing her. When the status opens it, Deny and Approve are there. A tap the daemon still refuses
    (its window is not over) shows the daemon's sentence."""
    async def steps(page, stub):
        out = {"waits": await page.eval(CARD), "title": await page.eval("document.title"),
               "hot": await page.eval(f"!!{ROW % 'billing'}.querySelector('.tag.hot, .why')"), "role": await page.eval("document.getElementById('ask-asked').getAttribute('role')")}
        await asyncio.sleep(2.2)
        out["later"] = (await page.eval(CARD))["asked"]
        row = next(x for x in stub.status["sessions"] if x["name"] == "billing")
        del row["asked"]  # the owner-first time is over: the same request, this voice's to answer now
        row["can_answer"] = True
        assert await until(page, "document.querySelectorAll('#attention .answer button').length === 2")
        out["open"] = await page.eval(CARD)
        out["title_open"] = await page.eval("document.title")
        # the machine's window is not over although this voice's status said so: the daemon's own 409
        next(x for x in stub.status["sessions"] if x["name"] == "billing")["asked"] = {"name": "Avi", "until": time.time() + 3}
        await asyncio.sleep(0.9)  # past the card's arming time
        await page.eval("[...document.querySelectorAll('#attention .answer button')].find(b => b.textContent === 'Approve').click()")
        assert await until(page, "document.querySelector('#attention .err') && !document.querySelector('#attention .err').hidden")
        out["refused"] = await page.eval(CARD)
        return out, posts(stub, "/voice/approve")
    got, sent = asyncio.run(on_page(asking(with_avi(), "billing", "Avi", False), steps))
    waits = got["waits"]
    assert waits["what"] == "billing · avi-box needs approval" and waits["request"] == REQUEST and waits["buttons"] == []
    seconds = lambda line: int(re.fullmatch(r"Avi is asked first · (\d+) s", line).group(1))  # noqa: E731
    assert 11 <= seconds(waits["asked"]) <= 15 and seconds(got["later"]) < seconds(waits["asked"]) and got["role"] == "status"
    assert got["title"] == "Pointe" and got["hot"] is False
    assert got["open"]["buttons"] == ["Deny", "Approve"] and got["open"]["asked"] is None and got["title_open"] == "(1) Pointe"
    assert got["refused"]["err"] == f"Not answered: {ASKED_FIRST}"
    assert sent == [{"session": "billing", "request_id": "9f2c41aa", "decision": "allow"}]


@needs_chrome
def test_who_answered_shows_in_one_line_for_a_moment():
    """Dana approved it; Avi denied it; a voice that only learned who (its own answer came second) says "answered"."""
    async def steps(page, stub):
        assert (await page.eval(CARD))["asked"]
        row = next(x for x in stub.status["sessions"] if x["name"] == "billing")
        row.update(waiting=False, request=None, request_id=None, resolved_by={"name": "Dana", "verdict": "allow", "at": time.time()})
        del row["asked"], row["can_answer"]
        other = next(x for x in stub.status["sessions"] if x["name"] == "search")
        other["resolved_by"] = {"name": "Avi", "verdict": "deny", "at": time.time()}
        stub.status["sessions"][0]["resolved_by"] = {"name": "Somebody", "at": time.time()}  # shape only: no verdict
        assert await until(page, "document.querySelectorAll('#attention .ask.done').length === 3")
        shown = [await page.eval(DONE), await page.eval("!!document.querySelector('#attention .ask:not(.done)')")]
        await asyncio.sleep(2.5)  # the status still carries them (30 s): the lines are not drawn again or doubled
        still = len(await page.eval(DONE))
        assert await until(page, "document.querySelectorAll('#attention .ask.done').length === 0", 9)
        return shown, still, await page.eval("getComputedStyle(document.getElementById('attention')).display")
    shown, still, display = asyncio.run(on_page(asking(with_avi(), "billing", "Avi", False), steps))
    assert shown == [[["s0-shop · studio", "Somebody answered it", "status"], ["billing · avi-box", "Dana approved it", "status"],
                      ["search · avi-box", "Avi denied it", "status"]], False]
    assert still == 3 and display == "none"  # gone while the status still has them: one line, for a moment


@needs_chrome
def test_a_machine_i_may_only_watch_never_offers_approve():
    """A watch-only person is sent no request. Should a status carry one, while Avi is asked first or after (daemon
    `_there_status`: can_answer is false without the send grant), the page shows no card and counts nothing."""
    status = asking(with_avi("watch"), "billing", "Avi", False)
    opened = asking(with_avi("watch"), "billing", None, False)
    async def steps(page, stub):
        first = await page.eval("document.getElementById('attention').childElementCount")
        stub.status["sessions"] = opened["sessions"]
        await asyncio.sleep(1.4)
        return first, await page.eval("document.getElementById('attention').childElementCount"), await page.eval("document.title")
    assert asyncio.run(on_page(status, steps)) == (0, 0, "Pointe")


# ---------- the machine owner's own page ----------

@needs_chrome
def test_on_the_machine_the_owner_may_answer_while_a_person_is_asked_first_and_sees_who_answered():
    """Avi's page: Dana started ledger, so she is asked first. Avi is at his machine: his card has Approve and Deny and
    says who is asked. The row says "started by Dana". When Dana answers, one line says so. The approvals record names
    her on her answer, and nobody on Avi's own."""
    status = with_people()
    status["people_settings"] = dict(SETTINGS)
    status["sessions"].append(session("ledger", owner="Dana", started_by="Dana"))
    asking(status, "ledger", "Dana", True)
    record = [{"session": "ledger", "request_id": "9f2c41aa", "decision": "allow", "by": "tap", "person": "Dana", "link": "100.64.0.7",
               "request": REQUEST, "lock": "off", "score": None, "at": "2026-11-20 09:14:03"},
              {"session": "s0-shop", "request_id": "77aa01bc", "decision": "deny", "by": "voice", "request": "Bash\n{\"command\": \"make deploy\"}",
               "lock": "off", "score": None, "at": "2026-11-20 09:10:41"}]
    async def steps(page, stub):
        out = {"card": await page.eval(CARD), "marks": await page.eval(f"[...{ROW % 'ledger'}.querySelectorAll('.own')].map(e => e.textContent)"),
               "label": await page.eval(f"{ROW % 'ledger'}.querySelector('.nm').getAttribute('aria-label')"),
               "mine": await page.eval(f"{ROW % 's0-shop'}.querySelectorAll('.own').length"), "title": await page.eval("document.title")}
        row = next(x for x in stub.status["sessions"] if x["name"] == "ledger")
        row.update(waiting=False, request=None, request_id=None, resolved_by={"name": "Dana", "verdict": "allow", "at": time.time()})
        del row["asked"], row["can_answer"]
        assert await until(page, "document.querySelector('#attention .ask.done')")
        out["done"] = await page.eval(DONE)
        await page.eval("openSettings().then(() => settingsJump('g-approvals')); true")
        assert await until(page, "document.querySelectorAll('#approvals-list .ap').length === 2")
        out["record"] = await page.eval("[...document.querySelectorAll('#approvals-list .ap')].map(r => [r.querySelector('.ap-what').textContent, r.querySelector('.ap-who').textContent])")
        return out
    got = asyncio.run(on_page(status, steps, prepare=lambda stub: setattr(stub, "approvals", record)))
    assert got["card"]["what"] == "ledger needs approval" and got["card"]["buttons"] == ["Deny", "Approve"]
    assert re.fullmatch(r"Dana is asked first · \d+ s", got["card"]["asked"]) and got["title"] == "(1) Pointe"
    assert got["marks"] == ["started by Dana"] and got["mine"] == 0 and got["label"].startswith("ledger, Claude, needs approval")
    assert got["done"] == [["ledger", "Dana approved it", "status"]]
    assert got["record"] == [["Approved by a tap", "ledger · Dana, from 100.64.0.7"], ["Denied by voice", "s0-shop"]]


# ---------- a new session on a machine somebody invited this voice to ----------

@needs_chrome
@pytest.mark.parametrize("width", [1440, 390])
def test_a_new_session_starts_on_a_machine_i_was_invited_to(width):
    """The picker names whose machine it is and marks the ones this voice cannot start on, with the reason. Picking
    avi-box loads its own folders and agents, and says whose it is and how it starts sessions. Start posts with the
    machine, and the starting row says where. Back on this Mac, the sheet is as it was."""
    async def steps(page, stub):
        await page.eval("openNewSession()")
        assert await until(page, "document.getElementById('new-folder').options.length > 0")
        options = "[...document.getElementById('%s').options].map(o => [o.textContent, o.disabled, o.title])"
        out = {"machines": await page.eval(options % "new-machine"), "here": [await page.eval(options % "new-folder"), await page.eval(f"{TEXT}('new-there')")],
               "note": await page.eval(f"{TEXT}('new-note')")}
        pick = "(() => { const m = document.getElementById('new-machine'); m.value = '%s'; m.dispatchEvent(new Event('change', {bubbles: true})); return true; })()"
        await page.eval(pick % "avi-box")
        assert await until(page, "document.getElementById('new-folder').options[0].textContent === 'ledger'")
        out["there"] = {"folders": await page.eval(options % "new-folder"), "line": await page.eval(f"{TEXT}('new-there')"),
                        "path": await page.eval(f"{TEXT}('new-path')"), "note": await page.eval(f"{TEXT}('new-note')"),
                        "start": await page.eval("document.getElementById('new-start').disabled"), "role": await page.eval("document.getElementById('new-there').getAttribute('role')"),
                        "fits": await page.eval("(() => { const b = document.querySelector('#newsheet .sheetbox'); return b.scrollWidth <= b.clientWidth + 1; })()")}
        await page.eval(pick % "studio")
        assert await until(page, "document.getElementById('new-folder').options[0].textContent === 'shop'")
        out["back"] = [await page.eval(f"{TEXT}('new-there')"), await page.eval(f"{TEXT}('new-note')")]
        await page.eval(pick % "avi-box")
        assert await until(page, "document.getElementById('new-folder').options[0].textContent === 'ledger'")
        await page.eval("(() => { document.getElementById('new-folder').value = '/home/avi/work/atlas'; document.getElementById('new-name').value = 'maps'; document.getElementById('new-start').click(); return true; })()")
        assert await until(page, "document.querySelector('#list .s.starting')")
        if width < 900:
            await page.eval("toggleSessions(true)")
        out["starting"] = await page.eval("(() => { const r = document.querySelector('#list .s.starting'); return [r.querySelector('.nm').textContent, r.querySelector('.own').textContent, r.querySelector('.why').textContent, r.title]; })()")
        out["closed"] = await page.eval("!document.getElementById('newsheet').classList.contains('open')")
        return out, [p for p in posts(stub, "/voice/new-session")], stub.asked
    got, sent, asked = asyncio.run(on_page(with_avi(), steps, width=width))
    assert got["machines"] == [["studio (this Mac)", False, ""], ["avi-box · Avi's", False, ""], ["devbox (not available)", True, HUB_ONLY],
                               ["lab · Noor's (not available)", True, WATCH]]
    assert got["here"] == [[["shop", False, ""], ["billing", False, ""]], ""] and "Claude Code opens in a new terminal window on the Mac." in got["note"]
    line = "avi-box is Avi's machine. avi-box starts sessions that skip permission prompts: it can edit files and run commands as avi without asking."
    assert got["there"] == {"folders": [["ledger", False, ""], ["atlas", False, ""]], "line": line, "path": "/home/avi/work/ledger", "start": False, "role": "status",
                            "note": "", "fits": True}  # nothing about a terminal window on this Mac, nor why another machine is not offered
    assert got["back"][0] == "" and "Claude Code opens in a new terminal window on the Mac." in got["back"][1]
    assert sent == [{"harness": "claude-code", "folder": "/home/avi/work/atlas", "name": "maps", "machine": "avi-box"}]
    assert asked == ["", "machine=avi-box", "", "machine=avi-box"]
    assert got["starting"][:2] == ["maps", "avi-box"] and got["starting"][2].startswith("avi-box starts sessions that skip permission prompts")
    assert got["starting"][3] == "Claude Code in maps on avi-box" and got["closed"]


@needs_chrome
def test_a_machine_that_refuses_says_its_sentence_and_start_stays_off():
    """The machine turned starts off, or does not answer: the daemon's one sentence, no folder, no Start. A machine that
    asks before actions says so."""
    async def steps(page, stub):
        await page.eval("openNewSession()")
        assert await until(page, "document.getElementById('new-folder').options.length > 0")
        pick = "(() => { const m = document.getElementById('new-machine'); m.value = 'avi-box'; m.dispatchEvent(new Event('change', {bubbles: true})); return true; })()"
        stub.there_refusal = (403, "Not started. Avi turned off starting sessions on avi-box for the people invited to it.")
        await page.eval(pick)
        assert await until(page, f"{TEXT}('new-err')")
        refused = [await page.eval(f"{TEXT}('new-err')"), await page.eval("document.getElementById('new-folder').options.length"),
                   await page.eval("document.getElementById('new-start').disabled"), await page.eval(f"{TEXT}('new-there')"),
                   await page.eval("document.getElementById('new-machine').value")]
        stub.there_refusal, stub.there["permissions"], stub.there["account"] = None, "ask", ""
        await page.eval(pick)
        assert await until(page, "document.getElementById('new-folder').options.length === 2")
        return refused, await page.eval(f"{TEXT}('new-there')"), await page.eval(f"{TEXT}('new-err')")
    refused, asks, err = asyncio.run(on_page(with_avi(), steps))
    assert refused == ["Not started. Avi turned off starting sessions on avi-box for the people invited to it.", 0, True, "", "avi-box"]
    assert asks == "avi-box is Avi's machine. avi-box starts sessions that ask before actions." and err == ""


# ---------- what people can do ----------

@needs_chrome
@pytest.mark.parametrize("width", [1440, 390])
def test_what_people_can_do_has_three_controls_and_one_route(width):
    """On the machine's own page, while somebody is invited: Approve requests, Start sessions, Sessions they start. Each
    change posts its one key. The two times stay with the command line: no number field. A value the Mac refuses is
    said, and the control goes back to what the Mac has."""
    status = with_people()
    status["people_settings"] = dict(SETTINGS)
    async def steps(page, stub):
        await open_machines(page)
        await page.eval("document.getElementById('people-can').scrollIntoView({block: 'center'})")
        state = "[document.getElementById('people-approve').checked, document.getElementById('people-start').checked, document.getElementById('people-ask').value]"
        out = {"shown": [await page.eval(f"{SEEN}('{i}')") for i in ("people-can-h", "people-can", "people-can-help")], "state": await page.eval(state),
               "words": await page.eval("""[document.getElementById('people-can-h').textContent, ...['people-approve', 'people-start', 'people-ask'].map(i => document.getElementById(i).labels[0].textContent.trim()),
                                            ...[...document.getElementById('people-ask').options].map(o => o.textContent), document.getElementById('people-can-help').textContent]"""),
               "inputs": await page.eval("[...document.querySelectorAll('#people-can input, #people-can select')].map(e => e.type)"),
               "fits": await page.eval("""(() => { const p = document.getElementById('set-panel').getBoundingClientRect();
                   return [...document.querySelectorAll('#people-can input, #people-can select, #people-can label')].every(e => { const r = e.getBoundingClientRect(); return r.left >= p.left - 1 && r.right <= p.right + 1; }); })()""")}
        await page.eval("document.getElementById('people-approve').click()")
        await asyncio.sleep(1.4)
        await page.eval("document.getElementById('people-start').click()")
        await asyncio.sleep(1.4)
        await page.eval("(() => { const s = document.getElementById('people-ask'); s.value = 'ask'; s.dispatchEvent(new Event('change', {bubbles: true})); return true; })()")
        await asyncio.sleep(1.4)
        out["changed"] = [await page.eval(state), dict(stub.status["people_settings"])]
        stub.settings_refused = True
        await page.eval("document.getElementById('people-approve').click()")
        assert await until(page, f"{TEXT}('people-can-err')")
        await asyncio.sleep(1.4)
        out["refused"] = [await page.eval(f"{TEXT}('people-can-err')"), await page.eval(state)]
        return out, posts(stub, "/voice/people/settings")
    got, sent = asyncio.run(on_page(status, steps, width=width))
    assert got["shown"] == [True, True, True] and got["state"] == [True, True, "default"] and got["fits"]
    assert got["words"] == ["What people can do", "Approve requests", "Start sessions", "Sessions they start", "Follow my default", "Always ask first",
                            "On: a person who can talk may answer a request once its session's owner had the first chance, and start a session in a folder "
                            "you work in. Each answer is recorded with their name."]
    assert got["inputs"] == ["checkbox", "checkbox", "select-one"]  # owner_first_secs and people_hold_secs: `pointe people window`, `pointe people hold`
    assert got["changed"] == [[False, False, "ask"], {**SETTINGS, "approve": "off", "start": "off", "sessions_ask": "ask"}]
    assert got["refused"] == [SETTING_PROBLEM, [False, False, "ask"]]
    assert sent == [{"approve": "off"}, {"start": "off"}, {"sessions_ask": "ask"}, {"approve": "anyone"}]


# ---------- a session a person started on somebody else's machine ----------

@needs_chrome
def test_a_person_keeps_a_session_they_started_on_avis_machine_private():
    """On Dana's voice: tide is hers (she started it on avi-box), so it has no owner tag and its ⋯ sheet offers Private.
    The status of a voice says nothing of `private` for a session there: the page keeps the lock it set. Avi's own
    session there offers none, and a refusal is said in the machine's words."""
    status = with_avi()
    status["sessions"].append(session("tide", machine="avi-box", started_by="Dana"))
    sheet = "[...document.querySelectorAll('#row-acts button')].filter(b => !b.hidden).map(b => b.textContent)"
    async def steps(page, stub):
        out = {"marks": await page.eval(f"[{ROW % 'tide'}.querySelectorAll('.own').length, {ROW % 'tide'}.querySelector('.nm').getAttribute('aria-keyshortcuts')]")}
        await page.eval("openRowSheet('tide')")
        out["sheet"] = await page.eval(sheet)
        await page.eval("document.getElementById('row-private').click()")
        assert await until(page, f"{ROW % 'tide'}.querySelector('.marks .lock')")
        await asyncio.sleep(2.4)  # two polls of a status with no `private` in it
        out["kept"] = [await page.eval(f"!!{ROW % 'tide'}.querySelector('.marks .lock')"), "private" in stub.status["sessions"][-1]]
        await page.eval("openRowSheet('tide')")
        out["sheet2"] = await page.eval(sheet)
        await page.eval("document.getElementById('row-private').click()")
        assert await until(page, f"!{ROW % 'tide'}.querySelector('.marks .lock')")
        await page.eval("openRowSheet('billing')")
        out["theirs"] = await page.eval(sheet)
        await page.eval("closeSheet('rowsheet'); setPrivate('billing', true)")
        assert await until(page, f"{TEXT}('renameproblem')")
        out["refused"] = await page.eval(f"{TEXT}('renameproblem')")
        await asyncio.sleep(1.4)
        out["undone"] = await page.eval(f"!!{ROW % 'billing'}.querySelector('.marks .lock')")
        return out, posts(stub, "/voice/share")
    got, sent = asyncio.run(on_page(status, steps))
    assert got["marks"] == [0, "F2 Delete P"] and got["sheet"] == ["Rename", "Private", "Disconnect"]
    assert got["kept"] == [True, False] and got["sheet2"] == ["Rename", "Shared with people", "Disconnect"]
    assert got["theirs"] == ["Rename", "Disconnect"]
    assert got["refused"] == "billing is not a session you started on avi-box: only its owner changes who sees it." and got["undone"] is False
    assert sent == [{"session": "tide", "private": True}, {"session": "tide", "private": False}, {"session": "billing", "private": True}]


# ---------- nothing new without the fields ----------

@needs_chrome
def test_without_the_new_fields_a_prompt_a_start_and_settings_are_as_they_were():
    """Machines of one's own, nobody invited: the card has its two buttons and no "asked first"; no line says who
    answered; a starting session has no machine mark; the sheet's machines have no owner; no "What people can do"."""
    status = fixture(sessions=4, machines=2, approval=True)
    status["starting"] = [{"id": "st9", "name": "atlas", "harness": "claude-code", "label": "Claude Code", "folder": "atlas", "state": "starting",
                           "detail": "", "since": time.time(), "permissions": "ask", "notice": ""}]
    async def steps(page, stub):
        stub.start_machines = lambda: [{"name": "studio", "here": True, "available": True, "why": None},
                                       {"name": "devbox", "here": False, "available": False, "why": HUB_ONLY}]
        out = {"card": await page.eval(CARD), "done": await page.eval(DONE), "asked": await page.eval("!!document.getElementById('ask-asked')"),
               "starting": await page.eval("document.querySelector('#list .s.starting').querySelectorAll('.marks, .own').length"),
               "title": await page.eval("document.title")}
        await page.eval("openNewSession()")
        assert await until(page, "document.getElementById('new-folder').options.length > 0")
        out["sheet"] = [await page.eval("[...document.getElementById('new-machine').options].map(o => o.textContent)"), await page.eval(f"{SEEN}('new-there')")]
        await page.eval("closeSheet('newsheet')")
        await open_machines(page)
        out["settings"] = [await page.eval(f"{SEEN}('{i}')") for i in ("people-can-h", "people-can", "people-can-help")]
        return out
    got = asyncio.run(on_page(status, steps))
    assert got["card"]["buttons"] == ["Deny", "Approve"] and got["card"]["asked"] is None and got["asked"] is False and got["done"] == []
    assert got["starting"] == 0 and got["title"] == "(1) Pointe"
    assert got["sheet"] == [["studio (this Mac)", "devbox (not available)"], False] and got["settings"] == [False, False, False]
    # a machine with people and no setting in the status (an older daemon): the group stays away
    assert "$('people-can-h').hidden = $('people-can').hidden = $('people-can-help').hidden = !can;" in PAGE


def test_the_new_words():
    """What the apps share (PeopleCopy), and never "hub", "node" or "guest" on screen."""
    block = PAGE[PAGE.index("const PEOPLE_COPY = {"):]
    words = {k: v.replace("\\'", "'") for k, v in re.findall(r"(\w+): '((?:[^'\\]|\\.)*)'", block[:block.index("};")])}
    assert {k: words[k] for k in ("canDo", "approveRequests", "startSessions", "sessionsTheyStart", "followDefault", "alwaysAsk")} == {
        "canDo": "What people can do", "approveRequests": "Approve requests", "startSessions": "Start sessions",
        "sessionsTheyStart": "Sessions they start", "followDefault": "Follow my default", "alwaysAsk": "Always ask first"}
    says = PAGE[PAGE.index("const PEOPLE_SAYS = {"):]
    says = says[:says.index("};")]
    for said in ("`${name} is asked first · ${secs} s`", "`${name} approved it`", "`${name} denied it`", "`${name} answered it`", "`started by ${name}`"):
        assert said in says
    for text in [*words.values(), says]:
        assert not re.search(r"\b(hub|node|guest)s?\b", text, re.I) and "—" not in text, text
    # how a machine starts sessions: the daemon's own words (machines.start_default_line), for the sheet
    sys.path.insert(0, str(ROOT / "pointe"))
    import machines
    skips, asks = machines.start_default_line("avi-box", {"permissions": "skip", "account": "avi"}), machines.start_default_line("avi-box", {"permissions": "ask"})
    assert skips == "avi-box starts sessions that skip permission prompts: it can edit files and run commands as avi without asking."
    assert asks == "avi-box starts sessions that ask before actions."
    assert "`${machine} starts sessions that skip permission prompts: it can edit files and run commands${account ? ' as ' + account : ''} without asking.`" in says
    assert "`${machine} starts sessions that ask before actions.`" in says
