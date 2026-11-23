"""A node: a machine whose sessions another machine's voice (the hub) talks to. docs/design/multi-machine.md.

The node is a file shipper and a hand, not a cut-down brain. It listens on 127.0.0.1:<daemon port> as the daemon does
(same token and daemon.pid files), so register-session, the permission hook, claude-voice-attach and `pointe join`
work unchanged; it ships each session's transcript to the hub as complete lines with this machine's byte offsets,
delivers the hub's sends, and holds permission prompts, re-checking every verdict against its own copy of the request.
No model, no vendor key, no Pipecat: tests/test_node.py asserts the import set.

    node.py serve [--port PORT]   run the node (bin/voice-node starts it)
Pairing and the everyday commands (pointe node join|status|leave) are node_cli.py.
"""

import argparse
import asyncio
import hmac
import json
import os
import platform
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import aiohttp  # noqa: E402
from loguru import logger  # noqa: E402

import childenv  # noqa: E402
import guards  # noqa: E402
import harnesses  # noqa: E402
import nodelink  # noqa: E402
import readout  # noqa: E402
from harnesses.base import HOST  # noqa: E402
from sessions import Registry, Session, wait_state  # noqa: E402

# loguru's default sink prints each frame's variables under a traceback (diagnose): a key, a URL with ?key=, in a log a
# failure shows. Replaced by one that does not, before Pointe logs anything (tests/test_log_tracebacks.py).
try:
    logger.remove(0)
except ValueError:  # replaced already
    pass
else:
    logger.add(sys.stderr, diagnose=False, backtrace=False)

NO_WAIT = {"blocked_on": "", "blocked_since": None, "held_at": None}

STATE = Path(os.environ.get("CLAUDE_VOICE_STATE", Path.home() / ".claude-voice"))
PORT = int(os.environ.get("CLAUDE_VOICE_DAEMON_PORT", "7860"))
POLL_SECS = 0.3  # as the daemon tails a local transcript (sessions.py)
READ_MAX = 4 << 20  # bytes read from one transcript per poll: a long backlog ships over several polls
LIVENESS_SECS = 5
GRACE_SECS = nodelink.HOLD_GRACE_SECS


# ---------- masking: the high-precision rules only ----------

_PRECISE = [*readout._SECRET_SHAPES]


def precise_mask(text: str) -> str:
    """readout.mask's high-precision rules: token shapes, private-key blocks, URL passwords, and quoted or env-style
    values of secret-like names. Not this machine's own key values (a node has none) and not bare `name: value` guesses,
    so the hub's reader is not handed a record with ordinary values blanked."""
    if not text:
        return text
    for shape in _PRECISE:
        text = shape.sub(readout.MASK, text)
    text = readout._URL_PASSWORD.sub(lambda m: m.group(1) + readout.MASK + m.group(3), text)
    text = readout._ASSIGNED_QUOTED.sub(lambda m: f"{m.group(1)}{m.group(2)}{readout.MASK}{m.group(2)}", text)
    text = readout._ASSIGNED_ENV.sub(lambda m: m.group(1) + readout.MASK, text)
    return readout._ASSIGNED_INLINE.sub(lambda m: m.group(1) + readout.MASK, text)


def _mask_strings(value):
    if isinstance(value, str):
        return precise_mask(value)
    if isinstance(value, list):
        return [_mask_strings(v) for v in value]
    if isinstance(value, dict):
        return {k: _mask_strings(v) for k, v in value.items()}
    return value


def mask_line(line: str) -> str:
    """One transcript line with its string fields masked. Masked inside the parsed entry, never on the raw text, so a
    quote or an escape cannot be eaten and the hub still reads a JSON entry. Unchanged lines ship byte for byte."""
    try:
        entry = json.loads(line)
    except ValueError:
        masked = precise_mask(line)
        return masked if masked.endswith("\n") else masked + "\n"
    masked = _mask_strings(entry)
    return line if masked == entry else json.dumps(masked, ensure_ascii=False) + "\n"


def _line_end(f, read: int) -> int | None:
    """Bytes from the read's start to the end of the line it is in, with `read` bytes already read and no newline in
    them; None when the file ends before the line does."""
    while True:
        chunk = f.read(READ_MAX)
        if not chunk:
            return None
        i = chunk.find(b"\n")
        if i >= 0:
            return read + i + 1
        read += len(chunk)


def masked_frames(session_id: str, gen: int, offset: int, data: bytes, skipped: int = 0) -> tuple[list[str], int]:
    """nodelink.transcript_frames, with each line masked: offsets count this file's bytes, entries are the masked
    lines (masking changes lengths, which is why the hub persists next_offset and never trusts a mirror's size).
    `skipped` bytes at `offset`, before `data`, are a line not shipped: the first frame counts them."""
    frames: list[str] = []
    start = offset
    pos = offset + skipped
    entries: list[str] = []
    size = 0
    overhead = len(nodelink.encode("transcript", id=session_id, gen=gen, offset=0, next_offset=0, entries=[])) + 40

    def flush() -> None:
        nonlocal start, entries, size
        frames.append(nodelink.encode("transcript", id=session_id, gen=gen, offset=start, next_offset=pos,
                                      entries=entries))
        start, entries, size = pos, [], 0

    for raw in nodelink.complete_lines(data):
        entry = mask_line(raw.decode("utf-8", "replace")) if len(raw) <= nodelink.MAX_ENTRY_BYTES else None
        if entry is None or len(entry.encode()) > nodelink.MAX_ENTRY_BYTES:
            logger.warning(f"{session_id}: a transcript line of {len(raw)} bytes not shipped")
        else:
            cost = len(json.dumps(entry, ensure_ascii=False).encode()) + 2
            if entries and overhead + size + cost > nodelink.MAX_FRAME_BYTES:
                flush()
            entries.append(entry)
            size += cost
        pos += len(raw)
    if pos > start:
        flush()
    return frames, pos


# ---------- pairing files ----------

def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + ".tmp")
    tmp.touch(mode=0o600)
    tmp.chmod(0o600)
    tmp.write_text(text)
    tmp.replace(path)


def pairing(state: Path) -> tuple[dict, str] | None:
    """node.json and the key for its hub, or None when this machine is not paired."""
    config = _read_json(state / "node.json")
    hub = config.get("hub") or {}
    try:
        key = (state / "node_keys" / str(hub.get("id"))).read_text().strip()
    except OSError:
        return None
    return (config, key) if key and hub.get("host") and hub.get("fp") else None


def forget(state: Path) -> None:
    hub_id = (_read_json(state / "node.json").get("hub") or {}).get("id")
    if hub_id:
        (state / "node_keys" / str(hub_id)).unlink(missing_ok=True)
    (state / "node.json").unlink(missing_ok=True)


def _os() -> str:
    return "macos" if sys.platform == "darwin" else sys.platform


def _version() -> str:
    found = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M)
    return found.group(1) if found else "0"


def _config(state: Path) -> dict:
    """$STATE/config.json: `approvals` and `remote_taps` are read here, at each use, so an edit applies at once."""
    return _read_json(state / "config.json")


# ---------- the node ----------

def _unreachable(e: Exception) -> str:
    """Why the hub cannot be reached, in words: "ClientConnectorError" told a person nothing (QA round 2)."""
    if isinstance(e, asyncio.TimeoutError):
        return "it did not answer in time"
    if isinstance(e, aiohttp.ClientConnectorError):
        return "nothing answers there (is it on, and on this network?)"
    if isinstance(e, aiohttp.WSServerHandshakeError):
        return f"it refused the link (HTTP {e.status})"
    return "the connection failed"


@dataclass
class Tail:
    path: str
    gen: int = 0
    offset: int | None = None  # next byte to ship; None until the hub says where it is (welcome, resume)
    files: list[str] = field(default_factory=list)


@dataclass
class Held:
    request_id: str
    frame: dict  # the permission.request sent, for the snapshot's `pending`
    readable: str | None
    future: asyncio.Future
    deadline: float  # loop time
    holding_by: float  # loop time by which the hub must say `holding`
    holding: asyncio.Event = field(default_factory=asyncio.Event)
    offline_since: float | None = None  # loop time the link dropped while this was held
    why: str | None = None  # why it went back to the terminal, if not a verdict


async def _noop_feed(session, text, respond) -> None:
    """The node does not voice anything: the hub reads the mirror. An adapter's watch still runs, for its side effects
    (OpenCode and Codex write their mirror transcripts there; a turn end releases a held prompt)."""


class Node:
    def __init__(self, state: Path = STATE, port: int = PORT):
        self.state, self.port = Path(state), port
        self.registry = Registry()
        self.registry.load(self.state / "sessions.json")
        self.tails: dict[str, Tail] = {}
        self.held: dict[str, Held] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.tasks: dict[str, list[asyncio.Task]] = {}
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.call_up = self.approvals_terminal = False
        self.vendors: list[str] = []
        self.rtt_ms: int | None = None
        self.link_error = ""
        self.poll = POLL_SECS
        self.holding_wait = nodelink.HOLDING_WAIT_SECS
        self.grace = GRACE_SECS
        self.backoff = nodelink.backoff
        self._send_lock = asyncio.Lock()
        self._background: list[asyncio.Task] = []
        self._spawned: set[asyncio.Task] = set()
        self._last_heard = 0.0
        self.hub_offsets: dict[str, dict] = {}  # the hub's resume, by local id: where its mirror of each session ends
        self.linked = asyncio.Event()  # set while welcomed
        self.finished = asyncio.Event()  # unpaired, revoked or left: the node has nothing left to do
        saved = _read_json(self.state / "node_tails.json")
        self._saved_tails = {k: v for k, v in saved.items() if isinstance(v, dict)}

    @property
    def token(self) -> str:
        try:
            return (self.state / "token").read_text().strip()
        except OSError:
            return ""

    # ---- lifecycle ----

    async def start(self) -> None:
        HOST.hold_permission = self.hold
        HOST.post_channel = self._no_channel
        HOST.state_dir = self.state
        HOST.known_homes = lambda: sorted({s.home for s in self.registry.sessions.values() if s.home})
        for session in list(self.registry.sessions.values()):
            self._start_session(session)
        self._background = [asyncio.create_task(self._link_forever()), asyncio.create_task(self._liveness())]

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._spawned.add(task)
        task.add_done_callback(self._spawned.discard)

    async def stop(self) -> None:
        self._release_all("stopped")
        tasks = [*self._background, *self._spawned, *[t for ts in self.tasks.values() for t in ts]]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
        if self.ws is not None and not self.ws.closed:
            await self.ws.close()

    @staticmethod
    async def _no_channel(session, path, body) -> bool:
        return False  # launch mode (a channel) runs only on the hub's machine

    def _start_session(self, session: Session) -> None:
        saved = self._saved_tails.get(session.id) or {}
        path = self._path(session)
        gen = int(saved.get("gen") or 0)
        if saved.get("path") and saved["path"] != path:
            gen += 1  # it moved while the node was down
        self.tails[session.id] = Tail(path=path, gen=gen)
        self._save_tails()
        watchers = [asyncio.create_task(c) for c in harnesses.of(session).watch(session, _noop_feed)]
        self.tasks[session.id] = [*watchers, asyncio.create_task(self._tail(session)),
                                  asyncio.create_task(self._send_files(session))]

    def _stop_session(self, session_id: str) -> None:
        for task in self.tasks.pop(session_id, []):
            task.cancel()
        self.tails.pop(session_id, None)
        self._saved_tails.pop(session_id, None)
        self._save_tails()

    def _save_tails(self) -> None:
        self._saved_tails.update({sid: {"path": t.path, "gen": t.gen} for sid, t in self.tails.items()})
        _write_private(self.state / "node_tails.json", json.dumps(self._saved_tails))

    @staticmethod
    def _path(session: Session) -> str:
        return harnesses.of(session).transcript_path(session)

    # ---- the HTTP surface the scripts on this machine use ----

    async def register(self, body: dict) -> dict:
        """/voice/register, as the daemon takes it (bin/register-session, harnesses/join.py). ValueError: a 400."""
        if not re.fullmatch(r"[\w-]{1,128}", str(body.get("id"))):
            raise ValueError("bad session id")
        if body.get("channel_url"):
            raise ValueError("launch mode (a channel) runs only on the hub's machine: use /pointe:voice here")
        harness = str(body.get("harness") or "claude-code")
        if harness not in harnesses.names():
            raise ValueError(f"unknown harness; known: {', '.join(harnesses.names())}")
        adapter = harnesses.get(harness)
        home = str(body.get("config_dir") or "")
        if home and (not Path(home).is_absolute() or Path(home).expanduser() == Path.home() / ".claude"):
            home = ""
        session = Session(
            id=body["id"], name=_session_name(body), cwd=str(body["cwd"]), pid=int(body.get("pid") or 0),
            transcript=str(body.get("transcript") or ""), inbox_socket=body.get("inbox_socket"),
            inbox_token=body.get("inbox_token"), harness=harness, home=home,
            harness_data=body.get("harness_data") if isinstance(body.get("harness_data"), dict) else {})
        if body.get("name_given"):
            session.named_by = "user"
        existing = self.registry.sessions.get(session.id)
        if existing:
            for key in ("inbox_socket", "inbox_token", "transcript", "pid", "home"):
                setattr(existing, key, getattr(session, key) or getattr(existing, key))
            self.registry.save()
            return {"name": existing.name, "active": False, "node": True}
        if not body.get("name_given"):
            title = adapter.title(session)
            if title and not self.registry.rename_check(session.id, title):
                session.name, session.named_by = title, "title"
        self.registry.add(session)
        logger.info(f"registered {session.name} (pid {session.pid}, inbox, {harness})")
        self._start_session(session)
        if self.linked.is_set():
            await self._send("session.joined", id=session.id)
            await self._snapshot()
            await self._apply_resume({session.id: self.hub_offsets[session.id]} if session.id in self.hub_offsets
                                     else {}, only=session.id)
        return {"name": session.name, "active": False, "node": True}

    async def leave(self) -> bool:
        """`pointe node leave`: forget the hub. True when `bye` reached it (it forgets this machine too); False when the
        link is down, so the hub still lists this machine until `pointe hub revoke` there."""
        told = await self._send("bye")
        forget(self.state)
        self.finished.set()
        return told

    async def disconnect(self, session_id: str, notify: bool = True) -> bool:
        """The session leaves the voice (pointe leave, claude-voice-attach off, or the hub's `leave`)."""
        session = self.registry.sessions.get(session_id)
        if session is None:
            return False
        self._release(session_id, None, "left")
        self.registry.remove(session_id)
        self._stop_session(session_id)
        try:
            await harnesses.of(session).leave(session)
        except Exception as e:  # an adapter's cleanup must not keep the session listed
            logger.warning(f"{session.name}: leave failed ({type(e).__name__})")
        logger.info(f"{session.name} disconnected")
        if notify and self.linked.is_set():
            await self._send("session.left", id=session_id, why="disconnected")
            await self._snapshot()
        return True

    async def permission_hook(self, payload: dict, gone=None) -> dict:
        """Claude Code's PermissionRequest hook. {} leaves the prompt to the terminal, as on the daemon."""
        session = self.registry.sessions.get(payload.get("session_id"))
        if session is None:
            return {}
        run_in = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None  # the shell's folder now
        verdict = await self.hold(session, str(payload.get("tool_name")), payload.get("tool_input") or {}, gone, run_in=run_in)
        if verdict is None:
            return {}
        decision = {"behavior": verdict, **({"message": "The user denied this."} if verdict == "deny" else {})}
        return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}}

    def status(self) -> dict:
        paired = pairing(self.state)
        hub = (paired[0]["hub"] if paired else {}).get("name")
        return {"node": True, "hub": hub, "link": "up" if self.linked and self.linked.is_set() else "down",
                "link_error": self.link_error, "connected": bool(self.linked and self.linked.is_set() and self.call_up),
                "approvals_terminal": self.approvals_terminal, "rtt_ms": self.rtt_ms, "vendors": self.vendors,
                "remote_taps": _config(self.state).get("remote_taps") or "trusted",
                "key_fp": nodelink.fingerprint(paired[1]) if paired else None,
                "sessions": [{"id": s.id, "name": s.name, "harness": s.harness, "cwd": s.cwd,
                              "pending": s.id in self.held} for s in self.registry.sessions.values()]}

    def app(self):
        from contextlib import asynccontextmanager

        from fastapi import FastAPI, HTTPException, Request

        @asynccontextmanager
        async def lifespan(_app):
            await self.start()
            yield
            await self.stop()

        api = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

        @api.get("/voice/health")
        async def health():
            return {"ok": True, "node": True}  # bin/voice-node tells a node from a daemon by "node"

        @api.post("/voice/register")
        async def register(request: Request):
            try:
                return await self.register(await request.json())
            except (ValueError, KeyError, TypeError) as e:
                raise HTTPException(status_code=400, detail=str(e))

        @api.post("/voice/disconnect")
        async def disconnect(request: Request):
            if not await self.disconnect(str((await request.json()).get("id"))):
                raise HTTPException(status_code=404, detail="not on the voice")
            return {"disconnected": True}

        @api.post("/voice/permission-hook")
        async def permission_hook(request: Request):
            return await self.permission_hook(await request.json(), request.is_disconnected)

        @api.get("/voice/status")
        async def status():
            return self.status()

        @api.post("/voice/node/leave")
        async def leave():
            return {"left": True, "told_hub": await self.leave()}

        return _LocalOnly(api, lambda: self.token)

    # ---- the link ----

    async def _link_forever(self) -> None:
        attempt = 0
        while not self.finished.is_set():
            paired = pairing(self.state)
            if paired is None:
                self.link_error = "not paired"
                self.finished.set()
                return
            welcomed = await self._link_once(*paired)
            if self.finished.is_set():
                return
            attempt = 0 if welcomed else attempt + 1
            await asyncio.sleep(self.backoff(attempt))

    async def _link_once(self, config: dict, key: str) -> bool:
        """One connection: True if the hub welcomed it."""
        hub = config["hub"]
        url = f"wss://{_netloc(hub['host'], int(hub.get('port') or 7443))}{nodelink.PATH}"
        welcomed = False
        try:
            # aiohttp checks the DER SHA-256 right after the TLS handshake, before the HTTP upgrade is written
            async with aiohttp.ClientSession() as http, http.ws_connect(
                    url, ssl=aiohttp.Fingerprint(bytes.fromhex(hub["fp"])), max_msg_size=nodelink.MAX_FRAME_BYTES,
                    autoping=True, timeout=aiohttp.ClientWSTimeout(ws_close=5)) as ws:
                challenge = await self._receive(ws, 10)
                if not challenge or challenge["t"] != "challenge":
                    self.link_error = "the hub sent no challenge"
                    return False
                if challenge["hub"]["id"] != hub["id"]:
                    self.link_error = f"this is not {hub.get('name')}: another hub answers at {hub['host']}"
                    return False
                await ws.send_str(nodelink.encode(
                    "hello", protocol=nodelink.PROTOCOL, auth=nodelink.answer(key, challenge["nonce"], hub["id"]),
                    now=time.time(), node={"id": str(config.get("id")), "name": str(config.get("name") or ""),
                                           "os": _os(), "arch": platform.machine(), "version": _version(),
                                           "harnesses": harnesses.names()}))
                welcome = await self._receive(ws, 10)
                if not welcome or welcome["t"] != "welcome":
                    self._closed(ws)
                    return False
                welcomed = True
                self._hub_named(config, challenge["hub"].get("name"))
                await self._welcomed(ws, welcome)
                watchdog = asyncio.create_task(self._watchdog(ws))
                try:
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        self._last_heard = time.monotonic()
                        frame = nodelink.decode(msg.data, nodelink.HUB_FRAMES)
                        if frame:
                            await self._on_frame(frame)
                finally:
                    watchdog.cancel()
                self._closed(ws)
        except aiohttp.ServerFingerprintMismatch:
            self.link_error = ("the hub's certificate is not the one paired. If the hub re-paired or rotated its "
                               "certificate (pointe pair rotate), pair again: pointe node leave, then a new invite")
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError, ValueError) as e:
            self.link_error = f"cannot reach {hub.get('name')} at {hub['host']}: {_unreachable(e)}"
        finally:
            self._unlinked()
        if self.link_error:
            logger.info(f"link: {self.link_error}")
        return welcomed

    def _hub_named(self, config: dict, name) -> None:
        """The hub says its name at each link (its certificate checked first): a renamed hub is called by its new name
        here too, in pointe node status, pointe open and node leave. node.json was written once, at the join."""
        name = " ".join(str(name or "").split())[:80]
        if not name or name == config["hub"].get("name"):
            return
        logger.info(f"link: the hub {config['hub'].get('name')} is now called {name}")
        config["hub"]["name"] = name
        current = _read_json(self.state / "node.json")
        if (current.get("hub") or {}).get("id") == config["hub"].get("id"):
            current["hub"]["name"] = name
            _write_private(self.state / "node.json", json.dumps(current) + "\n")  # one line, as node_cli writes it

    @staticmethod
    async def _receive(ws, timeout: float) -> dict | None:
        msg = await ws.receive(timeout=timeout)
        return nodelink.decode(msg.data, nodelink.HUB_FRAMES) if msg.type == aiohttp.WSMsgType.TEXT else None

    def _closed(self, ws) -> None:
        code = ws.close_code
        if code == nodelink.CLOSE_UNAUTHORIZED:
            self.link_error = "the hub no longer knows this machine (revoked): the key is deleted; pair again"
            forget(self.state)
            self._release_all("revoked")
            self.finished.set()
        elif code == nodelink.CLOSE_BAD_HELLO:
            self.link_error = "the hub did not get this machine's hello in time; it reconnects"
        elif code == nodelink.CLOSE_ALREADY_CONNECTED:
            self.link_error = "already connected: another process with this machine's key is linked to the hub"
        elif code == nodelink.CLOSE_TOO_OLD:
            self.link_error = "the hub needs a newer Pointe on this machine: update it, then it reconnects"
        elif code == nodelink.CLOSE_DEAD:
            self.link_error = "the link went quiet (no heartbeat)"
        else:
            self.link_error = f"the link closed ({code})"

    async def _welcomed(self, ws, welcome: dict) -> None:
        self.ws, self.link_error = ws, ""
        self.call_up, self.approvals_terminal = welcome["call_up"], welcome["approvals_terminal"]
        self.vendors = welcome["vendors"]
        self._last_heard = time.monotonic()
        self.hub_offsets = {}
        self.linked.set()
        logger.info(f"linked to the hub (call {'up' if self.call_up else 'down'})")
        if self.approvals_terminal or _config(self.state).get("approvals") == "terminal":
            self._release_all("call")  # back, but approvals are answered in terminals: the terminal answers
        await self._snapshot()  # `pending` carries any prompt held over the drop
        if self._forwarding():
            await self._reoffer()
        # Back with no call yet (a restarted hub, before its page reconnects): held prompts wait out their grace
        # window for the call, and are re-offered when `call` says it is up.
        await self._apply_resume(welcome["resume"], everyone=True)

    async def _reoffer(self) -> None:
        """Prompts held through a dropped link, asked again with their request ids: the hub (restarted, or back from a
        network drop) puts them to the user as a re-asked prompt. `holding` is due again."""
        loop = asyncio.get_running_loop()
        for held in list(self.held.values()):
            if held.future.done() or held.offline_since is None:
                continue
            held.offline_since, held.holding_by = None, loop.time() + self.holding_wait
            held.frame["deadline_ms"] = max(0, int((held.deadline - loop.time()) * 1000))
            await self._send(**held.frame)

    def _waiting_for_call(self) -> bool:
        """Some prompt is still held over a drop (its grace window running): a `call` down that only repeats what the
        welcome said must not hand it back early."""
        return any(h.offline_since is not None and not h.future.done() for h in self.held.values())

    def _unlinked(self) -> None:
        if self.linked.is_set() and self.held:
            logger.info(f"link to the hub dropped: held prompts wait {self.grace:.0f} s for it, "
                        f"then go to their terminals")
        self.ws = None
        self.linked.clear()
        self.call_up = False
        self.rtt_ms = None  # a link that is down has no round trip: the last one measured is no longer true
        for tail in self.tails.values():
            tail.offset = None  # the hub says where to resume
        now = asyncio.get_running_loop().time()
        for held in self.held.values():
            if held.offline_since is None:
                held.offline_since = now
                held.holding.clear()

    async def _watchdog(self, ws) -> None:
        """The hub pings every 2 s: silence for DEAD_AFTER_SECS is a dead link (a VPN down, the hub asleep)."""
        while not ws.closed:
            await asyncio.sleep(1)
            if time.monotonic() - self._last_heard > nodelink.DEAD_AFTER_SECS:
                await ws.close(code=nodelink.CLOSE_DEAD)
                return

    async def _send(self, t: str, **fields) -> bool:
        ws = self.ws
        if ws is None or ws.closed:
            return False
        try:
            async with self._send_lock:
                await ws.send_str(nodelink.encode(t, **fields))
            return True
        except (aiohttp.ClientError, ConnectionError, RuntimeError) as e:
            logger.info(f"link: {t} not sent ({type(e).__name__})")
            return False

    def _unprefixed(self, hub_or_local_id: str) -> str:
        """The node's own id for a session id from the hub, which may be the hub's `<node_short>-<id>` form."""
        node_id = str(_read_json(self.state / "node.json").get("id") or "")
        prefix = f"{node_id[:6]}-"
        if node_id and hub_or_local_id not in self.registry.sessions and hub_or_local_id.startswith(prefix):
            return hub_or_local_id[len(prefix):]
        return hub_or_local_id

    def _local(self, hub_or_local_id: str) -> str | None:
        """The registered session a hub frame names, or None."""
        local = self._unprefixed(hub_or_local_id)
        return local if local in self.registry.sessions else None

    async def _on_frame(self, frame: dict) -> None:
        t = frame["t"]
        if t == "ping":
            self.rtt_ms = frame["rtt_ms"]
            await self._send("pong", id=frame["id"])
        elif t == "call":
            self.call_up, self.approvals_terminal = frame["up"], frame["approvals_terminal"]
            if self.approvals_terminal or (not self.call_up and not self._waiting_for_call()):
                self._release_all("call")  # as the daemon hands prompts back when a call ends
            elif self._forwarding():
                await self._reoffer()  # prompts held since before the link came back, now that someone can answer
        elif t == "send":
            self._spawn(self._deliver(frame))
        elif t == "permission.holding":
            held = next((h for h in self.held.values() if h.request_id == frame["request_id"]), None)
            if held:
                held.holding.set()
        elif t == "permission.answer":
            await self._on_answer(frame)
        elif t == "resume":
            await self._apply_resume(frame["resume"])
        elif t == "discover":
            self._spawn(self._discover(frame))
        elif t == "attach":
            self._spawn(self._attach(frame))
        elif t == "leave":
            local = self._local(frame["id"])
            if local:
                await self.disconnect(local, notify=False)
                await self._snapshot()
        elif t == "unpaired":
            self.link_error = "the hub revoked this machine: the key is deleted"
            forget(self.state)
            self._release_all("revoked")
            self.finished.set()
            if self.ws is not None:
                await self.ws.close()

    # ---- adding sessions from the hub (docs/design/attach-by-voice.md) ----

    # What the hub gets of a session that is not on the voice: enough to list it and match words, never its transcript
    # path, socket or account.
    _SHARED = ("harness", "id", "name", "cwd", "state", "when", "title", "branch", "first", "last", "keywords", "kind",
               "status", "name_given", "approvals", "joinable", "why")

    async def _list_here(self, since: float, cap: int) -> list:
        found = []
        for name in harnesses.names():
            try:
                found += await asyncio.wait_for(harnesses.get(name).discover(since, cap), 20)
            except Exception as e:
                logger.info(f"{name} sessions not listed: {type(e).__name__}")
        found = [f for f in found if f.id not in self.registry.sessions]
        self._found = {(f.harness, f.id): f for f in found}
        return found

    async def _discover(self, frame: dict) -> None:
        found = await self._list_here(float(frame["since"]), int(frame["cap"]))
        await self._send("discovered", req=frame["req"], found=[{k: getattr(f, k) for k in self._SHARED} for f in found[:400]])

    async def _attach(self, frame: dict) -> None:
        """Join a listed session here, as /pointe:voice (or `pointe join`) in it would. A recent Claude Code session
        is not reopened from the hub: that needs a terminal on this machine."""
        key = (frame["harness"], frame["id"])
        found = getattr(self, "_found", {}).get(key)
        if found is None:
            await self._list_here(time.time() - 7 * 86400, 40)
            found = self._found.get(key)
        why = None
        try:
            if found is None:
                raise harnesses.StartError("That session is no longer listed there.")
            kind = found.harness  # a listed session, not a session yet: this machine's adapter
            adapter = harnesses.get(kind)
            if frame.get("reopen"):
                if adapter.reopens_in_terminal:
                    raise harnesses.StartError("Pointe reopens Claude Code sessions only on the hub's Mac for now. Resume it "
                                               "there and join it.")
                body = await adapter.reopen(found, "")
            else:
                body = adapter.attach_body(found)
            await self.register({**body, "harness": found.harness})
        except (harnesses.StartError, ValueError) as e:
            why = str(e)
        await self._send("attach.result", req=frame["req"], ok=why is None, **({"why": why} if why else {}))

    async def _deliver(self, frame: dict) -> None:
        local = self._local(frame["id"])
        ok, held = False, {}
        if local:
            session = self.registry.sessions[local]
            began = time.time()
            try:
                ok = bool(await asyncio.wait_for(harnesses.of(session).send(session, frame["text"]),
                                                 nodelink.SEND_TIMEOUT_SECS))
            except asyncio.TimeoutError:
                logger.info(f"send to {session.name} timed out")
            if not ok and (session.held_at or 0) >= began:
                held = {"held": "held"}
            elif not ok and (session.refused_at or 0) >= began:
                held = {"held": "refused"}
        await self._send("send.result", req=frame["req"], ok=ok, **held)

    # ---- transcripts ----

    async def _apply_resume(self, resume: dict, everyone: bool = False, only: str | None = None) -> None:
        """Reseek to where the hub's mirror ends. With `everyone` (a welcome) or `only` (one session joining), a
        session the hub has no offset for starts at 0 in its current gen. Every gen opened here re-ships a file from
        byte 0 that already happened, so its repoint says `history`; a live move (_ship) says it only when the file it
        moved to already holds lines."""
        wanted = {self._unprefixed(k): v for k, v in resume.items()}
        self.hub_offsets.update(wanted)
        for sid, tail in self.tails.items():
            if only is not None and sid != only:
                continue
            at = wanted.get(sid)
            if at is None:
                if everyone or only is not None:
                    tail.offset = 0
                    await self._send("transcript.repointed", id=sid, gen=tail.gen, history=True)
                continue
            size = _size(tail.path)
            if at["gen"] == tail.gen and at["offset"] <= size:
                tail.offset = at["offset"]
                continue
            # the hub is on another file, or past this one's end (it was replaced): a new gen from 0
            tail.gen = max(tail.gen, at["gen"]) + (0 if at["gen"] < tail.gen else 1)
            tail.offset = 0
            self._save_tails()
            await self._send("transcript.repointed", id=sid, gen=tail.gen, history=True)

    async def _tail(self, session: Session) -> None:
        while True:
            await asyncio.sleep(self.poll)
            try:
                await self._ship(session)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # one bad read must not stop the session's record for good
                logger.warning(f"{session.name}: shipping failed ({type(e).__name__}: {e})")

    async def _ship(self, session: Session) -> None:
        tail = self.tails.get(session.id)
        if tail is None or not self.linked.is_set():
            return
        path = self._path(session)
        if path != tail.path:
            tail.path, tail.gen, tail.offset = path, tail.gen + 1, 0
            session.transcript = path
            self._save_tails()
            logger.info(f"{session.name} moved to a new transcript (gen {tail.gen})")
            # A file that already holds lines (/resume) is history, as a local follower seeks to the end of the file
            # it moves to; an empty one (/clear) is live from its first line.
            await self._send("transcript.repointed", id=session.id, gen=tail.gen, history=_size(path) > 0)
            self._spawn(self._send_files(session))
        if tail.offset is None:
            return
        size = _size(path)
        if size < tail.offset:  # rewritten in place: a new gen, from the start
            tail.gen, tail.offset = tail.gen + 1, 0
            self._save_tails()
            await self._send("transcript.repointed", id=session.id, gen=tail.gen)
        if size <= tail.offset:
            return
        with open(path, "rb") as f:
            f.seek(tail.offset)
            data = f.read(min(size - tail.offset, READ_MAX))
            skipped = 0
            if len(data) == READ_MAX and b"\n" not in data:
                # one line longer than a read (a pasted screenshot): without this, every poll re-reads the same bytes
                skipped = _line_end(f, len(data))
                if skipped is None:
                    return  # the line is not written to its end yet
                logger.warning(f"{session.name}: a transcript line of {skipped} bytes not shipped")
                f.seek(tail.offset + skipped)
                data = f.read(max(0, min(size - tail.offset - skipped, READ_MAX)))
        gen, start = tail.gen, tail.offset
        frames, nxt = masked_frames(session.id, gen, start, data, skipped)
        for frame in frames:
            if not await self._send_raw(frame):
                return  # the link dropped: the hub's resume says where to start again
        if tail.gen == gen and tail.offset == start:  # no resume moved it meanwhile
            tail.offset = nxt

    async def _send_raw(self, text: str) -> bool:
        ws = self.ws
        if ws is None or ws.closed:
            return False
        try:
            async with self._send_lock:
                await ws.send_str(text)
            return True
        except (aiohttp.ClientError, ConnectionError, RuntimeError):
            return False

    async def _send_files(self, session: Session) -> None:
        """Up to 40 tracked file names, for the hub's routing hints: at join and after each repoint."""
        tail = self.tails.get(session.id)
        if tail is None:
            return
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "-C", session.cwd, "ls-files", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                env=childenv.child_env())
            out, _ = await asyncio.wait_for(proc.communicate(), 5)
        except (OSError, asyncio.TimeoutError):
            return
        finally:
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.wait()
        names = out.decode(errors="replace").splitlines()[:nodelink.MAX_FILES]
        if names != tail.files:
            tail.files = names
            await self._send("files", id=session.id, names=names)

    async def _snapshot(self) -> None:
        sessions = []
        for s in self.registry.sessions.values():
            adapter = harnesses.of(s)
            held = self.held.get(s.id)
            sessions.append({
                "id": s.id, "name": s.name, "name_given": s.named_by == "user", "cwd": s.cwd, "pid": s.pid,
                "harness": s.harness, "home": s.home, "title": adapter.title(s),
                "capabilities": {**adapter.capabilities(), "side_questions": False},
                "files": self.tails[s.id].files if s.id in self.tails else [],
                "pending": {k: v for k, v in held.frame.items() if k != "t"} if held else None,
                **wait_state(s)})  # a prompt in its terminal, shown on the hub as for its own sessions
        await self._send("sessions", sessions=sessions)

    async def _liveness(self) -> None:
        """As the daemon's loop: probe, drop exited sessions, follow titles."""
        titles: dict[str, str | None] = {}
        waits: dict[str, dict] = {}
        while True:
            await asyncio.sleep(LIVENESS_SECS)
            sessions = list(self.registry.sessions.values())
            probes = [harnesses.of(s).probe(s) for s in sessions]
            if probes:
                try:
                    await asyncio.wait_for(asyncio.gather(*probes, return_exceptions=True), 4)
                except asyncio.TimeoutError:
                    pass
            changed = False
            for session in sessions:
                if not session.alive():
                    self._release(session.id, None, "left")
                    self.registry.remove(session.id)
                    self._stop_session(session.id)
                    logger.info(f"{session.name} exited; removed")
                    await self._send("session.left", id=session.id, why="exited")
                    changed = True
                    continue
                title = harnesses.of(session).title(session)
                if titles.get(session.id) != title:
                    changed = changed or session.id in titles
                    titles[session.id] = title
                wait = wait_state(session)
                if waits.get(session.id, NO_WAIT) != wait:  # a session first seen waiting is news too
                    changed = True
                waits[session.id] = wait
            if changed and self.linked.is_set():
                await self._snapshot()

    # ---- permissions ----

    def _forwarding(self) -> bool:
        return (_config(self.state).get("approvals") != "terminal" and self.linked is not None and self.linked.is_set()
                and self.call_up and not self.approvals_terminal)

    async def hold(self, session: Session, tool_name: str, tool_input: dict, gone=None,
                   deadline_secs: float | None = None, run_in: str | None = None) -> str | None:
        """harnesses.base.HOST.hold_permission on a node: forward the prompt to the hub and wait for a verdict that
        passes the re-check. "allow", "deny", or None (back to the harness's own prompt)."""
        if not self._forwarding():
            return None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (deadline_secs or harnesses.of(session).permission_deadline)
        lock = self.locks.setdefault(session.id, asyncio.Lock())  # one prompt per session at a time, as on the hub
        try:
            await asyncio.wait_for(lock.acquire(), max(0.1, deadline - loop.time()))
        except asyncio.TimeoutError:
            return None
        try:
            return await self._hold_one(session, tool_name, tool_input, gone, deadline, run_in)
        finally:
            lock.release()

    async def _hold_one(self, session: Session, tool_name: str, tool_input: dict, gone, deadline: float,
                        run_in: str | None = None) -> str | None:
        if (gone is not None and await gone()) or not self._forwarding():
            return None
        loop = asyncio.get_running_loop()
        readable = guards.readable_request(tool_name, tool_input, session.cwd, run_in)  # from the unmasked input
        request_id = nodelink.new_id()
        frame = {"t": "permission.request", "id": session.id, "request_id": request_id, "tool": tool_name,
                 "description": precise_mask(str(tool_input.get("description") or "use this tool")),
                 "preview": precise_mask(json.dumps(tool_input, ensure_ascii=False)), "readable": readable,
                 "deadline_ms": max(0, int((deadline - loop.time()) * 1000))}
        held = Held(request_id=request_id, frame=frame, readable=readable, future=loop.create_future(),
                    deadline=deadline, holding_by=loop.time() + self.holding_wait)
        self.held[session.id] = held
        session.permission_id, session.permission_answer = request_id, held.future  # a turn end releases it
        try:
            if not await self._send(**frame):
                return None
            await self._snapshot()
            while not held.future.done():
                now = loop.time()
                if now >= deadline:
                    held.why = "timeout"
                    break
                if held.offline_since is not None:  # the link dropped: wait out the grace window for the hub
                    if now >= held.offline_since + self.grace:
                        held.why = "dropped"
                        break
                    until = held.offline_since + self.grace
                elif not held.holding.is_set():
                    if now >= held.holding_by:
                        held.why = "timeout"
                        break
                    until = held.holding_by
                else:
                    until = deadline
                await asyncio.wait([held.future], timeout=max(0.01, min(1.0, deadline - now, until - now)))
                if not held.future.done() and gone is not None and await gone():
                    held.why = "terminal"
                    break
        finally:
            verdict = held.future.result() if held.future.done() else None
            if not held.future.done():
                held.future.cancel()
            if self.held.get(session.id) is held:
                del self.held[session.id]
            session.permission_id, session.permission_answer = None, None
            if verdict is None:
                why = held.why or "terminal"  # a turn end with nothing chosen here: answered in the terminal
                logger.info(f"permission {session.name}/{request_id} handed back to the terminal ({why})")
                if why in ("timeout", "terminal", "left"):
                    await self._send("permission.resolved", id=session.id, request_id=request_id, how=why)
            if self.linked.is_set():
                self._spawn(self._snapshot())  # `pending` is gone
        return verdict

    def _release(self, session_id: str, verdict: str | None, why: str) -> None:
        held = self.held.get(session_id)
        if held and not held.future.done():
            held.why = why
            held.future.set_result(verdict)

    def _release_all(self, why: str) -> None:
        for session_id in list(self.held):
            self._release(session_id, None, why)

    def recheck(self, held: Held, frame: dict) -> str | None:
        """Why a verdict may not release the hook, or None if it may (the design's re-check table)."""
        if frame["verdict"] == "deny":
            return None  # a no from anywhere denies, even once approvals turned terminal mid-hold
        if _config(self.state).get("approvals") == "terminal":
            return "terminal"
        how = frame["how"]
        if how == "voice":
            if not held.readable:
                return "unreadable"
            return None if frame.get("spoken") == held.readable else "mismatch"
        if how == "notification":
            return None if held.readable else "unreadable"
        if how == "tap":
            if _config(self.state).get("remote_taps") == "readable_only" and not held.readable:
                return "unreadable"
            return None
        return "unknown"

    async def _on_answer(self, frame: dict) -> None:
        local = self._local(frame["id"])
        held = self.held.get(local) if local else None
        if held is None or held.request_id != frame["request_id"] or held.future.done():
            await self._send("permission.answered", request_id=frame["request_id"], ok=False, why="stale")
            return
        why = self.recheck(held, frame)
        if why is None:
            held.future.set_result(frame["verdict"])
            await self._send("permission.answered", request_id=frame["request_id"], ok=True)
        else:
            logger.warning(f"refused a {frame['how']} {frame['verdict']} for {frame['request_id']}: {why}")
            await self._send("permission.answered", request_id=frame["request_id"], ok=False, why=why)


def _size(path: str) -> int:
    try:
        return os.stat(path).st_size
    except OSError:
        return 0


def _netloc(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def _session_name(body: dict) -> str:
    """As the daemon names a session: the one given or the folder's, cleaned and cut; else from the id."""
    from sessions import speakable

    raw = str(body.get("name") or Path(str(body["cwd"])).name)
    name = " ".join(re.sub(r"[^\w ./-]+", " ", raw).split())[:40].strip(" ./-")
    return name if name and speakable(name) else f"session {str(body['id'])[:6]}"


class _LocalOnly:
    """Every route but /voice/health needs the token, and only requests addressed to this machine are served: the
    same rule the daemon's LocalAuth applies on loopback (a container can reach it with any Host header)."""

    def __init__(self, app, token):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        from starlette.requests import HTTPConnection
        from starlette.responses import PlainTextResponse

        connection = HTTPConnection(scope)
        token = self.token()
        ok = guards._local_headers(connection.headers) and (
            scope["path"] == "/voice/health" or (token and hmac.compare_digest(
                connection.headers.get("authorization", "").encode(), f"Bearer {token}".encode())))
        if not ok:
            return await PlainTextResponse("forbidden", status_code=403)(scope, receive, send)
        return await self.app(scope, receive, send)


# ---------- running ----------

def _local_health(port: int) -> dict | None:
    try:
        return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/voice/health", timeout=2).read())
    except (OSError, ValueError):
        return None


DAEMON_HERE = ("a Pointe daemon (a hub, with the call) is running on port {port}. A machine is the hub or a node, not "
               "both: stop it first with bin/voice-daemon stop, or use another port with CLAUDE_VOICE_DAEMON_PORT")


def _daemon_here(port: int) -> bool:
    health = _local_health(port)
    return bool(health) and not health.get("node")


def serve(port: int = PORT, state: Path = STATE) -> None:
    import uvicorn

    if _daemon_here(port):
        raise SystemExit(f"voice-node: {DAEMON_HERE.format(port=port)}")
    if pairing(state) is None:
        raise SystemExit("voice-node: this machine is not paired with a hub: pointe node join '<invite>'")
    node = Node(state, port)
    try:
        sockets = guards.loopback_sockets(port)  # both families, as the daemon does
    except OSError as e:
        raise SystemExit(f"voice-node: cannot listen on 127.0.0.1:{port} and [::1]:{port} ({e.strerror})")
    server = uvicorn.Server(uvicorn.Config(node.app(), port=port, log_level="warning"))

    async def run() -> None:
        serving = asyncio.create_task(server.serve(sockets=sockets))
        done, _ = await asyncio.wait([serving, asyncio.create_task(node.finished.wait())],
                                     return_when=asyncio.FIRST_COMPLETED)
        if serving not in done:  # unpaired, revoked or left: nothing left to serve
            logger.info(f"node: {node.link_error or 'left the hub'}; stopping")
            server.should_exit = True
            await serving

    asyncio.run(run())


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="node.py", description="Run this machine's node (bin/voice-node starts it)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve").add_argument("--port", type=int, default=PORT)
    serve(parser.parse_args(argv).port)


if __name__ == "__main__":
    main(sys.argv[1:])
