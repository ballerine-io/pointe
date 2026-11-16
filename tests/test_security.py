"""Who may reach the daemon, and which words answer a permission prompt."""

import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from guards import LOCAL_COOKIE, LocalAuth, page_host, permission_answer  # noqa: E402
from remote import COOKIE, Remote, TLS_PORT  # noqa: E402

HOST = "phone.example.internal"


@pytest.mark.parametrize("said", ["yes", "yes please", "go ahead", "okay, do it", "כן", "no problem"])
def test_a_plain_yes_approves(said):
    assert permission_answer(said) == "allow"


@pytest.mark.parametrize("said", ["yeah the weather is really nice today", "okay let me think about that one", "is it ok",
                                  "sure, what time is the meeting", "yeah and the weather is nice today",
                                  "okay, tell me more", "ok say that again", "okay hold on", "ok let me think", "yes but later",
                                  "okay but first explain", "okay thanks", "okay what's that", "allow me to explain",
                                  "go ahead and tell me what it does", "go ahead and deploy it", "בסדר תסביר",
                                  "yes, and then run the linter"])
def test_unrelated_speech_never_approves(said):
    assert permission_answer(said) is None


@pytest.mark.parametrize("said", ["no", "don't do that", "לא", "no, ask it to wait", "no, and tell it to stop"])
def test_a_no_denies(said):
    assert permission_answer(said) == "deny"


@pytest.mark.parametrize("said", ['Ask Claude Code to create an empty file called "denied.txt".',
                                  "ask hooked to stop the dev server", "tell it to cancel the old build"])
def test_a_no_word_inside_a_new_request_answers_nothing(said):
    """From the hook-mode run on 1.13.2: with a prompt pending, "Ask Claude Code to create an empty file called
    denied.txt" denied it: "denied" was a file name in a new request, not the user's answer."""
    assert permission_answer(said) is None


@pytest.fixture
def app(tmp_path):
    (tmp_path / "tls").mkdir()
    (tmp_path / "tls" / "cert.pem").write_text("x")
    (tmp_path / "tls" / "key.pem").write_text("x")
    (tmp_path / "remote.json").write_text(json.dumps({"host": HOST}))
    (tmp_path / "remote_token").write_text("s3cret-token")
    remote = Remote(tmp_path)
    app = FastAPI()
    app.middleware("http")(remote.guard)

    @app.get("/voice")
    def page():
        return {"ok": True}

    @app.get("/voice/health")
    def health():
        return {"ok": True}

    @app.post("/api/offer")
    def offer():
        return {"ok": True}

    @app.get("/voice/status")
    def status():
        return {"connected": True}

    @app.websocket("/ws")
    async def ws(socket):
        await socket.accept()
        await socket.close()

    app.add_middleware(LocalAuth, token="daemon-token", page_key="page-key", remote=remote)
    return app


def local(app):
    return TestClient(app, base_url="http://localhost:7860", follow_redirects=False)


def page(app):
    return TestClient(app, base_url=f"http://{page_host('page-key')}:7860", follow_redirects=False)


@pytest.mark.parametrize("method,path", [("get", "/voice/status"), ("post", "/api/offer")])
def test_no_secret_no_access(app, method, path):
    assert getattr(local(app), method)(path).status_code == 403


def test_the_cookie_is_never_set_on_plain_localhost(app):
    """Cookies ignore ports: on "localhost" it would reach any server the user opens on another port."""
    r = local(app).get("/voice?key=page-key")
    assert r.status_code == 303 and "set-cookie" not in r.headers
    assert r.headers["location"] == f"http://{page_host('page-key')}:7860/voice?key=page-key"


def test_an_empty_secret_opens_nothing(app):
    guarded = LocalAuth(FastAPI(), "", "")
    client = TestClient(guarded, base_url="http://localhost:7860")
    assert client.get("/voice/status").status_code == 403
    assert client.get("/voice/status", headers={"authorization": "Bearer "}).status_code == 403


def test_page_link_sets_a_cookie_and_hides_the_key(app):
    client = page(app)
    r = client.get("/voice?key=page-key")
    assert r.status_code == 303 and r.headers["location"] == "/voice" and "page-key" not in r.headers["location"]
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
    assert client.get("/voice/status").status_code == 200
    assert client.post("/api/offer").status_code == 200


def test_wrong_page_key_is_refused(app):
    assert local(app).get("/voice?key=nope").status_code == 403


def test_the_page_without_a_key_says_how_to_open_it(app):
    r = local(app).get("/voice")
    assert r.status_code == 403 and "voice-open" in r.text


def test_scripts_use_the_daemon_token(app):
    assert local(app).get("/voice/status", headers={"Authorization": "Bearer daemon-token"}).status_code == 200
    assert local(app).get("/voice/status", headers={"Authorization": "Bearer nope"}).status_code == 403


def test_health_says_nothing_and_needs_nothing(app):
    assert local(app).get("/voice/health").status_code == 200


def test_another_localhost_port_is_another_site(app):
    client = page(app)
    client.get("/voice?key=page-key")
    assert client.get("/voice/status", headers={"Origin": "http://localhost:3000"}).status_code == 403
    assert client.get("/voice/status", headers={"Origin": f"http://{page_host('page-key')}:7860"}).status_code == 200


def test_page_cannot_be_framed(app):
    client = page(app)
    client.get("/voice?key=page-key")
    assert "frame-ancestors 'self'" in client.get("/voice").headers["content-security-policy"]


def test_websocket_needs_a_secret_and_a_matching_origin(app):
    with pytest.raises(WebSocketDisconnect):
        with local(app).websocket_connect("/ws"):
            pass
    client = local(app)
    client.cookies.set(LOCAL_COOKIE, "page-key")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"Origin": "http://evil.example", "Host": "localhost:7860"}):
            pass


def tls(app):
    return TestClient(app, base_url=f"https://{HOST}:{TLS_PORT}", follow_redirects=False)


def test_a_forged_scheme_or_host_on_the_phone_listener_is_refused(app):
    assert tls(app).get("/voice/status", headers={"Host": "localhost", "X-Forwarded-Proto": "http"}).status_code == 403
    assert tls(app).get("/voice/status", headers={"Host": "localhost"}).status_code == 403


def test_a_paired_phone_still_works(app):
    client = tls(app)
    client.cookies.set(COOKIE, "s3cret-token")
    assert client.get("/voice/status").status_code == 200


@pytest.fixture
def phone_app(tmp_path):
    (tmp_path / "remote.json").write_text(json.dumps({"host": HOST}))
    (tmp_path / "remote_token").write_text("s3cret-token")
    remote = Remote(tmp_path)
    app = FastAPI()
    app.middleware("http")(remote.guard)

    @app.websocket("/voice/phone")
    async def phone(socket: WebSocket):
        await socket.accept()
        await socket.send_text("in")
        await socket.close()

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        await socket.accept()
        await socket.send_text("in")
        await socket.close()

    @app.post("/voice/register")
    def register():
        return {"ok": True}

    app.add_middleware(LocalAuth, token="daemon-token", page_key="page-key", remote=remote,
                       phone=lambda authorization: authorization == "Bearer phone-key")
    return app


def _phone_gets_in(client, path="/voice/phone", **headers) -> bool:
    from starlette.websockets import WebSocketDisconnect
    base = str(client.base_url).replace("http", "ws", 1)  # a bare path would go to "testserver"
    try:
        with client.websocket_connect(base + path, headers=headers) as socket:
            return socket.receive_text() == "in"
    except WebSocketDisconnect:
        return False


def test_the_phone_key_opens_the_phone_socket(phone_app):
    assert _phone_gets_in(local(phone_app), authorization="Bearer phone-key")
    assert _phone_gets_in(tls(phone_app), authorization="Bearer phone-key")


@pytest.mark.parametrize("auth", [None, "Bearer wrong", "Bearer daemon-token", "Bearer page-key"])
def test_no_other_secret_opens_the_phone_socket(phone_app, auth):
    headers = {"authorization": auth} if auth else {}
    assert not _phone_gets_in(local(phone_app), **headers)
    assert not _phone_gets_in(tls(phone_app), **headers)


def test_the_phone_key_opens_nothing_else(phone_app):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with local(phone_app).websocket_connect("ws://localhost:7860/ws", headers={"authorization": "Bearer phone-key"}) as s:
            s.receive_text()
    assert _phone_gets_in(local(phone_app), "/ws", authorization="Bearer daemon-token")  # control: the route works
    assert local(phone_app).post("/voice/register", headers={"authorization": "Bearer phone-key"}).status_code == 403


def test_a_forged_host_cannot_use_the_phone_key_off_the_tls_listener(phone_app):
    client = TestClient(phone_app, base_url="http://evil.example:7860")
    assert not _phone_gets_in(client, authorization="Bearer phone-key")


def test_the_phone_key_reaches_status_and_approve_but_nothing_else(phone_app):
    @phone_app.get("/voice/status")
    def status():
        return {"ok": True}

    @phone_app.post("/voice/approve")
    def approve():
        return {"ok": True}

    key = {"authorization": "Bearer phone-key"}
    for client in (local(phone_app), tls(phone_app)):
        assert client.get("/voice/status", headers=key).status_code == 200
        assert client.post("/voice/approve", headers=key, json={}).status_code == 200
        assert client.post("/voice/register", headers=key).status_code == 403
        assert client.get("/voice/status").status_code == 403


def test_the_phone_key_can_switch_hang_up_and_rename_but_not_read_the_context_or_change_settings(phone_app):
    for path in ("/voice/switch", "/voice/hung-up", "/voice/rename", "/voice/permission"):
        phone_app.post(path)(lambda: {"ok": True})
    phone_app.get("/voice/context")(lambda: {"ok": True})
    key = {"authorization": "Bearer phone-key"}
    for client in (local(phone_app), tls(phone_app)):
        assert client.post("/voice/switch", headers=key, json={}).status_code == 200
        assert client.post("/voice/hung-up", headers=key, json={}).status_code == 200
        assert client.post("/voice/rename", headers=key, json={}).status_code == 200  # the app renames a session, as the page
        assert client.post("/voice/permission", headers=key, json={}).status_code == 403
        assert client.get("/voice/context", headers=key).status_code == 403  # the model's whole context stays on the Mac


def test_the_phone_key_can_disconnect_a_session(phone_app):
    phone_app.post("/voice/disconnect")(lambda: {"ok": True})
    for client in (local(phone_app), tls(phone_app)):
        assert client.post("/voice/disconnect", headers={"authorization": "Bearer phone-key"}, json={}).status_code == 200


# ---------- machines: the node link's routes (docs/design/multi-machine.md, "Authentication") ----------

@pytest.fixture
def node_app(phone_app):
    @phone_app.websocket("/voice/node")
    async def node(socket: WebSocket):  # the real handler authenticates by HMAC over its own nonce
        await socket.accept()
        await socket.send_text("in")
        await socket.close()

    @phone_app.post("/voice/node/pair")
    def pair():  # the real handler checks the invite code
        return {"ok": True}

    return phone_app


def test_the_node_socket_reaches_its_own_check_with_no_page_or_phone_secret(node_app):
    assert _phone_gets_in(tls(node_app), "/voice/node")
    assert _phone_gets_in(local(node_app), "/voice/node")  # loopback, for tests and two simulated machines


def test_the_pair_route_reaches_its_own_check_with_no_pairing_cookie(node_app):
    assert tls(node_app).post("/voice/node/pair", json={}).status_code == 200
    assert local(node_app).post("/voice/node/pair", json={}).status_code == 200


def test_the_node_routes_refuse_a_forged_host_off_the_tls_listener(node_app):
    client = TestClient(node_app, base_url="http://evil.example:7860")
    assert not _phone_gets_in(client, "/voice/node")
    assert client.post("/voice/node/pair", json={}).status_code == 403


def test_the_node_routes_refuse_a_web_page(node_app):
    page_origin = {"origin": f"https://{HOST}"}
    assert not _phone_gets_in(tls(node_app), "/voice/node", **page_origin)  # a node is never a page
    assert tls(node_app).post("/voice/node/pair", json={}, headers=page_origin).status_code == 403


def test_each_node_route_takes_only_its_own_kind_of_connection(node_app):
    for client in (tls(node_app), local(node_app)):
        assert client.get("/voice/node").status_code == 403
        assert not _phone_gets_in(client, "/voice/node/pair")


def test_the_node_routes_open_nothing_else(node_app):
    assert tls(node_app).get("/voice/status").status_code == 403
    assert local(node_app).post("/voice/register").status_code == 403


# ---------- machines: the real node handlers (hub_nodes.py) ----------

@pytest.fixture
def hub_app(tmp_path, monkeypatch):
    import hub_nodes
    import nodelink
    from sessions import Registry

    monkeypatch.setattr(nodelink, "PING_SECS", 3600.0)
    (tmp_path / "tls").mkdir()
    (tmp_path / "tls" / "cert.pem").write_text("x")  # enabled, so a paired browser over TLS passes Remote.guard
    (tmp_path / "tls" / "key.pem").write_text("x")
    (tmp_path / "remote.json").write_text(json.dumps({"host": HOST}))
    (tmp_path / "remote_token").write_text("s3cret-token")
    remote = Remote(tmp_path)
    app = FastAPI()
    app.middleware("http")(remote.guard)
    app.get("/voice/status")(lambda: {"ok": True})
    hub = hub_nodes.Hub(tmp_path, Registry(), SimpleNamespace())
    hub_nodes.install(app, hub, link=lambda code: f"pointe://hub?code={code}")
    app.add_middleware(LocalAuth, token="daemon-token", page_key="page-key", remote=remote,
                       phone=lambda authorization: authorization == "Bearer phone-key")
    app.state.hub = hub
    return app


def _node_close_code(client, key: str, node_id: str, **headers) -> int | None:
    """Connect as a node with this key; the hub's close code, or None if it welcomed us."""
    import nodelink

    base = str(client.base_url).replace("http", "ws", 1)
    try:
        with client.websocket_connect(base + "/voice/node", headers=headers) as socket:
            challenge = json.loads(socket.receive_text())
            auth = nodelink.answer(key, challenge["nonce"], challenge["hub"]["id"]) if key else "00"
            socket.send_text(nodelink.encode("hello", protocol=1, auth=auth, now=0.0, node={
                "id": node_id, "name": "devbox", "os": "linux", "arch": "arm64", "version": "1", "harnesses": []}))
            frame = json.loads(socket.receive_text())
            return None if frame["t"] == "welcome" else -1
    except WebSocketDisconnect as e:
        return e.code


def test_the_node_socket_needs_the_hmac_and_no_other_secret_opens_it(hub_app):
    hub = hub_app.state.hub
    node = hub.nodes.add("devbox", "linux")
    assert _node_close_code(tls(hub_app), node["key"], node["id"]) is None  # control: the right key gets in
    assert _node_close_code(tls(hub_app), "cd" * 32, node["id"]) == 4401
    assert _node_close_code(local(hub_app), "", node["id"], authorization="Bearer phone-key") == 4401
    assert _node_close_code(local(hub_app), "", node["id"], authorization="Bearer daemon-token") == 4401
    page = local(hub_app)
    page.cookies.set(LOCAL_COOKIE, "page-key")
    assert _node_close_code(page, "", node["id"]) == 4401


def test_the_real_node_socket_refuses_a_forged_host_on_loopback(hub_app):
    node = hub_app.state.hub.nodes.add("devbox", "linux")
    assert _node_close_code(TestClient(hub_app, base_url="http://evil.example:7860"), node["key"], node["id"]) == 1008


def test_a_revoked_key_gets_4401(hub_app):
    import asyncio

    hub = hub_app.state.hub
    node = hub.nodes.add("devbox", "linux")
    asyncio.run(hub.revoke("devbox"))
    assert _node_close_code(tls(hub_app), node["key"], node["id"]) == 4401


def _pair(client, code, name="devbox"):
    return client.post("/voice/node/pair", json={"code": code, "name": name, "os": "linux", "arch": "x86_64",
                                                 "version": "1.0.1"})


def test_pairing_needs_an_outstanding_invite_and_the_right_code_once(hub_app):
    hub = hub_app.state.hub
    assert _pair(tls(hub_app), "AAAA-AAAA").status_code == 403  # no invite: closed
    code = hub.invites.make()
    wrong = _pair(tls(hub_app), "AAAA-AAAA" if code != "AAAA-AAAA" else "BBBB-BBBB")
    assert wrong.status_code == 403 and wrong.text == "wrong code"
    good = _pair(tls(hub_app), code)
    assert good.status_code == 200 and len(good.json()["node_key"]) == 64
    assert _pair(tls(hub_app), code, "other").status_code == 403  # single use


def test_pairing_answers_five_attempts_a_minute_from_one_address(hub_app):
    hub_app.state.hub.invites.make()
    codes = [_pair(tls(hub_app), "AAAA-AAAA").status_code for _ in range(6)]
    assert codes[:5] == [403] * 5 and codes[5] == 429


def test_the_invite_routes_take_the_page_or_the_daemon_token_but_not_a_page_over_the_tls_listener(hub_app):
    assert local(hub_app).post("/voice/hub/invite", json={}).status_code == 403  # no secret
    made = local(hub_app).post("/voice/hub/invite", json={}, headers={"authorization": "Bearer daemon-token"})
    assert made.status_code == 200 and made.json()["link"].startswith("pointe://hub?code=")
    remote_page = tls(hub_app)
    remote_page.cookies.set(COOKIE, "s3cret-token")  # a browser paired over the TLS listener: not shown the code
    assert remote_page.get("/voice/status").status_code == 200  # control: it is paired
    for method, path in (("post", "/voice/hub/invite"), ("get", "/voice/hub/invite"), ("get", "/voice/hub/nodes"),
                         ("post", "/voice/hub/revoke")):
        assert getattr(remote_page, method)(path, **({"json": {}} if method == "post" else {})).status_code == 403
    page = TestClient(hub_app, base_url=f"http://{page_host('page-key')}:7860")
    page.cookies.set(LOCAL_COOKIE, "page-key")
    assert page.get("/voice/hub/invite").json()["code"] == made.json()["code"]


def test_mirrors_are_private(hub_app, tmp_path):
    hub = hub_app.state.hub
    node = hub.nodes.add("devbox", "linux")
    hub.mirrors.append(node["id"], {"id": "s1", "gen": 0, "offset": 0, "next_offset": 3, "entries": ["{}\n"]})
    mirror = tmp_path / "harness" / "remote" / node["id"] / "s1.0.jsonl"
    assert mirror.with_name("s1.0.jsonl.part").stat().st_mode & 0o077 == 0  # a new session's backlog, first
    hub.mirrors.promote(node["id"], "s1")
    assert mirror.stat().st_mode & 0o077 == 0 and mirror.parent.stat().st_mode & 0o077 == 0
    assert (tmp_path / "nodes.json").stat().st_mode & 0o077 == 0


def test_the_not_paired_page_points_at_pointe_pair_link(app):
    r = tls(app).get("/voice/status")
    assert r.status_code == 403 and "pointe pair link" in r.text and "voice-remote" not in r.text


def test_the_phone_key_reaches_the_machines_routes_over_the_tls_listener_and_here(hub_app):
    key = {"authorization": "Bearer phone-key"}
    for client in (tls(hub_app), local(hub_app)):
        made = client.post("/voice/hub/invite", json={}, headers=key)
        assert made.status_code == 200 and made.json()["code"]  # the app shows the one-time code (behind Face ID)
        assert client.get("/voice/hub/invite", headers=key).json()["code"] == made.json()["code"]
        assert client.get("/voice/hub/nodes", headers=key).json() == {"nodes": []}
        assert client.post("/voice/hub/revoke", headers=key, json={"name": "nobody"}).status_code == 404  # reached it
        assert client.post("/voice/hub/invite", json={}).status_code == 403  # no key: no code


def test_the_phone_key_gained_the_three_machines_routes_and_nothing_else():
    from guards import _PHONE_PATHS

    before = {"/voice/phone", "/voice/approve", "/voice/status", "/voice/listen", "/voice/switch", "/voice/hung-up",
              "/voice/disconnect", "/voice/rename", "/voice/mode", "/voice/say", "/voice/correct", "/voice/polish",
              "/voice/meeting", "/voice/meeting/transcript", "/voice/notes", "/voice/prefs", "/voice/attention",
              "/voice/voiceprint", "/voice/artifact", "/voice/briefings", "/voice/briefings/latest",
              "/voice/briefings/schedule", "/voice/conflicts", "/voice/dictionary", "/voice/challenge", "/voice/drive",
              "/voice/dump"}
    assert _PHONE_PATHS - before == {"/voice/hub/invite", "/voice/hub/nodes", "/voice/hub/revoke"}
    assert before <= _PHONE_PATHS


def test_the_phone_key_still_cannot_pair_a_node_or_open_the_node_socket(hub_app):
    key = {"authorization": "Bearer phone-key"}
    hub = hub_app.state.hub
    node = hub.nodes.add("devbox", "linux")
    assert _node_close_code(tls(hub_app), "", node["id"], **key) == 4401  # the HMAC, never the phone key
    assert _pair(tls(hub_app), "AAAA-AAAA").status_code == 403  # no invite: the phone key opens no pairing
