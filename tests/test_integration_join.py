"""Every part of Pointe joined, end to end, with no vendor called and no real key: a hub, the page it serves, a phone, and
a node with a session on it (docs/design/multi-machine.md, docs/phone.md).

- The hub is the real daemon (tests/join_hub.py: daemon.py's app with only its voice replaced by a stand-in), on its own
  state folder and ports, its TLS listener set up as `pointe pair host` sets it up.
- The page is pointe/ui.html as that hub serves it, in headless Chrome (tests/page_rig.py), opened with its key the
  way bin/voice-open opens it. It makes the phone's pairing code, as Settings → Phone does.
- The phone pairs with that code over the listener it pins by certificate, holds the call (the wire protocol of the
  app: hello, pongs), reads the status and approves. Where it runs: on Linux (CI's `page` job) the phone is Python,
  speaking the app's routes and pin. On a Mac with Swift (a release's gate, and anyone running this with --runslow on a
  Mac) the status and the approve also run through the iPhone app's own code: PointeUI's PairingInvite, DaemonLink and
  API, in apps/PointeKit/Tests/PointeUIUnitTests/JoinLiveTests.swift, as a second phone. The call stays Python on both.
- The node is the real one (`pointe node join` with the hub's invite, then pointe/node.py serve, as bin/voice-node
  starts it), on its own state folder and port. Its session is registered by the real bin/register-session, and its
  permission prompt raised by the real bin/voice-permission-hook.

The join: the hub lists the node's session; the page shows it; the phone sees it; the node's prompt reaches the hub, the
page and the phone; the phone's approve comes back to the node's waiting hook as "allow". Both machines run on this one
host (CI's Ubuntu, or a Mac): a Linux node beside a Mac hub is tests/e2e/linux_node/, against a fake hub.
"""

import asyncio
import hashlib
import http.client
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from page_rig import CHROME, Browser, free_port  # noqa: E402

SESSION_ID = "7b0e5c3a-1d2f-4e6a-9b8c-0d1e2f3a4b5c"
COMMAND = "git status --short"
MACHINE = "devbox"
SWIFT = sys.platform == "darwin" and shutil.which("swift") and os.environ.get("POINTE_JOIN_SWIFT", "1") != "0"


class Box:
    """The two machines' folders, ports and processes; every process here is one this test started."""

    def __init__(self, root: Path):
        self.root = root
        self.hub, self.node, self.home, self.bin = (root / n for n in ("hub", "node", "home", "bin"))
        for d in (self.hub, self.node, self.home, self.bin):
            d.mkdir(mode=0o700)
        self.hub_port, self.tls_port, self.node_port = free_port(), free_port(), free_port()
        assert not {self.hub_port, self.tls_port, self.node_port} & {7860, 7443}
        self.procs: list[subprocess.Popen] = []
        # No Keychain and no keyring: `security` and `secret-tool` find nothing (as docs/install-verification.md does).
        for tool in ("security", "secret-tool"):
            (self.bin / tool).write_text("#!/bin/sh\nexit 44\n")
            (self.bin / tool).chmod(0o755)

    def env(self, state: Path, port: int) -> dict:
        return {"HOME": str(self.home), "PATH": f"{self.bin}:{Path(sys.executable).parent}:/usr/bin:/bin:/usr/sbin:/sbin",
                "CLAUDE_VOICE_STATE": str(state), "CLAUDE_VOICE_DAEMON_PORT": str(port),
                "CLAUDE_VOICE_TLS_PORT": str(self.tls_port), "CLAUDE_VOICE_SKIP_KEY_CHECK": "1",
                "GOOGLE_API_KEY": "synthetic-join-test-not-a-key", "POINTE_LINK_DIR": str(state / "link"),
                "POINTE_SYSTEM_APPLICATIONS": str(state / "Applications"), "ORT_DISABLE_TELEMETRY": "1",
                **({"TMPDIR": os.environ["TMPDIR"]} if "TMPDIR" in os.environ else {})}

    def start(self, args: list, state: Path, port: int, log: str) -> subprocess.Popen:
        proc = subprocess.Popen(args, env=self.env(state, port), stdin=subprocess.DEVNULL,
                                stdout=(self.root / log).open("w"), stderr=subprocess.STDOUT)
        self.procs.append(proc)
        return proc

    def stop(self) -> None:
        for proc in reversed(self.procs):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def log(self, name: str) -> str:
        path = self.root / name
        return path.read_text(errors="replace")[-4000:] if path.exists() else f"(no {name})"


async def until(what: str, probe, timeout: float = 30.0, every: float = 0.25):
    """`probe()` (or its awaitable) until it is truthy; the loop keeps running between tries, so the call answers pings."""
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        try:
            last = probe()
            if asyncio.iscoroutine(last):
                last = await last
            if last:
                return last
        except (OSError, ValueError, KeyError, urllib.error.URLError, http.client.HTTPException):
            pass
        await asyncio.sleep(every)
    raise AssertionError(f"timed out after {timeout:.0f} s: {what} (last: {str(last)[:300]})")


def local(port: int, path: str, token: str, body: dict | None = None, timeout: float = 10) -> dict:
    """A script's request on loopback, with the daemon's (or the node's) token."""
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="POST" if body is not None else "GET",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {token}", "content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return json.loads(reply.read() or b"{}")


class Phone:
    """The iPhone app's side, in Python: it trusts the listener only by the fingerprint in the pairing code, checked
    before anything is sent (PinnedDelegate in apps/PointeKit/Sources/PointeUI/Pairing.swift)."""

    def __init__(self, link: str):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(link).query))
        assert link.startswith("pointe://pair?") and q["v"] == "2", link
        self.host, self.port, self.fp, self.code = q["host"], int(q["port"]), q["fp"], q["code"]
        self.key: str | None = None

    def _context(self) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname, context.verify_mode = False, ssl.CERT_NONE  # trusted by its fingerprint below, not a CA
        return context

    def offered(self) -> str:
        with socket.create_connection((self.host, self.port), timeout=5) as raw:
            with self._context().wrap_socket(raw) as tls:
                return hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()

    def ask(self, path: str, body: dict | None = None, fp: str | None = None) -> tuple[int, dict | str]:
        conn = http.client.HTTPSConnection(self.host, self.port, timeout=15, context=self._context())
        try:
            conn.connect()
            if hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest() != (fp or self.fp):
                return 0, "the certificate is not the paired one: nothing sent"
            headers = {"content-type": "application/json", "x-pointe-device": "Test%20iPhone"}
            if self.key:
                headers["Authorization"] = f"Bearer {self.key}"
            conn.request("POST" if body is not None else "GET", path, body=json.dumps(body) if body is not None else None,
                         headers=headers)
            reply = conn.getresponse()
            text = reply.read().decode()
            try:
                return reply.status, json.loads(text)
            except ValueError:
                return reply.status, text
        finally:
            conn.close()

    def pair(self) -> str:
        status, body = self.ask("/voice/phone/pair", {"code": self.code, "device": "Test iPhone", "id": "join-e2e-python"})
        assert status == 200 and len(body["key"]) >= 32, (status, body)
        self.key = body["key"]
        return body["mac"]

    def status(self) -> dict:
        status, body = self.ask("/voice/status")
        assert status == 200, (status, body)
        return body

    async def call(self, ready: asyncio.Event, stop: asyncio.Event) -> None:
        """The call, as the app holds it: the socket with its key, a hello, and a pong for each ping."""
        import websockets

        assert self.offered() == self.fp, "pin the listener before the key goes out"
        async with websockets.connect(f"wss://{self.host}:{self.port}/voice/phone", ssl=self._context(),
                                      additional_headers={"Authorization": f"Bearer {self.key}"}, ping_interval=None,
                                      max_size=None, open_timeout=15) as ws:
            await ws.send(json.dumps({"type": "hello", "protocol": 5, "device": "Test iPhone", "capabilities": ["ptt"]}))
            ready.set()
            while not stop.is_set():
                try:
                    message = await asyncio.wait_for(ws.recv(), 0.5)
                except asyncio.TimeoutError:
                    continue
                if isinstance(message, str):
                    m = json.loads(message)
                    if m.get("type") == "ping":
                        await ws.send(json.dumps({"type": "pong", "id": m["id"]}))


async def page_invite(page) -> str:
    """Settings → Phone on the page: a route and a one-time code, made by the page's own request with its cookie."""
    made = await page.eval(
        "fetch('/voice/phone/invite', {method: 'POST', headers: {'content-type': 'application/json'},"
        " body: JSON.stringify({kind: 'host', host: '127.0.0.1'})}).then(async r => ({status: r.status, body: await r.text()}))")
    assert made["status"] == 200, made
    return json.loads(made["body"])["link"]


async def page_shows(page, *words: str) -> bool:
    text = await page.eval("document.body.innerText")
    return all(w in text for w in words)


def remote_session(status: dict) -> dict | None:
    return next((s for s in status.get("sessions") or [] if s.get("machine") == MACHINE), None)


@pytest.mark.skipif(not os.path.exists(CHROME), reason="headless Chrome is not installed here")
def test_hub_page_phone_and_node_join_and_a_node_prompt_is_approved_from_the_phone():
    box = Box(Path(tempfile.mkdtemp(prefix="pointe-join-")))
    try:
        asyncio.run(join(box))
    except BaseException:
        print("---- hub.log\n" + box.log("hub.log") + "\n---- node.log\n" + box.log("node.log"))
        raise
    finally:
        box.stop()
        shutil.rmtree(box.root, ignore_errors=True)


async def join(box: Box) -> None:
    sleeper = subprocess.Popen(["sleep", "600"])  # the node session's process
    box.procs.append(sleeper)
    stop_call = asyncio.Event()
    async with Browser() as browser:
        try:
            await joined(box, browser, sleeper, stop_call)
        finally:
            stop_call.set()


async def joined(box: Box, browser: Browser, sleeper: subprocess.Popen, stop_call: asyncio.Event) -> None:
    # ---- the hub: its listener as `pointe pair host 127.0.0.1` sets it up, then the daemon
    token = secrets.token_hex(24)
    (box.hub / "token").write_text(token)
    (box.hub / "first-hello").write_text("")
    made = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import pair; "
                           "pair.setup('127.0.0.1', '127.0.0.1')", str(ROOT / "pointe")],
                          env=box.env(box.hub, box.hub_port), capture_output=True, text=True, timeout=60)
    assert made.returncode == 0, made.stderr[-2000:]
    hub = box.start([sys.executable, "-I", str(ROOT / "tests" / "join_hub.py"), str(box.hub_port)], box.hub, box.hub_port,
                    "hub.log")
    await until("the hub answers", lambda: hub.poll() is None and local(box.hub_port, "/voice/health", token), 120)

    # ---- the node: the hub's invite, `pointe node join`, then the node as bin/voice-node starts it
    invite = local(box.hub_port, "/voice/hub/invite", token, {"name": MACHINE})["link"]
    paired = subprocess.run([sys.executable, str(ROOT / "pointe" / "node_cli.py"), "join", invite, "--name", MACHINE,
                             "--no-start"], env=box.env(box.node, box.node_port), capture_output=True, text=True, timeout=60)
    assert paired.returncode == 0, paired.stdout + paired.stderr
    node_token = secrets.token_hex(24)
    (box.node / "token").write_text(node_token)
    node = box.start([sys.executable, str(ROOT / "pointe" / "node.py"), "serve", "--port", str(box.node_port)],
                     box.node, box.node_port, "node.log")
    (box.node / "daemon.pid").write_text(str(node.pid))  # the hook answers only for the process that owns the port
    await until("the node is linked to the hub",
                lambda: any(n.get("online") for n in local(box.hub_port, "/voice/hub/nodes", token)["nodes"]), 60)

    # ---- a session on the node, registered by the real script
    claude = box.home / "claude"
    transcript = claude / "projects" / "shop" / f"{SESSION_ID}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(json.dumps({"type": "user", "message": {"content": "Tidy the checkout tests."}}) + "\n")
    project = box.root / "shop"
    project.mkdir()
    registered = subprocess.run([str(ROOT / "bin" / "register-session"), "--name", "shop"], cwd=project, stdin=subprocess.DEVNULL,
                                env={**box.env(box.node, box.node_port), "CLAUDE_CODE_SESSION_ID": SESSION_ID,
                                     "CLAUDE_PID": str(sleeper.pid), "CLAUDE_CONFIG_DIR": str(claude)},
                                capture_output=True, text=True, timeout=30)
    assert registered.returncode == 0, registered.stdout + registered.stderr
    on_hub = await until("the hub lists the node's session", lambda: remote_session(local(box.hub_port, "/voice/status", token)))
    name = on_hub["name"]
    assert "shop" in name and on_hub.get("online") is not False, on_hub

    # ---- the page, opened with its key as bin/voice-open opens it
    page_key = (box.hub / "page_key").read_text().strip()
    page = await browser.open(f"http://localhost:{box.hub_port}/voice?key={page_key}")
    await until("the page shows the node's session and its machine", lambda: page_shows(page, name, MACHINE), 20)

    # ---- the phone: the page's code, the pinned listener, the call
    phone = Phone(await page_invite(page))
    assert phone.offered() == phone.fp
    assert phone.ask("/voice/phone/pair", {"code": phone.code}, fp="0" * 64)[0] == 0, "a listener not pinned is sent nothing"
    assert phone.pair()
    seen = remote_session(phone.status())
    assert seen and seen["name"] == name, seen
    ready = asyncio.Event()
    call = asyncio.create_task(phone.call(ready, stop_call))
    await asyncio.wait_for(ready.wait(), 20)
    await until("the hub has the phone's call up", lambda: local(box.hub_port, "/voice/status", token).get("connected"), 20)
    await until("the node hears that the call is up", lambda: local(box.node_port, "/voice/health", node_token).get("node")
                and local(box.node_port, "/voice/status", node_token).get("connected"), 20)

    # ---- the node's prompt: through the hub to the page and the phone
    prompt = box.root / "prompt.json"
    prompt.write_text(json.dumps({"session_id": SESSION_ID, "hook_event_name": "PermissionRequest", "tool_name": "Bash",
                                  "tool_input": {"command": COMMAND, "description": "List changed files"}}))
    hook = subprocess.Popen([str(ROOT / "bin" / "voice-permission-hook")], env=box.env(box.node, box.node_port),
                            stdin=prompt.open(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    box.procs.append(hook)
    waiting = await until("the hub has the node's prompt",
                          lambda: (s := remote_session(local(box.hub_port, "/voice/status", token))) and s.get("request_id") and s)
    assert waiting["waiting"] and COMMAND in (waiting.get("request") or ""), waiting
    await until("the page shows the prompt", lambda: page_shows(page, COMMAND), 20)
    on_phone = remote_session(phone.status())
    assert on_phone["request_id"] == waiting["request_id"] and COMMAND in on_phone["request"], on_phone

    # ---- the approve, from the phone; back to the hook on the node
    if SWIFT:
        env = {**os.environ, "POINTE_E2E_JOIN_INVITE": await page_invite(page), "POINTE_E2E_JOIN_SESSION": name,
               "POINTE_E2E_JOIN_MACHINE": MACHINE, "POINTE_E2E_JOIN_REQUEST": waiting["request_id"]}
        run = await asyncio.to_thread(subprocess.run, ["swift", "test", "--filter", "JoinLiveTests"], cwd=ROOT / "apps" / "PointeKit",
                                      env=env, capture_output=True, text=True, timeout=1500)
        out = run.stdout + run.stderr
        assert run.returncode == 0 and "join-e2e: approved" in out, out[-3000:]
    else:
        status, body = phone.ask("/voice/approve", {"session": name, "request_id": waiting["request_id"], "decision": "allow"})
        assert status == 200, (status, body)
    out, err = await asyncio.to_thread(hook.communicate, timeout=30)
    assert json.loads(out)["hookSpecificOutput"]["decision"] == {"behavior": "allow"}, (out, err)
    await until("the prompt is gone from the hub",
                lambda: not (remote_session(local(box.hub_port, "/voice/status", token)) or {}).get("request_id"), 20)
    stop_call.set()
    await asyncio.wait_for(call, 5)
