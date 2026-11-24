"""The Mac app proves it holds the page key on each request instead of sending it (SECURITY.md, "The Mac app"). A
program that takes the daemon's port while the daemon is down then learns nothing it can use: each proof covers one
request (method, path, query, body), is used once, goes stale, and is bound to the token of the daemon it was made for,
which `bin/voice-daemon` writes anew at every start."""

import hashlib
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
import local_proof  # noqa: E402
from guards import LocalAuth  # noqa: E402

PAGE_KEY, TOKEN = "page-key-of-this-mac", "token-of-this-daemon-start"
NOW = 1_800_000_000


@pytest.fixture
def clock(monkeypatch):
    now = [float(NOW)]
    monkeypatch.setattr(local_proof.time, "time", lambda: now[0])
    return now


@pytest.fixture
def daemon(tmp_path, clock):
    import phone_pairing
    from remote import Remote

    app = FastAPI()
    reached = []

    @app.get("/voice/status")
    def status():
        reached.append("status")
        return {"ok": True}

    @app.post("/voice/approve")
    async def approve(request: Request):
        reached.append(await request.json())
        return {"ok": True}

    @app.websocket("/voice/call")
    async def call(socket: WebSocket):
        await socket.accept()
        await socket.send_text("in")
        await socket.close()

    phones = phone_pairing.Phones(tmp_path)
    phone_pairing.install(app, phone_pairing.PhoneLink(tmp_path, phones), page_key=PAGE_KEY, listener=None)
    app.add_middleware(LocalAuth, token=TOKEN, page_key=PAGE_KEY, remote=Remote(tmp_path), phone=phones.allowed)
    client = TestClient(app, base_url="http://127.0.0.1:7860", follow_redirects=False)
    client.reached = reached
    return client


def proof(method="GET", path="/voice/status", query="", body=b"", *, at=NOW, nonce="0" * 32, token=TOKEN, key=PAGE_KEY):
    return {local_proof.HEADER: local_proof.sign(key, token, at, nonce, method, path, query, body)}


def test_a_fresh_proof_opens_what_the_page_key_opens_and_the_key_never_travels(daemon):
    headers = proof()
    assert PAGE_KEY not in str(headers) and TOKEN not in str(headers)
    assert daemon.get("/voice/status", headers=headers).status_code == 200
    body = b'{"session": "docs", "decision": "allow"}'
    ok = daemon.post("/voice/approve", content=body, headers={**proof("POST", "/voice/approve", body=body, nonce="1" * 32),
                                                               "content-type": "application/json"})
    assert ok.status_code == 200 and daemon.reached[-1] == {"session": "docs", "decision": "allow"}, "the handler reads the body"


def test_a_proof_counts_as_the_page_for_the_routes_only_the_page_on_this_mac_may_use(daemon):
    assert daemon.get("/voice/phone/invite").status_code == 403
    assert daemon.get("/voice/phone/invite", headers=proof(path="/voice/phone/invite")).status_code == 200


def test_the_query_is_covered(daemon):
    headers = proof(path="/voice/status", query="term=Quillfeather")
    assert daemon.get("/voice/status?term=Otherword", headers=headers).status_code == 403
    assert daemon.get("/voice/status?term=Quillfeather", headers=proof(path="/voice/status", query="term=Quillfeather",
                                                                         nonce="2" * 32)).status_code == 200


def test_a_proof_works_once(daemon):
    headers = proof()
    assert daemon.get("/voice/status", headers=headers).status_code == 200
    assert daemon.get("/voice/status", headers=headers).status_code == 403
    assert daemon.reached == ["status"]


@pytest.mark.parametrize("age", [-121, 121, 100_000])
def test_a_stale_proof_is_refused(daemon, age):
    assert daemon.get("/voice/status", headers=proof(at=NOW - age)).status_code == 403
    assert daemon.reached == []


def test_a_proof_for_another_request_is_refused(daemon):
    assert daemon.post("/voice/approve", headers=proof(), json={}).status_code == 403, "made for GET /voice/status"
    body = b'{"session": "docs", "decision": "deny"}'
    other = b'{"session": "docs", "decision": "allow"}'
    refused = daemon.post("/voice/approve", content=other, headers={**proof("POST", "/voice/approve", body=body, nonce="3" * 32),
                                                                     "content-type": "application/json"})
    assert refused.status_code == 403 and daemon.reached == [], "another body: the handler never runs"


def test_a_proof_for_an_earlier_daemon_start_or_without_the_page_key_is_refused(daemon):
    assert daemon.get("/voice/status", headers=proof(token="token-of-the-last-start")).status_code == 403
    assert daemon.get("/voice/status", headers=proof(key="not-the-page-key", nonce="4" * 32)).status_code == 403
    assert daemon.get("/voice/status", headers=proof(key="", token=TOKEN, nonce="5" * 32)).status_code == 403


@pytest.mark.parametrize("value", ["", "v1", "v1.x.y.z.w", f"v2.{NOW}.{'0' * 32}.{'0' * 64}.{'0' * 64}",
                                   f"v1.{NOW}.{'0' * 31}.{hashlib.sha256(b'').hexdigest()}.{'0' * 64}"])
def test_a_malformed_proof_is_refused_and_not_tried_as_a_cookie(daemon, value):
    daemon.cookies.set("pointe_local", PAGE_KEY)
    assert daemon.get("/voice/status", headers={local_proof.HEADER: value}).status_code == 403


def test_the_call_socket_takes_a_proof(daemon):
    base = str(daemon.base_url).replace("http", "ws", 1)
    with daemon.websocket_connect(base + "/voice/call", headers=proof(path="/voice/call")) as socket:
        assert socket.receive_text() == "in"
    with pytest.raises(WebSocketDisconnect):
        with daemon.websocket_connect(base + "/voice/call", headers=proof(path="/voice/call")) as socket:  # used once
            socket.receive_text()


def test_the_swift_builder_and_this_check_agree():
    """The same inputs as LocalProofTests.testTheProofMatchesTheDaemons in apps/PointeKit: one wire format."""
    assert local_proof.sign("k3y", "t0k", 1_800_000_000, "00112233445566778899aabbccddeeff", "POST", "/voice/approve",
                            "term=Quillfeather", b'{"decision":"allow"}') == (
        "v1.1800000000.00112233445566778899aabbccddeeff."
        "6b838faadcc5ae20ac196a2be7bdcf932f9589a14d7ecbcd9d61e5b94c80d03a."
        "dd260863ec4e79d883e572ec444bb0263a82bda16d05f73f35b41415fc3984ff")
