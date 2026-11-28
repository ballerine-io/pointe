"""Defects a bug hunt proved in multi-machine at a pre-release build, each as the scenario that showed it
(docs/design/multi-machine.md is the contract). Ordered as found."""

import asyncio
import json
import math
import os
import sys
from pathlib import Path

import pytest
from aiohttp import web
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]
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
from test_mixed_harnesses import node  # noqa: E402,F401  (a fixture)
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


def test_the_phone_key_reaches_the_hub_routes_over_the_tls_listener(tmp_path, monkeypatch):
    """apps/PointeKit/Sources/PointeUI/API.swift posts voice/hub/invite and voice/hub/revoke with the phone key; guards must let it through."""
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

def test_a_prompt_reoffered_after_a_link_drop_is_put_to_the_user_again(d, monkeypatch):
    """The voice said the approval waits for the machine; when the node comes back within its grace window on a new
    link and re-sends the same request, the design puts it to the user again. The hub's "same request twice" dedupe
    ate it."""
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
        assert said and "waits up to" in said[-1]
        sessions.MACHINES["devbox"].online = True  # back within the node's grace window, on a new link: it re-offers req1
        sessions.MACHINES["devbox"].link += 1  # as hub_nodes.serve counts each link it accepts
        await d.remote_permission(s, "req1", "Bash", "d", "{}", "run: git status")
        assert puts == ["req1", "req1"], "the re-offer on a new link was not put to the user again"

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

@pytest.mark.parametrize("now", [float("nan"), float("inf")])
def test_a_hello_with_a_non_finite_clock_is_refused(world, now):
    """`since` filters on that node's mirrors compare against the skew: a NaN one never applies."""
    hub, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        fake.task = asyncio.create_task(hub.serve(fake.pipe))
        challenge = await fake.recv("challenge")
        hello = {"t": "hello", "protocol": nodelink.PROTOCOL, "now": now,
                 "auth": nodelink.answer(node["key"], challenge["nonce"], challenge["hub"]["id"]),
                 "node": {"id": node["id"], "name": "devbox", "os": "linux", "arch": "x86_64", "version": "1",
                          "harnesses": []}}
        await fake.pipe.to_hub.put(json.dumps(hello))  # json.dumps writes NaN and Infinity; encode() refuses them
        welcome = await fake.recv()
        await asyncio.wait_for(fake.task, 2)
        return welcome, sessions.MACHINES["devbox"].skew, fake.pipe.closed

    welcome, skew, closed = run(go())
    assert welcome is None and skew == 0.0, f"welcomed with skew {skew!r}"
    assert closed[0] == nodelink.CLOSE_BAD_HELLO


# ---------- 7. an unreadable nodes.json is replaced at once by an empty one with a new hub id ----------

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

def test_transcript_frames_survive_a_bare_carriage_return_inside_a_line():
    data = b'{"a": "x\ry"}\n{"b": 2}\n'
    frames, nxt = nodelink.transcript_frames("s1", 0, 0, data)
    assert nxt == len(data)
    assert [e for f in frames for e in json.loads(f)["entries"]] == ['{"a": "x\ry"}\n', '{"b": 2}\n']


def test_masked_frames_survive_a_bare_carriage_return_inside_a_line():
    data = b'{"a": "x\ry"}\n{"b": 2}\n'
    frames, nxt = node_mod.masked_frames("s1", 0, 0, data)
    assert nxt == len(data)
    assert [e for f in frames for e in json.loads(f)["entries"]] == ['{"a": "x\ry"}\n', '{"b": 2}\n']


# ---------- 9. a deny is refused once the node's approvals turned terminal mid-hold ----------

def test_a_deny_releases_a_held_prompt_even_after_approvals_turned_terminal_on_the_node(tmp_path):
    """The re-check table: a deny releases the hook always. Approvals: terminal set while the prompt is held must not
    turn the user's no into a refusal that leaves the prompt hanging until its deadline."""
    from test_node import READABLE, _answer, _prompt

    async def scenario(hub, n):
        task, frame = await _prompt(hub, n, tmp_path, READABLE)
        (tmp_path / "state" / "config.json").write_text(json.dumps({"approvals": "terminal"}))
        answered = await _answer(hub, frame, "deny", how="tap")
        assert answered["ok"] is True, f"the no was refused: {answered}"
        assert await asyncio.wait_for(task, 2) == "deny"

    node_run(scenario, tmp_path)


# ---------- 10. the collision suffix makes this Mac's own name an alias of one session ----------

def test_a_local_session_that_joins_after_a_remote_one_is_not_named_after_this_mac(d, node):
    """This Mac's name is never an alias (every "on this Mac" would match). Suffixing a late local "web" with it made
    "go to studio" pick that one session, though api runs on studio too."""
    from test_mixed_harnesses import _join
    from test_orchestrator import add, client_for

    add(d, "cc1", "api", "/repos/api")
    _join(d, "laptop", "w1", "web")
    joined = client_for(d).post("/voice/register", headers={"authorization": "Bearer secret"},
                                json={"id": "cc2", "name": "web", "cwd": "/repos/web", "pid": os.getpid(),
                                      "transcript": "/tmp/none.jsonl", "name_given": True}).json()
    assert "studio" not in joined["name"]
    assert sessions.name_groups("go to studio", list(d.REGISTRY.sessions.values())) == []


# ---------- 11. node-supplied strings reach the brain's context and the screens at any length ----------

def test_strings_from_a_node_are_cut_before_they_reach_the_daemon(world):
    """A frame may be 1 MB: a node's folder goes into the brain's context every turn, a prompt's description and preview
    into the read-out and the cards, its read-out into the voice."""
    from test_hub_nodes import _request

    hub, host, registry, *_ = world
    node = paired(hub)
    huge = "x" * 200_000

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry(cwd="/home/" + huge, home="/h/" + huge, title=huge, files=[huge]))
        await fake.send("files", id="s1", names=[huge, "ok.py"])
        await fake.send("permission.request", **_request(tool="T" * 50_000, description=huge, preview=huge,
                                                          readable="run: " + huge))
        await fake.recv("permission.holding", timeout=1)
        await fake.drop()

    run(go())
    s = registry.sessions[nodelink.hub_session_id(node["id"], "s1")]
    assert len(s.cwd) <= 4096
    assert all(len(f) <= 4096 for f in s.harness_data["files"])
    [call] = [c for c in host.calls if c[0] == "permission"]
    _, _, _, tool, description, preview, readable = call
    assert len(tool) <= 200 and len(description) <= 2_000 and len(preview) <= 20_100
    assert readable is None  # too long to be read out: never cut, since a voice yes must match it exactly


# ---------- 12. a node can fill the hub's disk with mirrors ----------

def test_a_nodes_mirrors_stop_growing_at_its_cap_and_the_link_stays_in_step(world, monkeypatch):
    """Each frame is capped, but nothing capped their sum: a runaway or hostile node filled the hub's disk."""
    hub, host, registry, *_ = world
    monkeypatch.setattr(hub_nodes, "MAX_MIRROR_BYTES_PER_NODE", 3000, raising=False)
    node = paired(hub)
    line = _line("y" * 900)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry(), entry("s2", "api"))
        offset = {"s1": 0, "s2": 0}
        for i in range(6):
            sid = ("s1", "s2")[i % 2]
            n = len(line.encode())
            await fake.send("transcript", id=sid, gen=0, offset=offset[sid], next_offset=offset[sid] + n, entries=[line])
            offset[sid] += n
            await settle()
        with pytest.raises(asyncio.TimeoutError):  # no resume: the hub stays in step with the node's offsets
            await fake.recv("resume", timeout=0.2)
        await fake.drop()
        return offset

    offset = run(go())
    folder = hub.mirrors.root / node["id"]
    used = sum(p.stat().st_size for p in folder.glob("*.jsonl*"))
    assert used <= 3000, f"{used} bytes of mirrors for one node"
    assert hub.mirrors.resume(node["id"]) == {sid: {"gen": 0, "offset": at} for sid, at in offset.items()}


# ---------- 13. behind a connector every attempt is from 127.0.0.1: a guesser locks the real node out ----------

def test_wrong_codes_from_the_connector_do_not_lock_out_the_right_one(world):
    """Through bin/voice-connector every pairing attempt arrives from 127.0.0.1, so the per-address limit is shared with
    the real node. A guesser there delays it until a token is back, never for the invite's whole life, and cannot
    cancel the invite."""
    hub, host, registry, clock, mono, _ = world
    code = hub.invites.make()
    wrong = {"code": "AAAA-AAAA" if code != "AAAA-AAAA" else "BBBB-BBBB", "name": "devbox", "os": "linux"}
    assert [hub.pair(wrong, "127.0.0.1")[0] for _ in range(6)] == [403] * 5 + [429]
    assert hub.pair({"code": code, "name": "devbox", "os": "linux"}, "127.0.0.1")[0] == 429  # not compared
    mono.now += 60
    status, body = hub.pair({"code": code, "name": "devbox", "os": "linux"}, "127.0.0.1")
    assert status == 200, body


def test_an_invite_is_cancelled_after_too_many_wrong_codes_and_says_from_where(world):
    """The backstop: PAIR_WRONG_PER_INVITE wrong codes from all addresses together end the invite, and the owner sees
    how many came and from which addresses."""
    hub, *_ = world
    code = hub.invites.make()
    wrong = {"code": "AAAA-AAAA" if code != "AAAA-AAAA" else "BBBB-BBBB", "name": "devbox", "os": "linux"}
    addresses = [f"192.168.1.{i // 4 + 10}" for i in range(hub_nodes.PAIR_WRONG_PER_INVITE)]  # 4 each, under the burst
    for i, address in enumerate(addresses[:-1]):
        assert hub.pair(wrong, address)[0] == 403
        assert hub.invites.status()["wrong_codes"] == i + 1
    status, why = hub.pair(wrong, addresses[-1])
    assert status == 403 and why == hub_nodes.NO_SUCH_INVITE  # the guesser is told nothing; the owner is, below
    assert hub.invites.status() is None
    assert hub.pair({"code": code, "name": "devbox", "os": "linux"}, "192.168.1.99")[0] == 403  # the code is gone
    assert hub.invites.ended.startswith("the invite was cancelled after")
    assert all(a in hub.invites.ended for a in set(addresses)) and "LAN" in hub.invites.ended


def test_the_page_and_the_app_are_shown_an_invite_cancelled_by_guessing(d, monkeypatch):
    import remote
    from types import SimpleNamespace

    from test_orchestrator import client_for

    monkeypatch.setattr(harnesses.HOST, "invite", lambda: None, raising=False)
    monkeypatch.setattr(harnesses.HOST, "invite_ended", lambda: "the invite was cancelled after 20 wrong codes, from "
                        "100.64.0.66 (Tailscale): 20", raising=False)
    assert "100.64.0.66" in client_for(d).get("/voice/status").json()["invite_ended"]
    tls_page = SimpleNamespace(scope={"server": ("studio", remote.TLS_PORT), "state": {}})
    assert d._invite_ended(tls_page) is None  # as the code itself: never to a page over the TLS listener
    page = (Path(__file__).resolve().parents[1] / "pointe" / "ui.html").read_text()
    assert "s.invite_ended" in page and 'id="mach-ended"' in page


def test_one_address_cannot_cancel_an_invite_by_guessing(world):
    """Twenty wrong codes in two seconds from one address used to cancel the invite. Its token bucket is taken from
    before the code is compared, and refills too slowly for one address to reach the cap in the invite's life."""
    hub, host, registry, clock, mono, _ = world
    code = hub.invites.make()
    wrong = {"code": "AAAA-AAAA" if code != "AAAA-AAAA" else "BBBB-BBBB", "name": "devbox", "os": "linux"}
    answers = []
    for _ in range(hub_nodes.INVITE_SECS - 1):  # a guess every second, the invite's whole life
        answers.append(hub.pair(wrong, "100.64.0.66")[0])
        mono.now += 1
    assert hub.invites.outstanding and hub.invites.wrong < hub_nodes.PAIR_WRONG_PER_INVITE
    assert answers.count(403) == hub.invites.wrong and set(answers) == {403, 429}
    status, body = hub.pair({"code": code, "name": "devbox", "os": "linux"}, "100.64.0.7")  # the real node
    assert status == 200, body


# ---------- 14. a node that crashed waits out the hub's heartbeat before it can link again ----------


@pytest.mark.parametrize("new_address, told", [("203.0.113.9", True), ("100.64.0.7", False)])
def test_a_takeover_from_another_address_is_said_on_the_machine_and_one_from_the_same_is_not(world, monkeypatch,
                                                                                             new_address, told):
    """multi-machine.md, "a stolen node key": a new connection with a node's key that replaces its silent link from
    another address puts one line on the machine's row, naming both addresses, so the owner can revoke it. The same
    address (the node itself reconnecting) says nothing."""
    from test_hub_nodes import Pipe

    class At(Pipe):
        def __init__(self, host):
            super().__init__()
            self.client = type("Client", (), {"host": host})()

    hub, *_ = world
    monkeypatch.setattr(hub_nodes, "STALE_PROBE_SECS", 0.2, raising=False)
    node = paired(hub)

    async def go():
        old, new = FakeNode(hub, node), FakeNode(hub, node)
        old.pipe, new.pipe = At("100.64.0.7"), At(new_address)
        assert (await old.connect())["t"] == "welcome"
        assert (await new.connect())["t"] == "welcome"  # old never answers its ping: stale, replaced
        await new.drop()

    run(go())
    notice = sessions.MACHINES[node["name"]].notice
    if told:
        assert "203.0.113.9" in notice and "100.64.0.7" in notice and "revoke" in notice, notice
    else:
        assert notice == ""

def test_a_new_connection_replaces_an_old_link_that_no_longer_answers(world, monkeypatch):
    """The laptop slept or the node's machine rebooted: its old link stays open on the hub, silent, until the heartbeat
    gives up (about 15 s), and every reconnect meanwhile is refused 4409. A new connection with the key now makes the
    hub ping the old one; silence for STALE_PROBE_SECS proves it stale, and the new one is welcomed."""
    hub, host, registry, *_ = world
    monkeypatch.setattr(hub_nodes, "STALE_PROBE_SECS", 0.2, raising=False)
    node = paired(hub)

    async def go():
        old, new = FakeNode(hub, node), FakeNode(hub, node)
        assert (await old.connect())["t"] == "welcome"
        await old.send_sessions(entry())
        welcome = await new.connect()  # old never reads again: it answers no ping
        await asyncio.wait_for(old.task, 2)  # the old link's handler ended
        await new.send_sessions(entry("s2", "api"))
        alive = hub.live[node["id"]].online
        await new.drop()
        return welcome, old.pipe.closed, alive

    welcome, old_closed, alive = run(go())
    assert welcome and welcome["t"] == "welcome", "the restarted node was refused while its dead link lingered"
    assert old_closed and old_closed[0] == nodelink.CLOSE_DEAD
    assert alive  # the old handler ending did not mark the node offline under the new link
    assert nodelink.hub_session_id(node["id"], "s2") in registry.sessions


def test_a_second_connection_is_still_refused_4409_while_the_first_answers(world, monkeypatch):
    """The protection the probe must keep: a cloned VM or a stolen key cannot shadow a node whose link is alive."""
    hub, *_ = world
    monkeypatch.setattr(hub_nodes, "STALE_PROBE_SECS", 0.5, raising=False)
    node = paired(hub)

    async def answer_pings(fake):
        while await fake.recv("never", timeout=10) is not None:
            pass

    async def go():
        first, clone = FakeNode(hub, node), FakeNode(hub, node)
        assert (await first.connect())["t"] == "welcome"
        reader = asyncio.create_task(answer_pings(first))
        refused = await clone.connect()
        still = hub.live[node["id"]].online and first.pipe.closed is None and hub.live[node["id"]].socket is first.pipe
        reader.cancel()
        await first.drop()
        return refused, clone.pipe.closed, still, first.pings

    refused, closed, still, pings = run(go())
    assert refused is None and closed[0] == nodelink.CLOSE_ALREADY_CONNECTED
    assert still and pings >= 1  # it was asked, answered, and stays


# ---------- 15. a lone surrogate in a frame wedges the link ----------

def test_a_lone_surrogate_in_a_frame_does_not_wedge_the_link(world):
    """json.loads turns a "\\ud800" escape into a string UTF-8 cannot encode. decode() measured the entry with
    .encode() and raised, the reader died with the link, and the node reconnected and resent the same frame forever."""
    hub, host, registry, *_ = world
    node = paired(hub)

    async def go():
        fake = FakeNode(hub, node)
        await fake.connect()
        await fake.send_sessions(entry(cwd="/home/u/x\ud800y".encode("utf-8", "surrogatepass").decode("utf-8", "replace")))
        bad = '{"t": "transcript", "id": "s1", "gen": 0, "offset": 0, "next_offset": 9, "entries": ["{\\"a\\": \\"\\ud800\\"}\\n"]}'
        await fake.pipe.to_hub.put(bad)
        await fake.pipe.to_hub.put('{"t": "sessions", "sessions": [{"id": "s1", "name": "sh\\udc00op", "cwd": "/x", '
                                   '"harness": "claude-code"}]}')
        await settle()
        await fake.send("transcript", id="s1", gen=0, offset=9, next_offset=10, entries=[_line("after")])
        await settle()
        up = hub.live[node["id"]].online
        resume = hub.mirrors.resume(node["id"])
        await fake.drop()
        return up, resume

    up, resume = run(go())
    assert up, "the link dropped on an un-encodable string"
    assert resume == {"s1": {"gen": 0, "offset": 10}}
    mirror = hub.mirrors.path(node["id"], "s1", 0)
    text = mirror.read_text() if mirror.exists() else hub.mirrors._part(mirror).read_text()
    assert len(text.splitlines()) == 2 and "after" in text.splitlines()[1]  # the bad line kept, replaced, in step
    assert all(s.name.encode() for s in registry.sessions.values())


# ---------- 16. this Mac runs processes and reads its own disk at a node's paths ----------

@pytest.fixture
def no_processes(monkeypatch):
    """Every way the daemon starts a process, recorded and refused."""
    import subprocess

    started = []

    def refuse(*a, **k):
        started.append((a, k))
        raise AssertionError(f"a process was started: {a} {k}")

    async def refuse_async(*a, **k):
        refuse(*a, **k)

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse_async)
    return started


def test_the_conflict_scan_runs_no_git_for_a_remote_session(d, node, tmp_path, no_processes):
    """A node's folder names a place on the node. On this Mac the same path may exist (or be planted): git there
    describes the wrong repository, and a repository's config can run code."""
    from test_mixed_harnesses import _join

    s = _join(d, "devbox", "s1", "shop")
    s.cwd = str(tmp_path)  # a path that also exists on this Mac
    (tmp_path / ".git").mkdir()
    asyncio.run(d._scan_conflicts(s, {"verdict": "done"}, "finished"))
    assert no_processes == []
    remembered = d.ALARM.reports[s.id]
    assert remembered.root == "" and remembered.cwd != str(tmp_path)  # "same folder" only on the same machine


def test_recognition_terms_run_no_git_for_a_remote_session_and_use_its_nodes_file_names(d, node, tmp_path, no_processes):
    from test_mixed_harnesses import _join

    s = _join(d, "devbox", "s1", "shop", files=["billing/pricing.py", "README.md"])
    s.cwd = str(tmp_path)
    (tmp_path / ".git").mkdir()
    terms = d._recognition_terms()
    assert no_processes == []  # _git_files swallows any error, so the refusal itself proves nothing: the record does
    assert "billing" in terms


def test_drive_mode_reads_no_path_on_this_mac_for_a_remote_prompt(d, node, tmp_path, monkeypatch):
    """Whether a road yes may approve a file edit rested on os.path.realpath of the node's folder, resolved on this
    Mac's disk. For a remote session there is nothing here to resolve: a file tool is not road safe."""
    import drive as drives
    from test_mixed_harnesses import _join

    looked = []
    real = drives.os.path.realpath
    monkeypatch.setattr(drives.os.path, "realpath", lambda p, *a, **k: looked.append(p) or real(p, *a, **k))

    async def quiet(*a, **k):
        return None

    monkeypatch.setattr(d, "say", quiet)
    monkeypatch.setattr(d, "_ask_permission", quiet)
    s = _join(d, "devbox", "s1", "shop")
    s.cwd = str(tmp_path)
    preview = json.dumps({"file_path": "pricing.py", "old_string": "a", "new_string": "b"})
    asyncio.run(d._put_permission(s, "req1", "Edit", "edit pricing", preview, node_readable=None))
    assert looked == [] and not d.state.drive.is_road_safe("req1")


def test_a_remote_turns_final_message_is_not_checked_against_files_on_this_mac(tmp_path, monkeypatch):
    """Turn.finish adds a 'read' artifact for a file named in the final message if os.path.isfile finds it at the
    session's folder: for a remote session that folder is on the node."""
    import artifacts

    looked = []
    monkeypatch.setattr(artifacts.os.path, "isfile", lambda p: looked.append(p) or True)
    s = sessions.Session(id="n1-s1", name="shop", cwd=str(tmp_path), machine="devbox", harness="claude-code",
                         harness_data={"remote_id": "s1", "node_id": "n1"})
    mirror = tmp_path / "mirror.jsonl"
    mirror.write_text("")
    s.transcript = str(mirror)
    monkeypatch.setattr(sessions, "current_transcript", lambda session: str(mirror))

    async def go():
        fed = []

        async def feed(session, text, respond):
            fed.append(text)

        task = asyncio.create_task(sessions.follow_transcript(s, feed, lambda: None))
        await asyncio.sleep(0.2)
        with mirror.open("a") as f:
            f.write(json.dumps({"type": "assistant", "message": {"stop_reason": "end_turn", "content": [
                {"type": "text", "text": "I checked pricing.py and it is fine."}]}}) + "\n")
        for _ in range(30):
            if fed:
                break
            await asyncio.sleep(0.1)
        task.cancel()
        return fed

    assert run(go())
    assert looked == [] and s.artifacts == []
