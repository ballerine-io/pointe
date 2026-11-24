"""Phone access: HTTPS + the configured name + a pairing cookie; nothing else from outside localhost."""

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
from remote import COOKIE, Remote  # noqa: E402

HOST = "phone.example.internal"


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

    @app.get("/voice/status")
    def status():
        return {"ok": True}

    return app


def remote_client(app):
    return TestClient(app, base_url=f"https://{HOST}:7443", follow_redirects=False)


def test_localhost_is_unchanged(app):
    assert TestClient(app, base_url="http://127.0.0.1:7860").get("/voice").status_code == 200


def test_remote_needs_pairing(app):
    assert remote_client(app).get("/voice/status").status_code == 403


def test_an_unpaired_phone_browser_is_told_in_words_how_to_pair_again(app):
    """The page shows this text when the phone's browser is no longer paired: words, not "not paired" and a backtick."""
    r = remote_client(app).get("/voice/status")
    assert r.status_code == 403 and "`" not in r.text
    assert r.text.startswith("This browser is no longer paired with the Mac.") and "pointe pair link" in r.text


def test_pairing_link_sets_the_cookie_and_hides_the_secret(app):
    c = remote_client(app)
    r = c.get("/voice?pair=s3cret-token")
    assert r.status_code == 303 and r.headers["location"].startswith("/voice?k=")
    assert "s3cret-token" not in r.headers["location"]
    assert "secure" in r.headers["set-cookie"].lower() and "httponly" in r.headers["set-cookie"].lower()
    assert c.get("/voice/status").status_code == 200


def test_wrong_secret_is_refused(app):
    c = remote_client(app)
    assert c.get("/voice?pair=guess").status_code == 403
    assert c.get("/voice/status", cookies={COOKIE: "guess"}).status_code == 403


def test_forged_host_or_plain_http_is_refused(app):
    cookies = {COOKIE: "s3cret-token"}
    assert TestClient(app, base_url="https://evil.example:7443").get("/voice/status", cookies=cookies).status_code == 403
    assert TestClient(app, base_url=f"http://{HOST}:7860").get("/voice/status", cookies=cookies).status_code == 403
    assert TestClient(app, base_url="https://127.0.0.1:7443").get("/voice/status").status_code == 403


def test_other_page_origin_is_refused(app):
    c = remote_client(app)
    c.cookies.set(COOKIE, "s3cret-token")
    assert c.get("/voice/status", headers={"origin": "https://evil.example"}).status_code == 403
    assert c.get("/voice/status", headers={"origin": f"https://{HOST}:7443"}).status_code == 200


def test_off_when_not_configured(tmp_path):
    remote = Remote(tmp_path)
    app = FastAPI()
    app.middleware("http")(remote.guard)
    app.get("/voice")(lambda: {"ok": True})
    assert not remote.enabled
    assert TestClient(app, base_url=f"https://{HOST}:7443").get("/voice?pair=x").status_code == 403
    assert TestClient(app, base_url="http://localhost:7860").get("/voice").status_code == 200


def test_home_screen_app_key_pairs_without_safari_cookies(app):
    first = remote_client(app)
    key = first.get("/voice?pair=s3cret-token").headers["location"].split("k=")[1]
    fresh = remote_client(app)  # a Home Screen app with its own, empty cookie jar
    r = fresh.get(f"/voice?k={key}")
    assert r.status_code == 200 and "pointe_pair" in r.headers.get("set-cookie", "")
    assert fresh.get("/voice/status").status_code == 200
    assert remote_client(app).get("/voice?k=wrong").status_code == 403


def test_the_listener_takes_no_websocket_message_larger_than_a_node_frame(app, tmp_path, monkeypatch):
    """uvicorn buffers a whole message before any handler checks it (16 MB by default), and /voice/node takes one before
    the node proves its key: the cap is the largest frame the link sends (nodelink.MAX_FRAME_BYTES)."""
    import asyncio

    import nodelink
    import uvicorn

    configs = []

    class Recorded(uvicorn.Config):
        def __init__(self, *args, **kwargs):
            configs.append(kwargs)
            super().__init__(*args, **kwargs)

    async def serve(self, sockets=None):
        return None

    monkeypatch.setattr(uvicorn, "Config", Recorded)
    monkeypatch.setattr(uvicorn.Server, "serve", serve)
    asyncio.run(Remote(tmp_path).serve(app))
    assert configs and all(c.get("ws_max_size") == nodelink.MAX_FRAME_BYTES for c in configs)


def _rotated_remote(tmp_path):
    (tmp_path / "tls").mkdir()
    (tmp_path / "tls" / "cert.pem").write_text("x")
    (tmp_path / "tls" / "key.pem").write_text("x")
    (tmp_path / "remote.json").write_text(json.dumps({"host": HOST}))
    (tmp_path / "remote_token").write_text("old-token")
    remote = Remote(tmp_path)
    app = FastAPI()
    app.middleware("http")(remote.guard)
    app.get("/voice/status")(lambda: {"ok": True})
    client = remote_client(app)
    client.cookies.set(COOKIE, "old-token")
    assert client.get("/voice/status").status_code == 200
    (tmp_path / "remote_token").write_text("new-token-after-rotate")  # `pointe pair rotate` in a terminal
    return remote, client


def test_after_rotate_the_old_browser_cookie_is_refused_at_once(tmp_path):
    """Not at the next liveness round: the owner rotated because the cookie may have leaked."""
    remote, client = _rotated_remote(tmp_path)
    assert client.get("/voice/status").status_code == 403
    assert client.get("/voice/status", cookies={COOKIE: "new-token-after-rotate"}).status_code == 200
    assert remote.changed()  # the liveness round still sees the change, and restarts the listener on the new files


def test_after_rotate_the_old_cookie_opens_no_websocket(tmp_path):
    from types import SimpleNamespace

    remote, _ = _rotated_remote(tmp_path)
    socket_with = lambda token: SimpleNamespace(headers={"host": f"{HOST}:7443"}, cookies={COOKIE: token})  # noqa: E731
    assert not remote.websocket_allowed(socket_with("old-token"))
    assert remote.websocket_allowed(socket_with("new-token-after-rotate"))
    assert remote.changed()


@pytest.mark.parametrize("host", ["evil.example:7443", "", "127.0.0.1:7443", f"{HOST}.evil.example:7443"])
def test_a_websocket_addressed_to_another_name_is_refused_like_a_request(tmp_path, host):
    """HTTP must name the configured host; an upgrade on the same listener too (a rebinding page names its own)."""
    from types import SimpleNamespace

    remote, _ = _rotated_remote(tmp_path)
    token = "new-token-after-rotate"
    assert remote.websocket_allowed(SimpleNamespace(headers={"host": f"{HOST}:7443"}, cookies={COOKIE: token}))
    assert not remote.websocket_allowed(SimpleNamespace(headers={"host": host}, cookies={COOKIE: token}))
