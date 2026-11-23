"""The two pairing routes take no secret, so anyone who reaches the phone listener can post to them. They answer before
reading a byte when no invite is out, and never read more than a pairing's few hundred bytes when one is."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROUTES = ["/voice/node/pair", "/voice/phone/pair"]


@pytest.fixture
def world(tmp_path, monkeypatch):
    import hub_nodes
    import nodelink
    import phone_pairing
    from sessions import Registry

    monkeypatch.setattr(nodelink, "PING_SECS", 3600.0)
    app = FastAPI()
    hub = hub_nodes.Hub(tmp_path, Registry(), SimpleNamespace())
    hub_nodes.install(app, hub, link=lambda code: f"pointe://hub?code={code}")
    link = phone_pairing.PhoneLink(tmp_path, phone_pairing.Phones(tmp_path))
    phone_pairing.install(app, link, page_key="page-key", listener=None)
    invites = {"/voice/node/pair": hub.invites, "/voice/phone/pair": link.invites}
    return SimpleNamespace(app=app, invites=invites)


def post(app, path: str, chunks: list[bytes], length: int | None = None) -> tuple[int, int]:
    """(status, bytes the app took from the client): the body arrives in `chunks`, as a client streams it."""
    taken, queue, sent = [], list(chunks), []

    async def receive():
        if queue:
            chunk = queue.pop(0)
            taken.append(len(chunk))
            return {"type": "http.request", "body": chunk, "more_body": bool(queue)}
        await asyncio.sleep(3600)  # a client still sending

    async def send(message):
        sent.append(message)

    headers = [(b"host", b"studio.example.internal:7443"), (b"content-type", b"application/json")]
    if length is not None:
        headers.append((b"content-length", str(length).encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "https",
             "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "", "headers": headers,
             "client": ("10.0.0.9", 50000), "server": ("10.0.0.1", 7443)}
    asyncio.run(asyncio.wait_for(app(scope, receive, send), 10))
    return next(m["status"] for m in sent if m["type"] == "http.response.start"), sum(taken)


@pytest.mark.parametrize("path", ROUTES)
def test_with_no_invite_out_the_route_answers_before_reading_the_body(world, path):
    status, taken = post(world.app, path, [b"x" * 65536] * 16, length=65536 * 16)
    assert status == 403 and taken == 0


@pytest.mark.parametrize("path", ROUTES)
def test_a_declared_body_over_the_cap_is_refused_unread(world, path):
    world.invites[path].make()
    status, taken = post(world.app, path, [b"x" * 65536] * 16, length=65536 * 16)
    assert status == 413 and taken == 0


@pytest.mark.parametrize("path", ROUTES)
def test_a_streamed_body_is_read_no_further_than_the_cap(world, path):
    world.invites[path].make()
    status, taken = post(world.app, path, [b"x" * 1024] * 1024)  # 1 MB, no Content-Length
    assert status == 413 and taken <= 8 * 1024


@pytest.mark.parametrize("path", ROUTES)
def test_a_pairing_sized_body_still_reaches_the_code_check(world, path):
    code = world.invites[path].make()
    wrong = "AAAA-AAAA" if code != "AAAA-AAAA" else "BBBB-BBBB"
    body = ('{"code": "%s", "name": "devbox", "os": "linux", "arch": "x86_64", "version": "1.0.1", '
            '"device": "Mira\'s iPhone", "id": "dev-1"}' % wrong).encode()
    status, taken = post(world.app, path, [body], length=len(body))
    assert status == 403 and taken == len(body)
    good = ('{"code": "%s", "name": "devbox", "os": "linux", "arch": "x86_64", "version": "1.0.1", '
            '"device": "Mira\'s iPhone", "id": "dev-1"}' % code).encode()
    assert post(world.app, path, [good], length=len(good))[0] == 200


@pytest.mark.parametrize("path", ROUTES)
def test_a_caller_with_no_secret_cannot_tell_why_its_code_was_refused(world, path):
    """No invite, an expired one, a wrong code and the wrong code that ends the invite answer the same words, so a
    scanner cannot tell when a code is live. The owner still sees why the invite ended (the page, the app, the CLI)."""
    from fastapi.testclient import TestClient

    import hub_nodes

    client = TestClient(world.app, base_url="https://studio.example.internal:7443")
    invites = world.invites[path]

    def answer(code: str) -> tuple[int, str]:
        r = client.post(path, json={"code": code, "name": "devbox", "os": "linux", "device": "Mira's iPhone", "id": "d"})
        return r.status_code, r.text

    said = [answer("AAAA-AAAA")]  # no invite out
    code = invites.make()
    invites._until = 0  # expired
    said.append(answer(code))
    code = invites.make()
    wrong = "AAAA-AAAA" if code != "AAAA-AAAA" else "BBBB-BBBB"
    said.append(answer(wrong))
    invites.wrong = hub_nodes.PAIR_WRONG_PER_INVITE - 1
    said.append(answer(wrong))  # the one that ends it
    assert invites.ended and invites.ended.startswith("the invite was cancelled")
    assert len(set(said)) == 1, said
    assert said[0] == (403, hub_nodes.NO_SUCH_INVITE)
