"""Inside the Linux container: pair the real node with a fake hub, register a synthetic session with the real
bin/register-session, and raise permission prompts with the real bin/voice-permission-hook. No model key here.

Run by tests/e2e/linux_node/run.sh, once per PORT_TOOL (lsof, ss, none). Prints one PASS line per check; exits 1 on
the first failure. Also runs on a Mac, on isolated ports:
    CLAUDE_VOICE_STATE=/tmp/cv-state-mmb1 CLAUDE_VOICE_DAEMON_PORT=7966 NODE_E2E_WORK=/tmp/cv-mmb-work PORT_TOOL=lsof \
      .venv/bin/python tests/e2e/linux_node/driver.py"""

import asyncio
import datetime
import hashlib
import ipaddress
import json
import os
import shutil
import ssl
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from aiohttp import web  # noqa: E402

import nodelink  # noqa: E402

POINTE = Path(__file__).resolve().parents[3]
STATE = Path(os.environ["CLAUDE_VOICE_STATE"])
HUB_PORT = int(os.environ.get("NODE_E2E_HUB_PORT", "7565"))
NODE_PORT = os.environ["CLAUDE_VOICE_DAEMON_PORT"]
HUB = {"id": "hub0123456789", "name": "studio"}
CODE = "K7PQ-2MXD"
WORK = Path(os.environ.get("NODE_E2E_WORK", "/work"))


def check(ok: bool, what: str) -> None:
    print(("PASS " if ok else "FAIL ") + what, flush=True)
    if not ok:
        print((STATE / "daemon.log").read_text()[-3000:] if (STATE / "daemon.log").exists() else "(no node log)")
        sys.exit(1)


def certificate() -> tuple[ssl.SSLContext, str]:
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
    (WORK / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (WORK / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                     serialization.NoEncryption()))
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(WORK / "cert.pem", WORK / "key.pem")
    return context, hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


class Hub:
    def __init__(self):
        self.node_id, self.key = "abc123" + "0" * 26, nodelink.new_key()
        self.frames: asyncio.Queue = asyncio.Queue()
        self.ws = None
        self.hello = asyncio.Event()

    async def pair(self, request):
        body = await request.json()
        if body.get("code") != CODE:
            return web.Response(status=403, text="wrong code")
        return web.json_response({"node_id": self.node_id, "node_key": self.key, "hub": HUB, "vendors": ["Anthropic"]})

    async def link(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        nonce = nodelink.new_nonce()
        await ws.send_str(nodelink.encode("challenge", nonce=nonce, hub=HUB))
        hello = nodelink.decode(await ws.receive_str(), nodelink.NODE_FRAMES)
        if not hello or not nodelink.check(self.key, nonce, HUB["id"], hello.get("auth")):
            await ws.close(code=nodelink.CLOSE_UNAUTHORIZED)
            return ws
        await ws.send_str(nodelink.encode("welcome", protocol=1, call_up=True, approvals_terminal=False,
                                          vendors=["Anthropic"], resume={}))
        self.ws = ws
        self.hello.set()
        pinger = asyncio.create_task(self._ping(ws))
        async for msg in ws:
            frame = nodelink.decode(msg.data, nodelink.NODE_FRAMES)
            if frame and frame["t"] != "pong":
                await self.frames.put(frame)
        pinger.cancel()
        return ws

    async def _ping(self, ws):
        n = 0
        while not ws.closed:
            n += 1
            await ws.send_str(nodelink.encode("ping", id=n, rtt_ms=None))
            await asyncio.sleep(nodelink.PING_SECS)

    async def send(self, t, **fields):
        await self.ws.send_str(nodelink.encode(t, **fields))

    async def next(self, t, timeout=10, **match):
        deadline = time.monotonic() + timeout
        while True:
            frame = await asyncio.wait_for(self.frames.get(), max(0.01, deadline - time.monotonic()))
            if frame["t"] == t and all(frame.get(k) == v for k, v in match.items()):
                return frame


async def run(*args, stdin: str | None = None, env: dict | None = None, cwd=None):
    proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, env={**os.environ, **(env or {})},
                                                cwd=cwd)
    out, err = await proc.communicate(stdin.encode() if stdin is not None else None)
    return proc.returncode, out.decode(), err.decode()


def hook_payload(sid: str, tool: str, tool_input: dict) -> str:
    return json.dumps({"session_id": sid, "hook_event_name": "PermissionRequest", "tool_name": tool,
                       "tool_input": tool_input})


async def main() -> None:
    tool = os.environ.get("PORT_TOOL", "none")
    check({"lsof": bool(shutil.which("lsof")), "ss": bool(shutil.which("ss")) and not shutil.which("lsof"),
           "none": not shutil.which("lsof") and not shutil.which("ss")}[tool], f"[{tool}] this image has only its port tool")
    context, fp = certificate()
    hub = Hub()
    app = web.Application()
    app.router.add_get(nodelink.PATH, hub.link)
    app.router.add_post(nodelink.PAIR_PATH, hub.pair)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", HUB_PORT, ssl_context=context).start()

    invite = f"pointe://hub?v=1&host=127.0.0.1&port={HUB_PORT}&fp={fp}&code={CODE}"
    bad = await run(sys.executable, str(POINTE / "node.py"), "join", invite.replace(fp, "0" * 64))
    check(bad[0] != 0 and "not the one in the invite" in bad[2], "join refuses a certificate not in the invite")
    code, out, err = await run(sys.executable, str(POINTE / "node.py"), "join", invite, "--name", "devbox")
    check(code == 0 and "Paired with studio" in out, f"join pairs and starts the node ({out.strip()[:80]}{err[-300:]})")
    await asyncio.wait_for(hub.hello.wait(), 20)
    check(True, "the node dialed the hub, pinned its certificate and answered the HMAC challenge")
    check(json.loads(subprocess.run(["curl", "-sf", f"http://127.0.0.1:{NODE_PORT}/voice/health"], capture_output=True,
                                    text=True).stdout).get("node") is True, f"the node answers on 127.0.0.1:{NODE_PORT}")

    sleeper = subprocess.Popen(["sleep", "86400"])
    sid = "11111111-2222-3333-4444-555555555555"
    home = WORK / "home"
    transcript = home / "projects" / "p" / f"{sid}.jsonl"
    transcript.parent.mkdir(parents=True)
    first = json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n"
    transcript.write_text(first)
    (WORK / "shop").mkdir()
    code, out, err = await run(str(POINTE / "bin" / "register-session"), "--name", "shop", cwd=WORK / "shop", stdin="",
                               env={"CLAUDE_CODE_SESSION_ID": sid, "CLAUDE_PID": str(sleeper.pid),
                                    "CLAUDE_CONFIG_DIR": str(home)})
    check(code == 0 and json.loads(out)["name"] == "shop", f"the real register-session registers with the node {err}")
    check((await hub.next("session.joined"))["id"] == sid, "the hub hears session.joined")
    frame = await hub.next("transcript", id=sid)
    check((frame["offset"], frame["next_offset"], frame["entries"]) == (0, len(first), [first]),
          "the transcript ships from offset 0 with the node's byte offsets")
    secret = json.dumps({"type": "user", "message": {"content": "ANTHROPIC_API_KEY=sk-ant-0123456789abcdefghij"}}) + "\n"
    plain = json.dumps({"type": "assistant", "message": {"content": "port: 7860"}}) + "\n"
    with transcript.open("a") as f:
        f.write(secret + plain)
    frame = await hub.next("transcript", id=sid)
    entries = list(frame["entries"])
    while len(entries) < 2:
        entries += (await hub.next("transcript", id=sid))["entries"]
    check(frame["offset"] == len(first) and "0123456789abcdefghij" not in entries[0] and entries[1] == plain,
          "a credential arrives masked, an ordinary value does not")

    hook = str(POINTE / "bin" / "voice-permission-hook")
    task = asyncio.create_task(run(hook, stdin=hook_payload(sid, "Bash", {"command": "git status"})))
    request = await hub.next("permission.request")
    check(request["readable"] == "run: git status", "the real hook's prompt reaches the hub with the node's read-out")
    await hub.send("permission.holding", request_id=request["request_id"])
    await hub.send("permission.answer", id=nodelink.hub_session_id(hub.node_id, sid), request_id="deadbeef",
                   verdict="allow", how="tap")
    stale = await hub.next("permission.answered", request_id="deadbeef")
    check(stale["ok"] is False and stale["why"] == "stale", "a verdict for a stale request id is refused")
    await hub.send("permission.answer", id=nodelink.hub_session_id(hub.node_id, sid), request_id=request["request_id"],
                   verdict="allow", how="tap")
    _, out, _ = await task
    check(json.loads(out)["hookSpecificOutput"]["decision"] == {"behavior": "allow"},
          f"[{tool}] the hook's stdout carries the hub's tap")

    task = asyncio.create_task(run(hook, stdin=hook_payload(sid, "WebFetch", {"url": "https://example.com"})))
    request = await hub.next("permission.request")
    await hub.send("permission.holding", request_id=request["request_id"])
    await hub.send("permission.answer", id=sid, request_id=request["request_id"], verdict="allow", how="voice",
                   spoken="fetch example.com")
    refused = await hub.next("permission.answered", request_id=request["request_id"])
    check(refused["ok"] is False and refused["why"] == "unreadable", "a voice yes to an unreadable request is refused")
    await hub.send("permission.answer", id=sid, request_id=request["request_id"], verdict="deny", how="voice")
    _, out, _ = await task
    check(json.loads(out)["hookSpecificOutput"]["decision"]["behavior"] == "deny", "a no denies")

    real_pid = (STATE / "daemon.pid").read_text()
    (STATE / "daemon.pid").write_text(str(sleeper.pid))  # not what listens on the port
    code, out, _ = await run(hook, stdin=hook_payload(sid, "Bash", {"command": "git status"}))
    (STATE / "daemon.pid").write_text(real_pid)
    try:
        await hub.next("permission.request", timeout=1.5)
        forwarded = True
    except asyncio.TimeoutError:
        forwarded = False
    check(out == "" and not forwarded, f"[{tool}] the hook answers nothing when the port's owner is not the node")

    _, out, _ = await run(sys.executable, str(POINTE / "node.py"), "status")
    check("Link: up" in out and "shop" in out, "pointe node status shows the link and the session")
    _, out, _ = await run(str(POINTE / "bin" / "voice-open"))
    check("the call is on studio" in out, "voice-open on a node says where the call is")
    code, out, _ = await run(str(POINTE / "bin" / "voice-daemon"), "stop")
    check(code == 0, "voice-daemon stop stops the node")
    sleeper.kill()
    await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
