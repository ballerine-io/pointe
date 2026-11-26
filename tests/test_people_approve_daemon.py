"""Phase 3 of people and machines, at the daemon's seams (docs/design/people-and-machines.md, "Phase 3"): a person's
verdict delivered and recorded with their name, a prompt held with no call of the owner's own, the owner's start path
run for a person, and, on a person's voice, a prompt that waits for somebody asked first. The link and the machine's
own checks are tests/test_people_approve.py; here the daemon is the real one."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import approvals  # noqa: E402
import guests  # noqa: E402
import harnesses  # noqa: E402
import hub_nodes  # noqa: E402
import nodelink  # noqa: E402
from test_guests import real  # noqa: E402,F401  (a fixture: the daemon's own PEOPLE on this test's people file)
from test_mixed_harnesses import node  # noqa: E402,F401  (a fixture)
from test_new_session import _ask, _settle, home  # noqa: E402,F401  (home: a fixture)
from test_orchestrator import add, client_for, d, fake_conn  # noqa: E402,F401
from test_people_approve import Sock  # noqa: E402
from test_people_voice import AVI_BOX, avi, on_avi_box  # noqa: E402,F401  (avi: a fixture)

@pytest.fixture(autouse=True)
def people_may(monkeypatch):
    """These tests are of a machine whose owner turned approving and starting on. Both are off as released, until the
    page and the apps have their screens (test_released_off_until_the_owner_turns_each_on)."""
    monkeypatch.setitem(guests.DEFAULTS, "approve", "anyone")
    monkeypatch.setitem(guests.DEFAULTS, "start", "on")


def dana_on(d, grant="send", call_up=True) -> guests.Link:
    """Dana, invited to this machine, with her voice linked."""
    who = d.PEOPLE.people.add("Dana", grant, "100.64.0.7", ["Anthropic"], 5.0)
    link = guests.Link(id=who["id"], name="Dana", ws=Sock(), address="100.64.0.7", protocol=2,
                       features=list(nodelink.FEATURES), heard=0.0, call_up=call_up)
    d.PEOPLE.live[who["id"]] = link
    return link


@pytest.fixture
def machine(real, monkeypatch):  # noqa: F811
    monkeypatch.setattr(real.PEOPLE, "live", {})
    monkeypatch.setattr(real.PEOPLE, "offers", {})
    monkeypatch.setattr(real.PEOPLE, "offer_poll", 0)
    monkeypatch.setattr(real.PEOPLE, "resolved", {})
    return real


def journal(d):
    lines = []
    sink = d.logger.add(lambda m: lines.append(m.record["message"]), level="INFO")
    return lines, lambda: d.logger.remove(sink)


# ---------- on the machine ----------

def test_a_prompt_is_held_with_no_call_only_while_a_person_who_may_answer_is_linked(machine, monkeypatch):
    d = machine
    shop = add(d, "s1", "shop")
    assert d.state.conn is None and d._nobody_hears(shop) is True  # nobody is invited: the terminal, as ever
    link = dana_on(d)
    assert d._nobody_hears(shop) is False
    link.call_up = False  # her call ended: nobody would hear it
    assert d._nobody_hears(shop) is True
    link.call_up = True
    d.PEOPLE.people.by_name("Dana")["grant"] = "watch"
    assert d._nobody_hears(shop) is True
    d.PEOPLE.people.by_name("Dana")["grant"] = "send"
    monkeypatch.setattr(d.vendors, "config", lambda: {"approvals": "terminal"})  # the owner answers in terminals
    assert d._nobody_hears(shop) is True


def test_a_persons_tap_answers_the_real_hook_and_the_record_names_them_and_their_link(machine):
    d = machine
    shop = add(d, "s1", "shop")
    link = dana_on(d)
    lines, stop = journal(d)

    async def go():
        held = asyncio.create_task(d._harness_permission(shop, "Bash", {"command": "git status", "description": "Show status"}))
        for _ in range(200):
            if shop.permission_id and "s1" in d.PEOPLE.offers:
                break
            await asyncio.sleep(0.01)
        request_id = shop.permission_id
        sent = [f for f in link.ws.sent if f["t"] == "permission.request"]
        assert sent and sent[0]["request_id"] == request_id and sent[0]["readable"] == "run: git status"
        assert "first" not in sent[0]  # Avi has no call: it is hers at once
        await d.PEOPLE._on_answer(link, {"t": "permission.answer", "id": "s1", "request_id": request_id,
                                         "verdict": "allow", "how": "tap"})
        assert [f for f in link.ws.sent if f["t"] == "permission.answered"][-1]["ok"] is True
        return request_id, await asyncio.wait_for(held, 2)

    try:
        request_id, verdict = asyncio.run(go())
    finally:
        stop()
    assert verdict == "allow" and shop.permission_id is None
    [record] = [approvals.parse({"event": text, "at": "now"}) for text in lines if text.startswith(approvals.MARK)]
    assert (record["person"], record["link"], record["by"], record["decision"]) == ("Dana", "100.64.0.7", "tap", "allow")
    assert record["session"] == "shop" and record["request_id"] == request_id and "git status" in record["request"]
    assert any(text.startswith("people: Dana approved shop's request by tap, from 100.64.0.7: Bash: ") for text in lines)
    note = d.NOTES.items[-1]
    assert (note.kind, note.text) == ("session_news", "Dana approved shop's request to run: git status.")
    status = client_for(d).get("/voice/status").json()
    assert status["sessions"][0]["resolved_by"]["name"] == "Dana" and status["people_settings"]["approve"] == "anyone"


def test_the_owners_own_record_has_no_person_on_it():
    line = approvals.event(session="shop", machine=None, request_id="r1", decision="allow", how="tapped", request="Bash",
                           lock="off", score=None)
    assert "person" not in approvals.parse({"event": line, "at": "now"})


def test_the_owner_on_a_call_hears_who_answered(machine, monkeypatch):
    d = machine
    shop = add(d, "s1", "shop")
    said = []

    async def say_fixed(line):
        said.append(line)

    monkeypatch.setattr(d, "_say_fixed", say_fixed)

    async def go():
        d.state.conn = fake_conn()
        shop.permission_id, shop.permission_spoken, shop.permission_full = "r1", "run: npm test", "Bash\n{}"
        shop.permission_answer = asyncio.get_running_loop().create_future()
        took = await d._person_answered(shop, "r1", "deny", "voice", {"id": "p1", "name": "Dana"}, "100.64.0.7")
        await asyncio.sleep(0.01)
        stale = await d._person_answered(shop, "r1", "allow", "tap", {"id": "p1", "name": "Dana"}, "100.64.0.7")
        return took, stale, shop.permission_answer.result()

    assert asyncio.run(go()) == (True, False, "deny")  # and a verdict for a request no longer pending delivers nothing
    assert said == ["Dana denied shop's request to run: npm test."]


def test_the_owners_call_ending_leaves_a_prompt_with_a_person_who_can_still_answer(machine):
    d = machine
    shop, tide = add(d, "s1", "shop"), add(d, "s2", "tide")
    dana_on(d)
    d.PEOPLE.people.private.add("s2")  # Dana does not see tide

    async def go():
        for s in (shop, tide):
            s.permission_id = f"r-{s.id}"
            s.permission_answer = asyncio.get_running_loop().create_future()
            await d.PEOPLE.offer(s, s.permission_id, "Bash", {"command": "git status"}, "", "{}")
        d._hand_prompts_back()
        return shop.permission_answer.done(), tide.permission_answer.done()

    assert asyncio.run(go()) == (False, True)


def test_a_persons_start_runs_the_owners_start_path_with_the_owners_default(home, monkeypatch):
    d = home.d
    monkeypatch.setattr(d.PEOPLE, "people", guests.People(home.tmp / "people.json"))
    dana = d.PEOPLE.people.add("Dana", "send", "100.64.0.7", [], 5.0)
    opencode = harnesses.get("opencode")
    check = ["ok"]
    monkeypatch.setattr(opencode, "skips", True, raising=False)
    monkeypatch.setattr(opencode, "skip_check", lambda folder: check[0], raising=False)
    d.PREFS.update({"sessions.permissions": "skip"})

    async def go():
        out = [await d._person_start(dana, "opencode", home.billing, "invoices", "", False)]  # the owner's default: skip
        out.append(await d._person_start(dana, "opencode", home.billing, None, "", True))  # "always ask first"
        check[0] = "confirm"  # Claude Code's one-time consent is the owner's to give, never a person's
        out.append(await d._person_start(dana, "opencode", home.shop, "third", "", False))
        d.PREFS.update({"sessions.permissions": "ask"})
        out.append(await d._person_start(dana, "opencode", home.shop, "fourth", "", False))
        out.append(await d._person_start(dana, "opencode", "/etc", None, "", False))
        out.append(await d._person_start(dana, "gemini", home.shop, None, "", False))
        out.append(await d._person_start(dana, "opencode", home.shop, "<b>", "", False))
        return out

    first, asked, unconfirmed, owner_asks, elsewhere, unknown, bad_name = asyncio.run(go())
    assert first[0] is True and home.skips == [True, False, False, False]
    assert [s[:3] for s in home.started] == [("opencode", home.billing, "invoices"), ("opencode", home.billing, "billing-2"),
                                             ("opencode", home.shop, "third"), ("opencode", home.shop, "fourth")]
    session = d.REGISTRY.sessions[first[1]["id"]]
    assert session.owner == "Dana" and session.harness_data["started_by"] == {"id": dana["id"], "name": "Dana"}
    assert asked[0] and unconfirmed[0] and owner_asks[0]
    assert elsewhere == (False, {"why": "folder"}) and unknown == (False, {"why": "harness"})
    assert bad_name[0] is False and bad_name[1]["why"] == "failed" and "name cannot be used" in bad_name[1]["detail"]
    assert not d.PREFS.get("sessions.skip_told")  # the owner's own one-time line is still theirs to hear
    status = client_for(d).get("/voice/status").json()
    row = next(s for s in status["sessions"] if s["name"] == "invoices")
    assert (row["owner"], row["started_by"]) == ("Dana", "Dana")


def test_what_a_persons_sheet_lists_is_the_owners_own_list(home):
    d = home.d
    options = d._start_options()
    assert sorted(f["path"] for f in options["folders"]) == sorted([home.shop, home.billing])
    assert options["folders"] == d._start_folders() and options["permissions"] == "ask"
    d.PREFS.update({"sessions.permissions": "skip"})
    assert d._start_options()["permissions"] == "skip"


# ---------- on a person's voice ----------

def test_a_prompt_for_somebody_asked_first_is_shown_not_read_and_a_tap_is_told_to_wait(d, avi, monkeypatch):  # noqa: F811
    shop = on_avi_box(d, "s1", "shop", owner="Avi")
    read, announced = [], []

    async def speak(text, window):
        read.append(text)

    async def announce(session):
        announced.append(session.name)

    monkeypatch.setattr(d, "_announce_permission", announce)

    async def go():
        d.state.conn = fake_conn()
        d.state.front = SimpleNamespace(_speak=speak)
        d.REGISTRY.set_active(shop.id)
        assert await d.remote_permission(shop, "9f2c41aa", "Bash", "Run the tests", '{"command": "npm test"}',
                                         "run: npm test", first="Avi", yours_in_ms=20_000)
        await d._read_out(shop)  # a yes that came early asks for a read-out: nothing is said yet
        waiting = client_for(d).get("/voice/status").json()["sessions"][0]
        tap = client_for(d).post("/voice/approve", json={"session": "shop", "decision": "allow", "request_id": "9f2c41aa"})
        # the machine sends it again, without `first`: now it is read out as any prompt is
        assert await d.remote_permission(shop, "9f2c41aa", "Bash", "Run the tests", '{"command": "npm test"}', "run: npm test")
        opened = client_for(d).get("/voice/status").json()["sessions"][0]
        assert await d.remote_permission(shop, "9f2c41aa", "Bash", "Run the tests", '{"command": "npm test"}', "run: npm test")
        return waiting, tap, opened

    waiting, tap, opened = asyncio.run(go())
    assert read == [] and announced == ["shop"]  # once, when it opened; the same request again says nothing more
    assert waiting["waiting"] is True and waiting["request_id"] == "9f2c41aa" and waiting["can_answer"] is False
    assert waiting["asked"]["name"] == "Avi" and 15 < waiting["asked"]["until"] - d.time.time() <= 20
    assert tap.status_code == 409 and tap.json()["detail"] == "Avi is asked first. You can answer in a moment."
    assert "asked" not in opened and opened["can_answer"] is True


def test_a_prompt_somebody_answered_there_leaves_the_card_with_their_name_in_the_notes(d, avi):  # noqa: F811
    shop = on_avi_box(d, "s1", "shop", owner="Avi")

    async def go():
        d.state.conn = fake_conn()
        await d.remote_permission(shop, "9f2c41aa", "Bash", "", '{"command": "npm test"}', "run: npm test", first="Avi",
                                  yours_in_ms=20_000)
        d.remote_resolved(shop, "9f2c41aa", "answered", by="Avi", verdict="allow")
        await asyncio.sleep(0)

    asyncio.run(go())
    assert shop.permission_id is None and shop.id not in d.state.remote_first
    assert d.NOTES.items[-1].text == "Avi approved shop's request."
    row = client_for(d).get("/voice/status").json()["sessions"][0]
    assert row["resolved_by"]["name"] == "Avi" and row["resolved_by"]["verdict"] == "allow" and "asked" not in row


def test_a_session_this_person_started_there_says_so_and_is_theirs(d, avi):  # noqa: F811
    on_avi_box(d, "s1", "tide", owner="Dana", started_by="Dana")
    on_avi_box(d, "s2", "skiff", owner="Ben", started_by="Ben")
    rows = {s["name"]: s for s in client_for(d).get("/voice/status").json()["sessions"]}
    assert rows["tide"]["started_by"] == "Dana" and "owner" not in rows["tide"]  # her own: no owner named
    assert (rows["skiff"]["owner"], rows["skiff"]["started_by"]) == ("Ben", "Ben")


class Machine:
    """avi-box as the voice's Hub reaches it: what it lists, and what it was asked to start."""

    def __init__(self, d, monkeypatch, permissions="skip", **over):
        self.asked, self.result = [], {"ok": True, "id": "n1", "name": "shop-2"}
        self.node = SimpleNamespace(id=AVI_BOX, name="avi-box", online=True, features=list(nodelink.FEATURES),
                                    machine=SimpleNamespace(dialed=True, owner="Avi", grant="send", removed=False))
        for key, value in over.items():
            setattr(self.node.machine if key in ("grant", "removed") else self.node, key, value)
        self.options = {"folders": [{"path": "/srv/shop", "name": "shop"}, {"path": "/srv/tide", "name": "tide"}],
                        "harnesses": [{"name": "claude-code", "title": "Claude Code", "available": True, "why": None}],
                        "permissions": permissions, "account": "avi"}
        self.entry = {"id": AVI_BOX}

        async def folders(node_):
            return self.options

        async def start(node_, harness, folder, name, prompt=""):
            self.asked.append((harness, folder, name, prompt))
            return self.result

        monkeypatch.setattr(d.HUB, "machine", lambda name: self.node if str(name).lower() == "avi-box" else None)
        monkeypatch.setattr(d.HUB, "folders", folders)
        monkeypatch.setattr(d.HUB, "start", start)
        monkeypatch.setattr(d.HUB.nodes, "get", lambda node_id: self.entry)
        monkeypatch.setattr(d.HUB.nodes, "update", lambda node_id, **fields: self.entry.update(fields))
        monkeypatch.setattr(d, "STARTS", {})


def test_the_sheet_lists_a_machines_own_folders_and_starts_there(d, avi, monkeypatch):  # noqa: F811
    box = Machine(d, monkeypatch)
    client = client_for(d)
    got = client.get("/voice/new-session", params={"machine": "avi-box"}).json()
    assert got["folders"] == [{"path": "/srv/shop", "name": "shop", "source": "machine"},
                              {"path": "/srv/tide", "name": "tide", "source": "machine"}]
    assert got["machine"] == {"name": "avi-box", "owner": "Avi", "permissions": "skip", "account": "avi"}
    there = next(m for m in client.get("/voice/new-session").json()["machines"] if m["name"] == "avi-box")
    assert there == {"name": "avi-box", "here": False, "available": True, "why": None, "owner": "Avi"}
    assert next(m for m in client.get("/voice/status").json()["machines"] if m["name"] == "avi-box")["can_start"] is True

    async def go():
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(transport=ASGITransport(app=d.app), base_url="http://127.0.0.1:7860",
                               cookies={"pointe_local": d.PAGE_KEY}) as http:
            first = await http.post("/voice/new-session", json={"machine": "avi-box", "harness": "claude-code",
                                                                "folder": "/srv/shop", "prompt": "run the tests",
                                                                "permissions": "ask"})
            await asyncio.sleep(0.05)
            second = await http.post("/voice/new-session", json={"machine": "avi-box", "harness": "claude-code",
                                                                 "folder": "/srv/tide"})
            await asyncio.sleep(0.05)
            return first.json(), second.json()

    first, second = asyncio.run(go())
    assert box.asked == [("claude-code", "/srv/shop", None, "run the tests"), ("claude-code", "/srv/tide", None, "")]
    assert first["machine"] == "avi-box" and first["notice"] == (
        "avi-box starts sessions that skip permission prompts: it can edit files and run commands as avi without asking.")
    assert second["notice"] == ""  # said once for each machine
    assert all(s.state == "joined" and s.machine == "avi-box" for s in d.STARTS.values())


@pytest.mark.parametrize("over, said", [
    ({"features": ["attach", "held", "people"]},
     "Not started. avi-box runs an older Pointe. Its owner updates it there, and then you can start sessions on it."),
    ({"grant": "watch"}, "Not started. Avi lets you watch avi-box, not start sessions there."),
    ({"online": False}, "Not started. avi-box is offline."),
])
def test_a_machine_this_voice_cannot_start_on_says_why_in_the_sheet_and_the_status(d, avi, monkeypatch, over, said):  # noqa: F811
    Machine(d, monkeypatch, **over)
    monkeypatch.setattr(d.HUB, "start_problem", lambda n: hub_nodes.Hub.start_problem(d.HUB, n))
    client = client_for(d)
    refused = client.get("/voice/new-session", params={"machine": "avi-box"})
    assert refused.status_code == 409 and refused.json()["detail"] == said
    posted = client.post("/voice/new-session", json={"machine": "avi-box", "harness": "claude-code", "folder": "/srv/shop"})
    assert posted.status_code == 409 and posted.json()["detail"] == said
    there = next(m for m in client.get("/voice/new-session").json()["machines"] if m["name"] == "avi-box")
    assert there["available"] is False and said.endswith(there["why"])
    assert next(m for m in client.get("/voice/status").json()["machines"] if m["name"] == "avi-box")["can_start"] is False


def test_a_start_the_machine_refuses_is_listed_as_failed_with_its_sentence(d, avi, monkeypatch):  # noqa: F811
    box = Machine(d, monkeypatch)
    box.result = {"ok": False, "why": "off"}

    async def go():
        start = await d._begin_start_there("avi-box", "claude-code", "/srv/shop", None, "", "page")
        await asyncio.sleep(0.05)
        return start

    start = asyncio.run(go())
    assert start.state == "failed"
    assert start.detail == "Not started. Avi turned off starting sessions on avi-box for the people invited to it."


def test_by_voice_the_read_back_names_the_machine_whose_it_is_and_once_how_it_starts_sessions(home, avi, monkeypatch):  # noqa: F811
    d = home.d
    monkeypatch.setattr(d, "paired_machines", lambda: [avi])
    box = Machine(d, monkeypatch)

    async def go():
        first = await _ask(d, "Start a session on avi-box in the shop folder.")
        yes = await _ask(d, "Yes.")
        await asyncio.sleep(0.05)
        again = await _ask(d, "Start a session on avi-box in tide.")
        nowhere = await _ask(d, "Start a session on avi-box in billing.")
        return first, yes, again, nowhere

    first, yes, again, nowhere = asyncio.run(go())
    assert first["confirm_first"] == (
        "Start a Claude Code session on avi-box, Avi's machine, in shop? avi-box starts sessions that skip permission "
        "prompts: it can edit files and run commands as avi without asking.")
    assert yes["starting"] == "shop" and box.asked == [("claude-code", "/srv/shop", None, "")]
    assert again["confirm_first"] == "Start a Claude Code session on avi-box, Avi's machine, in tide?"
    # billing is a folder here, not there: the machine's own list decides
    assert "starts only in a folder Avi works in there" in nowhere["error"] and "shop, tide" in nowhere["error"]
    assert home.started == []  # nothing started on this machine
