"""Defects a bug hunt proved in multi-machine at cc48926, each as the scenario that showed it
(docs/design/multi-machine.md is the contract). Ordered as found."""

import asyncio
import json
import math
import sys
from pathlib import Path

import pytest
from aiohttp import web
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harnesses  # noqa: E402
import hub_nodes  # noqa: E402
import node as node_mod  # noqa: E402
import nodelink  # noqa: E402
import sessions  # noqa: E402
from guards import LocalAuth  # noqa: E402
from remote import TLS_PORT, Remote  # noqa: E402
from test_hub_nodes import FakeNode, _line, entry, paired, run, settle, world  # noqa: E402,F401  (world is a fixture)
from test_node import FakeHub, _body, _pair  # noqa: E402
from test_node import run as node_run  # noqa: E402
from test_orchestrator import d  # noqa: E402,F401  (d is a fixture)


# ---------- 1. a hello timeout is closed with the revocation code, and the node deletes its key ----------

def test_silence_before_hello_is_not_closed_with_the_revocation_code(world, monkeypatch):
    """A node that connects and then stalls (laptop lid closed, slow VPN) must not be told it was revoked."""
    hub, *_ = world
    monkeypatch.setattr(hub_nodes, "HELLO_WAIT_SECS", 0.05)
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        fake.task = asyncio.create_task(hub.serve(fake.pipe))
        await fake.recv("challenge")
        await asyncio.wait_for(fake.task, 2)  # never sends hello
        return fake.pipe.closed

    code, reason = run(go())
    assert code == nodelink.CLOSE_BAD_HELLO, f"a hello timeout is closed {code} {reason!r}: the node reads 4401 as revoked"


class _TimingOutHub(FakeHub):
    """A hub that gives up waiting for hello (hub_nodes.serve's `no hello` path): challenge, then its close code."""

    async def _ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.connections += 1
        await ws.send_str(nodelink.encode("challenge", nonce=nodelink.new_nonce(), hub=self.HUB))
        await ws.close(code=nodelink.CLOSE_BAD_HELLO, message=b"no hello")
        return ws


def test_a_node_keeps_its_key_when_the_hub_only_timed_out_waiting_for_hello(tmp_path):
    async def go():
        hub = _TimingOutHub(tmp_path)
        await hub.start()
        state = tmp_path / "state"
        _pair(state, hub)
        (state / "token").write_text("t0k3n")
        n = node_mod.Node(state, port=0)
        n.backoff = lambda attempt: 0.1
        await n.start()
        try:
            for _ in range(50):
                if hub.connections >= 1 and n.link_error:
                    break
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.2)
            return (state / "node_keys" / hub.HUB["id"]).exists(), n.finished.is_set(), n.link_error
        finally:
            await n.stop()
            await hub.stop()

    key_kept, finished, error = asyncio.run(go())
    assert key_kept and not finished, f"the node unpaired itself after a transient: {error!r}"


# ---------- 2. the phone app cannot reach /voice/hub/* over the TLS listener ----------

HOST = "phone.example.internal"


@pytest.mark.xfail(strict=True, reason="guards._PHONE_PATHS: fixed on the mm-wire branch, not here")
def test_the_phone_key_reaches_the_hub_routes_over_the_tls_listener(tmp_path, monkeypatch):
    """ios/Pointe/API.swift posts voice/hub/invite and voice/hub/revoke with the phone key; guards must let it through."""
    monkeypatch.setattr(sessions, "MACHINES", {})
    (tmp_path / "remote.json").write_text(json.dumps({"host": HOST}))
    (tmp_path / "remote_token").write_text("s3cret-token")
    remote = Remote(tmp_path)
    app = FastAPI()
    app.middleware("http")(remote.guard)
    hub = hub_nodes.Hub(tmp_path, sessions.Registry(), host=type("H", (), {})())
    hub_nodes.install(app, hub, link=lambda code: f"pointe://hub?v=1&host={HOST}&port={TLS_PORT}&fp={'ab' * 32}&code={code}")
    app.add_middleware(LocalAuth, token="daemon-token", page_key="page-key", remote=remote,
                       phone=lambda authorization: authorization == "Bearer phone-key")
    client = TestClient(app, base_url=f"https://{HOST}:{TLS_PORT}", follow_redirects=False)
    headers = {"Authorization": "Bearer phone-key"}
    made = client.post("/voice/hub/invite", json={}, headers=headers)
    assert made.status_code == 200, f"the app's Invite a machine gets {made.status_code}: {made.text!r}"
    assert client.get("/voice/hub/nodes", headers=headers).status_code == 200
    assert client.post("/voice/hub/revoke", json={"name": "nobody"}, headers=headers).status_code == 404


# ---------- 3. a prompt re-offered after a link drop is swallowed by the hub's dedupe ----------

@pytest.mark.xfail(strict=True, reason="daemon.remote_permission's dedupe: fixed on the mm-wire branch, not here")
def test_a_prompt_reoffered_after_a_link_drop_is_put_to_the_user_again(d, monkeypatch):
    """The voice said the approval went back to its terminal; when the node comes back within its grace window and
    re-sends the same request, the design puts it to the user again. The hub's "same request twice" dedupe eats it."""
    monkeypatch.setattr(sessions, "MACHINES", {"devbox": sessions.Machine(name="devbox", id="n1", online=True)})
    puts, said = [], []

    async def put(session, request_id, *a, **k):
        puts.append(request_id)
        session.permission_id = request_id

    async def say(text):
        said.append(text)

    monkeypatch.setattr(d, "_put_permission", put)
    monkeypatch.setattr(d, "say", say)
    d.state.conn = object()  # a call is up
    s = sessions.Session(id="n1-s1", name="shop", cwd="/x", machine="devbox", harness="claude-code",
                         harness_data={"remote_id": "s1", "node_id": "n1"})
    d.REGISTRY.add(s)

    async def go():
        assert await d.remote_permission(s, "req1", "Bash", "d", "{}", "run: git status") is True
        assert await d.remote_permission(s, "req1", "Bash", "d", "{}", "run: git status") is True  # snapshot + frame: once
        assert puts == ["req1"]
        sessions.MACHINES["devbox"].online = False  # the link dropped
        await d._watch_machines()
        assert said and "went back to its terminal" in said[-1]
        sessions.MACHINES["devbox"].online = True  # back within the node's grace window: it re-offers req1
        await d.remote_permission(s, "req1", "Bash", "d", "{}", "run: git status")
        assert puts == ["req1", "req1"], "the re-offer was not put to the user again: the voice's last word was 'went back to its terminal'"

    run(go())


# ---------- 4. a backlog re-shipped at a new gen of a known session is fed as news ----------

def test_a_hub_ahead_in_gen_makes_the_node_reship_its_whole_file_as_history(tmp_path):
    """The node has no tail state (left and rejoined); the hub's mirror is at gen 2. The node cannot adopt the hub's
    offset, so it bumps to gen 3 and ships the file from byte 0: a backlog, and it says so."""
    lines = [json.dumps({"n": i}) + "\n" for i in range(3)]
    hub_id = nodelink.hub_session_id("abc123" + "0" * 26, "sess-1")

    async def scenario(hub, n):
        body = _body(tmp_path)
        Path(body["transcript"]).write_text("".join(lines))
        await n.register(body)
        repointed = await hub.next("transcript.repointed")
        frame = await hub.next("transcript")
        return repointed, frame

    repointed, frame = node_run(scenario, tmp_path, resume={hub_id: {"gen": 2, "offset": 5}})
    assert repointed["gen"] == 3 and frame["offset"] == 0 and frame["entries"] == lines
    assert repointed.get("history") is True, "nothing in transcript.repointed tells the hub this gen opens with a backlog"


def test_a_backlog_arriving_at_a_new_gen_of_a_known_session_is_not_fed_as_news(world, monkeypatch):
    """The session already has a mirror (gen 0) and the follower is live on it. The node re-ships its file as history
    at gen 1: the hub must hold it back as it holds a first-join backlog, so the follower never reads it as reports."""
    hub, host, registry, *_ = world
    monkeypatch.setattr(sessions, "REPOINT_EVERY_SECS", 0.05)
    monkeypatch.setattr(hub_nodes, "HISTORY_QUIET_SECS", 0.3)
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
        await fake.send("transcript", id="s1", gen=0, offset=0, next_offset=1, entries=[_line("earlier")])
        await asyncio.sleep(0.5)  # the first-join backlog is promoted
        s = registry.sessions[nodelink.hub_session_id(node["id"], "s1")]
        [watcher] = harnesses.of(s).watch(s, feed)
        task = asyncio.create_task(watcher)
        await asyncio.sleep(0.2)
        await fake.send("transcript", id="s1", gen=0, offset=1, next_offset=2, entries=[_line("working on it")])
        await wait_for("working on it")  # the follower is live on gen 0
        await fake.send("transcript.repointed", id="s1", gen=1, history=True)
        await settle()
        assert hub.mirrors.in_backlog(node["id"], "s1")
        for i in range(3):
            await fake.send("transcript", id="s1", gen=1, offset=i, next_offset=i + 1, entries=[_line(f"old {i}")])
            await asyncio.sleep(0.05)
        await asyncio.sleep(1.6)  # promoted, and the follower's once-a-second look for the file has found it
        await fake.send("transcript", id="s1", gen=1, offset=3, next_offset=4, entries=[_line("new work")])
        await wait_for("new work")  # the follower moved to the promoted mirror and reads what comes after it
        task.cancel()
        await fake.drop()

    run(go())
    assert not any("old" in t for t in fed), f"history re-shipped at a new gen was fed as news: {fed}"


# ---------- 5. a hub restart in the middle of a backlog leaves the .part file forever ----------

@pytest.mark.parametrize("rest", [
False, True])
def test_a_backlog_part_file_left_by_a_hub_restart_becomes_the_mirror(world, monkeypatch, rest):
    """With nothing more to come (the hub had it all) the .part must still be promoted; with the rest of the backlog
    still crossing, it stays history until it is all here."""
    hub, host, registry, clock, mono, tmp = world
    monkeypatch.setattr(hub_nodes, "HISTORY_QUIET_SECS", 3600.0)  # the hub dies before the backlog is promoted
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry())
        await fake.send("transcript.repointed", id="s1", gen=0)
        await fake.send("transcript", id="s1", gen=0, offset=0, next_offset=1, entries=[_line("whole history")])
        await settle()
        await fake.drop()
        monkeypatch.setattr(hub_nodes, "HISTORY_QUIET_SECS", 0.2)
        again = hub_nodes.Hub(tmp, registry, host, clock=clock, monotonic=mono)  # the daemon restarts
        fake2 = FakeNode(again, again.nodes.get(node["id"]))
        welcome = await fake2.connect()
        await fake2.send_sessions(entry())
        if rest:  # the rest of the backlog, resumed where the hub's offset file says: still history, not news
            await fake2.send("transcript", id="s1", gen=0, offset=1, next_offset=2, entries=[_line("more history")])
        await settle()
        still_backlog = again.mirrors.in_backlog(node["id"], "s1")
        for _ in range(20):
            await asyncio.sleep(0.05)
        s = registry.sessions[nodelink.hub_session_id(node["id"], "s1")]
        path = Path(again.transcript_path(s))
        await fake2.drop()
        return welcome["resume"], still_backlog, path, again.mirrors.in_backlog(node["id"], "s1")

    resume, still_backlog, path, in_backlog = run(go())
    assert resume == {"s1": {"gen": 0, "offset": 1}}
    assert still_backlog, "the rest of the backlog after a restart was written live"
    assert path.exists() and not in_backlog, "the follower waits on a mirror that never appears until the next live line"
    assert path.read_text().count("history") == (2 if rest else 1)


# ---------- 6. a NaN or infinite clock in hello is accepted ----------

@pytest.mark.xfail(strict=True, reason="fixed in a later commit")
@pytest.mark.parametrize("now", [float("nan"), float("inf")])
def test_a_hello_with_a_non_finite_clock_is_refused(world, now):
    """`since` filters on that node's mirrors compare against the skew: a NaN one never applies."""
    hub, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node, now=now)
        welcome = await fake.connect()
        skew = sessions.MACHINES["devbox"].skew
        await fake.drop()
        return welcome, skew

    welcome, skew = run(go())
    assert welcome is None or math.isfinite(skew), f"welcomed with skew {skew!r}"


# ---------- 7. an unreadable nodes.json is replaced at once by an empty one with a new hub id ----------

@pytest.mark.xfail(strict=True, reason="fixed in a later commit")
def test_a_corrupt_nodes_file_is_moved_aside_and_the_hub_id_kept(tmp_path):
    """A new hub id means every node says 'another hub answers' forever and never re-pairs on its own."""
    path = tmp_path / "nodes.json"
    first = hub_nodes.NodesRegistry(path)
    first.add("devbox", "linux")
    hub_id = first.hub_id
    torn = '{"hub_id": "' + hub_id + '", "nodes": [{"id": "x", '
    path.write_text(torn)
    again = hub_nodes.NodesRegistry(path)
    assert again.hub_id == hub_id
    assert not path.exists(), "a parse error must not save over the file"
    [aside] = tmp_path.glob("nodes.json.broken*")
    assert aside.read_text() == torn
    assert hub_nodes.NodesRegistry(path).hub_id == hub_id  # a second restart before any save keeps it too


# ---------- 8. transcript lines split on a bare carriage return ----------

@pytest.mark.xfail(strict=True, reason="fixed in a later commit")
def test_transcript_frames_survive_a_bare_carriage_return_inside_a_line():
    data = b'{"a": "x\ry"}\n{"b": 2}\n'
    frames, nxt = nodelink.transcript_frames("s1", 0, 0, data)
    assert nxt == len(data)
    assert [e for f in frames for e in json.loads(f)["entries"]] == ['{"a": "x\ry"}\n', '{"b": 2}\n']


@pytest.mark.xfail(strict=True, reason="fixed in a later commit")
def test_masked_frames_survive_a_bare_carriage_return_inside_a_line():
    data = b'{"a": "x\ry"}\n{"b": 2}\n'
    frames, nxt = node_mod.masked_frames("s1", 0, 0, data)
    assert nxt == len(data)
    assert [e for f in frames for e in json.loads(f)["entries"]] == ['{"a": "x\ry"}\n', '{"b": 2}\n']
