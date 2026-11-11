"""Who may reach the daemon, and which words answer a permission prompt."""

import json
import sys
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


@pytest.mark.parametrize("said", ["no", "don't do that", "לא"])
def test_a_no_denies(said):
    assert permission_answer(said) == "deny"


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


def test_the_phone_key_can_switch_and_hang_up_but_not_read_the_context_or_change_settings(phone_app):
    for path in ("/voice/switch", "/voice/hung-up", "/voice/rename", "/voice/permission"):
        phone_app.post(path)(lambda: {"ok": True})
    phone_app.get("/voice/context")(lambda: {"ok": True})
    key = {"authorization": "Bearer phone-key"}
    for client in (local(phone_app), tls(phone_app)):
        assert client.post("/voice/switch", headers=key, json={}).status_code == 200
        assert client.post("/voice/hung-up", headers=key, json={}).status_code == 200
        for path in ("/voice/rename", "/voice/permission"):
            assert client.post(path, headers=key, json={}).status_code == 403, path
        assert client.get("/voice/context", headers=key).status_code == 403  # the model's whole context stays on the Mac


def test_the_phone_key_can_disconnect_a_session(phone_app):
    phone_app.post("/voice/disconnect")(lambda: {"ok": True})
    for client in (local(phone_app), tls(phone_app)):
        assert client.post("/voice/disconnect", headers={"authorization": "Bearer phone-key"}, json={}).status_code == 200
