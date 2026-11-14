"""The link between a hub (the Mac with the call) and a node (another machine whose sessions it voices).

One WebSocket per node at PATH, text frames, one JSON object each: {"t": "<type>", ...}. The frame tables below are
the contract both sides build to (docs/design/multi-machine.md, "Protocol"). Unknown types and malformed frames are
dropped, so one side can move first. A node imports this module: nothing here may load Pipecat, a model or a key.
"""

import hashlib
import hmac
import json
import math
import secrets
import time
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from loguru import logger

PROTOCOL = 1
INVITE_VERSION = 1  # the `pointe://hub?v=` line's format
MIN_PROTOCOL = 1  # the hub refuses a hello below this with CLOSE_TOO_OLD
PATH = "/voice/node"
PAIR_PATH = "/voice/node/pair"

CLOSE_BAD_HELLO = 4400  # no hello in time, or not a hello: the node keeps its key and reconnects
CLOSE_UNAUTHORIZED = 4401  # wrong HMAC, or a revoked key: the node deletes its key, and only for this code
CLOSE_DEAD = 4408  # no pong for DEAD_AFTER_SECS
CLOSE_ALREADY_CONNECTED = 4409  # a second connection with a key that is already connected; the first stays
CLOSE_TOO_OLD = 4426

MAX_FRAME_BYTES = 1 << 20
MAX_ENTRY_BYTES = 256 << 10  # one transcript line; a longer one is dropped with a warning, its bytes still counted
MAX_FILES = 40  # tracked file names sent for routing hints
PING_SECS = 2.0
DEAD_AFTER_SECS = 12.0
BACKOFF_MAX_SECS = 30
HOLDING_WAIT_SECS = 10.0  # the node hands a prompt back to its terminal if the hub has not said `holding` by then
SEND_TIMEOUT_SECS = 5.0
OFFLINE_GRACE_SECS = 600.0  # a node's sessions stay, offline, this long after its link drops
HOLD_GRACE_SECS = 20.0  # a prompt a node holds outlives a dropped link this long, so a restarting hub can ask it again


Check = Callable[[Any], bool]


def _str(v) -> bool:
    return isinstance(v, str)


def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _count(v) -> bool:
    return _int(v) and v >= 0


def _num(v) -> bool:
    """A finite number: json.loads takes NaN and Infinity, and a NaN skew makes every `since` filter false."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _bool(v) -> bool:
    return isinstance(v, bool)


def _dict(v) -> bool:
    return isinstance(v, dict)


def _list_of(check: Check, most: int | None = None) -> Check:
    return lambda v: isinstance(v, list) and (most is None or len(v) <= most) and all(check(x) for x in v)


def _one_of(*values: str) -> Check:
    return lambda v: v in values


def _or_none(check: Check) -> Check:
    return lambda v: v is None or check(v)


def _has(**fields: Check) -> Check:
    return lambda v: isinstance(v, dict) and all(check(v.get(k)) for k, check in fields.items())


_line = lambda v: isinstance(v, str) and v.endswith("\n")  # noqa: E731: only complete lines cross
_resume = lambda v: isinstance(v, dict) and all(  # noqa: E731
    _str(k) and _has(gen=_count, offset=_count)(at) for k, at in v.items())
_session = _has(id=_str, name=_str, cwd=_str, harness=_str)

# Field name -> check. A name ending in "?" is optional. Extra fields are kept and ignored.
NODE_FRAMES: dict[str, dict[str, Check]] = {
    "hello": {"protocol": _int, "auth": _str, "now": _num,
              "node": _has(id=_str, name=_str, os=_str, arch=_str, version=_str, harnesses=_list_of(_str))},
    "sessions": {"sessions": _list_of(_session)},
    "session.joined": {"id": _str},
    "session.left": {"id": _str, "why": _one_of("exited", "disconnected")},
    "transcript": {"id": _str, "gen": _count, "offset": _count, "next_offset": _count, "entries": _list_of(_line)},
    "transcript.repointed": {"id": _str, "gen": _count, "history?": _bool},
    "files": {"id": _str, "names": _list_of(_str, MAX_FILES)},
    "permission.request": {"id": _str, "request_id": _str, "tool": _str, "description": _str, "preview": _str,
                           "readable": _or_none(_str), "deadline_ms": _count},
    "permission.resolved": {"id": _str, "request_id": _str, "how": _one_of("terminal", "timeout", "left")},
    "permission.answered": {"request_id": _str, "ok": _bool, "why?": _str},
    "send.result": {"req": _str, "ok": _bool},
    "artifact.result": {"req": _str, "view?": _dict},
    "pong": {"id": _int},
    "bye": {},
}

HUB_FRAMES: dict[str, dict[str, Check]] = {
    "challenge": {"nonce": _str, "hub": _has(id=_str, name=_str)},
    "welcome": {"protocol": _int, "call_up": _bool, "approvals_terminal": _bool, "vendors": _list_of(_str),
                "resume": _resume},
    "resume": {"resume": _resume},
    "call": {"up": _bool, "approvals_terminal": _bool},
    "send": {"req": _str, "id": _str, "text": _str},
    "permission.holding": {"request_id": _str},
    "permission.answer": {"id": _str, "request_id": _str, "verdict": _one_of("allow", "deny"),
                          "how": _one_of("voice", "tap", "notification"), "spoken?": _str},
    "artifact.render": {"req": _str, "id": _str, "artifact_id": _str},
    "leave": {"id": _str},
    "unpaired": {},
    "ping": {"id": _int, "rtt_ms": _or_none(_count)},
}


def _valid(frame: dict, fields: dict[str, Check]) -> bool:
    for name, check in fields.items():
        if name.endswith("?"):
            name = name[:-1]
            if name not in frame:
                continue
        if name not in frame or not check(frame[name]):
            return False
    return frame["t"] != "transcript" or frame["next_offset"] >= frame["offset"]


def encode(t: str, **fields) -> str:
    """A frame to send. Raises ValueError for one the other side would drop: that is a bug on this side."""
    schema = NODE_FRAMES[t] if t in NODE_FRAMES else HUB_FRAMES.get(t)
    frame = {"t": t, **fields}
    if schema is None or not _valid(frame, schema):
        raise ValueError(f"not a valid {t!r} frame")
    text = json.dumps(frame, ensure_ascii=False)
    if len(text.encode()) > MAX_FRAME_BYTES:
        raise ValueError(f"{t!r} frame over {MAX_FRAME_BYTES} bytes")
    return text


_unencodable_logged = False


def _encodable(value):
    """`value` with every string UTF-8 can encode. json.loads turns a "\\ud800" escape into a lone surrogate, which
    raises at the first .encode() (the entry size check, a mirror write) and took the link down with it: a lone
    surrogate becomes U+FFFD, logged once."""
    global _unencodable_logged
    if isinstance(value, str):
        try:
            value.encode()
            return value
        except UnicodeEncodeError:
            if not _unencodable_logged:
                _unencodable_logged = True
                logger.warning("a frame carried a string UTF-8 cannot encode (a lone surrogate): replaced with U+FFFD")
            return value.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    if isinstance(value, list):
        return [_encodable(v) for v in value]
    if isinstance(value, dict):
        return {_encodable(k): _encodable(v) for k, v in value.items()}
    return value


def decode(text: str, frames: dict[str, dict[str, Check]]) -> dict | None:
    """A frame received, checked against the table of what this side may receive (NODE_FRAMES on the hub,
    HUB_FRAMES on the node). None for anything else: unknown, malformed, or over the size cap."""
    if not isinstance(text, str) or len(text.encode()) > MAX_FRAME_BYTES:
        return None
    try:
        frame = _encodable(json.loads(text))
    except ValueError:
        return None
    if not isinstance(frame, dict) or not isinstance(frame.get("t"), str) or frame["t"] not in frames:
        return None
    if not _valid(frame, frames[frame["t"]]):
        logger.warning(f"dropped a malformed {frame['t']!r} frame")
        return None
    if frame["t"] == "transcript":
        kept = [e for e in frame["entries"] if len(e.encode()) <= MAX_ENTRY_BYTES]
        if len(kept) < len(frame["entries"]):
            logger.warning(f"dropped {len(frame['entries']) - len(kept)} transcript entries over {MAX_ENTRY_BYTES} bytes")
            frame["entries"] = kept
    return frame


def complete_lines(data: bytes) -> list[bytes]:
    """The complete lines in `data`, each with its b"\\n"; a partial tail is left out. Split on b"\\n" only (JSONL's
    separator), never splitlines(): a bare CR inside a line would cut it into pieces that are not entries."""
    end = data.rfind(b"\n") + 1
    return [line + b"\n" for line in data[:end].split(b"\n")[:-1]]


def transcript_frames(session_id: str, gen: int, offset: int, data: bytes) -> tuple[list[str], int]:
    """`transcript` frames for the bytes read from a session's file at `offset`, and the offset to read from next.

    Only complete lines ship: a partial tail is left for the next poll. Each frame fits MAX_FRAME_BYTES, and frames
    are contiguous (one's next_offset is the next one's offset). A line over MAX_ENTRY_BYTES is not sent, but its
    bytes are counted, so the hub's offsets still match the node's file."""
    frames: list[str] = []
    start = pos = offset
    entries: list[str] = []
    size = 0
    overhead = len(encode("transcript", id=session_id, gen=gen, offset=0, next_offset=0, entries=[]).encode()) + 40

    def flush() -> None:
        nonlocal start, entries, size
        frames.append(encode("transcript", id=session_id, gen=gen, offset=start, next_offset=pos, entries=entries))
        start, entries, size = pos, [], 0

    for raw in complete_lines(data):
        if len(raw) > MAX_ENTRY_BYTES:
            logger.warning(f"{session_id}: a transcript line of {len(raw)} bytes not shipped")
        else:
            entry = raw.decode("utf-8", "replace")
            cost = len(json.dumps(entry, ensure_ascii=False).encode()) + 2
            if entries and overhead + size + cost > MAX_FRAME_BYTES:
                flush()
            entries.append(entry)
            size += cost
        pos += len(raw)
    if pos > start:
        flush()
    return frames, pos


def parse_invite(line: str) -> dict:
    """What `pointe node join` needs from the hub's invite line: {host, port, fp, code}. ValueError for anything else."""
    url = urlparse(line.strip())
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    if url.scheme != "pointe" or url.netloc != "hub" or query.get("v") != str(INVITE_VERSION):
        raise ValueError("not a Pointe hub invite (pointe://hub?v=1&...)")
    fp, port = query.get("fp", "").lower(), query.get("port", "")
    if not (query.get("host") and query.get("code") and port.isdigit() and 0 < int(port) < 65536
            and len(fp) == 64 and all(c in "0123456789abcdef" for c in fp)):
        raise ValueError("the invite is incomplete: copy the whole line `pointe hub invite` printed")
    return {"host": query["host"], "port": int(port), "fp": fp, "code": query["code"]}


def new_nonce() -> str:
    return secrets.token_hex(32)


def new_key() -> str:
    """A node key: 256 bits, hex. Held by the node (node_keys/<hub id>) and the hub (nodes.json), both 0600."""
    return secrets.token_hex(32)


def new_id() -> str:
    """A request id (`req`, `request_id`): random, so a verdict for one request can never match another."""
    return secrets.token_hex(8)


def answer(key: str, nonce: str, hub_id: str) -> str:
    """The node's `hello.auth`: HMAC-SHA256(node key, nonce || hub id). The key itself never crosses the link."""
    return hmac.new(bytes.fromhex(key), bytes.fromhex(nonce) + hub_id.encode(), hashlib.sha256).hexdigest()


def check(key: str, nonce: str, hub_id: str, offered) -> bool:
    """The hub's check of `hello.auth`. False, never an error, for anything malformed."""
    if not isinstance(offered, str):
        return False
    try:
        expected = answer(key, nonce, hub_id)
    except ValueError:
        return False
    return hmac.compare_digest(expected.encode(), offered.encode())


def fingerprint(key: str) -> str:
    """What both sides show, so the owner can see the machine that paired is the one they typed the code on."""
    return hashlib.sha256(bytes.fromhex(key)).hexdigest()[:16]


def hub_session_id(node_id: str, session_id: str) -> str:
    """The id a node's session has on the hub: unique across machines, even for a cloned VM's identical ids."""
    return f"{node_id[:6]}-{session_id}"


def backoff(attempt: int) -> float:
    """Seconds before reconnect number `attempt` (from 0): 1, 2, 4 ... 30."""
    return min(BACKOFF_MAX_SECS, 2 ** attempt)


class Links:
    """One live connection per node key: a cloned VM or a stale process cannot shadow the real node."""

    def __init__(self) -> None:
        self._live: dict[str, object] = {}

    def claim(self, node_id: str, connection: object) -> bool:
        if node_id in self._live:
            return False
        self._live[node_id] = connection
        return True

    def release(self, node_id: str, connection: object) -> None:
        if self._live.get(node_id) is connection:  # a refused second connection closing must not free the slot
            del self._live[node_id]


class Heartbeat:
    """The hub's pings to a node. Like phone.Heartbeat, but a node that never answers is dead too: every node speaks
    this protocol from its first version, so silence from the start is a dead link, not an old client."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.sent: dict[int, float] = {}
        self.next_id = 0
        self.rtt_ms: int | None = None
        self.last_heard = clock()

    def ping(self) -> str:
        self.next_id += 1
        self.sent[self.next_id] = self._clock()
        for old in [i for i in self.sent if i < self.next_id - 10]:
            del self.sent[old]
        return encode("ping", id=self.next_id, rtt_ms=self.rtt_ms)

    def pong(self, ping_id: int) -> None:
        sent = self.sent.pop(ping_id, None)
        if sent is None:
            return
        self.rtt_ms = round((self._clock() - sent) * 1000)
        self.last_heard = self._clock()

    def dead(self) -> bool:
        return self._clock() - self.last_heard > DEAD_AFTER_SECS
