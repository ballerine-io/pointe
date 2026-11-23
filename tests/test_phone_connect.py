"""Settings → Phone on the page: which routes reach this Mac, a one-time pairing code in a QR made here, the app trading
it for the phone key over the pinned listener, and Unpair. Who may do each (page cookie only), and what never shows."""

import asyncio
import json
import logging
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from guards import LOCAL_COOKIE, LocalAuth, page_host  # noqa: E402
import hub_nodes  # noqa: E402
from remote import COOKIE, Remote, TLS_PORT  # noqa: E402

HOST = "phone.example.internal"
TS = ("mac.tail1234.ts.net", "100.101.102.103")


class Clock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def pair(tmp_path, monkeypatch):
    import pair as module

    monkeypatch.setattr(module, "STATE", tmp_path)
    monkeypatch.setattr(module, "_tailscale", lambda: TS)
    monkeypatch.setattr(module, "_wifi", lambda: ("192.168.1.20", "192.168.1.20"))
    monkeypatch.setattr(module, "_resolve", lambda host: {"pointe.example.internal": ["100.96.0.7"],
                                                           "loop.example.internal": ["127.0.0.1"],
                                                           "public.example.com": ["93.184.216.34"]}.get(host, []))
    return module


def by_kind(found: dict) -> dict:
    return {(r["kind"], r["host"]): r for r in found["routes"]}


# ---------- which routes reach this Mac ----------

def test_with_nothing_paired_tailscale_is_recommended_over_wifi(pair):
    found = pair.routes()
    routes = by_kind(found)
    assert found["current"] is None and found["advice"] is None
    assert routes[("tailscale", TS[0])]["usable"] and routes[("tailscale", TS[0])]["recommended"]
    assert routes[("tailscale", TS[0])]["listen"] == TS[1]
    assert routes[("wifi", "192.168.1.20")]["usable"] and not routes[("wifi", "192.168.1.20")]["recommended"]
    assert [r["recommended"] for r in found["routes"]].count(True) == 1
    assert all(r["words"] for r in found["routes"])  # each said in plain words
    assert not any(r["new_certificate"] for r in found["routes"])  # nothing is paired yet: nothing to break


def test_the_route_paired_before_is_recommended_and_switching_says_it_makes_a_new_certificate(pair):
    pair.setup("pointe.example.internal", "127.0.0.1")
    found = pair.routes()
    routes = by_kind(found)
    here = routes[("host", "pointe.example.internal")]
    assert found["current"] == "pointe.example.internal"
    assert here["current"] and here["recommended"] and here["usable"] and not here["new_certificate"]
    assert "100.96.0.7" in here["words"]
    assert routes[("tailscale", TS[0])]["new_certificate"]  # the paired phone and machines would have to pair again


def test_a_typed_name_that_resolves_to_a_private_address_is_offered_on_loopback(pair):
    route = by_kind(pair.routes("Pointe.Example.Internal"))[("host", "pointe.example.internal")]
    assert route["usable"] and route["problem"] is None and route["listen"] == "127.0.0.1"


@pytest.mark.parametrize("name,usable,said", [
    ("loop.example.internal", True, "this Mac itself"),
    ("nowhere.example.internal", True, "can't look it up"),
    ("public.example.com", True, "public internet address"),
    ("bad name;rm", False, "not a host name"),
])
def test_a_typed_name_that_does_not_check_out_says_why(pair, name, usable, said):
    found = pair.routes(name)
    route = next(r for r in found["routes"] if r["kind"] == "host")
    assert route["usable"] is usable and said in route["problem"] and not route["recommended"]


def test_with_no_route_the_page_is_told_what_to_install(pair, monkeypatch):
    def no(): raise SystemExit("Tailscale is not running on this Mac.")
    monkeypatch.setattr(pair, "_tailscale", no)
    monkeypatch.setattr(pair, "_wifi", lambda: (_ for _ in ()).throw(SystemExit("No Wi-Fi address found.")))
    found = pair.routes()
    assert not any(r["usable"] for r in found["routes"])
    assert "Tailscale" in found["advice"] and "tailscale.com/download" in found["advice"] and "iPhone" in found["advice"]
    assert by_kind(found)[("tailscale", "")]["problem"] == "Tailscale is not running on this Mac."


def test_a_pairing_code_link_carries_no_lasting_secret(pair, tmp_path):
    pair.setup(HOST, "127.0.0.1")
    from phone import phone_key

    link = pair.invite_pairing_link("ABCD-EFGH")
    query = parse_qs(urlparse(link).query)
    assert link.startswith("pointe://pair?") and query["v"] == ["2"] and query["code"] == ["ABCD-EFGH"]
    assert query["host"] == [HOST] and query["port"] == [str(TLS_PORT)] and query["fp"] == [pair.fingerprint()]
    assert "key" not in query and phone_key(tmp_path) not in link
    assert (tmp_path / "remote_token").read_text() not in link


# ---------- the routes, on a guarded app ----------

class Listener:
    """The TLS listener: a restart is what the page's choice of route does now instead of at the next daemon start."""
    def __init__(self, remote: Remote):
        self.remote, self.restarts = remote, 0

    async def restart(self) -> str | None:
        self.restarts += 1
        self.remote.load()
        return None


@pytest.fixture
def world(tmp_path, pair):
    import phone_pairing

    pair.setup(HOST, "127.0.0.1")
    (tmp_path / "config.json").write_text(json.dumps({"machine": "studio"}))
    remote = Remote(tmp_path)
    app = FastAPI()
    app.middleware("http")(remote.guard)
    app.get("/voice/status")(lambda: {"ok": True})
    clock, mono = Clock(), Clock(5000.0)
    phones = phone_pairing.Phones(tmp_path, clock=clock)
    link = phone_pairing.PhoneLink(tmp_path, phones, monotonic=mono)
    listener = Listener(remote)
    unpaired = []

    async def on_unpair(ids):
        unpaired.append(ids)

    phone_pairing.install(app, link, page_key="page-key", listener=listener, on_unpair=on_unpair)
    app.add_middleware(LocalAuth, token="daemon-token", page_key="page-key", remote=remote, phone=phones.allowed)
    return SimpleNamespace(app=app, phones=phones, link=link, clock=clock, mono=mono, listener=listener,
                           unpaired=unpaired, state=tmp_path, remote=remote, pair=pair)


def page(w):
    client = TestClient(w.app, base_url=f"http://{page_host('page-key')}:7860", follow_redirects=False)
    client.cookies.set(LOCAL_COOKIE, "page-key")
    return client


def local(w):
    return TestClient(w.app, base_url="http://localhost:7860", follow_redirects=False)


def tls(w):
    return TestClient(w.app, base_url=f"https://{HOST}:{TLS_PORT}", follow_redirects=False)


def key_of(w) -> str:
    from phone import phone_key
    return phone_key(w.state)


def make(w, **body) -> dict:
    made = page(w).post("/voice/phone/invite", json={"kind": "host", "host": HOST, **body})
    assert made.status_code == 200, made.text
    return made.json()


def redeem(client, code, **extra):
    return client.post("/voice/phone/pair", json={"code": code, "device": "Mira's iPhone", "id": "dev-1", **extra})


def test_the_page_gets_a_qr_with_a_one_time_code_and_the_app_trades_it_for_the_key(world):
    made = make(world)
    assert made["svg"].startswith("<svg") and made["link"].startswith("pointe://pair?v=2&")
    # the page sizes the code by CSS: a fixed width/height on the svg kept the drawing at 285 px and clipped it
    assert 'viewBox="' in made["svg"] and ' width="' not in made["svg"].split(">", 1)[0]
    assert made["expires_in"] == 300 and parse_qs(urlparse(made["link"]).query)["code"] == [made["code"]]
    got = redeem(tls(world), made["code"])
    assert got.status_code == 200 and got.json()["mac"] == "studio" and len(got.json()["key"]) >= 40
    assert got.json()["key"] not in json.dumps(made)
    assert not (world.state / "phone_key").exists()  # its own key, minted here: no shared key is made or handed out
    assert redeem(tls(world), made["code"]).status_code == 403  # single use
    state = page(world).get("/voice/phone/invite").json()
    assert state["paired"]["name"] == "Mira's iPhone" and state["expires_in"] == 0 and "code" not in state


def test_the_code_expires(world):
    made = make(world)
    world.mono.now += 301
    assert redeem(tls(world), made["code"]).text == hub_nodes.NO_SUCH_INVITE


def test_wrong_codes_are_limited_and_end_the_invite_after_twenty(world):
    make(world)
    codes = [redeem(tls(world), "AAAA-AAAA").status_code for _ in range(6)]
    assert codes[:5] == [403] * 5 and codes[5] == 429
    world.link.invites.wrong = 19
    world.mono.now += 30  # the address has a token again: the limit is checked before the code
    assert redeem(tls(world), "AAAA-AAAA").text == hub_nodes.NO_SUCH_INVITE  # the guesser learns nothing
    assert page(world).get("/voice/phone/invite").json()["ended"].startswith("the invite was cancelled after 20 wrong codes")


def test_a_new_code_replaces_the_old_and_cancel_ends_it(world):
    first, second = make(world), make(world)
    assert redeem(tls(world), first["code"]).status_code == 403
    assert page(world).post("/voice/phone/invite", json={"cancel": True}).json() == {"ok": True}
    assert redeem(tls(world), second["code"]).status_code == 403


def test_the_pair_route_needs_no_secret_but_refuses_a_web_page_and_a_forged_host(world):
    code = make(world)["code"]
    assert redeem(tls(world), "AAAA-AAAA", **{}).status_code == 403  # reaches its own check: "wrong code"
    assert tls(world).post("/voice/phone/pair", json={"code": code},
                           headers={"origin": f"https://{HOST}"}).status_code == 403
    assert TestClient(world.app, base_url="http://evil.example:7860").post(
        "/voice/phone/pair", json={"code": code}).status_code == 403
    assert redeem(tls(world), code).status_code == 200  # the right code still pairs after all that


def test_the_new_key_opens_the_phone_routes(world):
    code = make(world)["code"]
    key = redeem(tls(world), code).json()["key"]
    assert tls(world).get("/voice/status", headers={"authorization": f"Bearer {key}"}).status_code == 200


@pytest.mark.parametrize("method,path", [("get", "/voice/phone/routes"), ("post", "/voice/phone/invite"),
                                         ("get", "/voice/phone/invite"), ("post", "/voice/phone/unpair")])
def test_only_the_page_on_this_mac_reaches_the_owner_routes(world, method, path):
    body = {"json": {"all": True} if path.endswith("unpair") else {"kind": "host", "host": HOST}} if method == "post" else {}
    phone_key = {"authorization": f"Bearer {key_of(world)}"}
    assert getattr(tls(world), method)(path, headers=phone_key, **body).status_code == 403  # the phone app
    assert getattr(local(world), method)(path, headers=phone_key, **body).status_code == 403
    assert getattr(local(world), method)(path, headers={"authorization": "Bearer daemon-token"}, **body).status_code == 403
    remote_page = tls(world)
    remote_page.cookies.set(COOKIE, (world.state / "remote_token").read_text())  # a browser paired over the listener
    assert remote_page.get("/voice/status").status_code == 200  # control: it is let in elsewhere
    assert getattr(remote_page, method)(path, **body).status_code == 403
    remote_page.cookies.set(LOCAL_COOKIE, "page-key")  # even holding the page's own cookie: never over the listener
    assert getattr(remote_page, method)(path, **body).status_code == 403
    assert getattr(local(world), method)(path, **body).status_code == 403  # no secret at all
    assert getattr(page(world), method)(path, **body).status_code == 200  # control: the page on this Mac


def test_the_page_cookie_with_a_foreign_origin_is_refused(world):
    assert page(world).get("/voice/phone/routes", headers={"origin": "http://localhost:3000"}).status_code == 403


def test_the_routes_answer_lists_and_checks_a_typed_name(world):
    found = page(world).get("/voice/phone/routes", params={"host": "loop.example.internal"}).json()
    assert ("host", "loop.example.internal") in by_kind(found) and found["current"] == HOST


def test_choosing_the_current_route_restarts_nothing(world):
    make(world)
    assert world.listener.restarts == 0


def test_choosing_another_route_sets_it_up_and_restarts_the_listener_now(world):
    made = page(world).post("/voice/phone/invite", json={"kind": "tailscale"}).json()
    assert world.listener.restarts == 1 and world.remote.host == TS[0] and world.remote.listen == [TS[1]]
    assert parse_qs(urlparse(made["link"]).query)["host"] == [TS[0]]
    assert json.loads((world.state / "remote.json").read_text()) == {"host": TS[0], "listen": [TS[1]]}


def test_an_unusable_route_is_refused_with_its_reason(world):
    r = page(world).post("/voice/phone/invite", json={"kind": "host", "host": "bad name;rm"})
    assert r.status_code == 409 and "not a host name" in r.text and world.listener.restarts == 0


def test_a_listener_that_cannot_start_makes_no_code(world):
    async def fails():
        return "could not listen on 100.101.102.103:7443"
    world.listener.restart = fails
    r = page(world).post("/voice/phone/invite", json={"kind": "tailscale"})
    assert r.status_code == 409 and "could not listen" in r.text and world.link.invites.code is None


# ---------- paired phones: one key each, last seen, unpair ----------

def phone(w, device="Mira's iPhone", device_id="dev-1") -> tuple[str, str]:
    """Pair a phone: (its key, its id on the Mac)."""
    key = redeem(tls(w), make(w)["code"], device=device, id=device_id).json()["key"]
    entry = next(p for p in w.phones.status()["paired"] if p["name"] == device)
    return key, entry["id"]


def status_with(w, key: str) -> int:
    return tls(w).get("/voice/status", headers={"authorization": f"Bearer {key}"}).status_code


def test_a_paired_phone_is_listed_online_then_last_seen(world):
    assert world.phones.status() == {"paired": []}
    key, _ = phone(world)
    status_with(world, key)
    [entry] = world.phones.status()["paired"]
    assert entry["name"] == "Mira's iPhone" and entry["online"] and entry["last_seen"] == world.clock.now
    assert not entry["legacy"] and key not in json.dumps(entry)
    world.clock.now += 60
    assert not world.phones.status()["paired"][0]["online"]


def test_each_phone_gets_its_own_key_and_both_work(world):
    first, a = phone(world)
    second, b = phone(world, "iPad", "dev-2")
    assert first != second and a != b
    assert status_with(world, first) == status_with(world, second) == 200
    assert [p["name"] for p in world.phones.status()["paired"]] == ["Mira's iPhone", "iPad"]


def test_pairing_the_same_phone_again_replaces_its_entry_and_retires_its_old_key(world):
    old, _ = phone(world)
    new, _ = phone(world)
    assert status_with(world, old) == 403 and status_with(world, new) == 200
    assert [p["name"] for p in world.phones.status()["paired"]] == ["Mira's iPhone"]


def test_unpair_one_signs_out_only_that_phone_and_ends_only_its_call(world):
    first, a = phone(world)
    second, b = phone(world, "iPad", "dev-2")
    assert page(world).post("/voice/phone/unpair", json={"id": a}).json() == {"ok": True}
    assert status_with(world, first) == 403  # at once
    assert status_with(world, second) == 200  # the other stays connected
    assert [p["id"] for p in world.phones.status()["paired"]] == [b] and world.unpaired == [{a}]
    assert page(world).post("/voice/phone/unpair", json={"id": a}).status_code == 404


def test_unpair_all_signs_out_every_phone_and_the_legacy_key(world):
    legacy = key_of(world)
    first, _ = phone(world)
    second, _ = phone(world, "iPad", "dev-2")
    assert page(world).post("/voice/phone/unpair", json={"all": True}).json() == {"ok": True}
    assert [status_with(world, k) for k in (legacy, first, second)] == [403, 403, 403]
    assert world.phones.status() == {"paired": []} and world.unpaired == [None]
    assert not (world.state / "phone_key").exists()


def test_the_shared_key_from_before_is_one_legacy_phone_until_it_reports_its_name(world):
    legacy = key_of(world)  # `pointe pair` made it before the upgrade: the owner's iPhone holds it
    [entry] = world.phones.status()["paired"]
    assert entry == {**entry, "id": "legacy", "name": "Paired phone", "legacy": True, "last_seen": None}
    assert status_with(world, legacy) == 200  # not signed out by the upgrade
    world.phones.report("legacy", "Mira’s iPhone")
    world.phones.report("legacy", "someone else")  # named once: a later report does not rename it
    assert world.phones.status()["paired"][0]["name"] == "Mira’s iPhone"
    assert world.phones.status()["paired"][0]["online"]


def test_a_minted_phone_is_never_renamed_by_a_report(world):
    _, a = phone(world)
    world.phones.report(a, "renamed")
    assert world.phones.status()["paired"][0]["name"] == "Mira's iPhone"


def test_unpair_the_legacy_phone_deletes_the_shared_key_and_pointe_pair_show_mints_a_new_one(world):
    legacy = key_of(world)
    other, _ = phone(world)
    assert page(world).post("/voice/phone/unpair", json={"id": "legacy"}).json() == {"ok": True}
    assert status_with(world, legacy) == 403 and status_with(world, other) == 200
    assert world.unpaired == [{"legacy"}]
    link = world.pair.pairing_link()  # `pointe pair show`: the old v1 link carries the legacy key, made again
    fresh = parse_qs(urlparse(link).query)["key"][0]
    assert fresh != legacy and status_with(world, fresh) == 200
    assert [p["id"] for p in world.phones.status()["paired"]][-1] == "legacy"


def test_every_key_is_compared_in_constant_time_with_no_early_exit(world, monkeypatch):
    import phone_pairing

    key_of(world)
    first, _ = phone(world)
    phone(world, "iPad", "dev-2")
    calls = []
    real = phone_pairing.hmac.compare_digest
    monkeypatch.setattr(phone_pairing.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    assert world.phones.allowed(f"Bearer {first}")
    assert len(calls) == 3  # both minted keys and the legacy one, though the first already matched
    calls.clear()
    assert not world.phones.allowed("Bearer " + "x" * 43) and len(calls) == 3


@pytest.mark.parametrize("bad", [None, "", "Bearer ", "Bearer  ", "Basic abc", "bearer abc"])
def test_no_key_or_a_malformed_header_opens_nothing(world, bad):
    phone(world)
    assert not world.phones.allowed(bad)


def test_a_device_name_is_cut_and_cleaned(world):
    redeem(tls(world), make(world)["code"], device="evil\x1b[31m\n" + "x" * 200)
    name = world.phones.status()["paired"][0]["name"]
    assert "\x1b" not in name and "\n" not in name and len(name) <= 60


def test_the_phones_file_is_private_and_holds_only_hashes(world):
    import hashlib

    key, _ = phone(world)
    path = world.state / "phones.json"
    stored = path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and key not in stored
    assert hashlib.sha256(key.encode()).hexdigest() in stored


def test_unpair_survives_a_restart(world):
    import phone_pairing

    first, a = phone(world)
    second, _ = phone(world, "iPad", "dev-2")
    page(world).post("/voice/phone/unpair", json={"id": a})
    again = phone_pairing.Phones(world.state, clock=world.clock)
    assert not again.allowed(f"Bearer {first}") and again.allowed(f"Bearer {second}")


def test_no_code_link_or_key_reaches_the_log(world, caplog):
    from loguru import logger

    handler = logger.add(lambda m: caplog.handler.emit(logging.makeLogRecord({"msg": str(m), "levelno": 20})))
    try:
        made = make(world)
        redeem(tls(world), "AAAA-AAAA")
        key = redeem(tls(world), made["code"]).json()["key"]
    finally:
        logger.remove(handler)
    text = caplog.text
    assert "phone paired" in text and "Mira's iPhone" in text  # control: the log does see the pairing
    for secret in (made["code"], made["code"].replace("-", ""), made["link"], key):
        assert secret not in text


# ---------- the real listener: a route chosen on the page is served at once ----------

def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _served_fingerprint(port: int) -> str:
    import hashlib
    import ssl

    pem = ssl.get_server_certificate(("127.0.0.1", port), timeout=3)
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()


def test_restart_serves_the_new_certificate_now_and_frees_the_port(pair, tmp_path, monkeypatch):
    import socket

    import remote as remote_module

    port = _free_port()
    monkeypatch.setattr(remote_module, "TLS_PORT", port)
    pair.setup("first.example.internal", "127.0.0.1")
    first = pair.fingerprint()
    listener = Remote(tmp_path)
    app = FastAPI()

    async def scenario():
        listener.start(app)
        for _ in range(50):
            if listener._servers and all(s.started for s in listener._servers):
                break
            await asyncio.sleep(0.1)
        before = await asyncio.to_thread(_served_fingerprint, port)
        pair.setup("second.example.internal", "127.0.0.1")
        problem = await listener.restart()
        after = await asyncio.to_thread(_served_fingerprint, port)
        await listener.stop()
        return before, problem, after

    before, problem, after = asyncio.run(scenario())
    assert (before, problem) == (first, None)
    assert after == pair.fingerprint() != first and listener.host == "second.example.internal"
    with socket.socket() as s:  # stopped means the port is free, not just the task gone
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))


def test_restart_says_why_when_the_port_is_taken(pair, tmp_path, monkeypatch):
    import socket

    import remote as remote_module

    port = _free_port()
    monkeypatch.setattr(remote_module, "TLS_PORT", port)
    pair.setup("first.example.internal", "127.0.0.1")
    listener = Remote(tmp_path)
    squatter = socket.socket()
    squatter.bind(("127.0.0.1", port))
    squatter.listen()
    try:
        async def scenario():
            listener._app = FastAPI()
            return await listener.restart()

        problem = asyncio.run(scenario())
    finally:
        squatter.close()
    assert problem and "could not listen on 127.0.0.1" in problem and listener._task is None


# ---------- the daemon wires it (integration) ----------

from test_orchestrator import d  # noqa: E402,F401  (a fixture)


def test_the_daemon_installs_the_phone_routes_and_reports_phones_in_status(d):
    paths = {getattr(r, "path", None) for r in d.app.routes}
    assert {"/voice/phone/pair", "/voice/phone/routes", "/voice/phone/invite", "/voice/phone/unpair"} <= paths
    key = d.phone.phone_key(d.STATE_DIR)  # the shared key from before: one legacy phone
    client = TestClient(d.app, base_url="http://127.0.0.1:7860")
    headers = {"authorization": f"Bearer {key}", "x-pointe-device": "Mira%E2%80%99s%20iPhone"}
    status = client.get("/voice/status", headers=headers).json()
    [entry] = [p for p in status["phones"]["paired"] if p["id"] == "legacy"]
    assert entry["online"] is True and entry["name"] == "Mira’s iPhone"  # seen, and named by the app's report
    assert key not in json.dumps(status)


def test_the_daemon_refuses_the_phone_key_and_daemon_token_on_the_owner_routes(d):
    client = TestClient(d.app, base_url="http://127.0.0.1:7860")
    for headers in ({"authorization": f"Bearer {d.phone.phone_key(d.STATE_DIR)}"},
                    {"authorization": f"Bearer {d.TOKEN}"}):
        assert client.get("/voice/phone/routes", headers=headers).status_code == 403
        assert client.post("/voice/phone/unpair", headers=headers, json={}).status_code == 403
    page_client = TestClient(d.app, base_url="http://127.0.0.1:7860", cookies={"pointe_local": d.PAGE_KEY})
    assert page_client.get("/voice/phone/invite").status_code == 200  # control


def test_the_daemon_ends_only_the_unpaired_phones_call(d, monkeypatch):
    closed = []

    class Socket:
        async def close(self, code, reason):
            closed.append(code)

    monkeypatch.setattr(d.state, "phone_socket", Socket())
    monkeypatch.setattr(d.state, "phone_socket_id", "aaa")
    asyncio.run(d._end_phone_call({"bbb"}))
    assert closed == []  # another phone was unpaired: this call stays up
    asyncio.run(d._end_phone_call({"aaa"}))
    asyncio.run(d._end_phone_call(None))
    assert closed == [4401, 4401]
