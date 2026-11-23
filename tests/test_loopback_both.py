"""The daemon holds its port on both loopback addresses. A browser tries ::1 first for localhost and <hash>.localhost, and
another account can bind [::1]:<port> beside a listener on 127.0.0.1 alone: it would be handed the page key by
bin/voice-open, and the cookie on every request after. Throwaway ports only: the live daemon is on 7860."""

import errno
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import guards  # noqa: E402


def _has_ipv6_loopback() -> bool:
    try:
        with socket.socket(socket.AF_INET6) as s:
            s.bind(("::1", 0))
        return True
    except OSError:
        return False


needs_ipv6 = pytest.mark.skipif(not _has_ipv6_loopback(), reason="no IPv6 loopback on this machine")


def _free_port() -> int:
    """A port free on 127.0.0.1 and on ::1 at once."""
    for _ in range(50):
        with socket.socket() as four:
            four.bind(("127.0.0.1", 0))
            port = four.getsockname()[1]
            try:
                with socket.socket(socket.AF_INET6) as six:
                    six.bind(("::1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no port free on both loopbacks")


def _squat_v6(port: int) -> socket.socket:
    """Another program on [::1]:port, as another account would hold it, asking to share the port where it can."""
    s = socket.socket(socket.AF_INET6)
    s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    s.bind(("::1", port))
    s.listen()
    return s


@needs_ipv6
def test_both_loopback_addresses_are_held_on_one_port():
    port = _free_port()
    held = guards.loopback_sockets(port)
    try:
        assert sorted(s.getsockname()[0] for s in held) == ["127.0.0.1", "::1"]
        assert {s.getsockname()[1] for s in held} == {port}
        with pytest.raises(OSError):  # nobody else gets ::1 while the daemon is up
            _squat_v6(port).close()
    finally:
        for s in held:
            s.close()


@needs_ipv6
def test_a_program_already_on_the_ipv6_loopback_stops_the_start():
    port = _free_port()
    squatter = _squat_v6(port)
    try:
        with pytest.raises(OSError) as refused:
            guards.loopback_sockets(port)
        assert refused.value.errno == errno.EADDRINUSE
        with socket.socket() as again:  # the IPv4 half was let go, not leaked
            again.bind(("127.0.0.1", port))
    finally:
        squatter.close()


def test_a_machine_with_no_ipv6_loopback_listens_on_ipv4_alone(monkeypatch):
    real = socket.socket

    def no_ipv6(family=socket.AF_INET, *a, **k):
        if family == socket.AF_INET6:
            raise OSError(errno.EAFNOSUPPORT, "Address family not supported by protocol")
        return real(family, *a, **k)

    monkeypatch.setattr(guards.socket, "socket", no_ipv6)
    with real() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    held = guards.loopback_sockets(port)
    try:
        assert [s.getsockname()[0] for s in held] == ["127.0.0.1"]
    finally:
        for s in held:
            s.close()


def _served_on(monkeypatch, run_main) -> list | None:
    """The addresses of the sockets the server was handed (None: it bound its own, from a host)."""
    import uvicorn

    got = []

    def run(self, sockets=None):
        got.append(sorted(s.getsockname()[0] for s in sockets) if sockets is not None else None)
        for s in sockets or []:
            s.close()

    monkeypatch.setattr(uvicorn.Server, "run", run)

    async def serve(self, sockets=None):
        run(self, sockets)

    monkeypatch.setattr(uvicorn.Server, "serve", serve)
    run_main()
    assert len(got) == 1
    return got[0]


@needs_ipv6
def test_the_daemon_serves_on_both_loopback_addresses(monkeypatch):
    import daemon

    port = _free_port()
    monkeypatch.setattr(sys, "argv", ["daemon.py", "--port", str(port)])
    monkeypatch.setattr(daemon, "SERVER", daemon.SERVER)
    monkeypatch.setattr(daemon, "PORT", daemon.PORT)
    assert _served_on(monkeypatch, daemon.main) == ["127.0.0.1", "::1"]


@needs_ipv6
def test_the_daemon_will_not_start_beside_a_program_on_the_ipv6_loopback(monkeypatch):
    import daemon

    port = _free_port()
    monkeypatch.setattr(sys, "argv", ["daemon.py", "--port", str(port)])
    monkeypatch.setattr(daemon, "SERVER", daemon.SERVER)
    monkeypatch.setattr(daemon, "PORT", daemon.PORT)
    import uvicorn

    def served(self, sockets=None):
        raise AssertionError("the daemon served beside a program on [::1]")

    monkeypatch.setattr(uvicorn.Server, "run", served)
    squatter = _squat_v6(port)
    try:
        with pytest.raises(SystemExit) as stopped:
            daemon.main()
        assert "::1" in str(stopped.value) and str(port) in str(stopped.value)
    finally:
        squatter.close()


@needs_ipv6
def test_the_node_serves_on_both_loopback_addresses(monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace

    import node

    port = _free_port()
    monkeypatch.setattr(node, "_daemon_here", lambda port: False)
    monkeypatch.setattr(node, "pairing", lambda state: ({}, "k"))
    done = asyncio.Event
    monkeypatch.setattr(node, "Node", lambda state, port: SimpleNamespace(app=lambda: None, finished=done(),
                                                                         link_error=None))
    assert _served_on(monkeypatch, lambda: node.serve(port, tmp_path)) == ["127.0.0.1", "::1"]


@needs_ipv6
def test_the_listener_check_sees_a_program_on_the_ipv6_loopback():
    """bin/voice-ours and bin/voice-daemon ask bin/voice-listeners who listens: an IPv6-only listener counts."""
    port = _free_port()
    squatter = _squat_v6(port)
    try:
        out = subprocess.run([str(ROOT / "bin" / "voice-listeners"), "pids", str(port)], capture_output=True, text=True,
                             timeout=10)
        taken = subprocess.run([str(ROOT / "bin" / "voice-listeners"), "taken", str(port)], timeout=10)
    finally:
        squatter.close()
    assert str(os.getpid()) in out.stdout.split() and taken.returncode == 0


def test_no_listener_trusts_forwarded_headers_or_writes_an_access_log():
    """uvicorn trusts X-Forwarded-For from 127.0.0.1 and ::1 by default, so on the loopback listener another account's
    process could pick the address that every per-address limit (pairing guesses, waiting node sockets) and the
    owner's "paired from" line are keyed by. The access log would write addresses that carry ?pair=, ?k= and ?key=."""
    import ast

    configs = []
    for path in sorted([*ROOT.glob("*.py"), *ROOT.glob("harnesses/*.py")]):
        for call in ast.walk(ast.parse(path.read_text())):
            if isinstance(call, ast.Call) and ast.unparse(call.func) in ("uvicorn.Config", "Config"):
                kw = {k.arg: ast.unparse(k.value) for k in call.keywords}
                configs.append((f"{path.name}:{call.lineno}", kw.get("proxy_headers"), kw.get("access_log")))
    assert {where.split(":")[0] for where, *_ in configs} >= {"daemon.py", "node.py", "remote.py"}, configs
    bad = [where for where, proxy, access in configs if proxy != "False" or access != "False"]
    assert not bad, "uvicorn.Config(..., proxy_headers=False, access_log=False):\n" + "\n".join(bad)


def test_x_forwarded_for_on_loopback_does_not_change_the_client_address():
    import asyncio

    import uvicorn

    seen = []

    async def app(scope, receive, send):
        seen.append(scope["client"][0])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                           proxy_headers=False, access_log=False, lifespan="off"))

    async def go():
        task = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.01)
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\nX-Forwarded-For: 100.64.0.77\r\nConnection: close\r\n\r\n")
        await writer.drain()
        await reader.read()
        writer.close()
        server.should_exit = True
        await task

    asyncio.run(go())
    assert seen == ["127.0.0.1"]
