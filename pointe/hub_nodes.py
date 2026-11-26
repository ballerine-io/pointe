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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run as a script in isolated mode (-I)
import harnesses  # noqa: E402
import nodelink  # noqa: E402
import sessions  # noqa: E402
import skew  # noqa: E402
from guards import valid_name  # noqa: E402
from harnesses.remote import RemoteHarness  # noqa: E402
from nodelink import NODE_FRAMES, decode, encode, hub_session_id  # noqa: E402
from sessions import Machine, Registry, Session, _distinctive, _name_words, speakable  # noqa: E402

INVITE_SECS = 600
CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford's 32: no I, L, O or U to misread
CODE_LETTERS = 8  # 40 bits
PAIR_BURST = 5  # codes one address may try at once; its bucket refills so it alone never reaches PAIR_WRONG_PER_INVITE
PAIR_WRONG_PER_INVITE = 20  # then the invite ends: the bound on guesses from all addresses together
# Every refused code gets these words (429 aside): "no invite", "expired" and "wrong" would tell a scanner when a code
# is live, and the invite-ending answer named the guessers' addresses. The owner sees why (`ended`), the log too.
NO_SUCH_INVITE = "no such invite: the code is wrong, expired or already used. Ask for a new one"
PAIR_BODY_BYTES = 4096  # a pairing posts a few hundred bytes; read no more from a caller with no secret
PRUNE_AFTER_SECS = 7 * 86400
PRUNE_EVERY_SECS = 3600.0
HELLO_WAIT_SECS = 10.0
# Sockets on /voice/node that have not proven a key yet (each waits up to HELLO_WAIT_SECS for its hello). A real node
# holds one for a round trip; every node behind one connector shares its address (127.0.0.1), so the share is not one.
MAX_WAITING_PER_ADDRESS = 8
MAX_WAITING = 32
REFUSED_LOG_SECS = 60.0  # a refused link is logged once per address in this: refusing takes no secret, so no bound
STALE_PROBE_SECS = 3.0  # a new connection with a key already linked: the old link must answer a ping within this
MAX_MIRROR_BYTES_PER_NODE = 4 << 30  # every mirror of one node together; past it, entries are counted, not written
DISCOVER_TIMEOUT_SECS = 25.0  # a node lists its sessions (each account's `claude agents --json`) or joins one in this
HISTORY_QUIET_SECS = 1.5  # a newly joined session's backlog: no frame for this long and it is all here
_ID = re.compile(r"[\w-]{1,128}")  # a node's session id: it names a mirror file, so nothing that walks a path
# What a node says reaches the brain's context every turn (a folder, file names), the read-out and the cards (a
# prompt's tool, description and preview) and the voice (its read-out): each is cut to these before the daemon sees it.
MAX_PATH_CHARS = 4096
MAX_LABEL_CHARS = 200  # names, titles, tool names
MAX_DESCRIPTION_CHARS = 2000
MAX_PREVIEW_CHARS = 20_000
MAX_READABLE_CHARS = 1000  # over this the read-out is dropped (unreadable), never cut: a voice yes must match it exactly
MAX_SENT_CHARS = 600  # another person's request, as the notes and the brain keep it (a `sent` frame)
_LIMITS = {"cwd": MAX_PATH_CHARS, "home": MAX_PATH_CHARS, "name": MAX_LABEL_CHARS, "title": MAX_LABEL_CHARS,
           "owner": MAX_LABEL_CHARS,
           "harness": MAX_LABEL_CHARS, "tool": MAX_LABEL_CHARS, "description": MAX_DESCRIPTION_CHARS,
           "preview": MAX_PREVIEW_CHARS}


def _cut(text: str, most: int) -> str:
    return text if len(text) <= most else text[:most - 1] + "…"


def _bounded(fields: dict) -> dict:
    """A copy of a node's session entry or permission request with every string it carries cut to its limit."""
    out = {k: _cut(v, _LIMITS[k]) if k in _LIMITS and isinstance(v, str) else v for k, v in fields.items()}
    if isinstance(out.get("files"), list):
        out["files"] = _names(out["files"])
    if isinstance(out.get("pending"), dict):
        out["pending"] = _bounded(out["pending"])
    if isinstance(out.get("readable"), str) and len(out["readable"]) > MAX_READABLE_CHARS:
        out["readable"] = None
    return out


def _bounded_busy(busy) -> dict:
    """`send.result.busy` from a machine: who the session works for and since when, each cut."""
    busy = busy if isinstance(busy, dict) else {}
    by, since = busy.get("by"), busy.get("since")
    return {"by": _cut(by, MAX_LABEL_CHARS) if isinstance(by, str) else "",
            "since": since if nodelink._num(since) else _cut(since, 20) if isinstance(since, str) else None}


def _names(names: list) -> list:
    return [_cut(n, MAX_PATH_CHARS) if isinstance(n, str) else n for n in names]


def _here(state_dir: Path) -> str:
    """This Mac's name among the machines, the rule daemon._here() uses: config.json "machine", else the short host name."""
    path = state_dir / "config.json"
    try:
        configured = json.loads(path.read_text()).get("machine")
    except (OSError, ValueError, AttributeError):
        configured = None
    return str(configured or socket.gethostname().split(".")[0] or "this Mac")


async def _maybe(result):
    """A HOST hook may be a plain function or a coroutine function."""
    return await result if asyncio.iscoroutine(result) else result


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


def removed_line(name: str) -> str:
    """The line a machine keeps on the screens after its owner removed this person from it."""
    return f"{name} removed you"


def paired_line(paired: dict) -> str:
    """What the owner reads to see that the machine that paired is the one they typed the code on."""
    where = f" ({paired['network']})" if paired.get("network") else ""
    return f"{paired['name']} paired from {paired['address']}{where}, key {paired['key_fp']}"


def _write_private(path: Path, text: str) -> None:
    """Temp and replace, 0600 from the first byte, as Registry.save does."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")  # two writers never share one temp file
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def _legible_hub_id(raw: str) -> str | None:
    found = re.search(r'"hub_id"\s*:\s*"([\w-]{1,64})"', raw)
    return found.group(1) if found else None


def _entries(data: dict) -> dict[str, dict]:
    """The machines a nodes.json lists. One with no key is kept only when it is a machine that removed this person
    (`removed`): it stays listed, with that line, and is never dialed."""
    return {n["id"]: n for n in data.get("nodes", [])
            if isinstance(n, dict) and isinstance(n.get("id"), str) and (n.get("key") or n.get("removed"))}


class NodesRegistry:
    """$STATE/nodes.json, 0600: this hub's id and each paired node's {id, name, os, key, paired_at}. It holds the keys.
    A machine somebody invited this voice to (machines.py) is an entry too, with `dial: {host, port, fp}`, the
    machine's own id (`host_id`), its `owner`, this person's `grant`, id (`person`) and name there (`person_name`)."""

    def __init__(self, path: Path):
        self.path = path
        data: dict = {}
        broken = False
        if path.exists():
            try:
                data = json.loads(path.read_text())
            except (ValueError, OSError) as e:
                broken = True
                data = {"hub_id": self._set_aside(e)}
        else:
            data = {"hub_id": self._hub_id_set_aside()}
        data = data if isinstance(data, dict) else {}
        self.nodes: dict[str, dict] = _entries(data)
        self.hub_id = data.get("hub_id") if isinstance(data.get("hub_id"), str) else secrets.token_hex(8)
        if not broken:  # a broken file is not saved over: the next pairing or revoke writes a new one
            self.save()
        else:
            self._read = self._on_disk()

    def _on_disk(self) -> tuple | None:
        try:
            st = self.path.stat()
        except OSError:
            return None
        return st.st_ino, st.st_mtime_ns, st.st_size

    def refresh(self) -> None:
        """nodes.json changed under the daemon (`pointe pair rotate` or `off` emptied it): only the machines it lists now
        are paired. Before every lookup and change, so a signed-out machine is refused at once and a later save cannot
        bring it back. Unreadable or gone: none is."""
        if self._on_disk() == self._read:
            return
        self._read = self._on_disk()
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        self.nodes = _entries(data)
        if isinstance(data.get("hub_id"), str):
            self.hub_id = data["hub_id"]

    def _set_aside(self, error: Exception) -> str | None:
        """Move an unreadable nodes.json to nodes.json.broken-<time> for repair by hand; its hub id if one is legible
        (a new one would make every node say "another hub answers" and never come back on its own)."""
        try:
            raw = self.path.read_bytes().decode(errors="replace")
        except OSError:
            raw = ""
        aside = self.path.with_name(f"{self.path.name}.broken-{int(time.time())}")
        try:
            os.replace(self.path, aside)
        except OSError as e:
            aside = self.path
            logger.error(f"{self.path} could not be moved aside ({type(e).__name__})")
        hub_id = _legible_hub_id(raw)
        logger.error(f"{self.path} is unreadable ({type(error).__name__}); kept as {aside}. No machine is paired until "
                     f"it is repaired and the daemon restarted, or each machine pairs again. Hub id "
                     f"{'kept' if hub_id else 'lost: paired machines must pair again'}")
        return hub_id

    def _hub_id_set_aside(self) -> str | None:
        """With no nodes.json, the hub id of the newest one set aside, if any: a restart before the next save keeps it."""
        for aside in sorted(self.path.parent.glob(f"{self.path.name}.broken-*"), reverse=True):
            try:
                hub_id = _legible_hub_id(aside.read_bytes().decode(errors="replace"))
            except OSError:
                continue
            if hub_id:
                return hub_id
        return None

    def save(self) -> None:
        _write_private(self.path, json.dumps({"hub_id": self.hub_id, "nodes": list(self.nodes.values())}) + "\n")
        self._read = self._on_disk()

    def get(self, node_id) -> dict | None:
        self.refresh()
        return self.nodes.get(node_id) if isinstance(node_id, str) else None

    def by_name(self, name: str) -> dict | None:
        self.refresh()
        return next((n for n in self.nodes.values() if n["name"].lower() == name.lower()), None)

    def add(self, name: str, os_name: str, key: str | None = None, **more) -> dict:
        """A new machine, under an id made here. `key` and `more` are a dialed machine's: the key its owner's Pointe
        gave this person, and where it is dialed."""
        self.refresh()
        prefixes = {n["id"][:6] for n in self.nodes.values()}
        node_id = secrets.token_hex(8)
        while node_id[:6] in prefixes:  # hub session ids carry the first six: they must tell nodes apart
            node_id = secrets.token_hex(8)
        node = {"id": node_id, "name": name, "os": os_name, "key": key or nodelink.new_key(), "paired_at": time.time(),
                **more}
        self.nodes[node_id] = node
        self.save()
        return node

    def update(self, node_id: str, **fields) -> dict | None:
        self.refresh()
        node = self.nodes.get(node_id)
        if node is not None and any(node.get(k) != v for k, v in fields.items()):
            node.update(fields)
            self.save()
        return node

    def remove(self, node_id: str) -> None:
        self.refresh()
        if self.nodes.pop(node_id, None):
            self.save()


def _normal_code(code) -> str:
    return re.sub(r"[\s-]", "", str(code)).upper()


def _digest(letters: str) -> bytes:
    return hashlib.sha256(letters.encode()).digest()


async def pairing_body(request) -> dict | None:
    """The JSON object a pairing route was sent, read no further than PAIR_BODY_BYTES; None when it is longer. These
    routes take no secret, so a body of any size from anyone on the network would otherwise be held in memory whole."""
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > PAIR_BODY_BYTES):
        return None
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > PAIR_BODY_BYTES:
            return None
    try:
        parsed = json.loads(body)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class Invites:
    """At most one invite at a time, in memory only. The code is compared by its SHA-256; the plain code is kept only
    so the page and the app can show it while it is valid (status `invite`)."""

    def __init__(self, clock: Callable[[], float], secs: float = INVITE_SECS):
        self._clock, self._secs = clock, secs
        self._hash: bytes | None = None
        self.code: str | None = None
        self.name: str | None = None
        self._until = 0.0
        self.paired: dict | None = None  # the last pairing: name, source address, key fingerprint
        self._buckets: dict[str, tuple[float, float]] = {}  # address -> (tokens, when counted)
        self._told_over_rate: set[str] = set()  # addresses whose 429 is in the log for this invite
        self.wrong = 0  # wrong codes against this invite
        self.guessers: dict[str, int] = {}  # address -> wrong codes from it, against this invite
        self.ended: str | None = None  # why the last invite ended early, for the owner
        self.link: str | None = None  # the join line for this code: a code alone is "not a Pointe hub invite"

    def make(self, name: str | None = None) -> str:
        letters = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LETTERS))
        self.code, self._hash, self.name = f"{letters[:4]}-{letters[4:]}", _digest(letters), name
        self._until, self.paired, self.wrong, self.ended, self.link = self._clock() + self._secs, None, 0, None, None
        self._buckets, self.guessers, self._told_over_rate = {}, {}, set()
        return self.code

    def cancel(self) -> None:
        self.code = self._hash = self.name = self.link = None

    @property
    def outstanding(self) -> bool:
        return self._hash is not None and self._clock() < self._until

    def status(self) -> dict | None:
        if not self.outstanding:
            return None
        return {"code": self.code, "expires_in": max(0, round(self._until - self._clock())), "wrong_codes": self.wrong,
                **({"link": self.link} if self.link else {})}  # an invite made in a terminal shows on the page whole

    def check(self, code, address: str) -> tuple[int, str] | None:
        """None when `code` is this invite's, else (status, why) for the caller to answer. Each address has a token
        bucket, taken from BEFORE the code is compared: a guess over its rate is not tried at all, so it cannot burn the
        invite either. It holds PAIR_BURST and refills at a rate that keeps one address under PAIR_WRONG_PER_INVITE for
        the invite's whole life, so only guesses from several addresses together can end it (the backstop). The cost:
        a guesser sharing the real node's address (127.0.0.1 behind bin/voice-connector) delays it until a token is
        back, about a minute at most; it cannot lock it out for good."""
        if not self._take(address):
            return 429, "too many attempts: wait a minute"
        if self.matches(code):
            return None
        self.wrong += 1
        self.guessers[address] = self.guessers.get(address, 0) + 1
        if self.wrong < PAIR_WRONG_PER_INVITE:
            return 403, "wrong code"
        self.ended = f"the invite was cancelled after {self.wrong} wrong codes, from {self._from()}"
        self.cancel()
        return 403, self.ended

    def worth_logging(self, refused: tuple[int, str], address: str) -> bool:
        """A compared code is logged each time (PAIR_WRONG_PER_INVITE at most); a 429 once per address an invite, as
        nothing bounds how many a caller can earn."""
        if refused[0] != 429:
            return True
        if address in self._told_over_rate:
            return False
        self._told_over_rate.add(address)
        return True

    def _take(self, address: str) -> bool:
        now = self._clock()
        rate = (PAIR_WRONG_PER_INVITE - PAIR_BURST - 1) / self._secs  # tokens a second
        tokens, then = self._buckets.get(address, (float(PAIR_BURST), now))
        tokens = min(float(PAIR_BURST), tokens + (now - then) * rate)
        if tokens < 1:
            self._buckets[address] = (tokens, now)
            return False
        self._buckets[address] = (tokens - 1, now)
        return True

    def _from(self) -> str:
        """The addresses wrong codes came from, most first, each with its network."""
        ranked = sorted(self.guessers.items(), key=lambda kv: -kv[1])
        named = [f"{a or 'an unknown address'}{f' ({network(a)})' if network(a) else ''}: {n}" for a, n in ranked[:5]]
        more = f", and {len(ranked) - 5} more" if len(ranked) > 5 else ""
        return "; ".join(named) + more

    def matches(self, code) -> bool:
        return self._hash is not None and hmac.compare_digest(_digest(_normal_code(code)), self._hash)


class Mirrors:
    """$STATE/harness/remote/<node id>/<id>.<gen>.jsonl, 0600 in 0700 folders, each beside <id>.<gen>.offset: the node's
    next_offset after the last frame appended. Resume comes from those, never from a mirror's size: masking on the node
    changes line lengths, so a mirror's size says nothing about the node's file.

    A session the hub has no mirror of gets its whole file from offset 0: that backlog is written to
    <id>.<gen>.jsonl.part, which the follower cannot see, and becomes the mirror (promote) once it is all here. The
    follower opens the mirror at its end, so what came before the join is in the record but never fed as news."""

    def __init__(self, root: Path):
        self.root = root
        self._used: dict[str, int] = {}  # bytes of each node's mirror files, summed on first use

    def used(self, node_id: str) -> int:
        if node_id not in self._used:
            folder = self.root / node_id
            self._used[node_id] = sum(p.stat().st_size for p in folder.glob("*.jsonl*")) if folder.is_dir() else 0
        return self._used[node_id]

    def path(self, node_id: str, sid: str, gen: int) -> Path:
        return self.root / node_id / f"{sid}.{gen}.jsonl"

    @staticmethod
    def _part(path: Path) -> Path:
        return path.with_name(path.name + ".part")

    @staticmethod
    def _offset(path: Path) -> Path:
        return path.with_suffix(".offset")

    def _file(self, node_id: str, sid: str, gen: int) -> Path:
        """Where frames for this gen go now: the backlog while it arrives, else the mirror."""
        path = self.path(node_id, sid, gen)
        return self._part(path) if self._part(path).exists() else path

    def _gens(self, node_id: str, sid: str) -> list[int]:
        folder = self.root / node_id
        if not folder.is_dir():
            return []
        gens = set()
        for p in folder.glob(f"{sid}.*.jsonl*"):
            gen, _, kind = p.name[len(sid) + 1:].partition(".")
            if gen.isdigit() and kind in ("jsonl", "jsonl.part"):
                gens.add(int(gen))
        return sorted(gens)

    def latest(self, node_id: str, sid: str) -> int | None:
        gens = self._gens(node_id, sid)
        return gens[-1] if gens else None

    def stored(self, node_id: str, sid: str, gen: int) -> int:
        try:
            return int(self._offset(self.path(node_id, sid, gen)).read_text())
        except (OSError, ValueError):
            return 0

    def _create(self, path: Path) -> None:
        _private_dir(self.root.parent)
        _private_dir(self.root)
        _private_dir(path.parent)
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))

    def repoint(self, node_id: str, sid: str, gen: int, history: bool = False) -> bool:
        """The session moved to a new file (/clear, /resume), or this hub sees it for the first time: a new mirror from
        offset 0; older ones go. True when it is a backlog: no mirror of this session before, or the node said the
        new gen re-ships a file that already happened (`history`)."""
        latest = self.latest(node_id, sid)
        if latest is not None and gen <= latest:
            return False
        path = self.path(node_id, sid, gen)
        backlog = latest is None or history
        self._create(self._part(path) if backlog else path)
        _write_private(self._offset(path), "0\n")
        for old in self._gens(node_id, sid):
            if old < gen:
                old_path = self.path(node_id, sid, old)
                for p in (old_path, self._part(old_path), self._offset(old_path)):
                    p.unlink(missing_ok=True)
        self._used.pop(node_id, None)
        return backlog

    def promote(self, node_id: str, sid: str) -> None:
        gen = self.latest(node_id, sid)
        if gen is not None and self._part(self.path(node_id, sid, gen)).exists():
            os.replace(self._part(self.path(node_id, sid, gen)), self.path(node_id, sid, gen))

    def in_backlog(self, node_id: str, sid: str) -> bool:
        gen = self.latest(node_id, sid)
        return gen is not None and self._part(self.path(node_id, sid, gen)).exists()

    def full(self, node_id: str) -> bool:
        return self.used(node_id) >= MAX_MIRROR_BYTES_PER_NODE

    def append(self, node_id: str, frame: dict) -> bool:
        """Append a `transcript` frame's entries if it starts where the last one ended; False for a gap or a stale gen,
        and the caller asks the node to resume from resume_point(). Entries that would take the node's mirrors past
        MAX_MIRROR_BYTES_PER_NODE are not written, but the offset still moves, so the link stays in step (full())."""
        sid, gen = frame["id"], frame["gen"]
        latest = self.latest(node_id, sid)
        if latest is not None and gen < latest:
            return False
        if latest is None or gen > latest:
            self.repoint(node_id, sid, gen)
        if frame["offset"] != self.stored(node_id, sid, gen):
            return False
        data = "".join(frame["entries"]).encode()
        if self.used(node_id) + len(data) <= MAX_MIRROR_BYTES_PER_NODE:
            fd = os.open(self._file(node_id, sid, gen), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "ab") as f:
                f.write(data)
            self._used[node_id] += len(data)
        else:
            self._used[node_id] = MAX_MIRROR_BYTES_PER_NODE  # full until a repoint or a prune frees some
        _write_private(self._offset(self.path(node_id, sid, gen)), f"{frame['next_offset']}\n")
        return True

    def resume_point(self, node_id: str, sid: str) -> dict:
        gen = self.latest(node_id, sid) or 0
        return {"gen": gen, "offset": self.stored(node_id, sid, gen)}

    def sids(self, node_id: str) -> set[str]:
        folder = self.root / node_id
        return {p.name.split(".")[0] for p in folder.glob("*.jsonl*")} if folder.is_dir() else set()

    def resume(self, node_id: str) -> dict:
        return {sid: self.resume_point(node_id, sid) for sid in sorted(self.sids(node_id))}

    def prune(self, now: float, live: set[tuple[str, str]]) -> None:
        """A session's mirrors go PRUNE_AFTER_SECS after it is first seen off the voice (a `.left` mark holds when)."""
        if not self.root.is_dir():
            return
        for folder in [p for p in self.root.iterdir() if p.is_dir()]:
            for sid in {p.name.split(".")[0] for p in folder.iterdir()}:
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
                    self._used.pop(folder.name, None)
            if not any(folder.iterdir()):
                folder.rmdir()


@dataclass
class Node:
    """A paired node as the hub sees it now. `machine` is its entry in sessions.MACHINES, which routing, the brain's
    context and the status read."""

    id: str
    machine: Machine
    offline_at: float  # monotonic: when its link dropped, or this hub started
    socket: object = None
    sessions: dict[str, dict] | None = None  # its last `sessions` snapshot by its own ids; None: none since this start
    waiting: dict[str, asyncio.Future] = field(default_factory=dict)
    lock: asyncio.Lock | None = None
    backlog: dict[str, asyncio.TimerHandle] = field(default_factory=dict)
    full: bool = False  # its mirrors reached MAX_MIRROR_BYTES_PER_NODE (logged once)
    heartbeat: nodelink.Heartbeat | None = None  # the live link's
    link_tasks: set[asyncio.Task] = field(default_factory=set)  # the live link's reader and keep-alive
    protocol: int = nodelink.MIN_PROTOCOL  # the live link's: the newest both sides speak
    features: list[str] = field(default_factory=list)  # the live link's: those both sides listed (nodelink.FEATURES)
    skewed: bool = False  # machine.notice is _skewed's line: cleared when the machine links
    heard: asyncio.Event = field(default_factory=asyncio.Event)  # set on every frame from the node
    probing: bool = False
    address: str = ""  # the peer address of the live link

    @property
    def name(self) -> str:
        return self.machine.name

    @property
    def online(self) -> bool:
        return self.socket is not None


class Hub:
    """The daemon's side of every node link. `host` is what the daemon lends (harnesses.HOST: register_remote,
    remote_permission, remote_resolved, call_state, and optionally vendors); see harnesses/__init__.py for the seam."""

    def __init__(self, state_dir: Path, registry: Registry, host=None,
                 clock: Callable[[], float] = time.time, monotonic: Callable[[], float] = time.monotonic):
        self.state_dir, self.registry, self.host = state_dir, registry, host if host is not None else harnesses.HOST
        self._clock, self._mono = clock, monotonic
        self.nodes = NodesRegistry(state_dir / "nodes.json")
        self.invites = Invites(monotonic)
        self.mirrors = Mirrors(state_dir / "harness" / "remote")
        self.links = nodelink.Links()
        self._waiting: dict[str, int] = {}  # address: sockets there still before their hello (serve)
        self._refusals_told: dict[str, float] = {}  # address: when a refused link from it was last logged
        self.live: dict[str, Node] = {}
        for paired in self.nodes.nodes.values():
            self._track(paired)
        self._tasks: set[asyncio.Task] = set()
        self.on_forget: Callable[[str], None] | None = None  # machines.Dialer: a forgotten machine is no longer dialed

    def _track(self, paired: dict) -> Node:
        """A node's live record, and its entry in sessions.MACHINES: offline since now until its link is up."""
        dialed = isinstance(paired.get("dial"), dict)
        machine = Machine(name=paired["name"], id=paired["id"], os=paired.get("os", ""), online=False,
                          since=self._clock(), key_fp=nodelink.fingerprint(paired["key"]) if paired.get("key") else "",
                          dialed=dialed, owner=str(paired.get("owner") or "") if dialed else "",
                          grant=str(paired.get("grant") or "") if dialed else "",
                          me=str(paired.get("person_name") or "") if dialed else "",
                          removed=bool(dialed and paired.get("removed")),
                          notice=removed_line(paired["name"]) if paired.get("removed") else "")
        sessions.MACHINES[machine.name] = machine
        node = self.live[paired["id"]] = Node(id=paired["id"], machine=machine, offline_at=self._mono())
        if paired.get("removed"):  # its sessions are not kept for a link that will not come back
            node.offline_at -= nodelink.OFFLINE_GRACE_SECS
        return node

    def wrap(self, session: Session, inner: harnesses.Harness) -> harnesses.Harness:
        """For harnesses.set_remote: the adapter of a session on another machine."""
        return RemoteHarness(self, inner)

    def _hook(self, name: str):
        return getattr(self.host, name, None)

    def _call_state(self) -> dict:
        state = self._hook("call_state")
        call = state() if state else None
        return {"up": bool(call and call.get("up")), "approvals_terminal": bool(call and call.get("approvals_terminal"))}

    def _vendors(self) -> list[str]:
        vendors = self._hook("vendors")
        return list(vendors()) if vendors else []

    # ---------- what RemoteHarness and the daemon ask ----------

    def _node_of(self, session: Session) -> Node | None:
        return self.live.get(session.harness_data.get("node_id")) if session.machine else None

    def _sessions_of(self, node: Node) -> list[Session]:
        return [s for s in self.registry.sessions.values() if s.machine and s.harness_data.get("node_id") == node.id]

    def _session(self, node: Node, sid: str) -> Session | None:
        return self.registry.sessions.get(hub_session_id(node.id, sid))

    def alive(self, session: Session) -> bool:
        """From the node's state, never a pid: listed in its last snapshot while online, and kept for
        OFFLINE_GRACE_SECS after its link drops (or after this hub started, until the node reconnects). False makes
        the daemon's _reap_dead take it off: so a session that left, or a revoked node's, goes within one check."""
        node = self._node_of(session)
        if node is None:
            return False
        if node.online:
            return node.sessions is None or session.harness_data.get("remote_id") in node.sessions
        return self._mono() - node.offline_at < nodelink.OFFLINE_GRACE_SECS

    def transcript_path(self, session: Session) -> str:
        """The mirror of the session's newest file, so a /clear on the node moves the follower here too."""
        node_id, sid = session.harness_data.get("node_id", ""), session.harness_data.get("remote_id", "")
        return str(self.mirrors.path(node_id, sid, self.mirrors.latest(node_id, sid) or 0))

    def machines(self) -> list[dict]:
        """The nodes, for `pointe hub nodes` (the status's `machines` is the daemon's, from sessions.MACHINES)."""
        return [{"id": n.id, "name": n.name, "here": False, "os": n.machine.os, "online": n.online,
                 "since": n.machine.since, "sessions": len(self._sessions_of(n)), "rtt_ms": n.machine.rtt_ms,
                 "key_fp": n.machine.key_fp,
                 **({"owner": n.machine.owner, "grant": n.machine.grant} if n.machine.dialed else {}),
                 **({"removed": True} if n.machine.removed else {}),
                 **({"notice": n.machine.notice} if n.machine.notice else {})} for n in self.live.values()]

    def name_problem(self, name: str, replacing: str = "") -> str | None:
        """A machine's own sessions do not count: one revoked and paired again (a rotated certificate) still has its
        old sessions listed, named "shop devbox" by the machine suffix, until the next liveness check reaps them.
        `replacing`: the id of the entry this name is for, when a machine is added again."""
        others = [s for s in self.registry.sessions.values() if (s.machine or "").lower() != name.lower()]
        self.nodes.refresh()
        taken = [n["name"] for n in self.nodes.nodes.values() if n["id"] != replacing]
        return name_problem(name, taken, others, _here(self.state_dir))

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

    async def _request(self, node: Node, key: str, text: str, timeout: float = nodelink.SEND_TIMEOUT_SECS):
        """Send a frame and wait for its reply: the reply's value, or None (offline, or no reply in time)."""
        future = asyncio.get_running_loop().create_future()
        node.waiting[key] = future
        try:
            if not await self._send(node, text):
                return None
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            node.waiting.pop(key, None)

    async def send(self, session: Session, text: str, anyway: bool = False) -> bool:
        """`anyway`: deliver although the session works on another person's request. A send the machine refused
        (a person may only watch, the session is busy, private, at a prompt, or the words claim a consent) leaves why
        on the session (`turned_down`), for the daemon to say in a sentence (machines.refusal)."""
        node = self._node_of(session)
        if node is None or not node.online:
            return False
        req = nodelink.new_id()
        sent = encode("send", req=req, id=session.harness_data["remote_id"], text=text,
                      **({"anyway": True} if anyway else {}))
        session.turned_down = None
        reply = await self._request(node, f"send:{req}", sent)
        if not isinstance(reply, tuple):
            return False
        ok, held, why, busy = reply
        if held == "held":  # the node's Claude Code kept it for approval in that terminal: said as on this machine
            session.held_at = time.time()
        elif held == "refused":
            session.refused_at = time.time()
        if ok is not True and why and node.machine.dialed:
            session.turned_down = {"why": _cut(why, MAX_LABEL_CHARS), "at": time.time(), "skew": node.machine.skew,
                                   "busy": _bounded_busy(busy)}
        return ok is True

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

    async def discover(self, since: float, cap: int) -> list:
        """What each online node lists (docs/design/attach-by-voice.md), as discovery.Found records named by machine.
        A node that does not answer in time (offline, or an older Pointe) lists nothing."""
        from discovery import Found

        async def one(node: Node) -> list:
            req = nodelink.new_id()
            reply = await self._request(node, f"discover:{req}", encode("discover", req=req, since=float(since), cap=int(cap)),
                                        timeout=DISCOVER_TIMEOUT_SECS)
            out = []
            for raw in reply if isinstance(reply, list) else []:
                found = Found.from_dict(raw)
                if found is not None and _ID.fullmatch(found.id):
                    found.machine = node.name
                    out.append(found)
            return out

        groups = await asyncio.gather(*(one(n) for n in self.live.values() if n.online))
        return [f for group in groups for f in group]

    async def attach(self, found) -> tuple[bool, str | None]:
        """Ask the found session's node to join it, as /pointe:voice there would; it then arrives in the node's
        `sessions` snapshot. (ok, why)."""
        node = next((n for n in self.live.values() if n.name == found.machine), None)
        if node is None or not node.online:
            return False, f"{found.machine} is offline."
        req = nodelink.new_id()
        fields = {"reopen": True} if found.state != "open" else {}
        reply = await self._request(node, f"attach:{req}", encode("attach", req=req, harness=found.harness, id=found.id, **fields),
                                    timeout=DISCOVER_TIMEOUT_SECS)
        if reply is None:
            return False, f"{found.machine} did not answer. It may run an older Pointe: update it there."
        return reply

    async def leave(self, session: Session) -> None:
        node = self._node_of(session)
        if node is not None:
            await self._send(node, encode("leave", id=session.harness_data["remote_id"]))

    def on_call(self, call: dict) -> None:
        """HOST.on_call: the daemon's call state changed. Sent as `call` to every node, from the event loop."""
        frame = encode("call", up=bool(call.get("up")), approvals_terminal=bool(call.get("approvals_terminal")))
        for node in [n for n in self.live.values() if n.online]:
            self._spawn(self._send(node, frame))

    def _spawn(self, coro) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drop_unpaired(self) -> None:
        """Machines whose keys left nodes.json under the daemon (`pointe pair rotate` or `off`): their links close now,
        as a revoke closes one."""
        self.nodes.refresh()
        for node in [n for n in self.live.values() if self.nodes.get(n.id) is None]:
            await self._forget(node, "revoked")

    async def revoke(self, name: str) -> bool:
        paired = self.nodes.by_name(name)
        if paired is None:
            return False
        await self._forget(self.live.get(paired["id"]) or self._track(paired), "revoked")
        return True

    async def _forget(self, node: Node, why: str) -> None:
        """Revoked here, or it left: its key goes, and a live link is closed. Its sessions are no longer alive, so the
        daemon's next liveness check takes them off the voice."""
        if why == "left" and node.machine.dialed:  # a machine this voice dialed says it is done with this person
            return self.removed(node)
        self.nodes.remove(node.id)
        self.live.pop(node.id, None)
        if sessions.MACHINES.get(node.name) is node.machine:
            del sessions.MACHINES[node.name]
        ws = node.socket
        if ws is not None:
            if why == "revoked":  # a machine this voice dialed is told as a node tells its hub: `bye`
                await self._send(node, encode("bye" if node.machine.dialed else "unpaired"))
            node.socket = None  # gone, not offline
            await _close(ws, 1000, why)
        if self.on_forget is not None:
            self.on_forget(node.id)
        logger.info(f"node {node.name} {why}: forgotten")

    def removed(self, node: Node) -> None:
        """The owner of a machine this voice dialed removed this person (the link closed with 4401): the key goes,
        the machine stays listed with one line that says so, and it is not dialed again. Its sessions leave the voice
        at the next liveness check."""
        self.nodes.update(node.id, key="", removed=True)
        node.machine.notice, node.skewed, node.machine.removed = removed_line(node.name), False, True
        node.machine.key_fp = ""
        node.offline_at = self._mono() - nodelink.OFFLINE_GRACE_SECS
        logger.info(f"{node.machine.notice}: its key is deleted, and it is not dialed again")

    # ---------- pairing ----------

    def pair(self, body, address: str) -> tuple[int, dict | str]:
        """POST /voice/node/pair: (status, the node's key and the hub's identity, or why not)."""
        invites = self.invites
        if not invites.outstanding:
            return 403, NO_SUCH_INVITE
        body = body if isinstance(body, dict) else {}
        refused = invites.check(body.get("code", ""), address)
        if refused:
            if invites.worth_logging(refused, address):
                logger.warning(f"node pairing from {address}: {refused[1]}")
            return refused if refused[0] == 429 else (403, NO_SUCH_INVITE)
        name = " ".join(str(invites.name or body.get("name") or "").split())
        problem = self.name_problem(name)
        if problem:
            return 409, problem
        invites.cancel()
        paired = self.nodes.add(name, str(body.get("os") or ""))
        self._track(paired)
        invites.paired = {"name": name, "address": address, "network": network(address),
                          "key_fp": nodelink.fingerprint(paired["key"])}
        logger.info(paired_line(invites.paired))
        return 200, {"node_id": paired["id"], "node_key": paired["key"], "name": name,
                     "hub": {"id": self.nodes.hub_id, "name": _here(self.state_dir)}, "vendors": self._vendors()}

    # ---------- the link ----------

    async def serve(self, ws) -> None:
        """The /voice/node WebSocket: a nonce, the node's HMAC over it, then frames until the link drops."""
        address = _peer(ws)
        if sum(self._waiting.values()) >= MAX_WAITING or self._waiting.get(address, 0) >= MAX_WAITING_PER_ADDRESS:
            if self._tell_refusal(address):
                logger.warning(f"node link from {address or 'loopback'} refused before its hello: too many are waiting")
            return await _close(ws, 1013, "too many connections waiting")  # before accept: the node backs off, retries
        self._waiting[address] = self._waiting.get(address, 0) + 1
        try:
            proven = await self._hello(ws, address)
        finally:
            self._waiting[address] -= 1
            if not self._waiting[address]:
                del self._waiting[address]
        if proven is not None:
            await self._linked(ws, address, *proven)

    def _tell_refusal(self, address: str) -> bool:
        now = self._mono()
        if now - self._refusals_told.get(address, now - REFUSED_LOG_SECS) < REFUSED_LOG_SECS:
            return False
        if len(self._refusals_told) >= 4096:  # many addresses: forget the old ones rather than grow
            self._refusals_told = {a: t for a, t in self._refusals_told.items() if now - t < REFUSED_LOG_SECS}
        self._refusals_told[address] = now
        return True

    async def _hello(self, ws, address: str) -> tuple[dict, dict] | None:
        """The challenge and the node's answer: (its pairing, its hello), or None once the socket is closed."""
        await ws.accept()
        nonce = nodelink.new_nonce()
        await ws.send_text(encode("challenge", nonce=nonce, hub={"id": self.nodes.hub_id, "name": _here(self.state_dir)},
                                  protocol=nodelink.PROTOCOL, protocol_min=nodelink.MIN_PROTOCOL, version=skew.version()))
        try:
            hello = decode(await asyncio.wait_for(ws.receive_text(), HELLO_WAIT_SECS), NODE_FRAMES)
        except Exception:  # silence, or it went
            return await _close(ws, nodelink.CLOSE_BAD_HELLO, "no hello")
        if hello is None or hello["t"] != "hello":
            return await _close(ws, nodelink.CLOSE_BAD_HELLO, "hello first")
        paired = self.nodes.get(hello["node"]["id"])
        if paired is not None and (paired.get("dial") or not paired.get("key")):
            paired = None  # a machine this voice dials never links from its side: its entry's key is this person's
        if nodelink.common(hello["protocol"], hello.get("protocol_min")) is None:
            # No protocol both speak: said to the node in the close, and on this side with the machine, by name, when
            # the hello is from the machine it claims to be (its key answers the nonce as every protocol has).
            older = hello["protocol"] < nodelink.MIN_PROTOCOL
            if paired is not None and nodelink.check(paired["key"], nonce, self.nodes.hub_id, hello["auth"]):
                self._skewed(paired, _cut(hello["node"]["version"], 20), older)
            return await _close(ws, nodelink.CLOSE_TOO_OLD, nodelink.too_old(
                "host", nodelink.MIN_PROTOCOL, hello["protocol"]) if older else nodelink.too_old(
                "voice", hello.get("protocol_min") or hello["protocol"], nodelink.PROTOCOL))
        if paired is None or not nodelink.check(paired["key"], nonce, self.nodes.hub_id, hello["auth"]):
            if self._tell_refusal(address):
                logger.warning(f"node link from {address or 'loopback'} refused: "
                               f"{_cut(hello['node']['name'], MAX_LABEL_CHARS)!r} is not paired, or its key is wrong")
            return await _close(ws, nodelink.CLOSE_UNAUTHORIZED, "not paired with this hub")
        return paired, hello

    def _skewed(self, paired: dict, version: str, older: bool) -> None:
        """A paired machine whose Pointe shares no protocol with this one: it stays listed, offline, with one line
        that says which side to update. Its sessions are not offered until it links."""
        node = self.live.get(paired["id"]) or self._track(paired)
        sessions.MACHINES[node.name] = node.machine
        node.machine.notice = (
            f"{node.name} runs an older Pointe ({version}). Update it there to see its sessions: pointe update" if older
            else f"{node.name} runs a newer Pointe ({version}) than this machine. Update this one to see its sessions: "
                 "pointe update")
        node.skewed = True
        logger.warning(f"node link refused: {node.machine.notice}")

    async def _linked(self, ws, address: str, paired: dict, hello: dict) -> None:
        """A proven node: one link per key, then frames until it drops."""
        if not self.links.claim(paired["id"], ws) and not await self._replace_stale(paired, ws, address):
            logger.warning(f"node {paired['name']}: a second connection with its key refused")
            return await _close(ws, nodelink.CLOSE_ALREADY_CONNECTED, "already connected")
        node = self.live.get(paired["id"]) or self._track(paired)
        node.socket, node.lock, node.address = ws, asyncio.Lock(), address
        sessions.MACHINES[node.name] = node.machine
        node.machine.online, node.machine.since = True, None
        node.machine.link += 1
        node.machine.skew = self._clock() - hello["now"]
        node.protocol = nodelink.common(hello["protocol"], hello.get("protocol_min"))
        node.features = nodelink.shared(hello.get("features"))
        if node.skewed:  # the machine was updated: _skewed's line no longer holds
            node.skewed, node.machine.notice = False, ""
        heartbeat = node.heartbeat = nodelink.Heartbeat(self._mono)
        logger.info(f"node {node.name} connected (skew {node.machine.skew:+.1f} s)")
        try:
            call = self._call_state()
            await self._send(node, encode("welcome", protocol=node.protocol, features=node.features, call_up=call["up"],
                                          approvals_terminal=call["approvals_terminal"], vendors=self._vendors(),
                                          resume=self.mirrors.resume(node.id)))
            if node.socket is not ws:  # replaced (_replace_stale) while the welcome was going out
                return
            for sid in self.mirrors.sids(node.id):
                if self.mirrors.in_backlog(node.id, sid):  # left by a restart mid-backlog: the rest may never come
                    self._backlog_wait(node, sid)
            tasks = node.link_tasks = {asyncio.create_task(self._read(node, ws, heartbeat)),
                                       asyncio.create_task(self._keep_alive(node, ws, heartbeat))}
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
        finally:
            self.links.release(paired["id"], ws)
            if node.socket is ws:
                self._went_offline(node)

    async def _replace_stale(self, paired: dict, ws, address: str = "") -> bool:
        """A new connection proved it holds the key of a node whose link is still open: True if that old link is stale
        and `ws` now holds the slot. The old link is pinged; any frame from it within STALE_PROBE_SECS proves it alive
        and the new one is refused 4409, so a clone or a stolen key still cannot shadow a node that answers. Silence
        means the node crashed, slept or lost its network, and is reconnecting: without this it would be refused until
        the heartbeat gave up (DEAD_AFTER_SECS). A takeover from another address than the old link's can also be a
        stolen key that silenced the real node's link: the owner is told in one line (Machine.notice, and the log)."""
        old = self.live.get(paired["id"])
        stale = old.socket if old is not None else None
        if stale is None or old.probing or old.heartbeat is None:
            return False
        old.probing = True
        try:
            old.heard.clear()
            if await self._send(old, old.heartbeat.ping()):
                try:
                    await asyncio.wait_for(old.heard.wait(), STALE_PROBE_SECS)
                    return False
                except asyncio.TimeoutError:
                    pass
        finally:
            old.probing = False
        if old.socket is not stale:  # it went, or was replaced, while we waited
            return self.links.claim(paired["id"], ws)
        logger.warning(f"node {old.name}: a new connection with its key, and its old link did not answer for "
                       f"{STALE_PROBE_SECS:.0f} s: the old link is closed")
        if address != old.address:
            old.machine.notice = (f"At {time.strftime('%H:%M', time.localtime(self._clock()))} a connection from "
                                  f"{address or 'an unknown address'} replaced its silent link from "
                                  f"{old.address or 'an unknown address'}. If that was not this machine, revoke it")
            logger.warning(f"node {old.name}: {old.machine.notice}")
        for task in old.link_tasks:
            task.cancel()
        self.links.release(paired["id"], stale)
        self._went_offline(old)
        self._spawn(_close(stale, nodelink.CLOSE_DEAD, "replaced by a new connection"))
        return self.links.claim(paired["id"], ws)

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
            node.heard.set()
            heartbeat.heard()
            frame = decode(text, NODE_FRAMES)
            if frame is None:
                continue
            if frame["t"] == "pong":
                heartbeat.pong(frame["id"])
                node.machine.rtt_ms = heartbeat.rtt_ms
            elif frame["t"] == "bye":
                return await self._forget(node, "left")
            else:
                try:
                    await self._on_frame(node, frame)
                except Exception:
                    logger.exception(f"node {node.name}: handling a {frame['t']!r} frame failed")

    def _went_offline(self, node: Node) -> None:
        """The node released whatever it held to its terminals. Its sessions stay, offline (the daemon's
        _watch_machines says so), until OFFLINE_GRACE_SECS."""
        node.socket, node.offline_at = None, self._mono()
        node.machine.online, node.machine.since = False, self._clock()
        for future in node.waiting.values():
            if not future.done():
                future.set_result(None)
        logger.info(f"node {node.name} offline")

    async def _on_frame(self, node: Node, frame: dict) -> None:
        t = frame["t"]
        if t == "sessions":
            await self._snapshot(node, frame["sessions"])
        elif t == "session.left":
            (node.sessions or {}).pop(frame["id"], None)  # no longer alive: the next liveness check takes it off
        elif t == "transcript":
            sid = frame["id"]
            if _ID.fullmatch(sid) and (sid in (node.sessions or {}) or self.mirrors.latest(node.id, sid) is not None):
                if not self.mirrors.append(node.id, frame):
                    await self._send(node, encode("resume", resume={sid: self.mirrors.resume_point(node.id, sid)}))
                    return
                if self.mirrors.full(node.id) != node.full:
                    node.full = not node.full
                    if node.full:
                        logger.error(f"node {node.name}: its mirrors reached {MAX_MIRROR_BYTES_PER_NODE >> 20} MB; new "
                                     f"transcript lines are not written until a session moves to a new file or leaves")
                if self.mirrors.in_backlog(node.id, sid):
                    self._backlog_wait(node, sid)
        elif t == "transcript.repointed":
            if _ID.fullmatch(frame["id"]) and frame["id"] in (node.sessions or {}):
                if self.mirrors.repoint(node.id, frame["id"], frame["gen"], history=frame.get("history", False)):
                    self._backlog_wait(node, frame["id"])
        elif t == "files":
            session = self._session(node, frame["id"])
            if session is not None:
                session.harness_data["files"] = _names(frame["names"])
        elif t == "permission.request":
            await self._permission(node, frame)
        elif t == "permission.resolved":
            session = self._session(node, frame["id"])
            resolved = self._hook("remote_resolved")
            if session and resolved:
                await _maybe(resolved(session, frame["request_id"], frame["how"]))
        elif t == "discovered":
            future = node.waiting.get(f"discover:{frame['req']}")
            if future is not None and not future.done():
                future.set_result(frame["found"])
        elif t == "attach.result":
            future = node.waiting.get(f"attach:{frame['req']}")
            if future is not None and not future.done():
                future.set_result((frame["ok"], frame.get("why")))
        elif t == "permission.answered":
            future = node.waiting.get(f"answer:{frame['request_id']}")
            if future is not None and not future.done():
                future.set_result((frame["ok"], frame.get("why")))
        elif t == "send.result":
            future = node.waiting.get(f"send:{frame['req']}")
            if future is not None and not future.done():
                future.set_result((frame["ok"], frame.get("held"), frame.get("why"), frame.get("busy")))
        elif t == "you" and node.machine.dialed:  # the machine's owner changed what this person may do there
            node.machine.grant = frame["grant"]
            self.nodes.update(node.id, grant=frame["grant"])
            logger.info(f"{node.name}: this voice may now {frame['grant']}")
        elif t == "sent" and node.machine.dialed:
            session = self._session(node, frame["id"])
            told = self._hook("remote_sent")
            if session is not None and told is not None:
                await _maybe(told(session, _cut(frame["by"], MAX_LABEL_CHARS), _cut(frame["text"], MAX_SENT_CHARS),
                                  frame["at"] + node.machine.skew))

    def _backlog_wait(self, node: Node, sid: str) -> None:
        """The backlog is all here once frames stop for HISTORY_QUIET_SECS: then it becomes the mirror."""
        if sid in node.backlog:
            node.backlog[sid].cancel()

        def promote():
            node.backlog.pop(sid, None)
            self.mirrors.promote(node.id, sid)

        node.backlog[sid] = asyncio.get_running_loop().call_later(HISTORY_QUIET_SECS, promote)

    async def _snapshot(self, node: Node, entries: list[dict]) -> None:
        """A node's full list. New ones join through the daemon's register_remote (it also refreshes known ones and
        puts a prompt the node still holds, `pending`); ones no longer listed are no longer alive."""
        node.sessions = {e["id"]: _bounded(e) for e in entries if _ID.fullmatch(e["id"])}
        if not node.machine.dialed:  # a node of one's own has no other people: it cannot name an owner
            for entry in node.sessions.values():
                entry.pop("owner", None)
        register = self._hook("register_remote")
        for entry in node.sessions.values():
            session = await register(node.id, node.name, entry) if register else None
            pending = entry.get("pending")
            if session is not None and isinstance(pending, dict):
                request = {"t": "permission.request", **pending, "id": entry["id"]}
                if nodelink._valid(request, NODE_FRAMES["permission.request"]):
                    await self._permission(node, request)  # put once by the daemon; `holding` so the node keeps it

    async def _permission(self, node: Node, frame: dict) -> None:
        """Put to the user by the daemon (remote_permission, which returns before the read-out is spoken); `holding`
        only if it holds it, else the node hands it to its terminal after HOLDING_WAIT_SECS."""
        session = self._session(node, frame["id"])
        put = self._hook("remote_permission")
        if session is None or put is None:
            return
        frame = _bounded(frame)
        held = await put(session, frame["request_id"], frame["tool"], frame["description"], frame["preview"],
                         frame["readable"])
        if held:
            await self._send(node, encode("permission.holding", request_id=frame["request_id"]))

    def prune(self) -> None:
        live = {(s.harness_data.get("node_id"), s.harness_data.get("remote_id"))
                for s in self.registry.sessions.values() if s.machine}
        self.mirrors.prune(self._clock(), live)


def _peer(ws) -> str:
    client = getattr(ws, "client", None)
    return str(getattr(client, "host", "") or "")


async def _close(ws, code: int, reason: str) -> None:
    try:
        await ws.close(code=code, reason=reason)
    except Exception:  # already closed
        pass


def install(app, hub: Hub, link: Callable[[str], str] | None = None) -> None:
    """The node routes, the owner's /voice/hub/* routes, the remote adapter and what the link sets on its host
    (on_call, invite), and hourly mirror pruning. In daemon.py, after the lifespan is set:
        hub_nodes.install(app, hub_nodes.Hub(STATE_DIR, REGISTRY))
    `link(code)` builds the invite line (pair.invite_link; SystemExit with the fix when no address is paired)."""
    from contextlib import asynccontextmanager

    from fastapi import Request, WebSocket
    from fastapi.responses import JSONResponse, PlainTextResponse

    from remote import Remote

    if link is None:
        from pair import invite_link as link
    harnesses.set_remote(hub.wrap)
    hub.host.on_call = hub.on_call
    hub.host.invite = hub.invites.status
    hub.host.invite_ended = lambda: hub.invites.ended  # cancelled by guessing: shown to the owner until the next invite

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
        if not hub.invites.outstanding:  # answered before a byte of the body is read
            return PlainTextResponse(hub.pair({}, "")[1], status_code=403)
        body = await pairing_body(request)
        if body is None:
            return PlainTextResponse("too large", status_code=413)
        status, answer = hub.pair(body, request.client.host if request.client else "")
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
            from pair import NOT_SET_UP
            # The words are the CLI's (pointe hub invite prints them); the header lets the page offer its own Phone step.
            return PlainTextResponse(str(e), status_code=409, headers={"x-pointe-fix": "phone"} if str(e) == NOT_SET_UP else None)
        hub.invites.link = line
        return {"code": code, "expires_in": INVITE_SECS, "link": line}

    @app.get("/voice/hub/invite")
    async def hub_invite_status(request: Request):
        if not owner(request):
            return refused
        return {**(hub.invites.status() or {"code": None, "expires_in": 0}), "paired": hub.invites.paired,
                "ended": hub.invites.ended}

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

def _daemon(method: str, path: str, body: dict | None = None, timeout: float = 5) -> dict:
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
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                              skew.HEADER: skew.header("cli", skew.version())})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        said = e.read().decode(errors="replace")
        if said.lstrip().startswith("{"):  # a Pointe of another version, or without this key: its sentence (skew.py)
            raise SystemExit(skew.sentence(e.code, said, port))
        raise SystemExit(said or str(e))
    except urllib.error.URLError:
        raise SystemExit(f"The voice daemon is not running on port {port}: start it with /pointe:voice, then retry.")


def main(argv: list[str]) -> None:
    command = argv[0] if argv else "help"
    if command == "invite":
        name = argv[argv.index("--name") + 1] if "--name" in argv[:-1] else None
        made = _daemon("POST", "/voice/hub/invite", {"name": name} if name else {})
        print(made["link"])
        print("Valid once, for ten minutes. On the other machine: pointe node join '<the line above>'", flush=True)
        wrong = 0
        try:
            while True:
                time.sleep(1)
                now = _daemon("GET", "/voice/hub/invite")
                if now.get("paired"):
                    return print(paired_line(now["paired"]))
                if not now.get("code"):
                    why = f"{now['ended'][0].upper()}{now['ended'][1:]}" if now.get("ended") else \
                        "The invite expired or was cancelled"
                    raise SystemExit(f"{why}: run pointe hub invite again.")
                if now.get("wrong_codes", 0) > wrong:
                    wrong = now["wrong_codes"]
                    print(f"{wrong} wrong code{'s' if wrong > 1 else ''} tried against this invite (it ends at "
                          f"{PAIR_WRONG_PER_INVITE})", flush=True)
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
