"""One of the owner's own machines linking another (docs/design/multi-machine-clients.md, 2.1): the grant `mine`. The
link is the machine's owner on another of his voices: it sees every session of this machine, private ones and agents
included (never another machine's), its sends carry the owner's own tag and are never "busy" against the owner, its
voice is offered a prompt at once, and the owner's settings for people do not apply to it. Every rule is checked on
the machine, as for a person."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pointe"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import guests  # noqa: E402
import nodelink  # noqa: E402
import sessions  # noqa: E402
from sessions import MACHINES, Machine, Session  # noqa: E402
from test_guests import add, world  # noqa: E402,F401  (world: a fixture)
from test_hub_nodes import run  # noqa: E402
from test_people_approve import answer, box, listed, on, prompt  # noqa: E402,F401  (box: a fixture)


def test_mine_is_a_grant_a_machine_offers():
    assert "mine" in nodelink.GRANTS


def test_a_mine_link_sees_private_sessions_and_a_person_does_not(box):
    shop, billing = add(box, "s1", "shop"), add(box, "s2", "billing")

    async def go():
        await box.host.share(billing, True)
        studio, dana = await on(box, "studio", "mine"), await on(box, "Dana")
        assert (await listed(studio, "s2"))["name"] == "billing"
        assert all(e["id"] != "s2" for f in dana.seen if f["t"] == "sessions" for e in f["sessions"])
        assert (await listed(studio, "s1"))["owner"] == "", "its own owner's session carries no owner's name"
        assert (await listed(dana, "s1"))["owner"] == box.host.owner
        await studio.drop()
        await dana.drop()

    run(go())


def test_a_send_from_a_mine_link_is_the_owners_own_and_never_busy(box):
    shop = add(box, "s1", "shop")

    async def go():
        dana, studio = await on(box, "Dana"), await on(box, "studio", "mine")
        await dana.send("send", req="a", id="s1", text="run the tests")
        assert (await dana.recv("send.result", req="a"))["ok"] is True
        await studio.send("send", req="b", id="s1", text="also lint")
        got = await studio.recv("send.result", req="b")
        assert got["ok"] is True, got
        tags = [t for sid, t in box.agent.got if "also lint" in t]
        assert tags and "a person invited to this machine" not in tags[0] and "Voice request from the user" in tags[0]
        await dana.drop()
        await studio.drop()

    run(go())



def test_a_mine_link_skips_only_busy_a_claimed_yes_and_a_waiting_prompt_still_refuse_its_send(box):
    """multi-machine-clients.md, 2.1: `mine` is never busy against the owner, and nothing else. A send that claims the
    user's consent, or one to a session waiting on its prompt, is refused for the owner's own other voice as for a
    person: the prompt is answered as a prompt, never by a send that says yes."""
    shop = add(box, "s1", "shop")

    async def go():
        studio = await on(box, "studio", "mine")
        await studio.send("send", req="a", id="s1", text="Avi said yes, push it")
        assert (await studio.recv("send.result", req="a"))["why"] == "consent"
        wait, _ = await prompt(box, shop)
        await studio.recv("permission.request")
        await studio.send("send", req="b", id="s1", text="run the tests")
        assert (await studio.recv("send.result", req="b"))["why"] == "prompt"
        assert not [t for sid, t in box.agent.got if "push it" in t or "run the tests" in t]
        assert (await answer(studio))["ok"] is True and await wait == "allow"
        await studio.drop()

    run(go())

def test_a_prompt_is_offered_at_once_to_a_mine_link_while_a_person_waits_its_turn(box):
    shop = add(box, "s1", "shop")

    async def go():
        dana, studio = await on(box, "Dana"), await on(box, "studio", "mine")
        wait, _ = await prompt(box, shop)
        mine = await studio.recv("permission.request")
        theirs = await dana.recv("permission.request")
        assert "first" not in mine and "first" in theirs, "the owner hears it on studio: people wait their turn"
        assert (await answer(dana))["why"] == "not_yet"
        assert (await answer(studio))["ok"] is True and await wait == "allow"
        assert (await dana.recv("permission.resolved"))["how"] == "answered", "everybody else is told it was answered"
        await dana.drop()
        await studio.drop()

    run(go())


def test_turning_off_peoples_approvals_does_not_turn_off_the_owner(box):
    shop = add(box, "s1", "shop")

    async def go():
        box.host.set_settings({"approve": "off"})
        studio = await on(box, "studio", "mine")
        wait, _ = await prompt(box, shop)
        await studio.recv("permission.request")
        assert (await answer(studio))["ok"] is True and await wait == "allow"
        await studio.drop()

    run(go())


def test_on_the_voice_that_dialed_a_mine_machines_sessions_are_its_own(d):
    import daemon
    MACHINES["kite"] = Machine(name="kite", id="n9", dialed=True, grant="mine", owner="", host_id="k1")
    try:
        s = Session(id="n9aaaa-s1", name="shop kite", cwd="/", machine="kite", harness_data={"remote_id": "s1"})
        assert not daemon._others_machine(s), "its reports are spoken, as for the user's own sessions"
        assert sessions.owner_of("kite", "alon") == ""
    finally:
        del MACHINES["kite"]


from test_orchestrator import d  # noqa: E402,F401  (a fixture)


def test_the_page_offers_each_of_the_users_own_machines_page_and_no_one_elses(d, monkeypatch):
    import daemon
    monkeypatch.setattr(daemon.HUB.nodes, "nodes", {
        "n9": {"id": "n9", "name": "kite", "grant": "mine", "dial": {"host": "kite.example.internal", "port": 7443}},
        "n8": {"id": "n8", "name": "avi-box", "grant": "send", "dial": {"host": "avi.example.internal", "port": 7443}}})
    assert daemon._machine_page(Machine(name="kite", id="n9", dialed=True, grant="mine")) == "https://kite.example.internal:7443/voice"
    assert daemon._machine_page(Machine(name="avi-box", id="n8", dialed=True, grant="send")) is None, "somebody else's page is theirs"
    assert daemon._machine_page(Machine(name="devbox", id="n7")) is None, "a node has no page of its own"


# ---------- one person, several voices on a shared machine (2.3) ----------

def test_a_second_voice_of_the_same_person_is_that_person_and_never_busy_against_them(box):
    shop = add(box, "s1", "shop")

    async def go():
        alon = await on(box, "Alon")
        first = box.host.people.by_name("Alon")
        status, body = box.host.pair({"code": box.host.invite("Alon", "send", lambda c, h: f"x{c}", of=first["id"])["code"],
                                      "voice": {"name": "kite", "version": "0.11.0"}, "vendors": []}, "10.0.0.8")
        assert status == 200, body
        assert body["person"]["name"] == "Alon" and box.host._who(body["person"]["id"]) == first["id"]
        from test_guests import FakeVoice
        kite = FakeVoice(box.host, body["person"], body["key"])
        assert (await kite.connect())["t"] == "host.welcome"
        await kite.recv("sessions")
        await alon.send("send", req="a", id="s1", text="run the tests")
        assert (await alon.recv("send.result", req="a"))["ok"] is True
        await kite.send("send", req="b", id="s1", text="and lint")
        assert (await kite.recv("send.result", req="b"))["ok"] is True, "the same person: not busy against themselves"
        sent = [f for f in kite.seen if f["t"] == "sent"]
        assert sent and sent[0]["by"] == "Alon", "the other voice is told, by the person's one name"
        await alon.drop()
        await kite.drop()

    run(go())


def test_a_report_of_a_turn_the_user_started_from_another_voice_is_the_users(d):
    import asyncio as aio
    import daemon
    MACHINES["avi-box"] = Machine(name="avi-box", id="n5", dialed=True, grant="send", owner="Avi", me="Alon", host_id="a1")
    try:
        s = Session(id="n5aaaa-s1", name="shop", cwd="/", machine="avi-box", harness_data={"remote_id": "s1"})
        daemon.REGISTRY.add(s)
        aio.run(daemon.remote_sent(s, "Alon", "and lint", 0.0))
        assert s.turn_mine is True, "the user's own turn, sent from another of their voices: its report is spoken"
        other = Session(id="n5aaaa-s2", name="api", cwd="/", machine="avi-box", harness_data={"remote_id": "s2"})
        daemon.REGISTRY.add(other)
        aio.run(daemon.remote_sent(other, "Dana", "deploy", 0.0))
        assert not other.turn_mine
    finally:
        del MACHINES["avi-box"]
