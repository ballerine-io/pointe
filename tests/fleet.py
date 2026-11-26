"""A fleet of real Pointes on one host, for tests of several machines and several people's voices
(docs/design/people-and-machines.md): the launcher of a real daemon process, a scripted stand-in for a coding-agent
session, and a TCP proxy a test can cut, stall or delay. tests/test_people_loopback.py runs three daemons with them;
a simulator of N machines with M sessions each can use the same parts.

Every daemon is a process the test started, on its own state folder and on ports chosen free at run time, and it is
stopped by its own pid. No model runs and no vendor is called: the daemon is daemon.py with made-up keys and its
model calls refused before they leave the process.

    python -I tests/fleet.py <port>      the daemon; CLAUDE_VOICE_STATE and CLAUDE_VOICE_TLS_PORT set by the test
"""

import json
import os
import secrets
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_PORTS = {7860, 7443}  # a Pointe somebody uses: never these


def free_port() -> int:
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if port not in LIVE_PORTS:
            return port


def until(what: str, probe, timeout: float = 20.0, every: float = 0.1):
    """`probe()` until it is truthy; its value. A probe that raises (a daemon not up yet) counts as not yet."""
    end, last = time.monotonic() + timeout, None
    while time.monotonic() < end:
        try:
            last = probe()
            if last:
                return last
        except (OSError, ValueError, KeyError, StopIteration, urllib.error.URLError) as e:
            last = e
        time.sleep(every)
    raise AssertionError(f"timed out after {timeout:.0f} s: {what} (last: {str(last)[:300]})")


# ---------- a daemon ----------

class Daemon:
    """One real Pointe: `name` is its machine name and `owner` the person whose it is. start() returns when it
    answers; stop() ends the process this object started, and no other."""

    def __init__(self, root: Path, name: str, owner: str, env: dict | None = None):
        self.name, self.owner = name, owner
        self.state = root / name
        self.state.mkdir(mode=0o700, parents=True)
        self.home = root / f"{name}-home"
        self.home.mkdir(mode=0o700)
        self.bin = root / f"{name}-bin"
        self.bin.mkdir(mode=0o700)
        for tool in ("security", "secret-tool"):  # no Keychain and no keyring: both find nothing
            (self.bin / tool).write_text("#!/bin/sh\nexit 44\n")
            (self.bin / tool).chmod(0o755)
        self.port, self.tls_port = free_port(), free_port()
        self.token = secrets.token_hex(24)
        (self.state / "token").write_text(self.token)
        (self.state / "first-hello").write_text("")
        (self.state / "config.json").write_text(json.dumps({"machine": name, "owner": owner}))
        self.extra = dict(env or {})
        self.proc: subprocess.Popen | None = None
        self.starts = 0

    def env(self) -> dict:
        return {"HOME": str(self.home), "PATH": f"{self.bin}:{Path(sys.executable).parent}:/usr/bin:/bin:/usr/sbin:/sbin",
                "CLAUDE_VOICE_STATE": str(self.state), "CLAUDE_VOICE_DAEMON_PORT": str(self.port),
                "CLAUDE_VOICE_TLS_PORT": str(self.tls_port), "CLAUDE_VOICE_SKIP_KEY_CHECK": "1",
                "GOOGLE_API_KEY": "synthetic-fleet-not-a-key", "POINTE_LINK_DIR": str(self.state / "link"),
                "POINTE_SYSTEM_APPLICATIONS": str(self.state / "Applications"), "ORT_DISABLE_TELEMETRY": "1",
                **({"TMPDIR": os.environ["TMPDIR"]} if "TMPDIR" in os.environ else {}), **self.extra}

    def listen(self) -> None:
        """Its TLS listener on 127.0.0.1, as `pointe pair host 127.0.0.1` sets it up: what a person's voice dials."""
        made = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import pair; "
                               "pair.setup('127.0.0.1', '127.0.0.1')", str(ROOT / "pointe")],
                              env=self.env(), capture_output=True, text=True, timeout=60)
        assert made.returncode == 0, made.stderr[-2000:]

    def launch(self) -> None:
        """Start the process; up() waits for it. Several daemons start faster launched together."""
        assert self.proc is None or self.proc.poll() is not None, f"{self.name} is already running"
        self.starts += 1
        log = (self.state.parent / f"{self.name}.log").open("a")
        self.proc = subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve()), str(self.port)], env=self.env(),
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)

    def up(self, timeout: float = 120.0) -> "Daemon":
        until(f"{self.name} answers", lambda: self._alive() and self.get("/voice/health"), timeout, every=0.2)
        return self

    def start(self) -> "Daemon":
        self.launch()
        return self.up()

    def _alive(self) -> bool:
        if self.proc.poll() is not None:
            raise AssertionError(f"{self.name} exited ({self.proc.returncode}):\n{self.log()}")
        return True

    def stop(self) -> None:
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.send_signal(signal.SIGCONT)  # a frozen process takes no SIGTERM
        except ProcessLookupError:
            return
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)

    def restart(self) -> "Daemon":
        """A new process on the same state folder and ports."""
        self.stop()
        return self.start()

    def freeze(self) -> None:
        """Stopped where it stands (SIGSTOP), as a machine asleep: its sockets stay open and say nothing."""
        self.proc.send_signal(signal.SIGSTOP)

    def thaw(self) -> None:
        self.proc.send_signal(signal.SIGCONT)

    def log(self, chars: int = 4000) -> str:
        path = self.state.parent / f"{self.name}.log"
        return path.read_text(errors="replace")[-chars:] if path.exists() else f"(no {path.name})"

    def call(self, path: str, body: dict | None = None, timeout: float = 30) -> tuple[int, dict | str]:
        """A script's request on loopback with this daemon's token: (status, the JSON or the words)."""
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method="POST" if body is not None else "GET",
                                         data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Authorization": f"Bearer {self.token}", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as reply:
                status, text = reply.status, reply.read().decode()
        except urllib.error.HTTPError as e:
            status, text = e.code, e.read().decode(errors="replace")
        try:
            return status, json.loads(text or "{}")
        except ValueError:
            return status, text

    def get(self, path: str) -> dict:
        status, body = self.call(path)
        assert status == 200, (self.name, path, status, body)
        return body

    def post(self, path: str, body: dict) -> dict:
        status, answer = self.call(path, body)
        assert status == 200, (self.name, path, status, answer)
        return answer

    def status(self) -> dict:
        return self.get("/voice/status")

    def machine(self, name: str) -> dict | None:
        return next((m for m in self.status()["machines"] if m["name"] == name), None)

    def sessions(self, machine: str | None = None) -> dict[str, dict]:
        return {s["name"]: s for s in self.status()["sessions"] if machine is None or s.get("machine") == machine}

    def register(self, session: "StandIn") -> str:
        """The session joins this Pointe, as bin/register-session posts it. Its name here."""
        return self.post("/voice/register", session.body())["name"]

    def mirror(self, session_id: str) -> str:
        """What this voice has mirrored of another machine's session (harness/remote/<machine>/<id>.<gen>.jsonl), all
        generations in order: "" when it has none."""
        files = sorted((self.state / "harness" / "remote").glob(f"*/{session_id}.*.jsonl*"),
                       key=lambda p: int(p.name.split(".")[1]))
        return "".join(p.read_text() for p in files)


# ---------- a session ----------

class _Inbox(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class StandIn:
    """A scripted coding-agent session: an inbox socket that keeps what arrives (the lines sessions.post_inbox
    writes) and a transcript file the test appends Claude Code-shaped lines to. Its process is the test's own."""

    def __init__(self, folder: Path, sockets: Path, session_id: str, name: str):
        self.id, self.name = session_id, name
        self.cwd = folder / name
        self.cwd.mkdir(parents=True, exist_ok=True)
        self.transcript = folder / f"{session_id}.jsonl"
        self.transcript.touch()
        self.token = secrets.token_hex(8)
        self.socket = sockets / f"{session_id[:8]}.sock"  # short: a unix socket's path fits about 100 bytes
        self.received: list[dict] = []
        self.said = 0
        got = self.received

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                for raw in self.rfile:
                    try:
                        got.append(json.loads(raw))
                    except ValueError:
                        got.append({"type": "garbage", "raw": raw.decode(errors="replace")})

        self.server = _Inbox(str(self.socket), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def body(self) -> dict:
        return {"id": self.id, "name": self.name, "cwd": str(self.cwd), "pid": os.getpid(), "name_given": True,
                "transcript": str(self.transcript), "inbox_socket": str(self.socket), "inbox_token": self.token,
                "channel_url": None, "attached": True}  # attached: not in the middle of a turn that ran /pointe:voice

    def say(self, text: str) -> str:
        """The agent writes a line in its transcript (not the end of a turn: nothing is digested). The text, marked
        so a test can count it."""
        self.said += 1
        marked = f"[{self.name} line {self.said}] {text}"
        line = {"type": "assistant", "uuid": secrets.token_hex(8), "sessionId": self.id,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "message": {"role": "assistant", "stop_reason": None, "content": [{"type": "text", "text": marked}]}}
        with self.transcript.open("a") as f:
            f.write(json.dumps(line) + "\n")
        return marked

    def requests(self) -> list[str]:
        """The requests that reached the agent, in order."""
        return [str(m["message"]["content"]) for m in self.received if m.get("type") == "user"]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.socket.unlink(missing_ok=True)


def socket_folder() -> Path:
    """A short folder for inbox sockets: pytest's tmp_path is too long for a unix socket's path."""
    return Path(tempfile.mkdtemp(prefix="pf-", dir="/tmp"))


# ---------- a link the test can cut ----------

class Proxy:
    """127.0.0.1:<port> to a daemon's TLS listener, on threads of its own so a busy test never starves a link.
    `cut()` closes every connection (a network that dropped), `stalled` holds every byte while the sockets stay open
    (a VPN that went down: only heartbeats notice), `delay` holds each chunk that long (a slow link)."""

    def __init__(self, target: int):
        self.target, self.stalled, self.delay = target, False, 0.0
        self.conns: list[socket.socket] = []
        self.accepted = 0
        self._lock = threading.Lock()
        self._server = socket.socket()
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(16)
        self.port = self._server.getsockname()[1]
        self._closed = False
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        while not self._closed:
            try:
                client, _ = self._server.accept()
            except OSError:
                return
            try:
                upstream = socket.create_connection(("127.0.0.1", self.target), timeout=5)
            except OSError:
                client.close()
                continue
            upstream.settimeout(None)
            with self._lock:
                self.conns += [client, upstream]
                self.accepted += 1
            for src, dst in ((client, upstream), (upstream, client)):
                threading.Thread(target=self._pipe, args=(src, dst), daemon=True).start()

    def _pipe(self, src: socket.socket, dst: socket.socket) -> None:
        try:
            while data := src.recv(65536):
                if self.delay:
                    time.sleep(self.delay)
                while self.stalled and not self._closed:
                    time.sleep(0.05)
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                s.close()

    def cut(self) -> None:
        with self._lock:
            conns, self.conns = self.conns, []
        for s in conns:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()

    def close(self) -> None:
        self._closed = True
        self._server.close()
        self.cut()


def through(invite: str, proxy: Proxy) -> str:
    """A machine's invite line with the proxy's port in place of the machine's: the voice then dials the proxy. The
    certificate's fingerprint stays, so the pin still holds end to end."""
    from urllib.parse import parse_qsl, urlencode, urlsplit

    query = dict(parse_qsl(urlsplit(invite).query))
    query["port"] = str(proxy.port)
    return "pointe://machine?" + urlencode(query)


class Fleet:
    """The daemons, sessions and proxies of one test, all ended together."""

    def __init__(self, root: Path, env: dict | None = None):
        self.root, self.env = root, dict(env or {})
        self.sockets = socket_folder()
        self.daemons: list[Daemon] = []
        self.sessions: list[StandIn] = []
        self.proxies: list[Proxy] = []

    def daemon(self, name: str, owner: str) -> Daemon:
        self.daemons.append(Daemon(self.root, name, owner, self.env))
        return self.daemons[-1]

    def session(self, session_id: str, name: str) -> StandIn:
        self.sessions.append(StandIn(self.root / "work", self.sockets, session_id, name))
        return self.sessions[-1]

    def proxy(self, target: int) -> Proxy:
        self.proxies.append(Proxy(target))
        return self.proxies[-1]

    def start(self) -> None:
        for d in self.daemons:
            d.launch()
        for d in self.daemons:
            d.up()

    def close(self) -> None:
        for d in self.daemons:
            d.stop()
        for p in self.proxies:
            p.close()
        for s in self.sessions:
            s.close()
        shutil.rmtree(self.sockets, ignore_errors=True)

    def logs(self) -> str:
        return "\n".join(f"---- {d.name}.log\n{d.log()}" for d in self.daemons)


# ---------- the daemon process ----------

def _run_daemon(port: str) -> None:
    """daemon.py as it runs, with made-up keys and no model: a model call fails here, before any vendor is reached."""
    state = Path(os.environ["CLAUDE_VOICE_STATE"])
    assert ".claude-voice" not in str(state) and int(port) not in LIVE_PORTS \
        and int(os.environ["CLAUDE_VOICE_TLS_PORT"]) not in LIVE_PORTS, "never the live daemon"
    sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
    import vendors

    async def no_model(*_a, **_k):
        raise RuntimeError("no model runs in a fleet")

    vendors._stored = lambda vendor, keep=True: f"made-up-{vendor}-key"  # these keys reach nothing
    vendors.text = vendors.step = no_model
    vendors.warm = lambda choices: None
    import harnesses.claude_code

    harnesses.claude_code.ROSTER = False  # never this machine's real `claude agents --json`
    harnesses.claude_code.DEFAULT_HOME = state / "claude-home"
    harnesses.claude_code.MANAGED_SETTINGS = state / "managed-settings.json"
    import mac

    mac.SYSTEM = False
    import daemon

    daemon.COPY_SESSIONS = False
    daemon._read_model = no_model
    sys.argv = ["daemon.py", "--port", port]
    daemon.main()


if __name__ == "__main__":
    _run_daemon(sys.argv[1])
