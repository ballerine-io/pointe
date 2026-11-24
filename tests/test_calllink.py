"""The call's link (calllink.py, phone.py protocol 5): a call that outlives a dropped socket, and a pipeline that never
waits on a slow client. The app's side of the same rules: apps/PointeKit/Tests/PointeUIUnitTests/LinkMachineTests.swift."""

import asyncio
import json
import sys
from pathlib import Path

sys.path[0:0] = [str(Path(__file__).resolve().parent.parent / "pointe"), str(Path(__file__).resolve().parent.parent)]

import calllink  # noqa: E402
import phone  # noqa: E402
from test_orchestrator import d  # noqa: E402,F401  (a fixture)

RESUMABLE = json.dumps({"type": "hello", "protocol": 5, "device": "iPhone", "capabilities": ["ptt", "resume", "adpcm"]})
OLD = json.dumps({"type": "hello", "protocol": 4, "device": "iPhone", "capabilities": ["ptt"]})


class Socket:
    """A client socket: what it is told, and what it says."""

    def __init__(self, port=7443, phone_id=None):
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent: list = []
        self.closed: int | None = None
        self.stuck = asyncio.Event()  # cleared: a send waits, as on a client that stopped reading
        self.stuck.set()
        self.headers = {}
        self.query_params = {}
        self.scope = {"server": ("127.0.0.1", port), "state": {"pointe_phone_id": phone_id} if phone_id else {}}

    def say(self, text):
        self.inbox.put_nowait({"type": "websocket.receive", "text": text})

    def drop(self, code=1006):
        self.inbox.put_nowait({"type": "websocket.disconnect", "code": code})

    async def receive(self):
        return await self.inbox.get()

    async def send_text(self, text):
        await self.stuck.wait()
        self.sent.append(text)

    async def send_bytes(self, data):
        await self.stuck.wait()
        self.sent.append(data)

    async def close(self, code=1000, reason=""):
        self.closed = code

    def texts(self, kind=None):
        out = [json.loads(m) for m in self.sent if isinstance(m, str)]
        return [m for m in out if kind is None or m.get("type") == kind]


def link_on(socket, grace=5.0, **kw):
    beat = phone.Heartbeat()
    return calllink.CallLink(socket, "phone", beat, phone.PhoneSerializer(beat), grace=grace, **kw)


async def until(check, secs=5.0):
    """A loaded machine starts the transport slowly: wait for the outcome, not a fixed time."""
    for _ in range(int(secs / 0.01)):
        if check():
            return
        await asyncio.sleep(0.01)
    assert check()


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 10))


def test_the_hello_is_answered_with_the_calls_token_and_codec():
    async def go():
        a = Socket()
        link = link_on(a)
        a.say(RESUMABLE)
        assert json.loads((await link.receive())["text"])["type"] == "hello"  # the pipeline still sees the hello
        await settle()
        [answer] = a.texts("call")
        assert answer == {"type": "call", "resume": link.token, "resumed": False, "codec": "adpcm", "grace": 5.0}
        assert link.serializer.down == phone.ADPCM and link.resumable
        assert len(link.token) >= 20
    run(go())


def test_an_old_client_gets_pcm_and_no_grace():
    async def go():
        a = Socket()
        link = link_on(a)
        a.say(OLD)
        await link.receive()
        await settle()
        assert a.texts("call")[0]["codec"] == "pcm16" and a.texts("call")[0]["grace"] == 0
        a.drop(1006)
        assert (await link.receive())["type"] == "websocket.disconnect"  # as before protocol 5: the call ends
        assert link.ended
    run(go())


def test_a_dropped_link_holds_the_call_and_the_same_client_takes_it_back():
    async def go():
        a = Socket()
        link = link_on(a)
        a.say(RESUMABLE)
        await link.receive()
        a.drop(1006)  # Wi-Fi gone: no close frame
        waiting = asyncio.create_task(link.receive())
        await asyncio.sleep(0.05)
        assert not waiting.done() and not link.ended, "the pipeline waits for the client, the call goes on"
        b = Socket()
        hello = json.dumps({**json.loads(RESUMABLE), "resume": link.token})
        assert link.takes(calllink.resume_token(hello), "phone", None)
        carrying = asyncio.create_task(link.resume(b, hello))
        await settle()
        assert b.texts("call")[0]["resumed"] is True
        b.say('{"type": "pong", "id": 1}')
        assert (await waiting)["text"] == '{"type": "pong", "id": 1}'  # the next message comes from the new socket
        assert link.stats["resumes"] == 1 and link.stats["outages"] == 1
        b.drop(1000)  # hung up on the new link
        assert (await link.receive())["type"] == "websocket.disconnect"
        await carrying  # the handler that owns the new socket returns once it no longer carries the call
    run(go())


def test_a_new_link_replaces_one_the_mac_still_thinks_is_up():
    """A network switch: the old socket shows nothing, the phone dials on the new network. No 12 s wait for a 4409."""
    async def go():
        a = Socket()
        link = link_on(a)
        a.say(RESUMABLE)
        await link.receive()
        b = Socket()
        carrying = asyncio.create_task(link.resume(b, json.dumps({**json.loads(RESUMABLE), "resume": link.token})))
        await settle()
        assert a.closed == 4410 and link.socket is b
        a.say('{"type": "pong", "id": 9}')  # the old socket's last words are not the call's
        b.say('{"type": "pong", "id": 2}')
        assert (await link.receive())["text"] == '{"type": "pong", "id": 2}'
        await link.close(4401)
        await carrying
        assert b.closed == 4401
    run(go())


def test_nobody_back_within_the_grace_ends_the_call():
    async def go():
        a = Socket()
        link = link_on(a, grace=0.2)
        a.say(RESUMABLE)
        await link.receive()
        a.drop(1006)
        assert (await link.receive())["type"] == "websocket.disconnect"
        assert link.ended and not link.takes(link.token, "phone", None)
    run(go())


def test_only_this_calls_token_from_the_same_kind_of_client_and_phone_takes_it():
    async def go():
        link = link_on(Socket(), phone_id="p1")
        token = link.token
        assert link.takes(token, "phone", "p1")
        assert not link.takes(token + "x", "phone", "p1")
        assert not link.takes(token, "page", "p1")
        assert not link.takes(token, "phone", "p2"), "another paired phone cannot take this phone's call"
        assert not link.takes(None, "phone", "p1") and not link.takes(7, "phone", "p1")
    run(go())


def test_a_slow_reader_never_holds_up_the_pipeline_and_its_backlog_is_dropped_not_queued():
    async def go():
        a = Socket()
        link = link_on(a)
        a.say(RESUMABLE)
        await link.receive()
        await settle()
        a.stuck.clear()  # the client stopped reading: its socket's sends wait
        chunk = b"\x00" * 480  # 40 ms of 24 kHz ADPCM
        for _ in range(100):  # 4 s of the bot's voice, written as fast as the pipeline writes it
            await asyncio.wait_for(link.send_bytes(chunk), 0.05)
        queued = sum(len(c) for c in link._audio)
        assert queued <= calllink.QUEUE_SECS * phone.OUT_RATE / 2 + len(chunk)
        assert link.stats["dropped_bytes"] >= 80 * len(chunk)
        await link.send_text('{"type": "interrupt"}')  # the user cut in: what waits is stale
        assert not link._audio and link._text[-1] == '{"type": "interrupt"}'
        a.stuck.set()
        await settle()
        assert a.texts("interrupt"), "goes out before any of the stale audio"
    run(go())


def test_bot_audio_is_shed_while_the_client_is_far_behind_and_nearly_dry(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(phone.time, "monotonic", lambda: clock[0])

    async def go():
        a = Socket()
        link = link_on(a)
        beat = link.heartbeat
        first = json.loads(beat.ping())
        clock[0] += 0.2
        beat.pong(first["id"], 0)  # 200 ms round trip at best
        beat.ping()
        clock[0] += 4.0  # that ping waits behind 4 s of audio, and the client said it has nothing left to play
        await link.send_bytes(b"\x00" * 480)
        assert link.stats["shed_bytes"] == 480
        beat.pong(first["id"], 3000)  # it holds 3 s: plays on in time, nothing to drop
        beat.shedding = False
        await link.send_bytes(b"\x00" * 480)
        assert link.stats["shed_bytes"] == 480
    run(go())


def test_the_daemon_takes_the_call_back_on_a_new_socket_and_turns_away_a_stranger(d, monkeypatch):
    """socket_call: one call, one pipeline, over two sockets; a third without the token is told a call is up."""
    calls = []

    async def run_call(transport):
        calls.append(transport)
        d.state.conn = object()
        try:
            while True:
                if (await transport._client._websocket.receive())["type"] == "websocket.disconnect":
                    return
        finally:
            d.state.conn = None

    async def nothing(*_a, **_k):
        return None

    monkeypatch.setattr(d, "run_call", run_call)
    monkeypatch.setattr(d.KEEP_AWAKE, "update", nothing)

    class Accepting(Socket):
        async def accept(self):
            pass

    async def go():
        a = Accepting()
        a.say(RESUMABLE)
        first = asyncio.create_task(d.socket_call(a, "phone"))
        await until(lambda: a.texts("call"))
        token = a.texts("call")[0]["resume"]
        stranger = Accepting()
        stranger.say(RESUMABLE)
        await d.socket_call(stranger, "phone")
        assert stranger.closed == 4409
        a.drop(1006)
        b = Accepting()
        b.say(json.dumps({**json.loads(RESUMABLE), "resume": token}))
        second = asyncio.create_task(d.socket_call(b, "phone"))
        await until(lambda: b.texts("call") and d.state.call_link.socket is b)
        assert len(calls) == 1 and b.texts("call")[0]["resumed"] is True and d.state.call_link.socket is b
        assert d.state.phone_socket is d.state.call_link  # Unpair ends the call, whichever socket carries it
        b.drop(1000)
        await asyncio.wait_for(asyncio.gather(first, second), 5)
        assert len(calls) == 1 and d.state.call_link is None
    run(go())


def test_the_status_is_gzipped_for_a_phone_and_not_on_the_mac(d):
    """Polled twice a second during a call: a few kilobytes each time is as much as the voice on a weak path."""
    import gzip

    from fastapi.testclient import TestClient

    for n in range(8):  # a conversation on screen, as during a call
        d.state.conversation.append(("user" if n % 2 else "assistant", f"the rollout plan, step {n}: " + "details " * 40))
    key = d.phone.phone_key(d.STATE_DIR)
    client = TestClient(d.app, base_url="http://127.0.0.1:7860")
    phone_status = client.get("/voice/status", headers={"authorization": f"Bearer {key}", "accept-encoding": "gzip"})
    assert phone_status.status_code == 200 and phone_status.headers.get("content-encoding") == "gzip"
    assert phone_status.json()["talk"][-1]["text"].startswith("the rollout plan, step 7")  # the client unzips it
    raw = gzip.compress(phone_status.content)  # what crossed the wire, about
    assert len(raw) < len(phone_status.content) / 3
    page = TestClient(d.app, base_url="http://127.0.0.1:7860", cookies={"pointe_local": d.PAGE_KEY})
    on_the_mac = page.get("/voice/status", headers={"accept-encoding": "gzip"})
    assert on_the_mac.status_code == 200 and "content-encoding" not in on_the_mac.headers
