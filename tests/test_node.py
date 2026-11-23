"""node.py: a machine whose sessions another machine's voice (the hub) talks to. Tested against a fake hub.

The fake hub is a real TLS WebSocket server with a self-signed certificate, so the node's certificate pin and HMAC
answer are exercised as they run (docs/design/multi-machine.md, "Protocol", "Approvals: what the node re-checks")."""

import asyncio
import datetime
import hashlib
import ipaddress
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path

import pytest
from aiohttp import WSCloseCode, web

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import guards  # noqa: E402
import nodelink  # noqa: E402

# The modules a node runs on, loaded as the node loads them, in a fresh interpreter (this suite's process has long
# since imported the daemon).
NODE_IMPORTS = """
import json, sys
import node, node_cli, harnesses
harnesses.names()
node.precise_mask("ANTHROPIC_API_KEY=sk-ant-0123456789abcdef")
print(json.dumps(sorted(sys.modules)))
"""

FORBIDDEN = ("pipecat", "onnxruntime", "sherpa_onnx", "anthropic", "google", "openai", "numpy", "torch")


def test_a_node_imports_nothing_that_loads_a_model_or_a_vendor_sdk(tmp_path):
    out = subprocess.run([sys.executable, "-c", NODE_IMPORTS], cwd=ROOT, capture_output=True, text=True, timeout=60,
                         env={"CLAUDE_VOICE_STATE": str(tmp_path), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr
    loaded = json.loads(out.stdout.splitlines()[-1])
    assert "node" in loaded
    assert not [m for m in loaded if m.split(".")[0] in FORBIDDEN]


import node  # noqa: E402: after the fresh-interpreter test, which must not see this process's imports
import node_cli  # noqa: E402


# ---------- masking: only the high-precision rules ----------

def test_a_credential_in_a_transcript_line_arrives_masked_and_ordinary_values_do_not():
    line = json.dumps({"type": "user", "message": {"content": "export ANTHROPIC_API_KEY=sk-ant-0123456789abcdefghij"}}) + "\n"
    out = node.mask_line(line)
    assert "0123456789abcdefghij" not in out and out.endswith("\n")
    assert json.loads(out)["type"] == "user"  # still a transcript entry the hub's follower can read
    plain = json.dumps({"type": "assistant", "message": {"content": "port: 7860 and timeout: 30"}}) + "\n"
    assert node.mask_line(plain) == plain  # byte for byte: nothing to mask, nothing changed


def test_the_broader_rules_stay_off_for_transcripts(monkeypatch):
    monkeypatch.setenv("SOME_SERVICE_TOKEN", "abcdefgh12345678")  # this machine's own key values: the node has none
    assert node.precise_mask("the value abcdefgh12345678 here") == "the value abcdefgh12345678 here"
    assert node.precise_mask("password: hunter22x") == "password: hunter22x"  # a bare name: value guess
    assert "hunter22x" not in node.precise_mask('password = "hunter22x"')  # quoted value of a secret-like name
    assert "s3cret99" not in node.precise_mask("https://bob:s3cret99@example.com/x")
    assert "PRIVATE KEY" not in node.precise_mask("-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----")


def test_a_line_that_is_not_json_is_masked_as_text():
    assert "0123456789abcdef" not in node.mask_line("not json sk-ant-0123456789abcdefgh\n")


# ---------- transcript frames: complete lines, node byte offsets ----------

def test_frames_carry_the_node_files_byte_offsets_and_hold_back_a_partial_line():
    a = json.dumps({"n": 1, "t": "API_KEY=sk-ant-0123456789abcdefghijk"}) + "\n"  # masked: shorter on the hub
    b = json.dumps({"n": 2, "t": "héllo"}) + "\n"
    data = (a + b).encode() + b'{"n": 3, "par'
    frames, nxt = node.masked_frames("s1", 0, 100, data)
    assert nxt == 100 + len((a + b).encode())
    sent = [nodelink.decode(f, nodelink.NODE_FRAMES) for f in frames]
    assert sent[0]["offset"] == 100 and sent[-1]["next_offset"] == nxt
    entries = [e for f in sent for e in f["entries"]]
    assert len(entries) == 2 and "0123456789abcdefghijk" not in entries[0] and json.loads(entries[1])["t"] == "héllo"


def test_a_line_over_the_entry_cap_is_not_sent_but_its_bytes_count():
    big = json.dumps({"x": "a" * (nodelink.MAX_ENTRY_BYTES + 10)}) + "\n"
    small = '{"n": 1}\n'
    frames, nxt = node.masked_frames("s1", 0, 0, (big + small).encode())
    sent = [nodelink.decode(f, nodelink.NODE_FRAMES) for f in frames]
    assert nxt == len((big + small).encode())
    assert [e for f in sent for e in f["entries"]] == [small]
    assert sent[0]["offset"] == 0 and sent[-1]["next_offset"] == nxt


# ---------- the fake hub ----------

def _certificate(tmp: Path) -> tuple[Path, Path, str]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fake-hub")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp / "cert.pem", tmp / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return cert_path, key_path, hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


class FakeHub:
    """What the hub does on /voice/node, and nothing more: challenge, HMAC check, welcome, then frames both ways."""

    HUB = {"id": "hub0123456789", "name": "studio"}
    named: str | None = None  # the name the hub's invite gave the machine (pointe hub invite --name)

    def __init__(self, tmp: Path, resume: dict | None = None, call_up: bool = True, approvals_terminal: bool = False,
                 wrong_cert: bool = False):
        self.cert, self.keyfile, self.fp = _certificate(tmp)
        if wrong_cert:
            self.fp = "00" * 32
        self.node_id = "abc123" + "0" * 26
        self.key = nodelink.new_key()
        self.resume, self.call_up, self.approvals_terminal = resume or {}, call_up, approvals_terminal
        self.ws: web.WebSocketResponse | None = None
        self.frames: asyncio.Queue = asyncio.Queue()
        self.seen: list[dict] = []
        self.hellos: list[dict] = []
        self.pairs: list[dict] = []
        self.refuse_with: int | None = None
        self.connections = 0

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get(nodelink.PATH, self._ws)
        app.router.add_post(nodelink.PAIR_PATH, self._pair)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(self.cert, self.keyfile)
        site = web.TCPSite(self.runner, "127.0.0.1", 0, ssl_context=context)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        await self.runner.cleanup()

    async def _pair(self, request: web.Request) -> web.Response:
        body = await request.json()
        self.pairs.append(body)
        if body.get("code") != "K7PQ-2MXD":
            return web.Response(status=403, text="wrong code")
        named = {"name": self.named} if self.named else {}
        return web.json_response({"node_id": self.node_id, "node_key": self.key, "hub": self.HUB,
                                  "vendors": ["Anthropic", "Soniox"], **named})

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.connections += 1
        nonce = nodelink.new_nonce()
        await ws.send_str(nodelink.encode("challenge", nonce=nonce, hub=self.HUB))
        hello = nodelink.decode(await ws.receive_str(), nodelink.NODE_FRAMES)
        self.hellos.append(hello)
        if self.refuse_with:
            await ws.close(code=self.refuse_with)
            return ws
        if not hello or hello["t"] != "hello" or not nodelink.check(self.key, nonce, self.HUB["id"], hello["auth"]):
            await ws.close(code=nodelink.CLOSE_UNAUTHORIZED)
            return ws
        await ws.send_str(nodelink.encode("welcome", protocol=nodelink.PROTOCOL, call_up=self.call_up,
                                          approvals_terminal=self.approvals_terminal, vendors=["Anthropic"],
                                          resume=self.resume))
        self.ws = ws
        async for msg in ws:
            frame = nodelink.decode(msg.data, nodelink.NODE_FRAMES)
            if frame:
                await self.frames.put(frame)
        return ws

    async def send(self, t: str, **fields) -> None:
        await self.ws.send_str(nodelink.encode(t, **fields))

    async def next(self, t: str, timeout: float = 5, **match) -> dict:
        """The next frame of type t (and matching fields); others are kept in `seen`."""
        deadline = time.monotonic() + timeout
        while True:
            frame = await asyncio.wait_for(self.frames.get(), max(0.01, deadline - time.monotonic()))
            self.seen.append(frame)
            if frame["t"] == t and all(frame.get(k) == v for k, v in match.items()):
                return frame

    async def quiet(self, t: str, secs: float = 0.6) -> bool:
        """No frame of type t arrives within secs."""
        try:
            await self.next(t, secs)
            return False
        except asyncio.TimeoutError:
            return True

    def hub_id(self, session_id: str) -> str:
        return nodelink.hub_session_id(self.node_id, session_id)


def _pair(state: Path, hub: FakeHub) -> None:
    state.mkdir(parents=True, exist_ok=True)
    (state / "node.json").write_text(json.dumps({"id": hub.node_id, "name": "devbox", "hub": {
        **hub.HUB, "host": "127.0.0.1", "port": hub.port, "fp": hub.fp}}))
    (state / "node_keys").mkdir(exist_ok=True)
    (state / "node_keys" / hub.HUB["id"]).write_text(hub.key)


def _body(tmp: Path, sid: str = "sess-1", **extra) -> dict:
    """What bin/register-session posts."""
    transcript = tmp / f"{sid}.jsonl"
    transcript.touch()
    return {"id": sid, "name": "shop", "cwd": str(tmp), "pid": os.getpid(), "transcript": str(transcript),
            "inbox_socket": None, "inbox_token": None, "channel_url": None, "name_given": False,
            "config_dir": str(tmp / "claude-home"), **extra}


def run(scenario, tmp: Path, **hub_options):
    """Run scenario(hub, node) with a linked node on its own state dir."""

    async def go():
        hub = FakeHub(tmp, **hub_options)
        await hub.start()
        state = tmp / "state"
        _pair(state, hub)
        (state / "token").write_text("t0k3n")
        n = node.Node(state, port=0)
        n.poll = 0.05
        n.holding_wait = 1.0
        await n.start()
        try:
            await asyncio.wait_for(n.linked.wait(), 5)
            return await scenario(hub, n)
        finally:
            await n.stop()
            await hub.stop()

    return asyncio.run(go())


# ---------- the link ----------

def test_the_node_authenticates_with_an_hmac_and_never_sends_its_key(tmp_path):
    async def scenario(hub, n):
        hello = hub.hellos[0]
        assert hello["protocol"] == nodelink.PROTOCOL and hello["node"]["id"] == hub.node_id
        assert hub.key not in json.dumps(hello)
        assert abs(hello["now"] - time.time()) < 5
        assert "claude-code" in hello["node"]["harnesses"]
        await hub.send("ping", id=7, rtt_ms=None)
        assert (await hub.next("pong"))["id"] == 7

    run(scenario, tmp_path)


def test_a_renamed_hub_is_called_by_its_new_name_after_the_next_link(tmp_path):
    """node.json was written once, at the join: after the hub was renamed, pointe node status, pointe open and node leave
    kept its old name."""
    async def go():
        hub = FakeHub(tmp_path)
        await hub.start()
        state = tmp_path / "state"
        _pair(state, hub)  # paired while it was called studio
        hub.HUB = {**FakeHub.HUB, "name": "atelier"}  # then renamed: config.json "machine"
        (state / "token").write_text("t0k3n")
        n = node.Node(state, port=0)
        await n.start()
        try:
            await asyncio.wait_for(n.linked.wait(), 5)
        finally:
            await n.stop()
            await hub.stop()
        return json.loads((state / "node.json").read_text())

    saved = asyncio.run(go())
    assert saved["hub"]["name"] == "atelier" and saved["hub"]["id"] == FakeHub.HUB["id"] and saved["name"] == "devbox"


def test_a_hub_whose_certificate_is_not_the_pinned_one_gets_nothing(tmp_path):
    async def go():
        hub = FakeHub(tmp_path, wrong_cert=True)
        await hub.start()
        state = tmp_path / "state"
        _pair(state, hub)
        n = node.Node(state, port=0)
        await n.start()
        await asyncio.sleep(1.0)
        assert hub.connections == 0 and not hub.hellos  # refused before a byte of HTTP was sent
        assert "certificate" in n.link_error
        await n.stop()
        await hub.stop()

    asyncio.run(go())


def test_a_revoked_key_is_deleted_and_the_node_stops_reconnecting(tmp_path):
    async def go():
        hub = FakeHub(tmp_path)
        hub.refuse_with = nodelink.CLOSE_UNAUTHORIZED
        await hub.start()
        state = tmp_path / "state"
        _pair(state, hub)
        n = node.Node(state, port=0)
        await n.start()
        await asyncio.wait_for(n.finished.wait(), 5)
        assert not (state / "node_keys" / hub.HUB["id"]).exists() and not (state / "node.json").exists()
        await asyncio.sleep(1.5)
        assert hub.connections == 1
        await n.stop()
        await hub.stop()

    asyncio.run(go())


def test_unpaired_from_the_hub_deletes_the_key(tmp_path):
    async def scenario(hub, n):
        await hub.send("unpaired")
        await asyncio.wait_for(n.finished.wait(), 5)
        assert not (n.state / "node_keys" / hub.HUB["id"]).exists()

    run(scenario, tmp_path)


def test_a_second_connection_refused_as_already_connected_keeps_the_key_and_retries(tmp_path):
    async def go():
        hub = FakeHub(tmp_path)
        hub.refuse_with = nodelink.CLOSE_ALREADY_CONNECTED
        await hub.start()
        state = tmp_path / "state"
        _pair(state, hub)
        n = node.Node(state, port=0)
        n.backoff = lambda attempt: 0.1
        await n.start()
        deadline = time.monotonic() + 5
        while hub.connections < 2 and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert hub.connections >= 2 and (state / "node_keys" / hub.HUB["id"]).exists()
        assert "already connected" in n.link_error
        await n.stop()
        await hub.stop()

    asyncio.run(go())


# ---------- registration and transcripts ----------

def test_registration_is_announced_without_the_inbox_secrets(tmp_path):
    async def scenario(hub, n):
        got = await n.register(_body(tmp_path, inbox_socket="/tmp/sock", inbox_token="SECRET-INBOX"))
        assert got["name"] == "shop"
        assert (await hub.next("session.joined"))["id"] == "sess-1"
        snap = await hub.next("sessions")
        assert "SECRET-INBOX" not in json.dumps(snap) and "/tmp/sock" not in json.dumps(snap)
        s = snap["sessions"][0]
        assert (s["id"], s["name"], s["harness"], s["pid"]) == ("sess-1", "shop", "claude-code", os.getpid())
        assert s["capabilities"]["side_questions"] is False and s["pending"] is None

    run(scenario, tmp_path)


def test_a_launch_mode_channel_is_refused_on_a_node(tmp_path):
    async def scenario(hub, n):
        with pytest.raises(ValueError, match="hub"):
            await n.register(_body(tmp_path, channel_url="http://127.0.0.1:9999"))

    run(scenario, tmp_path)


def test_transcript_lines_ship_with_offsets_masked_and_complete_only(tmp_path):
    async def scenario(hub, n):
        body = _body(tmp_path)
        path = Path(body["transcript"])
        first = json.dumps({"type": "user", "message": {"content": "API_KEY=sk-ant-0123456789abcdefghijk"}}) + "\n"
        path.write_text(first)
        await n.register(body)
        repointed = await hub.next("transcript.repointed")
        frame = await hub.next("transcript")
        assert (frame["offset"], frame["next_offset"]) == (0, len(first.encode()))
        assert "0123456789abcdefghijk" not in frame["entries"][0]
        assert frame["gen"] == repointed["gen"]
        second = json.dumps({"type": "assistant", "message": {"content": "port: 7860"}}) + "\n"
        with path.open("a") as f:
            f.write(second[:10])
        assert await hub.quiet("transcript")  # a partial line waits
        with path.open("a") as f:
            f.write(second[10:])
        frame = await hub.next("transcript")
        assert frame["offset"] == len(first.encode()) and frame["entries"] == [second]

    run(scenario, tmp_path)


def test_the_hubs_resume_offset_is_where_shipping_starts(tmp_path):
    lines = [json.dumps({"n": i}) + "\n" for i in range(3)]
    start = len("".join(lines[:2]).encode())
    hub_id = nodelink.hub_session_id("abc123" + "0" * 26, "sess-1")
    state = tmp_path / "state"
    state.mkdir()
    (state / "node_tails.json").write_text(json.dumps({"sess-1": {"path": str(tmp_path / "sess-1.jsonl"), "gen": 4}}))

    async def scenario(hub, n):
        body = _body(tmp_path)
        Path(body["transcript"]).write_text("".join(lines))
        await n.register(body)
        frame = await hub.next("transcript")
        assert (frame["gen"], frame["offset"], frame["entries"]) == (4, start, [lines[2]])
        await hub.send("resume", resume={hub_id: {"gen": 4, "offset": 0}})  # the hub saw a gap: from there again
        frame = await hub.next("transcript")
        assert frame["offset"] == 0 and frame["entries"] == lines

    run(scenario, tmp_path, resume={hub_id: {"gen": 4, "offset": start}})


def test_a_session_that_moves_to_a_new_file_is_repointed_with_the_next_gen(tmp_path):
    home = tmp_path / "claude-home"
    (home / "sessions").mkdir(parents=True)
    (home / "projects" / "p").mkdir(parents=True)

    async def scenario(hub, n):
        body = _body(tmp_path)
        Path(body["transcript"]).write_text('{"n": 0}\n')
        await n.register(body)
        first = await hub.next("transcript")
        new = home / "projects" / "p" / "new-id.jsonl"
        new.write_text('{"n": "after clear"}\n')
        (home / "sessions" / f"{os.getpid()}.json").write_text(json.dumps({"sessionId": "new-id"}))
        repointed = await hub.next("transcript.repointed")
        assert repointed["gen"] == first["gen"] + 1
        frame = await hub.next("transcript", gen=repointed["gen"])
        assert frame["offset"] == 0 and frame["entries"] == ['{"n": "after clear"}\n']

    run(scenario, tmp_path)


def test_a_session_whose_process_exits_is_reported_left(tmp_path):
    async def scenario(hub, n):
        sleeper = subprocess.Popen(["sleep", "30"])
        await n.register(_body(tmp_path, pid=sleeper.pid))
        sleeper.kill()
        sleeper.wait()
        left = await hub.next("session.left", timeout=8)
        assert (left["id"], left["why"]) == ("sess-1", "exited")

    run(scenario, tmp_path)


def test_leaving_from_this_machine_is_reported_disconnected(tmp_path):
    async def scenario(hub, n):
        await n.register(_body(tmp_path))
        assert await n.disconnect("sess-1")
        left = await hub.next("session.left")
        assert (left["id"], left["why"]) == ("sess-1", "disconnected")
        assert not await n.disconnect("sess-1")

    run(scenario, tmp_path)


def test_leave_from_the_hub_takes_the_session_off_this_node(tmp_path):
    async def scenario(hub, n):
        await n.register(_body(tmp_path))
        await hub.send("leave", id=hub.hub_id("sess-1"))
        for _ in range(50):
            if "sess-1" not in n.registry.sessions:
                break
            await asyncio.sleep(0.05)
        assert "sess-1" not in n.registry.sessions

    run(scenario, tmp_path)


# ---------- sends ----------

def test_a_send_reaches_the_sessions_inbox_and_the_result_goes_back(tmp_path):
    sock = Path(f"/tmp/cv-mmb-{os.getpid()}.sock")
    got: list[list[dict]] = []

    async def scenario(hub, n):
        async def inbox(reader, writer):
            got.append([json.loads(line) for line in (await reader.read()).decode().splitlines()])
            writer.close()

        server = await asyncio.start_unix_server(inbox, str(sock))
        try:
            await n.register(_body(tmp_path, inbox_socket=str(sock), inbox_token="tok"))
            await hub.send("send", req="r1", id=hub.hub_id("sess-1"), text="run the tests")
            assert await hub.next("send.result", req="r1") == {"t": "send.result", "req": "r1", "ok": True}
            await asyncio.sleep(0.1)
            assert got[0][0] == {"type": "auth", "token": "tok"}
            content = got[0][1]["message"]["content"]
            assert content.startswith("[Voice request from the user") and content.endswith("run the tests")
            await hub.send("send", req="r2", id="nobody", text="x")
            assert (await hub.next("send.result", req="r2"))["ok"] is False
        finally:
            server.close()
            sock.unlink(missing_ok=True)

    run(scenario, tmp_path)


# ---------- permissions: hold, forward, re-check ----------

READABLE = ("Bash", {"command": "git status", "description": "Show status"})
UNREADABLE = ("WebFetch", {"url": "https://example.com/x", "prompt": "read it"})


async def _prompt(hub, n, tmp: Path, request=READABLE, holding: bool = True, gone=None):
    """A held prompt and its forwarded request frame."""
    if "sess-1" not in n.registry.sessions:
        await n.register(_body(tmp))
    session = n.registry.sessions["sess-1"]
    task = asyncio.create_task(n.hold(session, request[0], dict(request[1]), gone))
    frame = await hub.next("permission.request")
    if holding:
        await hub.send("permission.holding", request_id=frame["request_id"])
    return task, frame


async def _answer(hub, frame, verdict="allow", how="voice", **extra) -> dict:
    await hub.send("permission.answer", id=hub.hub_id("sess-1"), request_id=frame["request_id"], verdict=verdict,
                   how=how, **extra)
    return await hub.next("permission.answered", request_id=frame["request_id"])


def test_a_request_is_forwarded_with_the_nodes_own_readable_form_and_a_masked_preview(tmp_path):
    async def scenario(hub, n):
        task, frame = await _prompt(hub, n, tmp_path, ("Bash", {"command": "TOKEN=abcd1234efgh git push"}))
        assert frame["readable"] is None  # a credential: never read out
        assert "abcd1234efgh" not in frame["preview"] and frame["tool"] == "Bash"
        assert 0 < frame["deadline_ms"] <= 280_000
        await _answer(hub, frame, "deny")
        assert await task == "deny"
        task, frame = await _prompt(hub, n, tmp_path)
        assert frame["readable"] == guards.readable_request(*READABLE, str(tmp_path)) == "run: git status"
        await _answer(hub, frame, "deny")
        await task

    run(scenario, tmp_path)


def test_recheck_a_verdict_for_another_request_id_is_stale(tmp_path):
    async def scenario(hub, n):
        task, frame = await _prompt(hub, n, tmp_path)
        await hub.send("permission.answer", id=hub.hub_id("sess-1"), request_id="0000", verdict="allow", how="tap")
        answered = await hub.next("permission.answered", request_id="0000")
        assert (answered["ok"], answered["why"]) == (False, "stale")
        assert not task.done()
        await _answer(hub, frame, "deny")
        assert await task == "deny"

    run(scenario, tmp_path)


def test_recheck_a_deny_always_denies_even_an_unreadable_request(tmp_path):
    async def scenario(hub, n):
        task, frame = await _prompt(hub, n, tmp_path, UNREADABLE)
        assert (await _answer(hub, frame, "deny", how="notification"))["ok"] is True
        assert await task == "deny"

    run(scenario, tmp_path)


def test_recheck_a_voice_yes_needs_the_exact_readable_text(tmp_path):
    async def scenario(hub, n):
        task, frame = await _prompt(hub, n, tmp_path)
        off_by_one = await _answer(hub, frame, how="voice", spoken="run: git statu")
        assert off_by_one["ok"] is False and off_by_one["why"]
        missing = await _answer(hub, frame, how="voice")
        assert missing["ok"] is False
        assert not task.done()
        assert (await _answer(hub, frame, how="voice", spoken="run: git status"))["ok"] is True
        assert await task == "allow"

    run(scenario, tmp_path)


def test_recheck_a_voice_yes_cannot_approve_what_the_node_found_unreadable(tmp_path):
    async def scenario(hub, n):
        task, frame = await _prompt(hub, n, tmp_path, UNREADABLE)
        answered = await _answer(hub, frame, how="voice", spoken="fetch example.com")
        assert (answered["ok"], answered["why"]) == (False, "unreadable")
        await _answer(hub, frame, "deny")
        assert await task == "deny"

    run(scenario, tmp_path)


def test_recheck_a_notification_approves_only_a_readable_request(tmp_path):
    async def scenario(hub, n):
        task, frame = await _prompt(hub, n, tmp_path, UNREADABLE)
        assert (await _answer(hub, frame, how="notification"))["why"] == "unreadable"
        await _answer(hub, frame, "deny")
        await task
        task, frame = await _prompt(hub, n, tmp_path)
        assert (await _answer(hub, frame, how="notification"))["ok"] is True
        assert await task == "allow"

    run(scenario, tmp_path)


def test_recheck_a_tap_is_trusted_by_default_even_when_unreadable(tmp_path):
    async def scenario(hub, n):
        task, frame = await _prompt(hub, n, tmp_path, UNREADABLE)
        assert (await _answer(hub, frame, how="tap"))["ok"] is True
        assert await task == "allow"

    run(scenario, tmp_path)


def test_recheck_remote_taps_readable_only_refuses_an_unreadable_tap_and_allows_a_readable_one(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "config.json").write_text(json.dumps({"remote_taps": "readable_only"}))

    async def scenario(hub, n):
        task, frame = await _prompt(hub, n, tmp_path, UNREADABLE)
        assert (await _answer(hub, frame, how="tap"))["why"] == "unreadable"
        await _answer(hub, frame, "deny")
        await task
        task, frame = await _prompt(hub, n, tmp_path)
        assert (await _answer(hub, frame, how="tap"))["ok"] is True
        assert await task == "allow"

    run(scenario, tmp_path)


def test_recheck_approvals_terminal_on_the_node_forwards_nothing(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "config.json").write_text(json.dumps({"approvals": "terminal"}))

    async def scenario(hub, n):
        await n.register(_body(tmp_path))
        reply = await n.permission_hook({"session_id": "sess-1", "tool_name": "Bash", "tool_input": READABLE[1]})
        assert reply == {}
        assert await hub.quiet("permission.request")

    run(scenario, tmp_path)


def test_no_call_on_the_hub_or_approvals_terminal_there_leaves_the_prompt_to_the_terminal(tmp_path):
    async def scenario(hub, n):
        await n.register(_body(tmp_path))
        payload = {"session_id": "sess-1", "tool_name": "Bash", "tool_input": READABLE[1]}
        assert await n.permission_hook(payload) == {}
        await hub.send("call", up=True, approvals_terminal=True)
        await asyncio.sleep(0.2)
        assert await n.permission_hook(payload) == {}
        assert await hub.quiet("permission.request")
        await hub.send("call", up=True, approvals_terminal=False)
        await asyncio.sleep(0.2)
        hook = asyncio.create_task(n.permission_hook(payload))
        frame = await hub.next("permission.request")
        await hub.send("permission.holding", request_id=frame["request_id"])
        await _answer(hub, frame, how="tap")
        assert (await hook)["hookSpecificOutput"]["decision"] == {"behavior": "allow"}

    run(scenario, tmp_path, call_up=False)


def test_without_holding_from_the_hub_the_prompt_goes_back_to_the_terminal(tmp_path):
    async def scenario(hub, n):
        n.holding_wait = 0.3
        task, frame = await _prompt(hub, n, tmp_path, holding=False)
        resolved = await hub.next("permission.resolved")
        assert (resolved["request_id"], resolved["how"]) == (frame["request_id"], "timeout")
        assert await task is None
        assert (await _answer(hub, frame, how="tap"))["why"] == "stale"  # a late verdict

    run(scenario, tmp_path)


def test_holding_keeps_the_prompt_past_the_wait(tmp_path):
    async def scenario(hub, n):
        n.holding_wait = 0.3
        task, frame = await _prompt(hub, n, tmp_path)
        await asyncio.sleep(0.8)
        assert not task.done()
        await _answer(hub, frame, how="tap")
        assert await task == "allow"

    run(scenario, tmp_path)


def test_answered_in_the_terminal_is_resolved_on_the_hub(tmp_path):
    async def scenario(hub, n):
        answered_here = asyncio.Event()

        async def gone():
            return answered_here.is_set()

        task, frame = await _prompt(hub, n, tmp_path, gone=gone)
        answered_here.set()
        resolved = await hub.next("permission.resolved")
        assert (resolved["request_id"], resolved["how"]) == (frame["request_id"], "terminal")
        assert await task is None

    run(scenario, tmp_path)


def test_the_pending_prompt_is_in_the_snapshot(tmp_path):
    async def scenario(hub, n):
        task, frame = await _prompt(hub, n, tmp_path)
        snap = await hub.next("sessions")
        while not snap["sessions"][0]["pending"]:
            snap = await hub.next("sessions")
        assert snap["sessions"][0]["pending"]["request_id"] == frame["request_id"]
        await _answer(hub, frame, "deny")
        await task

    run(scenario, tmp_path)


def test_a_link_drop_mid_hold_hands_the_prompt_back_once_the_grace_window_passes(tmp_path):
    async def scenario(hub, n):
        n.grace = 0.8
        task, frame = await _prompt(hub, n, tmp_path)
        hub.refuse_with = nodelink.CLOSE_ALREADY_CONNECTED  # the hub does not come back
        await hub.ws.close(code=WSCloseCode.GOING_AWAY)
        await asyncio.sleep(0.4)
        assert not task.done()  # still held: a hub restart has the window to come back
        assert await asyncio.wait_for(task, 5) is None

    run(scenario, tmp_path)


def test_a_hub_back_within_the_grace_window_is_offered_the_same_prompt_again(tmp_path):
    async def scenario(hub, n):
        n.grace = 10
        n.backoff = lambda attempt: 0.1
        task, frame = await _prompt(hub, n, tmp_path)
        await hub.ws.close(code=WSCloseCode.GOING_AWAY)  # a hub restart
        again = await hub.next("permission.request", request_id=frame["request_id"])
        assert again["readable"] == frame["readable"] and again["deadline_ms"] < frame["deadline_ms"]
        pending = [s["pending"] for f in hub.seen if f["t"] == "sessions" for s in f["sessions"] if s["pending"]]
        assert pending and pending[-1]["request_id"] == frame["request_id"]
        assert not task.done()
        await hub.send("permission.holding", request_id=frame["request_id"])
        assert (await _answer(hub, frame, how="tap"))["ok"] is True
        assert await task == "allow"

    run(scenario, tmp_path)


def test_a_restarted_hub_whose_call_is_not_back_yet_gets_the_prompt_when_the_call_returns(tmp_path):
    """After a hub restart the page reconnects its call a moment after the node relinks: the prompt waits out the
    grace window for it, and is re-offered once the call is up."""
    async def scenario(hub, n):
        n.grace = 10
        n.backoff = lambda attempt: 0.1
        task, frame = await _prompt(hub, n, tmp_path)
        hub.call_up = False
        await hub.ws.close(code=WSCloseCode.GOING_AWAY)
        await hub.next("sessions")  # relinked
        await asyncio.sleep(0.5)
        assert not task.done()  # not handed back yet: the call may be on its way
        assert await hub.quiet("permission.request")  # nobody to ask yet
        await hub.send("call", up=True, approvals_terminal=False)
        again = await hub.next("permission.request", request_id=frame["request_id"])
        await hub.send("permission.holding", request_id=again["request_id"])
        assert (await _answer(hub, frame, how="tap"))["ok"] is True
        assert await task == "allow"

    run(scenario, tmp_path)


def test_a_hub_back_without_a_call_hands_the_prompt_back_after_the_grace_window(tmp_path):
    async def scenario(hub, n):
        n.grace = 0.8
        n.backoff = lambda attempt: 0.1
        task, frame = await _prompt(hub, n, tmp_path)
        hub.call_up = False
        await hub.ws.close(code=WSCloseCode.GOING_AWAY)
        assert await asyncio.wait_for(task, 5) is None

    run(scenario, tmp_path)


def test_a_hub_back_with_approvals_in_terminals_hands_the_prompt_back_at_once(tmp_path):
    async def scenario(hub, n):
        n.grace = 10
        n.backoff = lambda attempt: 0.1
        task, frame = await _prompt(hub, n, tmp_path)
        hub.approvals_terminal = True
        await hub.ws.close(code=WSCloseCode.GOING_AWAY)
        assert await asyncio.wait_for(task, 3) is None

    run(scenario, tmp_path)


def test_a_revoked_node_hands_its_prompts_back_at_once(tmp_path):
    async def scenario(hub, n):
        n.grace = 10
        task, frame = await _prompt(hub, n, tmp_path)
        await hub.send("unpaired")
        assert await asyncio.wait_for(task, 3) is None

    run(scenario, tmp_path)


def test_prompts_of_one_session_are_held_one_at_a_time(tmp_path):
    async def scenario(hub, n):
        task, frame = await _prompt(hub, n, tmp_path)
        second = asyncio.create_task(n.hold(n.registry.sessions["sess-1"], *READABLE))
        assert await hub.quiet("permission.request", 0.4)
        await _answer(hub, frame, "deny")
        await task
        frame2 = await hub.next("permission.request")
        assert frame2["request_id"] != frame["request_id"]
        await hub.send("permission.holding", request_id=frame2["request_id"])
        await _answer(hub, frame2, how="tap")
        assert await second == "allow"

    run(scenario, tmp_path)


# ---------- the real scripts against a running node ----------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _trimmed_path(tmp: Path, without: tuple[str, ...]) -> str:
    """A PATH with the tools the hook uses, minus `without`."""
    bindir = tmp / ("bin-without-" + "-".join(without))
    bindir.mkdir(exist_ok=True)
    for tool in ("bash", "cat", "curl", "grep", "pgrep", "dirname", "cut", "sort", "awk", "find", "tail", "tr", "head",
                 "lsof", "ss", "python3", "env", "readlink", "sed", "basename", "git", "ps"):
        found = shutil.which(tool)
        if found and tool not in without and not (bindir / tool).exists():
            (bindir / tool).symlink_to(found)
    return str(bindir)


@pytest.fixture
def served(tmp_path):
    """A node serving on a free port, linked to a fake hub, in a thread with its own loop."""
    import threading

    import uvicorn

    port = _free_port()
    ready, box = threading.Event(), {}

    def thread():
        async def go():
            hub = FakeHub(tmp_path)
            await hub.start()
            state = tmp_path / "state"
            _pair(state, hub)
            (state / "token").write_text("t0k3n")
            n = node.Node(state, port=port)
            server = uvicorn.Server(uvicorn.Config(n.app(), host="127.0.0.1", port=port, log_level="warning"))
            box.update(hub=hub, node=n, server=server, loop=asyncio.get_running_loop())
            serving = asyncio.create_task(server.serve())
            await asyncio.wait_for(n.linked.wait(), 10)
            while not server.started:
                await asyncio.sleep(0.05)
            (state / "daemon.pid").write_text(str(os.getpid()))
            ready.set()
            await serving
            await hub.stop()

        asyncio.run(go())

    t = threading.Thread(target=thread, daemon=True)
    t.start()
    assert ready.wait(15)
    box["port"], box["state"], box["tmp"] = port, tmp_path / "state", tmp_path
    yield box
    box["server"].should_exit = True
    t.join(10)


def _on(box, coro):
    return asyncio.run_coroutine_threadsafe(coro, box["loop"]).result(10)


def _env(box, path: str | None = None) -> dict:
    env = {**os.environ, "CLAUDE_VOICE_STATE": str(box["state"]), "CLAUDE_VOICE_DAEMON_PORT": str(box["port"])}
    if path:
        env["PATH"] = path
    return env


def test_register_session_and_status_work_against_the_node(served):
    (served["tmp"] / "home" / "projects").mkdir(parents=True)
    env = {**_env(served), "CLAUDE_CODE_SESSION_ID": "real-1", "CLAUDE_CONFIG_DIR": str(served["tmp"] / "home")}
    out = subprocess.run([str(ROOT / "bin" / "register-session"), "--name", "ledger"], env=env, cwd=served["tmp"],
                         capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=20)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["name"] == "ledger"
    assert served["node"].registry.sessions["real-1"].named_by == "user"
    import urllib.request

    request = urllib.request.Request(f"http://127.0.0.1:{served['port']}/voice/status",
                                     headers={"Authorization": "Bearer t0k3n"})
    status = json.loads(urllib.request.urlopen(request, timeout=5).read())
    assert status["node"] is True and status["hub"] == "studio" and status["link"] == "up"
    assert status["connected"] is True and [s["name"] for s in status["sessions"]] == ["ledger"]
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(f"http://127.0.0.1:{served['port']}/voice/status", timeout=5)


def _hook(served, path: str | None) -> subprocess.CompletedProcess:
    payload = {"session_id": "sess-1", "tool_name": "Bash", "tool_input": READABLE[1], "hook_event_name": "PermissionRequest"}
    return subprocess.Popen([str(ROOT / "bin" / "voice-permission-hook")], env=_env(served, path), stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True), payload


def _approve_through_the_real_hook(served, path: str | None) -> str:
    hub = served["hub"]
    if "sess-1" not in served["node"].registry.sessions:
        _on(served, served["node"].register(_body(served["tmp"])))
    proc, payload = _hook(served, path)
    proc.stdin.write(json.dumps(payload))
    proc.stdin.close()

    async def answer():
        try:
            frame = await hub.next("permission.request", 4)
        except asyncio.TimeoutError:
            return
        await hub.send("permission.holding", request_id=frame["request_id"])
        await _answer(hub, frame, how="tap")

    _on(served, answer())
    out = proc.stdout.read()
    proc.wait(10)
    return out


def test_the_real_hook_gets_the_hubs_tap_with_lsof(served):
    if not shutil.which("lsof"):
        pytest.skip("no lsof here")
    out = _approve_through_the_real_hook(served, None)
    assert json.loads(out)["hookSpecificOutput"]["decision"] == {"behavior": "allow"}


def test_the_real_hook_without_lsof_falls_back_to_ss_then_proc(served):
    with_ss = shutil.which("ss")
    out = _approve_through_the_real_hook(served, _trimmed_path(served["tmp"], ("lsof",)))
    if with_ss or Path("/proc/net/tcp").exists():
        assert json.loads(out)["hookSpecificOutput"]["decision"] == {"behavior": "allow"}
    else:  # macOS without lsof: no way to tell who holds the port, so nothing is forwarded (fail closed)
        assert out == ""
    out = _approve_through_the_real_hook(served, _trimmed_path(served["tmp"], ("lsof", "ss")))
    if Path("/proc/net/tcp").exists():
        assert json.loads(out)["hookSpecificOutput"]["decision"] == {"behavior": "allow"}
    else:
        assert out == ""


def test_the_hook_does_not_answer_for_a_squatter_on_the_port(served):
    (served["state"] / "daemon.pid").write_text("1")  # not the process that listens
    proc, payload = _hook(served, None)
    out, _ = proc.communicate(json.dumps(payload), timeout=10)
    assert out == "" and _on(served, served["hub"].quiet("permission.request", 0.5))


# ---------- refusing to share the port with a real daemon ----------

class _FakeDaemon:
    """Something that answers /voice/health as the daemon does: {"ok": true}, no "node"."""

    def __init__(self, port: int):
        import http.server
        import threading

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"ok": true}'
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def test_voice_node_refuses_to_start_beside_a_real_daemon(tmp_path):
    port = _free_port()
    daemon = _FakeDaemon(port)
    try:
        state = tmp_path / "state"
        state.mkdir()
        (state / "node.json").write_text(json.dumps({"id": "x", "name": "devbox", "hub": {"id": "h", "name": "studio"}}))
        (state / "daemon.pid").write_text(str(os.getpid()))
        env = {**os.environ, "CLAUDE_VOICE_STATE": str(state), "CLAUDE_VOICE_DAEMON_PORT": str(port)}
        out = subprocess.run([str(ROOT / "bin" / "voice-node"), "ensure"], env=env, capture_output=True, text=True,
                             timeout=30)
        assert out.returncode == 1 and "daemon" in out.stderr and "voice-daemon stop" in out.stderr
        out = subprocess.run([sys.executable, str(ROOT / "node.py"), "serve", "--port", str(port)], env=env,
                             capture_output=True, text=True, timeout=30)
        assert out.returncode != 0 and "voice-daemon stop" in out.stderr
    finally:
        daemon.close()


def test_voice_daemon_on_a_node_runs_the_node_instead(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "node.json").write_text(json.dumps({"id": "x", "name": "devbox", "hub": {"id": "h", "name": "studio"}}))
    env = {**os.environ, "CLAUDE_VOICE_STATE": str(state), "CLAUDE_VOICE_DAEMON_PORT": str(_free_port())}
    out = subprocess.run([str(ROOT / "bin" / "voice-daemon"), "status"], env=env, capture_output=True, text=True,
                         timeout=10)
    assert "node" in out.stdout and "studio" in out.stdout


def test_voice_open_on_a_node_says_where_the_call_is(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "node.json").write_text(json.dumps({"id": "x", "name": "devbox", "hub": {"id": "h", "name": "studio"}}))
    out = subprocess.run([str(ROOT / "bin" / "voice-open")], env={**os.environ, "CLAUDE_VOICE_STATE": str(state)},
                         capture_output=True, text=True, timeout=10)
    assert out.returncode == 0 and "the call is on studio" in out.stdout


# ---------- pairing ----------

def _invite(hub: FakeHub, code: str = "K7PQ-2MXD", fp: str | None = None) -> str:
    return f"pointe://hub?v=1&host=127.0.0.1&port={hub.port}&fp={fp or hub.fp}&code={code}"


def test_join_reads_the_invite_with_the_one_parser_the_hub_writes_for():
    assert not hasattr(node_cli, "parse_invite")  # one parser: nodelink's, beside the line's format
    got = nodelink.parse_invite("pointe://hub?v=1&host=studio.ts.net&port=7443&fp=" + "AB" * 32 + "&code=K7PQ-2MXD")
    assert got == {"host": "studio.ts.net", "port": 7443, "fp": "ab" * 32, "code": "K7PQ-2MXD"}  # a pasted fp in caps pins
    for bad in ("https://x", "pointe://pair?v=1&host=a&port=1&fp=ab&code=x", "pointe://hub?v=1&host=a&port=x&fp=ab&code=c"):
        with pytest.raises(ValueError):
            nodelink.parse_invite(bad)


def _join(tmp: Path, hub: FakeHub, invite: str, *extra) -> subprocess.CompletedProcess:
    state = tmp / "state"
    env = {**os.environ, "CLAUDE_VOICE_STATE": str(state), "CLAUDE_VOICE_DAEMON_PORT": str(_free_port())}
    return subprocess.run([sys.executable, str(ROOT / "node_cli.py"), "join", invite, "--name", "devbox", "--no-start", *extra],
                          env=env, capture_output=True, text=True, timeout=30)


def _with_hub(tmp: Path, then, **options):
    import threading

    box, ready = {}, threading.Event()

    def thread():
        async def go():
            hub = FakeHub(tmp, **options)
            await hub.start()
            box["hub"], box["loop"], box["stop"] = hub, asyncio.get_running_loop(), asyncio.Event()
            ready.set()
            await box["stop"].wait()
            await hub.stop()

        asyncio.run(go())

    t = threading.Thread(target=thread, daemon=True)
    t.start()
    assert ready.wait(10)
    try:
        return then(box["hub"])
    finally:
        box["loop"].call_soon_threadsafe(box["stop"].set)
        t.join(10)


def test_join_pins_the_hub_pairs_and_writes_its_key_0600(tmp_path):
    def then(hub):
        out = _join(tmp_path, hub, _invite(hub))
        assert out.returncode == 0, out.stderr
        assert "Paired with studio" in out.stdout and "Anthropic, Soniox" in out.stdout
        assert nodelink.fingerprint(hub.key) in out.stdout
        state = tmp_path / "state"
        config = json.loads((state / "node.json").read_text())
        assert config["id"] == hub.node_id and config["hub"]["fp"] == hub.fp and config["hub"]["port"] == hub.port
        key = state / "node_keys" / hub.HUB["id"]
        assert key.read_text().strip() == hub.key and key.stat().st_mode & 0o777 == 0o600
        assert hub.pairs[0]["name"] == "devbox" and hub.pairs[0]["os"] in ("linux", "macos")
        again = _join(tmp_path, hub, _invite(hub))
        assert again.returncode != 0 and "pointe node leave" in again.stderr

    _with_hub(tmp_path, then)


def test_join_takes_the_name_the_hub_gave_this_machine(tmp_path):
    def then(hub):
        hub.named = "buildbox"  # pointe hub invite --name buildbox wins over the --name typed here
        out = _join(tmp_path, hub, _invite(hub))
        assert out.returncode == 0, out.stderr
        assert "Paired with studio as buildbox" in out.stdout
        assert json.loads((tmp_path / "state" / "node.json").read_text())["name"] == "buildbox"

    _with_hub(tmp_path, then)


def test_join_refuses_a_hub_whose_certificate_is_not_in_the_invite(tmp_path):
    def then(hub):
        out = _join(tmp_path, hub, _invite(hub, fp="00" * 32))
        assert out.returncode != 0 and "not the one in the invite" in out.stderr
        assert not hub.pairs  # nothing was sent

    _with_hub(tmp_path, then)


def test_join_prints_the_hubs_refusal(tmp_path):
    def then(hub):
        out = _join(tmp_path, hub, _invite(hub, code="WRONG-CODE"))
        assert out.returncode != 0 and "wrong code" in out.stderr
        assert not (tmp_path / "state" / "node.json").exists()

    _with_hub(tmp_path, then)


def test_leave_deletes_the_pairing(tmp_path):
    def then(hub):
        assert _join(tmp_path, hub, _invite(hub)).returncode == 0
        state = tmp_path / "state"
        env = {**os.environ, "CLAUDE_VOICE_STATE": str(state), "CLAUDE_VOICE_DAEMON_PORT": str(_free_port())}
        status = subprocess.run([sys.executable, str(ROOT / "node_cli.py"), "status"], env=env, capture_output=True,
                                text=True, timeout=30)
        assert "studio" in status.stdout and nodelink.fingerprint(hub.key) in status.stdout
        assert "not running" in status.stdout
        out = subprocess.run([sys.executable, str(ROOT / "node_cli.py"), "leave"], env=env, capture_output=True, text=True,
                             timeout=30)
        assert out.returncode == 0, out.stderr
        assert not (state / "node.json").exists() and not list((state / "node_keys").iterdir())

    _with_hub(tmp_path, then)


def test_join_refuses_where_a_daemon_runs(tmp_path):
    port = _free_port()
    daemon = _FakeDaemon(port)
    try:
        def then(hub):
            state = tmp_path / "state"
            state.mkdir()
            (state / "daemon.pid").write_text(str(os.getpid()))
            env = {**os.environ, "CLAUDE_VOICE_STATE": str(state), "CLAUDE_VOICE_DAEMON_PORT": str(port)}
            out = subprocess.run([sys.executable, str(ROOT / "node_cli.py"), "join", _invite(hub), "--no-start"], env=env,
                                 capture_output=True, text=True, timeout=30)
            assert out.returncode != 0 and "voice-daemon stop" in out.stderr and not hub.pairs

        _with_hub(tmp_path, then)
    finally:
        daemon.close()


@pytest.mark.skipif(not shutil.which("uv"), reason="bin/pointe runs the node's commands with uv")
def test_pointe_node_runs_join_status_and_leave(tmp_path):
    """The command a person types: bin/pointe node <command>, in the node's own environment."""
    env = {**os.environ, "CLAUDE_VOICE_STATE": str(tmp_path / "state"), "CLAUDE_VOICE_DAEMON_PORT": str(_free_port())}
    status = subprocess.run([str(ROOT / "bin" / "pointe"), "node", "status"], env=env, capture_output=True, text=True,
                            timeout=300)
    assert status.returncode == 0 and "not paired with a hub" in status.stdout, status.stderr[-400:]
    joined = subprocess.run([str(ROOT / "bin" / "pointe"), "node", "join", "pointe://pair?v=1"], env=env,
                            capture_output=True, text=True, timeout=120)
    assert joined.returncode != 0 and "not a Pointe hub invite" in joined.stderr, joined.stderr[-400:]


def test_leave_says_whether_the_hub_was_told(tmp_path):
    async def scenario(hub, n):
        assert await n.leave() is True  # linked: `bye` went out, so the hub forgets this machine too
        assert (await hub.next("bye"))["t"] == "bye"

    run(scenario, tmp_path)


def test_leave_with_the_link_down_says_the_hub_was_not_told(tmp_path):
    async def go():
        n = node.Node(tmp_path / "state", port=0)
        return await n.leave()

    (tmp_path / "state").mkdir()
    assert asyncio.run(go()) is False


def test_leave_tells_the_owner_to_revoke_on_the_hub_when_the_hub_was_not_told(tmp_path, monkeypatch, capsys):
    """After pointe pair rotate the node cannot reach the hub: leave must not read as if the hub forgot it."""
    state = tmp_path / "state"
    state.mkdir()
    (state / "node.json").write_text(json.dumps({"name": "devbox", "hub": {"id": "h1", "name": "studio"}}))
    monkeypatch.setattr(node_cli, "_local", lambda *a, **k: {"left": True, "told_hub": False})
    monkeypatch.setattr(node_cli.subprocess, "run", lambda *a, **k: None)
    node_cli.leave(state, 0)
    out = capsys.readouterr().out
    assert "Left studio" in out and "pointe hub revoke devbox" in out
