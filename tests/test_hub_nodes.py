"""The hub's side of the node link, against a fake node (docs/design/multi-machine.md): pairing, the /voice/node socket,
the mirror files, and RemoteHarness. The daemon's own use of a remote session (status, routing, read-outs) is Track C's
and is tested in its files."""

import asyncio
import json
import os
import stat
import sys
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import harnesses  # noqa: E402
import hub_nodes  # noqa: E402
import nodelink  # noqa: E402
from harnesses.remote import RemoteHarness  # noqa: E402
from nodelink import HUB_FRAMES, decode, encode  # noqa: E402
from sessions import Registry, Session  # noqa: E402


class Clock:
    def __init__(self, now: float = 1_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


class Host(hub_nodes.Host):
    """What daemon.py lends the hub (Track C), recorded."""

    def __init__(self, registry: Registry):
        super().__init__()
        self.registry = registry
        self.calls: list[tuple] = []
        self.permission_wait: asyncio.Event | None = None
        self.call_up, self.approvals_terminal = True, False
        self.vendor_list = ["Anthropic", "Soniox"]
        self.register, self.drop, self.permission = self._register, self._drop, self._permission
        self.permission_gone, self.offline = self._gone, self._offline
        self.call_state = lambda: (self.call_up, self.approvals_terminal)
        self.vendors = lambda: self.vendor_list
        self.machine = lambda: "studio"

    async def _register(self, session, entry):
        self.calls.append(("register", session.id))
        existing = self.registry.sessions.get(session.id)
        if existing:
            return existing
        self.registry.add(session)
        return session

    async def _drop(self, session, why):
        self.calls.append(("drop", session.id, why))
        self.registry.remove(session.id)

    async def _permission(self, session, **request):
        self.calls.append(("permission", session.id, request))
        if self.permission_wait:
            await self.permission_wait.wait()

    async def _gone(self, session, request_id, how):
        self.calls.append(("gone", session.id, request_id, how))

    async def _offline(self, node_name, sessions):
        self.calls.append(("offline", node_name, sorted(s.id for s in sessions)))


class Pipe:
    """The hub's end of a WebSocket, with a fake node at the other end, in the same event loop."""

    def __init__(self):
        self.to_hub: asyncio.Queue = asyncio.Queue()
        self.to_node: asyncio.Queue = asyncio.Queue()
        self.closed: tuple | None = None

    async def accept(self):
        pass

    async def send_text(self, text):
        if self.closed:
            raise RuntimeError("closed")
        await self.to_node.put(text)

    async def receive_text(self):
        item = await self.to_hub.get()
        if item is None:
            raise WebSocketDisconnect(1000)
        return item

    async def close(self, code=1000, reason=None):
        if not self.closed:
            self.closed = (code, reason)
            await self.to_node.put(None)
            await self.to_hub.put(None)  # as Starlette's receive raises once the hub closed


class FakeNode:
    def __init__(self, hub, entry, sessions=(), now=None):
        self.hub, self.entry, self.pipe = hub, entry, Pipe()
        self.sessions = list(sessions)
        self.now = now
        self.task = None
        self.pings = 0

    async def connect(self, key=None, protocol=nodelink.PROTOCOL, node_id=None):
        self.task = asyncio.create_task(self.hub.serve(self.pipe))
        challenge = await self.recv("challenge")
        auth = nodelink.answer(key or self.entry["key"], challenge["nonce"], challenge["hub"]["id"])
        await self.send("hello", protocol=protocol, auth=auth, now=self.now if self.now is not None else hub_nodes.time.time(),
                        node={"id": node_id or self.entry["id"], "name": self.entry["name"], "os": "linux",
                              "arch": "x86_64", "version": "1.0.1", "harnesses": ["claude-code"]})
        return await self.recv()

    async def send(self, t, **fields):
        await self.pipe.to_hub.put(encode(t, **fields))

    async def send_sessions(self, *entries):
        await self.send("sessions", sessions=list(entries))
        await settle()

    async def recv(self, t=None, timeout=2.0):
        """The next frame (of type t), pings answered and skipped; None once the hub closed."""
        while True:
            text = await asyncio.wait_for(self.pipe.to_node.get(), timeout)
            if text is None:
                return None
            frame = decode(text, HUB_FRAMES)
            if frame["t"] == "ping":
                self.pings += 1
                await self.send("pong", id=frame["id"])
                continue
            if t is None or frame["t"] == t:
                return frame

    async def drop(self):
        await self.pipe.to_hub.put(None)
        await asyncio.wait_for(self.task, 2)


async def settle():
    for _ in range(20):
        await asyncio.sleep(0)


def entry(sid="s1", name="shop", **over):
    return {"id": sid, "name": name, "name_given": False, "cwd": f"/home/u/{name}", "pid": 4242, "harness": "claude-code",
            "home": "", "title": None, "capabilities": {"approvals": True}, "files": ["a.py"], **over}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(nodelink, "PING_SECS", 3600.0)  # no pings unless a test asks for them
    registry = Registry()
    host = Host(registry)
    clock, mono = Clock(), Clock(5000.0)
    hub = hub_nodes.Hub(tmp_path, registry, host, clock=clock, monotonic=mono)
    harnesses.set_remote(hub.wrap)
    yield hub, host, registry, clock, mono, tmp_path
    harnesses.set_remote(None)


def paired(hub, name="devbox"):
    status, body = hub.pair({"code": hub.invites.make(), "name": name, "os": "linux"}, "10.0.0.1")
    assert status == 200, body
    return hub.nodes.get(body["node_id"])


def run(coro):
    return asyncio.run(coro)


# ---------- the nodes file ----------

def test_node_keys_are_kept_0600_and_survive_a_restart(world):
    hub, host, registry, clock, mono, state = world
    node = paired(hub)
    path = state / "nodes.json"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    again = hub_nodes.NodesRegistry(path)
    assert again.get(node["id"])["key"] == node["key"] and again.hub_id == hub.nodes.hub_id
    assert len(node["key"]) == 64 and set(node) >= {"id", "name", "os", "key", "paired_at"}


def test_node_ids_never_share_the_six_hex_their_session_ids_are_prefixed_with(world, monkeypatch):
    hub = world[0]
    ids, real = iter(["aaaaaa0001", "aaaaaa0002", "bbbbbb0003"]), hub_nodes.secrets.token_hex
    monkeypatch.setattr(hub_nodes.secrets, "token_hex", lambda n: next(ids) if n == 8 else real(n))
    first, second = hub.nodes.add("one", "linux"), hub.nodes.add("two", "linux")
    assert first["id"][:6] != second["id"][:6]


# ---------- the link: challenge, hello, one connection per key ----------

def test_a_good_hello_gets_welcome_with_the_call_state_vendors_and_resume(world):
    hub, host, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        welcome = await fake.connect()
        assert welcome == {"t": "welcome", "protocol": nodelink.PROTOCOL, "call_up": True, "approvals_terminal": False,
                           "vendors": ["Anthropic", "Soniox"], "resume": {}}
        assert hub.live[node["id"]].online
        await fake.drop()

    run(go())


def test_the_challenge_names_this_hub(world):
    hub, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        fake.task = asyncio.create_task(hub.serve(fake.pipe))
        challenge = await fake.recv("challenge")
        assert challenge["hub"] == {"id": hub.nodes.hub_id, "name": "studio"} and len(challenge["nonce"]) == 64
        await fake.drop()

    run(go())


@pytest.mark.parametrize("how", ["wrong key", "unknown node", "not a hello"])
def test_a_bad_hello_is_closed_4401(world, how):
    hub, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        if how == "not a hello":
            fake.task = asyncio.create_task(hub.serve(fake.pipe))
            await fake.recv("challenge")
            await fake.send("pong", id=1)
            assert await fake.recv() is None
        else:
            kw = {"key": "cd" * 32} if how == "wrong key" else {"node_id": "f" * 16}
            assert await fake.connect(**kw) is None
        assert fake.pipe.closed[0] == nodelink.CLOSE_UNAUTHORIZED
        assert not hub.live[node["id"]].online

    run(go())


def test_an_old_protocol_is_refused_4426_with_a_reason(world, monkeypatch):
    hub, *_ = world
    monkeypatch.setattr(nodelink, "MIN_PROTOCOL", 2)
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        assert await fake.connect(protocol=1) is None
        assert fake.pipe.closed[0] == nodelink.CLOSE_TOO_OLD and "update" in fake.pipe.closed[1]

    run(go())


def test_a_second_connection_with_the_same_key_is_closed_4409_and_the_first_stays(world):
    hub, *_ = world
    node = paired(hub)

    async def go():
        first, clone = FakeNode(hub, node), FakeNode(hub, node)
        assert (await first.connect())["t"] == "welcome"
        assert await clone.connect() is None
        assert clone.pipe.closed[0] == nodelink.CLOSE_ALREADY_CONNECTED
        assert hub.live[node["id"]].online and first.pipe.closed is None
        await first.send_sessions(entry())
        assert hub.registry.sessions  # the first still talks to the hub
        await first.drop()

    run(go())


def test_a_revoked_node_cannot_connect(world):
    hub, *_ = world
    node = paired(hub)

    async def go():
        assert await hub.revoke("devbox")
        fake = FakeNode(hub, node)
        assert await fake.connect() is None and fake.pipe.closed[0] == nodelink.CLOSE_UNAUTHORIZED

    run(go())


def test_skew_is_measured_from_hello_and_shifts_time_filters(world):
    hub, host, registry, clock, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node, now=clock.now + 90)  # the node's clock is 90 s ahead
        await fake.connect()
        await fake.send_sessions(entry())
        session = registry.sessions[nodelink.hub_session_id(node["id"], "s1")]
        assert hub.live[node["id"]].skew == pytest.approx(-90)
        assert hub.node_time(session, clock.now - 60) == pytest.approx(clock.now + 30)  # "the last minute", node clock
        assert hub.node_time(Session(id="here", name="here", cwd="/"), 123.0) == 123.0  # a local session: unchanged
        await fake.drop()

    run(go())


# ---------- sessions ----------

def test_a_snapshot_registers_its_sessions_with_the_machine_set_and_no_inbox_secrets(world):
    hub, host, registry, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry(inbox_socket="/tmp/x.sock", inbox_token="t0k"))
        sid = nodelink.hub_session_id(node["id"], "s1")
        s = registry.sessions[sid]
        assert s.machine == "devbox" and s.name == "shop" and s.cwd == "/home/u/shop" and s.harness == "claude-code"
        assert s.harness_data == {"remote_id": "s1", "node_id": node["id"]}
        assert s.inbox_socket is None and s.inbox_token is None
        assert isinstance(harnesses.of(s), RemoteHarness) and s.alive()
        assert hub.files(s) == ["a.py"]
        await fake.drop()

    run(go())


def test_a_name_given_on_the_node_is_the_users(world):
    hub, host, registry, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry(name="billing", name_given=True))
        assert registry.sessions[nodelink.hub_session_id(node["id"], "s1")].named_by == "user"
        await fake.drop()

    run(go())


def test_a_session_missing_from_a_new_snapshot_has_exited(world):
    hub, host, registry, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry("s1"), entry("s2", "api"))
        await fake.send_sessions(entry("s2", "api"))
        assert ("drop", nodelink.hub_session_id(node["id"], "s1"), "exited") in host.calls
        assert list(registry.sessions) == [nodelink.hub_session_id(node["id"], "s2")]
        await fake.send("session.left", id="s2", why="exited")
        await settle()
        assert not registry.sessions
        await fake.drop()

    run(go())


def test_a_session_of_an_unknown_harness_or_with_a_bad_id_is_not_registered(world):
    hub, host, registry, *_, state = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry("../../evil"), entry("s2", harness="from-the-future"))
        assert not registry.sessions
        await fake.send("transcript", id="../../evil", gen=0, offset=0, next_offset=3, entries=["{}\n"])
        await settle()
        assert not list(state.parent.glob("evil*")) and not list(state.rglob("*evil*"))
        await fake.drop()

    run(go())


# ---------- mirrors ----------

def _line(text):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}) + "\n"


def test_transcript_frames_append_to_a_private_mirror_and_persist_the_nodes_offset(world):
    hub, host, registry, *_, state = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry())
        masked = _line("key [masked]")  # the node masked it: shorter than its 300 bytes in the node's file
        await fake.send("transcript", id="s1", gen=0, offset=0, next_offset=300, entries=[masked])
        await settle()
        s = registry.sessions[nodelink.hub_session_id(node["id"], "s1")]
        mirror = Path(harnesses.of(s).transcript_path(s))
        assert mirror == state / "harness" / "remote" / node["id"] / "s1.0.jsonl"
        assert mirror.read_text() == masked and mirror.stat().st_size != 300
        assert (mirror.parent / "s1.0.offset").read_text().strip() == "300"
        assert stat.S_IMODE(mirror.stat().st_mode) == 0o600
        assert stat.S_IMODE(mirror.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE((state / "harness" / "remote").stat().st_mode) == 0o700
        await fake.send("transcript", id="s1", gen=0, offset=300, next_offset=320, entries=[_line("more")])
        await settle()
        assert (mirror.parent / "s1.0.offset").read_text().strip() == "320" and mirror.read_text().count("\n") == 2
        await fake.drop()

    run(go())


def test_a_gap_is_refused_with_resume_from_the_stored_offset(world):
    hub, host, registry, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry())
        await fake.send("transcript", id="s1", gen=0, offset=0, next_offset=50, entries=[_line("one")])
        await fake.send("transcript", id="s1", gen=0, offset=80, next_offset=99, entries=[_line("gap")])
        assert (await fake.recv("resume"))["resume"] == {"s1": {"gen": 0, "offset": 50}}
        s = registry.sessions[nodelink.hub_session_id(node["id"], "s1")]
        assert "gap" not in Path(harnesses.of(s).transcript_path(s)).read_text()
        await fake.drop()

    run(go())


def test_after_a_hub_restart_welcome_resumes_from_the_offset_file_never_the_mirror_size(world):
    hub, host, registry, clock, mono, state = world
    node = paired(hub)

    async def first():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry())
        await fake.send("transcript", id="s1", gen=0, offset=0, next_offset=4000, entries=[_line("masked [x]")])
        await settle()
        await fake.drop()

    run(first())
    reborn = hub_nodes.Hub(state, Registry(), Host(Registry()), clock=clock, monotonic=mono)

    async def second():
        fake = FakeNode(reborn, node)
        welcome = await fake.connect()
        assert welcome["resume"] == {"s1": {"gen": 0, "offset": 4000}}
        await fake.send("transcript", id="s1", gen=0, offset=4100, next_offset=4200, entries=[_line("gap")])
        assert (await fake.recv("resume"))["resume"] == {"s1": {"gen": 0, "offset": 4000}}
        await fake.drop()

    run(second())


def test_a_repoint_moves_the_transcript_path_to_the_new_gen_and_prunes_the_old(world):
    hub, host, registry, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry())
        await fake.send("transcript", id="s1", gen=0, offset=0, next_offset=10, entries=[_line("before /clear")])
        await settle()
        s = registry.sessions[nodelink.hub_session_id(node["id"], "s1")]
        old = Path(harnesses.of(s).transcript_path(s))
        await fake.send("transcript.repointed", id="s1", gen=1)
        await settle()
        new = Path(harnesses.of(s).transcript_path(s))
        assert new.name == "s1.1.jsonl" and new.exists() and not old.exists()
        assert not old.with_suffix(".offset").exists()
        await fake.send("transcript", id="s1", gen=1, offset=0, next_offset=7, entries=[_line("after")])
        await settle()
        assert "after" in new.read_text()
        assert (await asyncio.wait_for(_resume_of(hub, node), 1)) == {"s1": {"gen": 1, "offset": 7}}
        await fake.drop()

    async def _resume_of(hub, node):
        return hub.mirrors.resume(node["id"])

    run(go())


def test_a_frame_for_a_newer_gen_is_a_repoint(world):
    hub, host, registry, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry())
        await fake.send("transcript", id="s1", gen=2, offset=0, next_offset=5, entries=[_line("new file")])
        await settle()
        s = registry.sessions[nodelink.hub_session_id(node["id"], "s1")]
        assert Path(harnesses.of(s).transcript_path(s)).name == "s1.2.jsonl"
        await fake.send("transcript", id="s1", gen=1, offset=5, next_offset=9, entries=[_line("stale gen")])
        assert (await fake.recv("resume"))["resume"] == {"s1": {"gen": 2, "offset": 5}}
        await fake.drop()

    run(go())


def test_the_follower_reads_the_mirror_and_reopens_after_a_repoint(world, monkeypatch):
    import sessions

    hub, host, registry, *_ = world
    monkeypatch.setattr(sessions, "REPOINT_EVERY_SECS", 0.05)
    node = paired(hub)
    fed = []

    async def feed(session, text, respond):
        fed.append(text)

    async def wait_for(what):
        for _ in range(100):
            if any(what in t for t in fed):
                return
            await asyncio.sleep(0.05)
        raise AssertionError(f"{what!r} never fed: {fed}")

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry())
        await fake.send("transcript", id="s1", gen=0, offset=0, next_offset=1, entries=[_line("history")])
        await settle()
        s = registry.sessions[nodelink.hub_session_id(node["id"], "s1")]
        [watcher] = harnesses.of(s).watch(s, feed)
        task = asyncio.create_task(watcher)
        await asyncio.sleep(0.2)
        await fake.send("transcript", id="s1", gen=0, offset=1, next_offset=2, entries=[_line("working on it")])
        await wait_for("working on it")
        await fake.send("transcript.repointed", id="s1", gen=1)
        await asyncio.sleep(0.4)  # the follower sees the move and opens the new mirror
        await fake.send("transcript", id="s1", gen=1, offset=0, next_offset=3, entries=[_line("after the clear")])
        await wait_for("after the clear")
        assert not any("history" in t for t in fed)
        task.cancel()
        await fake.drop()

    run(go())


def test_mirrors_of_a_departed_session_are_pruned_seven_days_after_it_left(world):
    hub, host, registry, clock, mono, state = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry("s1"), entry("s2", "api"))
        for sid in ("s1", "s2"):
            await fake.send("transcript", id=sid, gen=0, offset=0, next_offset=3, entries=[_line(sid)])
        await fake.send_sessions(entry("s2", "api"))  # s1 left
        await fake.drop()

    run(go())
    folder = state / "harness" / "remote" / node["id"]
    hub.prune()
    assert (folder / "s1.0.jsonl").exists()  # just left
    clock.now += 6 * 86400
    hub.prune()
    assert (folder / "s1.0.jsonl").exists()
    clock.now += 2 * 86400
    hub.prune()
    assert not (folder / "s1.0.jsonl").exists() and not (folder / "s1.0.offset").exists()
    assert (folder / "s2.0.jsonl").exists()  # still on the voice, however quiet


# ---------- RemoteHarness ----------

def test_alive_comes_from_node_state_with_ten_minutes_of_grace_offline(world):
    hub, host, registry, clock, mono, state = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry("s1"), entry("s2", "api"))
        s1 = registry.sessions[nodelink.hub_session_id(node["id"], "s1")]
        assert s1.alive()
        await fake.drop()
        assert ("offline", "devbox", sorted(registry.sessions)) in host.calls
        assert not hub.live[node["id"]].online and s1.alive()  # offline, kept
        mono.now += nodelink.OFFLINE_GRACE_SECS - 1
        assert s1.alive()
        mono.now += 2
        assert not s1.alive()  # _reap_dead moves it to departed

    run(go())


def test_alive_is_never_a_pid_check(world, monkeypatch):
    hub, host, registry, *_ = world
    node = paired(hub)
    monkeypatch.setattr(os, "kill", lambda *a: (_ for _ in ()).throw(AssertionError("a pid check")))

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry(pid=999999))  # no such pid on this machine
        assert registry.sessions[nodelink.hub_session_id(node["id"], "s1")].alive()
        await fake.drop()

    run(go())


def test_after_a_hub_restart_a_remote_session_is_offline_since_load_until_its_node_reconnects(world):
    hub, host, registry, clock, mono, state = world
    node = paired(hub)
    reborn = hub_nodes.Hub(state, Registry(), Host(Registry()), clock=clock, monotonic=mono)
    harnesses.set_remote(reborn.wrap)
    s = Session(id=nodelink.hub_session_id(node["id"], "s1"), name="shop", cwd="/x", machine="devbox",
                harness_data={"remote_id": "s1", "node_id": node["id"]})
    assert s.alive() and not reborn.live[node["id"]].online and reborn.live[node["id"]].since == clock.now
    mono.now += nodelink.OFFLINE_GRACE_SECS + 1
    assert not s.alive()
    unknown = Session(id="x-s1", name="x", cwd="/", machine="gone", harness_data={"remote_id": "s1", "node_id": "zz"})
    assert not unknown.alive()  # a node that is no longer paired


def test_alive_right_after_reconnect_waits_for_the_first_snapshot(world):
    hub, host, registry, clock, mono, state = world
    node = paired(hub)
    reborn = hub_nodes.Hub(state, Registry(), Host(Registry()), clock=clock, monotonic=mono)
    harnesses.set_remote(reborn.wrap)
    s = Session(id=nodelink.hub_session_id(node["id"], "s1"), name="shop", cwd="/x", machine="devbox",
                harness_data={"remote_id": "s1", "node_id": node["id"]})

    async def go():
        fake = FakeNode(reborn, node)
        await fake.connect()
        assert s.alive()  # online, no snapshot yet: not reaped in that window
        await fake.send_sessions(entry("s2", "api"))
        assert not s.alive()
        await fake.drop()

    run(go())


def test_a_remote_session_takes_its_labels_from_the_inner_adapter_and_has_no_forked_side_questions(world):
    hub, host, registry, *_ = world
    s = Session(id="n-s1", name="shop", cwd="/x", machine="devbox", harness="opencode",
                harness_data={"remote_id": "s1", "node_id": "n"})
    adapter = harnesses.of(s)
    inner = harnesses.get("opencode")
    assert isinstance(adapter, RemoteHarness)
    assert (adapter.label, adapter.agent, adapter.name, adapter.permission_deadline) == \
        (inner.label, inner.agent, inner.name, inner.permission_deadline)
    assert adapter.capabilities() == {**inner.capabilities(), "side_questions": False}
    assert adapter.noise("hello") == inner.noise("hello")
    assert run(adapter.side_question(s, "what is it doing")) is None


def test_a_send_goes_over_the_link_and_its_result_is_honoured(world):
    hub, host, registry, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry())
        s = registry.sessions[nodelink.hub_session_id(node["id"], "s1")]
        for ok in (True, False):
            sending = asyncio.create_task(harnesses.of(s).send(s, "pull the branch"))
            frame = await fake.recv("send")
            assert frame["id"] == "s1" and frame["text"] == "pull the branch"  # the node adds the voice tag
            await fake.send("send.result", req=frame["req"], ok=ok)
            assert await sending is ok
        await fake.drop()

    run(go())


def test_a_send_with_no_result_in_time_or_to_an_offline_node_is_false(world, monkeypatch):
    hub, host, registry, *_ = world
    monkeypatch.setattr(nodelink, "SEND_TIMEOUT_SECS", 0.05)
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry())
        s = registry.sessions[nodelink.hub_session_id(node["id"], "s1")]
        assert await harnesses.of(s).send(s, "pull") is False
        await fake.drop()
        assert await harnesses.of(s).send(s, "pull") is False

    run(go())


def test_leave_sends_leave(world):
    hub, host, registry, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry())
        s = registry.sessions[nodelink.hub_session_id(node["id"], "s1")]
        await harnesses.of(s).leave(s)
        assert (await fake.recv("leave"))["id"] == "s1"
        await fake.drop()

    run(go())


# ---------- permissions ----------

def _request(**over):
    return {"id": "s1", "request_id": "p1", "tool": "Bash", "description": "List files", "preview": '{"command": "ls"}',
            "readable": "run: ls", "deadline_ms": 280000, **over}


def test_holding_is_sent_on_receipt_before_the_read_out(world):
    hub, host, registry, *_ = world
    node = paired(hub)

    async def go():
        host.permission_wait = asyncio.Event()  # the read-out waits on the brain: it never finishes here
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry())
        await fake.send("permission.request", **_request())
        assert (await fake.recv("permission.holding", timeout=0.5))["request_id"] == "p1"
        await settle()
        [(_, sid, request)] = [c for c in host.calls if c[0] == "permission"]
        assert sid == nodelink.hub_session_id(node["id"], "s1")
        assert request == {"request_id": "p1", "tool": "Bash", "description": "List files", "preview": '{"command": "ls"}',
                           "readable": "run: ls", "deadline_ms": 280000}
        host.permission_wait.set()
        await fake.drop()

    run(go())


@pytest.mark.parametrize("readable,kept", [
    ("run: ls", True),
    ("run: git status in shop", True),
    ("run: echo yes", False),  # a consent word in what is read out: a yes could be heard as the request itself
    ("run: do it now", False),
    ("run: export TOKEN=sk-ant-api03-" + "x" * 40, False),  # a credential is never said aloud
    ("run: " + " ".join(["word"] * 30), False),  # too long to read out
    ("", False),
    (None, False),
])
def test_the_nodes_readable_is_used_only_after_the_cheap_checks(readable, kept):
    assert hub_nodes.checked_readable(readable) == (readable if kept else None)


def test_a_permission_request_with_an_unreadable_form_reaches_the_daemon_as_unreadable(world):
    hub, host, registry, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry())
        await fake.send("permission.request", **_request(readable="run: echo okay"))
        await fake.recv("permission.holding")
        await settle()
        [request] = [c[2] for c in host.calls if c[0] == "permission"]
        assert request["readable"] is None
        await fake.drop()

    run(go())


def test_a_pending_prompt_in_a_snapshot_is_put_to_the_user_again_once(world):
    hub, host, registry, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        pending = {k: v for k, v in _request().items() if k != "id"}
        await fake.send_sessions(entry(pending=pending))
        assert (await fake.recv("permission.holding"))["request_id"] == "p1"
        await settle()
        s = registry.sessions[nodelink.hub_session_id(node["id"], "s1")]
        s.permission_id = "p1"  # what the daemon's put did
        await fake.send_sessions(entry(pending=pending, title="a new title"))
        assert len([c for c in host.calls if c[0] == "permission"]) == 1
        await fake.drop()

    run(go())


def test_a_resolved_prompt_clears_the_card(world):
    hub, host, registry, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry())
        await fake.send("permission.resolved", id="s1", request_id="p1", how="terminal")
        await settle()
        assert ("gone", nodelink.hub_session_id(node["id"], "s1"), "p1", "terminal") in host.calls
        await fake.drop()

    run(go())


def test_a_verdict_goes_out_as_permission_answer_and_the_nodes_refusal_comes_back(world):
    hub, host, registry, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry())
        s = registry.sessions[nodelink.hub_session_id(node["id"], "s1")]
        answering = asyncio.create_task(hub.answer(s, "p1", "allow", "voice", spoken="run: ls"))
        frame = await fake.recv("permission.answer")
        assert frame == {"t": "permission.answer", "id": "s1", "request_id": "p1", "verdict": "allow", "how": "voice",
                         "spoken": "run: ls"}
        await fake.send("permission.answered", request_id="p1", ok=False, why="stale")
        assert await answering == (False, "stale")
        tapped = asyncio.create_task(hub.answer(s, "p2", "deny", "tap"))
        frame = await fake.recv("permission.answer")
        assert "spoken" not in frame
        await fake.send("permission.answered", request_id="p2", ok=True)
        assert await tapped == (True, None)
        await fake.drop()
        assert await hub.answer(s, "p3", "allow", "tap") == (False, "offline")

    run(go())


def test_the_call_state_reaches_every_node(world):
    hub, host, registry, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        host.call_up, host.approvals_terminal = True, True
        await hub.call_changed()
        assert await fake.recv("call") == {"t": "call", "up": True, "approvals_terminal": True}
        await fake.drop()

    run(go())


# ---------- heartbeat, revoke, bye ----------

def test_a_silent_node_is_closed_4408_and_its_sessions_go_offline_not_away(world, monkeypatch):
    hub, host, registry, clock, mono, state = world
    monkeypatch.setattr(nodelink, "PING_SECS", 0.01)
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry())
        mono.now += nodelink.DEAD_AFTER_SECS + 1  # no pong in time
        await asyncio.wait_for(fake.task, 2)
        assert fake.pipe.closed[0] == nodelink.CLOSE_DEAD
        assert not hub.live[node["id"]].online and hub.live[node["id"]].since == clock.now
        assert list(registry.sessions) == [nodelink.hub_session_id(node["id"], "s1")]

    run(go())


def test_pings_carry_the_round_trip(world, monkeypatch):
    hub, *_ = world
    monkeypatch.setattr(nodelink, "PING_SECS", 0.01)
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        rtts = []
        while 0 not in rtts and len(rtts) < 20:
            ping = decode(await asyncio.wait_for(fake.pipe.to_node.get(), 1), HUB_FRAMES)
            rtts.append(ping["rtt_ms"])
            await fake.send("pong", id=ping["id"])
        assert rtts[0] is None and 0 in rtts and hub.live[node["id"]].rtt_ms == 0  # the clock stood still
        await fake.drop()

    run(go())


def test_revoke_sends_unpaired_closes_the_link_and_takes_its_sessions_off(world):
    hub, host, registry, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry())
        assert await hub.revoke("devbox")
        assert (await fake.recv("unpaired"))["t"] == "unpaired"
        assert await fake.recv() is None
        assert ("drop", nodelink.hub_session_id(node["id"], "s1"), "revoked") in host.calls
        assert hub.nodes.get(node["id"]) is None and node["id"] not in hub.live
        assert not await hub.revoke("devbox")

    run(go())


def test_bye_forgets_the_node(world):
    hub, host, registry, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry())
        await fake.send("bye")
        await asyncio.wait_for(fake.task, 2)
        assert hub.nodes.get(node["id"]) is None and not registry.sessions

    run(go())


def test_machines_lists_each_node_for_status(world):
    hub, host, registry, clock, *_ = world
    node = paired(hub)
    assert hub.machines() == [{"id": node["id"], "name": "devbox", "here": False, "os": "linux", "online": False,
                               "since": clock.now, "sessions": 0, "rtt_ms": None,
                               "key_fp": nodelink.fingerprint(node["key"])}]

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry(), entry("s2", "api"))
        [m] = hub.machines()
        assert m["online"] and m["since"] is None and m["sessions"] == 2
        await fake.drop()

    run(go())


# ---------- pairing ----------

def test_pairing_with_the_code_returns_a_key_and_records_who_paired(world):
    hub, host, registry, clock, mono, state = world
    code = hub.invites.make()
    status, body = hub.pair({"code": code, "name": "devbox", "os": "linux", "arch": "x86_64", "version": "1.0.1"},
                            "100.101.5.7")
    assert status == 200
    assert set(body) == {"node_id", "node_key", "hub", "vendors"} and len(body["node_key"]) == 64
    assert body["hub"] == {"id": hub.nodes.hub_id, "name": "studio"} and body["vendors"] == ["Anthropic", "Soniox"]
    assert hub.nodes.get(body["node_id"])["key"] == body["node_key"]
    assert hub.invites.paired == {"name": "devbox", "address": "100.101.5.7", "network": "Tailscale",
                                  "key_fp": nodelink.fingerprint(body["node_key"])}
    assert not hub.invites.outstanding


def test_the_invite_name_wins_over_the_nodes(world):
    hub = world[0]
    code = hub.invites.make(name="buildbox")
    status, body = hub.pair({"code": code, "name": "ubuntu-22", "os": "linux"}, "192.168.1.9")
    assert status == 200 and hub.nodes.get(body["node_id"])["name"] == "buildbox"
    assert hub.invites.paired["network"] == "LAN"


def test_an_invite_code_is_8_letters_of_32_and_kept_only_hashed_on_the_hub(world):
    hub, *_, state = world
    code = hub.invites.make()
    letters = code.replace("-", "")
    assert len(letters) == 8 and set(letters) <= set(hub_nodes.CODE_ALPHABET) and len(hub_nodes.CODE_ALPHABET) == 32
    assert not any(code in p.read_text(errors="ignore") or letters in p.read_text(errors="ignore")
                   for p in state.rglob("*") if p.is_file())
    assert hub.pair({"code": letters.lower(), "name": "devbox", "os": "linux"}, "10.0.0.2")[0] == 200  # typed loosely


def test_the_invite_expires_after_ten_minutes_of_the_hubs_monotonic_clock(world):
    hub, host, registry, clock, mono, state = world
    code = hub.invites.make()
    clock.now -= 3600  # the wall clock is not what counts
    mono.now += hub_nodes.INVITE_SECS + 1
    assert hub.pair({"code": code, "name": "devbox", "os": "linux"}, "10.0.0.2") == (403, "invite expired")


def test_cancel_closes_the_route(world):
    hub = world[0]
    code = hub.invites.make()
    hub.invites.cancel()
    assert hub.pair({"code": code, "name": "devbox", "os": "linux"}, "10.0.0.2") == (403, "no invite outstanding")


@pytest.mark.parametrize("name,why", [
    ("dev", "cannot be picked by voice"),
    ("studio", "this Mac"),
    ("shop", "shop/main"),
    ("taken", "already paired"),
    ("bad*name!", "letters"),
])
def test_a_node_name_the_voice_could_not_tell_apart_is_refused(world, name, why):
    hub, host, registry, *_ = world
    hub.nodes.add("taken", "linux")
    registry.add(Session(id="local1", name="shop/main", cwd="/x"))
    code = hub.invites.make()
    status, message = hub.pair({"code": code, "name": name, "os": "linux"}, "10.0.0.2")
    assert status == 409 and why in message
    assert hub.invites.outstanding  # a refused name does not use the code up


def test_rate_limit_is_five_a_minute_per_address_and_ten_in_all(world):
    hub, host, registry, clock, mono, state = world
    hub.invites.make()
    bad = {"code": "AAAA-AAAA", "name": "devbox", "os": "linux"}
    assert [hub.pair(bad, "10.0.0.2")[0] for _ in range(6)] == [403] * 5 + [429]
    assert [hub.pair(bad, f"10.0.1.{i}")[0] for i in range(6)] == [403] * 5 + [429]  # ten in all
    mono.now += 61
    assert hub.pair(bad, "10.0.0.2")[0] == 403


def test_a_used_code_cannot_pair_twice(world):
    hub = world[0]
    code = hub.invites.make()
    assert hub.pair({"code": code, "name": "devbox", "os": "linux"}, "10.0.0.2")[0] == 200
    assert hub.pair({"code": code, "name": "other", "os": "linux"}, "10.0.0.3") == (403, "no invite outstanding")
