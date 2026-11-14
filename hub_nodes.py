"""The hub's side of the node link (docs/design/multi-machine.md): the machines paired with this Mac, the one-time
invites that pair them, the /voice/node socket each keeps open, and the mirror files its sessions' transcripts are
written to. The daemon lends it what only the daemon can do (Host); harnesses/remote.py drives a remote session
through it.

  pointe hub invite [--name devbox]   a one-time line for `pointe node join` on the other machine
  pointe hub nodes                    the machines paired with this Mac
  pointe hub revoke <name>            forget one: its link is closed and its sessions leave the voice
"""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run as a script in isolated mode (-I)
import harnesses  # noqa: E402
import nodelink  # noqa: E402
import readout  # noqa: E402
from guards import _WEAK_YES, _YES, _YES_PHRASES, _lower, _words, valid_name  # noqa: E402
from harnesses.remote import RemoteHarness  # noqa: E402
from nodelink import NODE_FRAMES, decode, encode, hub_session_id  # noqa: E402
from sessions import Registry, Session, _distinctive, _name_words, speakable  # noqa: E402

INVITE_SECS = 600
CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford's 32: no I, L, O or U to misread
CODE_LETTERS = 8  # 40 bits
PAIR_WINDOW_SECS = 60.0
PAIR_PER_ADDRESS = 5
PAIR_PER_WINDOW = 10
PRUNE_AFTER_SECS = 7 * 86400
PRUNE_EVERY_SECS = 3600.0
HELLO_WAIT_SECS = 10.0
_ID = re.compile(r"[\w-]{1,128}")  # a node's session id: it names a mirror file, so nothing that walks a path


def _short_host() -> str:
    return socket.gethostname().split(".")[0]


@dataclass
class Host:
    """What daemon.py lends the hub. Each hook is optional; one left None does nothing.

    register(session, entry) -> Session | None: put a node's session on the voice (daemon.register_remote). Called for
      every entry of every `sessions` snapshot, so for an id it already has it only updates and returns that session.
    drop(session, why): take it off; why is "exited" | "disconnected" (the node said so), "revoked" or "left" (the node
      itself was revoked, or left this hub).
    permission(session, *, request_id, tool, description, preview, readable, deadline_ms): put a prompt to the user as
      _put_permission does, with `readable` (already through checked_readable) instead of a recomputed read-out.
    permission_gone(session, request_id, how): the node's prompt was answered in its terminal, timed out, or left.
    offline(node_name, sessions): the node's link dropped; it handed its held prompts back to their terminals.
    """

    register: Callable[[Session, dict], Awaitable[Session | None]] | None = None
    drop: Callable[[Session, str], Awaitable[None]] | None = None
    permission: Callable[..., Awaitable[None]] | None = None
    permission_gone: Callable[[Session, str, str], Awaitable[None]] | None = None
    offline: Callable[[str, list[Session]], Awaitable[None]] | None = None
    call_state: Callable[[], tuple[bool, bool]] = lambda: (False, False)  # (a call is up, approvals: terminal)
    vendors: Callable[[], list[str]] = list
    machine: Callable[[], str] = _short_host  # this Mac's name: config.json "machine", else its short host name


def checked_readable(readable) -> str | None:
    """The node's read-out form, after the checks readable_request ends with. The hub never recomputes it from the
    masked preview (a masked command would read differently); anything that fails here is unreadable: a tap only."""
    if not isinstance(readable, str) or not readable.strip() or len(readable.split()) > readout.WORDS:
        return None
    if readout.redact(readable) is None:
        return None
    lowered = _lower(readable)
    if _words(lowered) & (_YES | _WEAK_YES) or any(p in lowered for p in _YES_PHRASES):
        return None
    return readable


def name_problem(name: str, taken: list[str], sessions, hub_name: str) -> str | None:
    """Why a node may not be called this, or None. Machine names are spoken ("tell devbox to pull"), so each must be
    pickable by voice and share no word with any session's name."""
    name = " ".join(str(name).split())
    if not name or not valid_name(name):
        return f"{name or 'an empty name'} is not a usable name: use letters, digits, spaces, dots, dashes"
    if not speakable(name):
        return f"{name} cannot be picked by voice: words like dev or main never select anything. Use a distinctive word"
    if name.lower() == hub_name.lower():
        return f"{name} is this Mac's name"
    if any(name.lower() == t.lower() for t in taken):
        return f"a machine called {name} is already paired"
    mine = {w for w in _name_words(name) if _distinctive(w)}
    clash = next((s for s in sessions if mine & set(_name_words(s.name))), None)
    if clash:
        return f"{name} shares a word with the session {clash.name}: the voice could not tell them apart"
    return None


def network(address: str) -> str:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return ""
    if ip in ipaddress.ip_network("100.64.0.0/10"):
        return "Tailscale"
    if ip.is_loopback:
        return "a connector on this Mac"
    return "LAN" if ip.is_private else ""


def paired_line(paired: dict) -> str:
    """What the owner reads to see that the machine that paired is the one they typed the code on."""
    where = f" ({paired['network']})" if paired.get("network") else ""
    return f"{paired['name']} paired from {paired['address']}{where}, key {paired['key_fp']}"


def _write_private(path: Path, text: str) -> None:
    """Temp and replace, 0600 from the first byte, as Registry.save does."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


class NodesRegistry:
    """$STATE/nodes.json, 0600: this hub's id and each paired node's {id, name, os, key, paired_at}. It holds the keys."""

    def __init__(self, path: Path):
        self.path = path
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text())
            except (ValueError, OSError) as e:
                logger.error(f"{path} unreadable ({type(e).__name__}): no machines paired until they pair again")
        data = data if isinstance(data, dict) else {}
        self.nodes: dict[str, dict] = {n["id"]: n for n in data.get("nodes", [])
                                       if isinstance(n, dict) and isinstance(n.get("id"), str) and n.get("key")}
        self.hub_id = data.get("hub_id") if isinstance(data.get("hub_id"), str) else secrets.token_hex(8)
        self.save()

    def save(self) -> None:
        _write_private(self.path, json.dumps({"hub_id": self.hub_id, "nodes": list(self.nodes.values())}) + "\n")

    def get(self, node_id) -> dict | None:
        return self.nodes.get(node_id) if isinstance(node_id, str) else None

    def by_name(self, name: str) -> dict | None:
        return next((n for n in self.nodes.values() if n["name"].lower() == name.lower()), None)

    def add(self, name: str, os_name: str) -> dict:
        prefixes = {n["id"][:6] for n in self.nodes.values()}
        node_id = secrets.token_hex(8)
        while node_id[:6] in prefixes:  # hub session ids carry the first six: they must tell nodes apart
            node_id = secrets.token_hex(8)
        node = {"id": node_id, "name": name, "os": os_name, "key": nodelink.new_key(), "paired_at": time.time()}
        self.nodes[node_id] = node
        self.save()
        return node

    def remove(self, node_id: str) -> None:
        if self.nodes.pop(node_id, None):
            self.save()


def _normal_code(code) -> str:
    return re.sub(r"[\s-]", "", str(code)).upper()


def _digest(letters: str) -> bytes:
    return hashlib.sha256(letters.encode()).digest()


class Invites:
    """At most one invite at a time, in memory only. The code is compared by its SHA-256; the plain code is kept only
    so the page and the app can show it while it is valid (status `invite`)."""

    def __init__(self, clock: Callable[[], float]):
        self._clock = clock
        self._hash: bytes | None = None
        self.code: str | None = None
        self.name: str | None = None
        self._until = 0.0
        self.paired: dict | None = None  # the last pairing: name, source address, key fingerprint
        self._attempts: deque[tuple[float, str]] = deque()

    def make(self, name: str | None = None) -> str:
        letters = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LETTERS))
        self.code, self._hash, self.name = f"{letters[:4]}-{letters[4:]}", _digest(letters), name
        self._until, self.paired = self._clock() + INVITE_SECS, None
        return self.code

    def cancel(self) -> None:
        self.code = self._hash = self.name = None

    @property
    def outstanding(self) -> bool:
        return self._hash is not None and self._clock() < self._until

    def status(self) -> dict | None:
        if not self.outstanding:
            return None
        return {"code": self.code, "expires_in": max(0, round(self._until - self._clock()))}

    def admit(self, address: str) -> bool:
        """At most PAIR_PER_ADDRESS attempts a minute from one address, and PAIR_PER_WINDOW in all."""
        now = self._clock()
        while self._attempts and now - self._attempts[0][0] >= PAIR_WINDOW_SECS:
            self._attempts.popleft()
        if len(self._attempts) >= PAIR_PER_WINDOW or sum(a == address for _, a in self._attempts) >= PAIR_PER_ADDRESS:
            return False
        self._attempts.append((now, address))
        return True

    def matches(self, code) -> bool:
        return self._hash is not None and hmac.compare_digest(_digest(_normal_code(code)), self._hash)


class Mirrors:
    """$STATE/harness/remote/<node id>/<id>.<gen>.jsonl, 0600 in 0700 folders, each beside <id>.<gen>.offset: the node's
    next_offset after the last frame appended. Resume comes from those, never from a mirror's size: masking on the node
    changes line lengths, so a mirror's size says nothing about the node's file."""

    def __init__(self, root: Path):
        self.root = root

    def path(self, node_id: str, sid: str, gen: int) -> Path:
        return self.root / node_id / f"{sid}.{gen}.jsonl"

    def _gens(self, node_id: str, sid: str) -> list[int]:
        folder = self.root / node_id
        if not folder.is_dir():
            return []
        return sorted(int(gen) for p in folder.glob(f"{sid}.*.jsonl")
                      if (gen := p.name[len(sid) + 1:-len(".jsonl")]).isdigit())

    def latest(self, node_id: str, sid: str) -> int | None:
        gens = self._gens(node_id, sid)
        return gens[-1] if gens else None

    def stored(self, node_id: str, sid: str, gen: int) -> int:
        try:
            return int(self.path(node_id, sid, gen).with_suffix(".offset").read_text())
        except (OSError, ValueError):
            return 0

    def _open(self, node_id: str, sid: str, gen: int) -> None:
        _private_dir(self.root.parent)
        _private_dir(self.root)
        _private_dir(self.root / node_id)
        os.close(os.open(self.path(node_id, sid, gen), os.O_WRONLY | os.O_CREAT, 0o600))

    def repoint(self, node_id: str, sid: str, gen: int) -> None:
        """The session moved to a new file (/clear, /resume): a new mirror from offset 0; older ones go."""
        latest = self.latest(node_id, sid)
        if latest is not None and gen <= latest:
            return
        self._open(node_id, sid, gen)
        _write_private(self.path(node_id, sid, gen).with_suffix(".offset"), "0\n")
        for old in self._gens(node_id, sid):
            if old < gen:
                self.path(node_id, sid, old).unlink(missing_ok=True)
                self.path(node_id, sid, old).with_suffix(".offset").unlink(missing_ok=True)

    def append(self, node_id: str, frame: dict) -> bool:
        """Append a `transcript` frame's entries if it starts where the last one ended; False for a gap or a stale gen,
        and the caller asks the node to resume from resume_point()."""
        sid, gen = frame["id"], frame["gen"]
        latest = self.latest(node_id, sid)
        if latest is not None and gen < latest:
            return False
        if latest is None or gen > latest:
            self.repoint(node_id, sid, gen)
        if frame["offset"] != self.stored(node_id, sid, gen):
            return False
        path = self.path(node_id, sid, gen)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write("".join(frame["entries"]))
        _write_private(path.with_suffix(".offset"), f"{frame['next_offset']}\n")
        return True

    def resume_point(self, node_id: str, sid: str) -> dict:
        gen = self.latest(node_id, sid) or 0
        return {"gen": gen, "offset": self.stored(node_id, sid, gen)}

    def resume(self, node_id: str) -> dict:
        folder = self.root / node_id
        sids = {p.name.split(".")[0] for p in folder.glob("*.jsonl")} if folder.is_dir() else set()
        return {sid: self.resume_point(node_id, sid) for sid in sorted(sids)}

    def prune(self, now: float, live: set[tuple[str, str]]) -> None:
        """A session's mirrors go PRUNE_AFTER_SECS after it is first seen off the voice (a `.left` mark holds when)."""
        if not self.root.is_dir():
            return
        for folder in [p for p in self.root.iterdir() if p.is_dir()]:
            for sid in {p.name.split(".")[0] for p in folder.iterdir() if p.suffix in (".jsonl", ".left")}:
                mark = folder / f"{sid}.left"
                if (folder.name, sid) in live:
                    mark.unlink(missing_ok=True)
                    continue
                try:
                    left = float(mark.read_text())
                except (OSError, ValueError):
                    _write_private(mark, f"{now}\n")
                    continue
                if now - left >= PRUNE_AFTER_SECS:
                    for p in folder.glob(f"{sid}.*"):
                        p.unlink(missing_ok=True)
            if not any(folder.iterdir()):
                folder.rmdir()


@dataclass
class Node:
    """A paired node as the hub sees it now."""

    id: str
    name: str
    os: str
    key_fp: str
    since: float | None  # offline since (wall clock); None while online. A hub that just started: since then
    offline_at: float  # the same moment on the monotonic clock, for the grace
    socket: object = None
    rtt_ms: int | None = None
    skew: float = 0.0  # hub clock minus node clock, from its last hello
    sessions: dict[str, dict] | None = None  # its last `sessions` snapshot by its own ids; None: none since this start
    files: dict[str, list[str]] = field(default_factory=dict)
    waiting: dict[str, asyncio.Future] = field(default_factory=dict)
    lock: asyncio.Lock | None = None

    @property
    def online(self) -> bool:
        return self.socket is not None


class Hub:
    def __init__(self, state_dir: Path, registry: Registry, host: Host,
                 clock: Callable[[], float] = time.time, monotonic: Callable[[], float] = time.monotonic):
        self.registry, self.host = registry, host
        self._clock, self._mono = clock, monotonic
        self.nodes = NodesRegistry(state_dir / "nodes.json")
        self.invites = Invites(monotonic)
        self.mirrors = Mirrors(state_dir / "harness" / "remote")
        self.links = nodelink.Links()
        self.live: dict[str, Node] = {n["id"]: self._node(n) for n in self.nodes.nodes.values()}
        self._tasks: set[asyncio.Task] = set()

    def _node(self, paired: dict) -> Node:
        return Node(id=paired["id"], name=paired["name"], os=paired.get("os", ""),
                    key_fp=nodelink.fingerprint(paired["key"]), since=self._clock(), offline_at=self._mono())

    def wrap(self, session: Session, inner: harnesses.Harness) -> harnesses.Harness:
        """For harnesses.set_remote: the adapter of a session on another machine."""
        return RemoteHarness(self, inner)

    # ---------- what RemoteHarness and the daemon ask ----------

    def _node_of(self, session: Session) -> Node | None:
        return self.live.get(session.harness_data.get("node_id")) if session.machine else None

    def _sessions_of(self, node: Node) -> list[Session]:
        return [s for s in self.registry.sessions.values() if s.machine and s.harness_data.get("node_id") == node.id]

    def _session(self, node: Node, sid: str) -> Session | None:
        return self.registry.sessions.get(hub_session_id(node.id, sid))

    def alive(self, session: Session) -> bool:
        """From the node's state, never a pid: listed in its last snapshot while online, and kept for
        OFFLINE_GRACE_SECS after its link drops (or after this hub started, until the node reconnects)."""
        node = self._node_of(session)
        if node is None:
            return False
        if node.online:
            return node.sessions is None or session.harness_data.get("remote_id") in node.sessions
        return self._mono() - node.offline_at < nodelink.OFFLINE_GRACE_SECS

    def online(self, session: Session) -> bool:
        node = self._node_of(session)
        return bool(node and node.online)

    def transcript_path(self, session: Session) -> str:
        """The mirror of the session's newest file, so a /clear on the node moves the follower here too."""
        node_id, sid = session.harness_data.get("node_id", ""), session.harness_data.get("remote_id", "")
        return str(self.mirrors.path(node_id, sid, self.mirrors.latest(node_id, sid) or 0))

    def node_time(self, session: Session, hub_time: float) -> float:
        """A time on this Mac's clock as the session's machine stamps it: shift a `since` by this before comparing it
        with a remote transcript's timestamps."""
        node = self._node_of(session)
        return hub_time - node.skew if node else hub_time

    def files(self, session: Session) -> list[str]:
        node = self._node_of(session)
        return node.files.get(session.harness_data.get("remote_id"), []) if node else []

    def machines(self) -> list[dict]:
        """The nodes, for /voice/status `machines` (the daemon adds this Mac's entry and each `need`)."""
        return [{"id": n.id, "name": n.name, "here": False, "os": n.os, "online": n.online, "since": n.since,
                 "sessions": len(self._sessions_of(n)), "rtt_ms": n.rtt_ms, "key_fp": n.key_fp}
                for n in self.live.values()]

    def name_problem(self, name: str) -> str | None:
        return name_problem(name, [n["name"] for n in self.nodes.nodes.values()], list(self.registry.sessions.values()),
                            self.host.machine())

    # ---------- hub to node ----------

    async def _send(self, node: Node, text: str) -> bool:
        ws = node.socket
        if ws is None:
            return False
        async with node.lock:
            try:
                await ws.send_text(text)
                return True
            except Exception:  # the link went: its reader sees the disconnect and marks the node offline
                return False

    async def _request(self, node: Node, key: str, text: str):
        """Send a frame and wait for its reply: the reply's value, or None (offline, or no reply in time)."""
        future = asyncio.get_running_loop().create_future()
        node.waiting[key] = future
        try:
            if not await self._send(node, text):
                return None
            return await asyncio.wait_for(future, nodelink.SEND_TIMEOUT_SECS)
        except asyncio.TimeoutError:
            return None
        finally:
            node.waiting.pop(key, None)

    async def send(self, session: Session, text: str) -> bool:
        node = self._node_of(session)
        if node is None or not node.online:
            return False
        req = nodelink.new_id()
        sent = encode("send", req=req, id=session.harness_data["remote_id"], text=text)
        return await self._request(node, f"send:{req}", sent) is True

    async def answer(self, session: Session, request_id: str, verdict: str, how: str,
                     spoken: str | None = None) -> tuple[bool, str | None]:
        """A verdict for the node's held prompt: (ok, why). The node re-checks it; `why` is its reason for a refusal
        ("stale", "unreadable", ...), or "offline" / "timeout" when it never answered."""
        node = self._node_of(session)
        if node is None or not node.online:
            return False, "offline"
        fields = {"spoken": spoken} if spoken is not None else {}
        frame = encode("permission.answer", id=session.harness_data["remote_id"], request_id=request_id,
                       verdict=verdict, how=how, **fields)
        reply = await self._request(node, f"answer:{request_id}", frame)
        if reply is None:
            return False, "offline" if not node.online else "timeout"
        return reply

    async def leave(self, session: Session) -> None:
        node = self._node_of(session)
        if node is not None:
            await self._send(node, encode("leave", id=session.harness_data["remote_id"]))

    async def call_changed(self) -> None:
        """Tell every node whether to forward prompts: a call is up and the hub's approvals are not `terminal`."""
        up, terminal = self.host.call_state()
        for node in list(self.live.values()):
            if node.online:
                await self._send(node, encode("call", up=up, approvals_terminal=terminal))

    async def revoke(self, name: str) -> bool:
        paired = self.nodes.by_name(name)
        if paired is None:
            return False
        await self._forget(self.live.get(paired["id"]) or self._node(paired), "revoked")
        return True

    async def _forget(self, node: Node, why: str) -> None:
        """Revoked here, or it left: its key goes, its sessions leave the voice, and a live link is closed."""
        self.nodes.remove(node.id)
        self.live.pop(node.id, None)
        ws = node.socket
        if ws is not None:
            if why == "revoked":
                await self._send(node, encode("unpaired"))
            node.socket = None  # gone, not offline: the reader's exit must not announce it
            await _close(ws, 1000, why)
        for session in self._sessions_of(node):
            if self.host.drop:
                await self.host.drop(session, why)
        logger.info(f"node {node.name} {why}: forgotten")

    # ---------- pairing ----------

    def pair(self, body, address: str) -> tuple[int, dict | str]:
        """POST /voice/node/pair: (status, the node's key and the hub's identity, or why not)."""
        invites = self.invites
        if invites.code is None:
            return 403, "no invite outstanding"
        if not invites.admit(address):
            return 429, "too many attempts: wait a minute"
        if not invites.outstanding:
            return 403, "invite expired"
        body = body if isinstance(body, dict) else {}
        if not invites.matches(body.get("code", "")):
            logger.warning(f"node pairing from {address}: wrong code")
            return 403, "wrong code"
        name = " ".join(str(invites.name or body.get("name") or "").split())
        problem = self.name_problem(name)
        if problem:
            return 409, problem
        invites.cancel()
        paired = self.nodes.add(name, str(body.get("os") or ""))
        self.live[paired["id"]] = self._node(paired)
        invites.paired = {"name": name, "address": address, "network": network(address),
                          "key_fp": nodelink.fingerprint(paired["key"])}
        logger.info(paired_line(invites.paired))
        return 200, {"node_id": paired["id"], "node_key": paired["key"],
                     "hub": {"id": self.nodes.hub_id, "name": self.host.machine()}, "vendors": self.host.vendors()}

    # ---------- the link ----------

    async def serve(self, ws) -> None:
        """The /voice/node WebSocket: a nonce, the node's HMAC over it, then frames until the link drops."""
        await ws.accept()
        nonce = nodelink.new_nonce()
        await ws.send_text(encode("challenge", nonce=nonce, hub={"id": self.nodes.hub_id, "name": self.host.machine()}))
        try:
            hello = decode(await asyncio.wait_for(ws.receive_text(), HELLO_WAIT_SECS), NODE_FRAMES)
        except Exception:  # silence, or it went
            return await _close(ws, nodelink.CLOSE_UNAUTHORIZED, "no hello")
        if hello is None or hello["t"] != "hello":
            return await _close(ws, nodelink.CLOSE_UNAUTHORIZED, "hello first")
        if hello["protocol"] < nodelink.MIN_PROTOCOL:  # before the HMAC: an older node may answer it differently
            return await _close(ws, nodelink.CLOSE_TOO_OLD,
                                f"this hub needs protocol {nodelink.MIN_PROTOCOL}: update Pointe on this machine")
        paired = self.nodes.get(hello["node"]["id"])
        if paired is None or not nodelink.check(paired["key"], nonce, self.nodes.hub_id, hello["auth"]):
            logger.warning(f"node link refused: {hello['node']['name']!r} is not paired, or its key is wrong")
            return await _close(ws, nodelink.CLOSE_UNAUTHORIZED, "not paired with this hub")
        if not self.links.claim(paired["id"], ws):
            logger.warning(f"node {paired['name']}: a second connection with its key refused")
            return await _close(ws, nodelink.CLOSE_ALREADY_CONNECTED, "already connected")
        node = self.live.setdefault(paired["id"], self._node(paired))
        node.socket, node.lock, node.since = ws, asyncio.Lock(), None
        node.skew = self._clock() - hello["now"]
        heartbeat = nodelink.Heartbeat(self._mono)
        logger.info(f"node {node.name} connected (skew {node.skew:+.1f} s)")
        try:
            up, terminal = self.host.call_state()
            await self._send(node, encode("welcome", protocol=nodelink.PROTOCOL, call_up=up, approvals_terminal=terminal,
                                          vendors=self.host.vendors(), resume=self.mirrors.resume(node.id)))
            tasks = {asyncio.create_task(self._read(node, ws, heartbeat)),
                     asyncio.create_task(self._keep_alive(node, ws, heartbeat))}
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
        finally:
            self.links.release(paired["id"], ws)
            if node.socket is ws:
                await self._went_offline(node)

    async def _keep_alive(self, node: Node, ws, heartbeat: nodelink.Heartbeat) -> None:
        while True:
            await asyncio.sleep(nodelink.PING_SECS)
            if heartbeat.dead():
                logger.warning(f"node {node.name} stopped answering for {nodelink.DEAD_AFTER_SECS:.0f} s: closing its link")
                return await _close(ws, nodelink.CLOSE_DEAD, "no answer to pings")
            if not await self._send(node, heartbeat.ping()):
                return

    async def _read(self, node: Node, ws, heartbeat: nodelink.Heartbeat) -> None:
        while True:
            try:
                text = await ws.receive_text()
            except Exception:  # WebSocketDisconnect, or a receive after close
                return
            frame = decode(text, NODE_FRAMES)
            if frame is None:
                continue
            if frame["t"] == "pong":
                heartbeat.pong(frame["id"])
                node.rtt_ms = heartbeat.rtt_ms
            elif frame["t"] == "bye":
                return await self._forget(node, "left")
            else:
                try:
                    await self._on_frame(node, frame)
                except Exception:
                    logger.exception(f"node {node.name}: handling a {frame['t']!r} frame failed")

    async def _went_offline(self, node: Node) -> None:
        node.socket, node.since, node.offline_at = None, self._clock(), self._mono()
        for future in node.waiting.values():
            if not future.done():
                future.set_result(None)
        logger.info(f"node {node.name} offline")
        if self.host.offline:
            await self.host.offline(node.name, self._sessions_of(node))

    async def _on_frame(self, node: Node, frame: dict) -> None:
        t = frame["t"]
        if t == "sessions":
            await self._snapshot(node, frame["sessions"])
        elif t == "session.left":
            (node.sessions or {}).pop(frame["id"], None)
            session = self._session(node, frame["id"])
            if session and self.host.drop:
                await self.host.drop(session, frame["why"])
        elif t == "transcript":
            sid = frame["id"]
            if _ID.fullmatch(sid) and (sid in (node.sessions or {}) or self.mirrors.latest(node.id, sid) is not None):
                if not self.mirrors.append(node.id, frame):
                    await self._send(node, encode("resume", resume={sid: self.mirrors.resume_point(node.id, sid)}))
        elif t == "transcript.repointed":
            if _ID.fullmatch(frame["id"]) and frame["id"] in (node.sessions or {}):
                self.mirrors.repoint(node.id, frame["id"], frame["gen"])
        elif t == "files":
            node.files[frame["id"]] = frame["names"]
        elif t == "permission.request":
            await self._permission(node, frame)
        elif t == "permission.resolved":
            session = self._session(node, frame["id"])
            if session and self.host.permission_gone:
                await self.host.permission_gone(session, frame["request_id"], frame["how"])
        elif t in ("permission.answered", "send.result"):
            key = f"answer:{frame['request_id']}" if t == "permission.answered" else f"send:{frame['req']}"
            future = node.waiting.get(key)
            if future is not None and not future.done():
                future.set_result((frame["ok"], frame.get("why")) if t == "permission.answered" else frame["ok"])

    async def _snapshot(self, node: Node, entries: list[dict]) -> None:
        """A node's full list: new ones join, ones no longer in it have exited, and a prompt it still holds (after a
        restart on either side) is put to the user again, once."""
        kept = []
        for entry in entries:
            if not _ID.fullmatch(entry["id"]) or entry["harness"] not in harnesses.names():
                logger.warning(f"node {node.name}: session {entry['id'][:40]!r} ({entry['harness'][:20]}) not taken")
                continue
            kept.append(entry)
        node.sessions = {e["id"]: e for e in kept}
        for e in kept:
            files = e.get("files")
            if isinstance(files, list) and all(isinstance(f, str) for f in files):
                node.files[e["id"]] = files[:nodelink.MAX_FILES]
        for session in self._sessions_of(node):
            if session.harness_data.get("remote_id") not in node.sessions and self.host.drop:
                await self.host.drop(session, "exited")
        for e in kept:
            session = await self.host.register(self.new_session(node, e), e) if self.host.register else None
            pending = e.get("pending")
            if session is not None and isinstance(pending, dict):
                request = {"t": "permission.request", **pending, "id": e["id"]}
                if nodelink._valid(request, NODE_FRAMES["permission.request"]) and \
                        session.permission_id != pending["request_id"]:
                    await self._permission(node, request)

    def new_session(self, node: Node, entry: dict) -> Session:
        """The hub's Session for a node's snapshot entry. Never the inbox socket or token: those stay on the node."""
        sid = entry["id"]
        pid, home = entry.get("pid"), entry.get("home")
        return Session(id=hub_session_id(node.id, sid), name=entry["name"], cwd=entry["cwd"],
                       pid=pid if isinstance(pid, int) and not isinstance(pid, bool) else 0,
                       home=home if isinstance(home, str) else "", harness=entry["harness"], machine=node.name,
                       named_by="user" if entry.get("name_given") is True else "folder",
                       transcript=str(self.mirrors.path(node.id, sid, self.mirrors.latest(node.id, sid) or 0)),
                       harness_data={"remote_id": sid, "node_id": node.id})

    async def _permission(self, node: Node, frame: dict) -> None:
        """`holding` goes back at once, before the read-out is scheduled: the node hands the prompt to its terminal if
        it has not heard it in HOLDING_WAIT_SECS, and the read-out can wait longer than that for the brain."""
        session = self._session(node, frame["id"])
        up, terminal = self.host.call_state()
        if session is None or not up or terminal or self.host.permission is None:
            return  # no `holding`: the node hands it to the terminal, as the daemon does with no call
        await self._send(node, encode("permission.holding", request_id=frame["request_id"]))
        task = asyncio.create_task(self.host.permission(
            session, request_id=frame["request_id"], tool=frame["tool"], description=frame["description"],
            preview=frame["preview"], readable=checked_readable(frame["readable"]), deadline_ms=frame["deadline_ms"]))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def prune(self) -> None:
        live = {(s.harness_data.get("node_id"), s.harness_data.get("remote_id"))
                for s in self.registry.sessions.values() if s.machine}
        self.mirrors.prune(self._clock(), live)


async def _close(ws, code: int, reason: str) -> None:
    try:
        await ws.close(code=code, reason=reason)
    except Exception:  # already closed
        pass


def install(app, hub: Hub, link: Callable[[str], str] | None = None) -> None:
    """The node routes, the owner's /voice/hub/* routes, the remote adapter, and hourly mirror pruning.
    `link(code)` builds the invite line (pair.invite_link; SystemExit with the fix when no address is paired)."""
    from contextlib import asynccontextmanager

    from fastapi import Request, WebSocket
    from fastapi.responses import JSONResponse, PlainTextResponse

    from remote import Remote

    if link is None:
        from pair import invite_link as link
    harnesses.set_remote(hub.wrap)

    @app.websocket(nodelink.PATH)
    async def node_socket(websocket: WebSocket):
        await hub.serve(websocket)

    async def body_of(request: Request) -> dict:
        try:
            body = await request.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    @app.post(nodelink.PAIR_PATH)
    async def node_pair(request: Request):
        status, answer = hub.pair(await body_of(request), request.client.host if request.client else "")
        return JSONResponse(answer) if status == 200 else PlainTextResponse(answer, status_code=status)

    def owner(request: Request) -> bool:
        """The page on this Mac, a script with the daemon token, or the phone app. Not a browser over the TLS
        listener: the invite code is shown only where the owner already is."""
        return not Remote.on_tls_listener(request.scope) or bool(request.scope.get("state", {}).get("pointe_phone"))

    refused = PlainTextResponse("forbidden", status_code=403)

    @app.post("/voice/hub/invite")
    async def hub_invite(request: Request):
        """{} makes a code (replacing any other); {"name": "devbox"} names the machine; {"cancel": true} ends it."""
        if not owner(request):
            return refused
        body = await body_of(request)
        if body.get("cancel"):
            hub.invites.cancel()
            return {"ok": True}
        name = " ".join(str(body.get("name") or "").split()) or None
        problem = hub.name_problem(name) if name else None
        if problem:
            return PlainTextResponse(problem, status_code=409)
        code = hub.invites.make(name=name)
        try:
            line = link(code)
        except SystemExit as e:
            hub.invites.cancel()
            return PlainTextResponse(str(e), status_code=409)
        return {"code": code, "expires_in": INVITE_SECS, "link": line}

    @app.get("/voice/hub/invite")
    async def hub_invite_status(request: Request):
        if not owner(request):
            return refused
        return {**(hub.invites.status() or {"code": None, "expires_in": 0}), "paired": hub.invites.paired}

    @app.get("/voice/hub/nodes")
    async def hub_node_list(request: Request):
        return {"nodes": hub.machines()} if owner(request) else refused

    @app.post("/voice/hub/revoke")
    async def hub_revoke(request: Request):
        if not owner(request):
            return refused
        name = str((await body_of(request)).get("name") or "")
        if not await hub.revoke(name):
            return PlainTextResponse(f"no machine called {name} is paired", status_code=404)
        return {"ok": True}

    previous = app.router.lifespan_context

    async def prune_every_hour() -> None:
        while True:
            try:
                hub.prune()
            except OSError as e:
                logger.warning(f"pruning node mirrors failed: {e}")
            await asyncio.sleep(PRUNE_EVERY_SECS)

    @asynccontextmanager
    async def lifespan(_app):
        pruner = asyncio.create_task(prune_every_hour())
        try:
            async with previous(_app):
                yield
        finally:
            pruner.cancel()

    app.router.lifespan_context = lifespan


# ---------- the command line: pointe hub ----------

def _daemon(method: str, path: str, body: dict | None = None) -> dict:
    import urllib.error
    import urllib.request

    state = Path(os.environ.get("CLAUDE_VOICE_STATE", Path.home() / ".claude-voice"))
    port = os.environ.get("CLAUDE_VOICE_DAEMON_PORT", "7860")
    try:
        token = (state / "token").read_text().strip()
    except OSError:
        raise SystemExit("The voice daemon has not run on this Mac yet: start it with /pointe:voice, then retry.")
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(e.read().decode(errors="replace") or str(e))
    except urllib.error.URLError:
        raise SystemExit(f"The voice daemon is not running on port {port}: start it with /pointe:voice, then retry.")


def main(argv: list[str]) -> None:
    command = argv[0] if argv else "help"
    if command == "invite":
        name = argv[argv.index("--name") + 1] if "--name" in argv[:-1] else None
        made = _daemon("POST", "/voice/hub/invite", {"name": name} if name else {})
        print(made["link"])
        print("Valid once, for ten minutes. On the other machine: pointe node join '<the line above>'", flush=True)
        try:
            while True:
                time.sleep(1)
                now = _daemon("GET", "/voice/hub/invite")
                if now.get("paired"):
                    return print(paired_line(now["paired"]))
                if not now.get("code"):
                    raise SystemExit("The invite expired or was cancelled: run pointe hub invite again.")
        except KeyboardInterrupt:
            print("\nThe invite stays valid until it expires.")
    elif command == "nodes":
        nodes = _daemon("GET", "/voice/hub/nodes")["nodes"]
        if not nodes:
            return print("No machines paired. Pair one with: pointe hub invite")
        for n in nodes:
            state = (f"online, {n['rtt_ms']} ms" if n["rtt_ms"] is not None else "online") if n["online"] else \
                f"offline since {time.strftime('%H:%M %b %d', time.localtime(n['since']))}"
            print(f"{n['name']}  {n['os']}  {state}  {n['sessions']} session(s)  key {n['key_fp']}")
    elif command == "revoke" and len(argv) > 1:
        _daemon("POST", "/voice/hub/revoke", {"name": " ".join(argv[1:])})
        print(f"{' '.join(argv[1:])} is no longer paired; its sessions left the voice.")
    else:
        print(__doc__.split("\n\n", 1)[1].rstrip())


if __name__ == "__main__":
    main(sys.argv[1:])
