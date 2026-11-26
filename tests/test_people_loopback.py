"""Three people's Pointes on one host, end to end with no model and no vendor (docs/design/people-and-machines.md):
avi's machine with its sessions, and the voices of dana and omer, whom avi invites. Three real daemon processes on
loopback (tests/fleet.py), each on its own state folder and on ports chosen free at run time; each voice dials avi's
TLS listener through a proxy the test can cut, stall or delay.

No call is up, so nothing is spoken and no request is sent to a session: everything is driven by the daemons' own
HTTP routes and read from /voice/status, the mirror files and the sessions' inboxes. What a send does on this link
(the grant, a busy session, a claimed consent) is tests/test_guests.py and tests/test_machines.py.

Slow: it starts five daemon processes in all. The heartbeat is 1 s with 5 s to a dead link here, in place of 2 s and
12 s (POINTE_LINK_PING_SECS, POINTE_LINK_DEAD_SECS), so a frozen machine costs seconds, not a quarter of a minute."""

import asyncio
import shutil
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT), str(ROOT / "tests")]
import nodelink  # noqa: E402
from fleet import Fleet, through, until  # noqa: E402

PING, DEAD = 1.0, 5.0
BOX = "avi-box"
TIMES: dict[str, float] = {}


class Phase:
    """One part of the run, timed: the report at the end says where the seconds went."""

    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        self.at = time.monotonic()

    def __exit__(self, *failed):
        TIMES[self.name] = round(time.monotonic() - self.at, 1)


def online(voice) -> bool:
    return bool((voice.machine(BOX) or {}).get("online"))


def once(voices, session, line: str, why: str) -> None:
    """The line is in each voice's mirror of the session, exactly once."""
    for voice in voices:
        until(f"{voice.name} mirrors {line!r} ({why})", lambda: line in voice.mirror(session.id), 20)
    for voice in voices:
        assert voice.mirror(session.id).count(line) == 1, f"{voice.name} mirrored {line!r} twice ({why})"


def nothing_twice(voices, session, lines: list[str], why: str) -> None:
    for voice in voices:
        mirror = voice.mirror(session.id)
        assert [mirror.count(line) for line in lines] == [1] * len(lines), f"{voice.name}, {why}: a line is missing or twice"


async def dial_with(port: int, fp: str, key: str, person: str, host_id: str) -> int | None:
    """One link as a voice opens it, with this key: the close code the machine answers its hello with."""
    import aiohttp

    async with aiohttp.ClientSession() as http, http.ws_connect(
            f"wss://127.0.0.1:{port}{nodelink.HOST_PATH}", ssl=aiohttp.Fingerprint(bytes.fromhex(fp))) as ws:
        challenge = nodelink.decode((await ws.receive(timeout=10)).data, nodelink.NODE_FRAMES)
        assert challenge["t"] == "host.challenge" and challenge["host"]["id"] == host_id
        await ws.send_str(nodelink.encode(
            "voice.hello", auth=nodelink.answer(key, challenge["nonce"], host_id), person=person,
            protocol=nodelink.PROTOCOL, protocol_min=2, features=[], voice={"name": "dana-mac", "version": "0"}, vendors=[]))
        answer = await ws.receive(timeout=10)
        return answer.data if answer.type == aiohttp.WSMsgType.CLOSE else None


@pytest.mark.slow
def test_three_peoples_pointes_on_loopback_share_cut_restart_and_remove(tmp_path):
    fleet = Fleet(tmp_path, {"POINTE_LINK_PING_SECS": str(PING), "POINTE_LINK_DEAD_SECS": str(DEAD)})
    try:
        run(fleet)
    except BaseException:
        print(fleet.logs())
        raise
    finally:
        fleet.close()
        print("seconds:", TIMES, "total", round(sum(TIMES.values()), 1))
        shutil.rmtree(tmp_path, ignore_errors=True)


def run(fleet: Fleet) -> None:
    with Phase("start three daemons"):
        avi, dana, omer = fleet.daemon(BOX, "Avi"), fleet.daemon("dana-mac", "Dana"), fleet.daemon("omer-mac", "Omer")
        assert not ({d.port for d in fleet.daemons} | {d.tls_port for d in fleet.daemons}) & {7860, 7443}
        avi.listen()
        fleet.start()
        shop, ledger, vault = (fleet.session(f"5e55{n}000-aaaa-4bbb-8ccc-00000000000{n}", name)
                               for n, name in enumerate(("shop", "ledger", "vault"), 1))
        for session in (shop, ledger, vault):
            assert avi.register(session) == session.name
        atlas = fleet.session("5e554000-aaaa-4bbb-8ccc-000000000004", "atlas")  # dana's own, on her own machine
        assert dana.register(atlas) == "atlas"
        assert avi.post("/voice/share", {"session": "vault", "private": True}) == {"ok": True, "private": True}
        first = shop.say("The migration ran on 3 tables.")  # before anyone is invited: history, not news
        to_dana, to_omer = fleet.proxy(avi.tls_port), fleet.proxy(avi.tls_port)

    with Phase("invite, add, see"):
        for voice, person, grant, proxy in ((dana, "Dana", "send", to_dana), (omer, "Omer", "watch", to_omer)):
            invite = avi.post("/voice/people/invite", {"name": person, "grant": grant})
            assert invite["grant"] == grant and invite["link"].startswith("pointe://machine?")
            added = voice.post("/voice/machines/add", {"line": through(invite["link"], proxy)})
            assert (added["name"], added["owner"], added["grant"]) == (BOX, "Avi", grant), added
            until(f"{voice.name} links to {BOX}", lambda: online(voice))
            assert voice.call("/voice/machines/add", {"line": invite["link"]})[0] == 400  # already in this voice
        for voice, grant in ((dana, "send"), (omer, "watch")):
            seen = until(f"{voice.name} sees avi's shared sessions",
                         lambda: s if set(s := voice.sessions(BOX)) == {"shop", "ledger"} else None)
            assert all(row["owner"] == "Avi" and row["online"] for row in seen.values()), seen
            box = voice.machine(BOX)
            assert (box["owner"], box["grant"], box["here"]) == ("Avi", grant, False) and "removed" not in box
            status = voice.status()
            assert "vault" not in {s["name"] for s in status["sessions"]}  # avi's private session is in no frame
            assert status["disclosure"]["machine"] == BOX
            assert voice.post("/voice/machines/add", {"seen": BOX}) == {"ok": True} and "disclosure" not in voice.status()
        assert "owner" not in dana.sessions()["atlas"] and dana.sessions()["atlas"]["machine"] == "dana-mac"
        people = {p["name"]: p for p in avi.status()["people"]}
        assert {n: (p["grant"], p["online"]) for n, p in people.items()} == {"Dana": ("send", True), "Omer": ("watch", True)}
        assert avi.sessions()["vault"]["private"] is True and "atlas" not in avi.sessions()  # nothing flows back to avi

    with Phase("transcripts mirror"):
        once((dana, omer), shop, first, "what was there before they joined")
        second = shop.say("All 12 tests pass.")
        once((dana, omer), shop, second, "a new line")
        said = [first, second]
        assert vault.say("The signing key moved.") not in dana.mirror(vault.id) + omer.mirror(vault.id)

    with Phase("a slow link to one voice"):
        to_omer.delay = 2.0  # every chunk to and from omer waits 2 s
        at = time.monotonic()
        said.append(shop.say("The deploy is at step 2 of 5."))
        until("dana has the line while omer's link is slow", lambda: said[-1] in dana.mirror(shop.id), 10, every=0.05)
        dana_took = time.monotonic() - at
        assert said[-1] not in omer.mirror(shop.id) and dana_took < 1.8, f"dana waited {dana_took:.1f} s on omer's slow link"
        once((omer,), shop, said[-1], "over the slow link")
        to_omer.delay = 0.0
        TIMES["dana's view, omer's link 2 s slow"] = round(dana_took, 2)

    with Phase("avi keeps a session private"):
        hidden = ledger.say("Refunds reconcile to the cent.")
        once((dana, omer), ledger, hidden, "while it is shared")
        assert avi.post("/voice/share", {"session": "ledger", "private": True})["private"] is True
        secret = ledger.say("The vendor contract ends in March.")
        for voice in (dana, omer):
            until(f"ledger leaves {voice.name}", lambda: set(voice.sessions(BOX)) == {"shop"}, 20)
        said.append(shop.say("Step 3 of 5."))
        once((dana, omer), shop, said[-1], "after ledger went private")  # the links are in step, so the next line holds:
        assert secret not in dana.mirror(ledger.id) + omer.mirror(ledger.id)  # nothing written after it went private

    with Phase("avi lets omer send"):
        assert avi.post("/voice/people/grant", {"name": "Omer", "grant": "send"}) == {"ok": True}
        until("omer's grant is send", lambda: omer.machine(BOX)["grant"] == "send")
        assert dana.machine(BOX)["grant"] == "send" and online(dana)

    with Phase("avi frozen, then back"):
        avi.freeze()
        at = time.monotonic()
        until("dana shows avi-box offline", lambda: not online(dana), DEAD + 12, every=0.2)
        took = time.monotonic() - at
        TIMES["offline shown after a freeze"] = round(took, 1)
        assert took < DEAD + 2 * PING + 5, f"offline only after {took:.1f} s"  # the heartbeat, a ping late, the close
        until("omer shows avi-box offline", lambda: not online(omer), DEAD + 12)
        row = dana.sessions(BOX)["shop"]
        assert row["online"] is False and dana.machine(BOX)["since"]  # still listed, and marked offline
        assert dana.sessions()["atlas"]["online"] is True and dana.machine("dana-mac")["online"]  # her own still answer
        said.append(shop.say("Step 4 of 5, written while avi was frozen."))
        avi.thaw()
        until("both voices are linked again", lambda: online(dana) and online(omer), 40)
        once((dana, omer), shop, said[-1], "after the freeze")
        nothing_twice((dana, omer), shop, said, "after the freeze")

    with Phase("one link cut"):
        omer_links, dana_links = to_omer.accepted, to_dana.accepted
        to_dana.cut()
        until("dana redials", lambda: to_dana.accepted > dana_links and online(dana), 30)
        said.append(shop.say("Step 5 of 5."))
        once((dana, omer), shop, said[-1], "after dana's link was cut")
        nothing_twice((dana, omer), shop, said, "after dana's link was cut")
        assert to_omer.accepted == omer_links and online(omer), "omer's link dropped when dana's was cut"

    with Phase("avi restarts"):
        avi.restart()
        until("both voices redial the new process", lambda: online(dana) and online(omer), 60)
        for voice in (dana, omer):
            until(f"{voice.name} sees shop again", lambda: set(voice.sessions(BOX)) == {"shop"}, 20)  # private ones stay private
        people = {p["name"]: (p["grant"], p["online"]) for p in avi.status()["people"]}
        assert people == {"Dana": ("send", True), "Omer": ("send", True)}
        said.append(shop.say("Deployed."))
        once((dana, omer), shop, said[-1], "after avi restarted")
        nothing_twice((dana, omer), shop, said, "after avi restarted")

    with Phase("dana restarts"):
        dana.restart()
        until("dana links again", lambda: online(dana), 60)
        until("dana sees shop again", lambda: set(dana.sessions(BOX)) == {"shop"}, 20)
        assert dana.machine(BOX)["owner"] == "Avi" and "disclosure" not in dana.status()
        said.append(shop.say("Smoke test green."))
        once((dana, omer), shop, said[-1], "after dana restarted")
        nothing_twice((dana, omer), shop, said, "after dana restarted")

    with Phase("avi removes dana"):
        import json

        kept = next(n for n in json.loads((dana.state / "nodes.json").read_text())["nodes"] if n["name"] == BOX)
        omer_links = to_omer.accepted
        assert avi.post("/voice/people/remove", {"name": "Dana"}) == {"ok": True}
        box = until("dana is told she was removed", lambda: m if (m := dana.machine(BOX)).get("removed") else None)
        assert box["notice"] == f"{BOX} removed you" and box["online"] is False
        now = json.loads((dana.state / "nodes.json").read_text())["nodes"]
        assert [n["key"] for n in now if n["name"] == BOX] == [""]  # her key there is gone from her side too
        until("avi's sessions leave dana", lambda: not dana.sessions(BOX), 20)
        assert "atlas" in dana.sessions()
        links = to_dana.accepted
        code = asyncio.run(dial_with(avi.tls_port, kept["dial"]["fp"], kept["key"], kept["person"], kept["host_id"]))
        assert code == nodelink.CLOSE_UNAUTHORIZED, f"the removed key was answered with {code}"
        said.append(shop.say("Rolled forward."))
        once((omer,), shop, said[-1], "after dana was removed")
        nothing_twice((omer,), shop, said, "after dana was removed")
        assert said[-1] not in dana.mirror(shop.id) and to_dana.accepted == links  # nothing more to her, and no redial
        assert [p["name"] for p in avi.status()["people"]] == ["Omer"]
        assert to_omer.accepted == omer_links and online(omer) and omer.machine(BOX)["grant"] == "send"

    # No call was up on any voice, so no request was ever sent: not to a session online, and not to one offline.
    assert [s.requests() for s in fleet.sessions] == [[] for _ in fleet.sessions]
