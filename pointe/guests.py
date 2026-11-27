"""A machine serves several people's voices (docs/design/people-and-machines.md): the people its owner invited, the
one-time invite that pairs each, the /voice/host socket a person's voice keeps open, and what the machine enforces on
it. On that link the machine is in the node's role (node.py): it ships each shared session's transcript, masked, with
its own byte offsets, once per linked person, and delivers a person's sends. What a person may see or do is decided
here, never by their voice: which sessions cross, who may send, and whose name a send carries.

  pointe people                              the people invited to this machine
  pointe people invite <name> [--watch]      a one-time line for that person's voice (--watch: they see and hear only)
  pointe people grant <name> send|watch      change what a person may do
  pointe people remove <name>                take a person off: their key is deleted and their link is closed
  pointe people approvals on|off             people who may send can answer a session's permission prompt, or not
  pointe people starts on|off                people who may send can start a session here, or not
  pointe people sessions default|ask         sessions people start follow your default, or always ask before actions
  pointe people window <seconds>             how long a prompt waits for its session's owner before the others get it
  pointe people hold <seconds>               with no call of yours, how long a prompt waits for people before your terminal gets it
  pointe share <session> [--private|--shared]   keep a session to yourself, or share it again
"""

import asyncio
import getpass
import json
import os
import platform
import secrets
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run as a script in isolated mode (-I)
import childenv  # noqa: E402
import guards  # noqa: E402
import harnesses  # noqa: E402
import hub_nodes  # noqa: E402
import nodelink  # noqa: E402
import sessions  # noqa: E402
import shipping  # noqa: E402
import skew  # noqa: E402
from hub_nodes import (INVITE_SECS, NO_SUCH_INVITE, PAIR_WRONG_PER_INVITE, Invites, _close, _cut, _here, _maybe,  # noqa: E402
                       _peer, _write_private, network, pairing_body)
from node import _config, _os, frames_of, masked_lines, precise_mask, recheck  # noqa: E402
from nodelink import GRANTS, HUB_FRAMES, decode, encode  # noqa: E402
from sessions import Registry, Session, speakable, terminal_wait, wait_state  # noqa: E402
from shipping import Tail, size as _size  # noqa: E402

HOST_MIN_PROTOCOL = 2  # this link exists from protocol 2: an older voice has no /voice/host
POLL_SECS = 0.3  # as a node tails a transcript
TITLE_SECS = 5.0  # a session's title is read again this often, as a node's liveness loop does
SETTLE_SECS = 15.0  # after a send a session counts as working this long, until its harness shows the turn
STALE_SECS = 2 * nodelink.PING_SECS  # a link silent this long gives way to a new one with the same key
MAX_VENDORS = 20
MAX_SENT_CHARS = 4000  # of a send, as the other voices on the session get it
# The prompts a session waits at for its owner's yes: no person's send goes in beside one.
PROMPTS = ("permission prompt", "sandbox request")
NOT_OFFERED = "Adding a session on this machine is its owner's to do."
# Prompts and starts for people (phase 3). The machine's owner sets these, for everybody at once.
OWNER_FIRST_SECS = 20.0  # a prompt waits this long for its session's owner before the other people may answer it
OWNER_FIRST_MAX_SECS = 120.0
# With no call of the machine owner's, a prompt held for other people goes to its terminal after this long with no
# answer: the terminal does not show a prompt while it is held, and the owner may be sitting at it.
PEOPLE_HOLD_SECS = 45.0
PEOPLE_HOLD_RANGE = (10.0, 280.0)
OFFER_POLL_SECS = 0.25
GONE_SECS = 1.0  # a prompt no longer pending is "answered in the terminal" this long after, unless the owner's voice says it answered
MAX_STARTS = 3  # starts people asked for that have not joined or failed yet
START_WAIT_SECS = 150.0  # a start's adapter (45 s) and the wait for a session that registers itself (90 s)
ANSWERED_KEPT = 64  # the last requests answered here, so a late verdict hears who answered
RESOLVED_SHOWN_SECS = 30.0  # `resolved_by` stays in the status this long
SETTINGS = {"approve": ("anyone", "off"), "start": ("on", "off"), "sessions_ask": ("default", "ask")}
DEFAULTS = {"approve": "anyone", "start": "on", "sessions_ask": "default", "owner_first_secs": OWNER_FIRST_SECS,
            "people_hold_secs": PEOPLE_HOLD_SECS}
SECONDS = {"owner_first_secs": (0.0, OWNER_FIRST_MAX_SECS), "people_hold_secs": PEOPLE_HOLD_RANGE}
SETTING_PROBLEM = ("People's approvals are anyone or off, starts are on or off, their sessions follow default or ask, "
                   f"the owner-first time is 0 to {OWNER_FIRST_MAX_SECS:.0f} seconds, and a prompt is held for people "
                   f"{PEOPLE_HOLD_RANGE[0]:.0f} to {PEOPLE_HOLD_RANGE[1]:.0f} seconds.")


def settings_of(raw) -> dict:
    """The machine's settings for people, from what people.json holds: anything it does not spell is the default."""
    out = dict(DEFAULTS)
    if isinstance(raw, dict):
        out.update({k: raw[k] for k, values in SETTINGS.items() if raw.get(k) in values})
        for key, (least, most) in SECONDS.items():
            if nodelink._num(raw.get(key)) and least <= raw[key] <= most:
                out[key] = float(raw[key])
    return out


def account() -> str:
    """The OS account this Pointe runs as: what a person's request runs as on this machine."""
    try:
        return getpass.getuser()
    except Exception:  # no account name (a container with a bare uid)
        return ""


def owner_name(state_dir: Path) -> str:
    """Who owns this machine, as people's voices and its agents hear it: config.json "owner", else the account
    Pointe runs as."""
    try:
        configured = json.loads((state_dir / "config.json").read_text()).get("owner")
    except (OSError, ValueError, AttributeError):
        configured = None
    if isinstance(configured, str) and configured.strip():
        return _cut(" ".join(configured.split()), 40)
    return account() or "the owner"


def qr(link: str) -> str:
    """The invite line as a QR code, drawn as the phone's invite is (phone_pairing._svg)."""
    from phone_pairing import _svg

    return _svg(link)


def name_problem(name: str, taken: list[str], owner: str) -> str | None:
    """Why a person may not be called this on this machine, or None. A person's name is said aloud ("Dana asked shop
    to run the tests") and stamped on what they send."""
    name = " ".join(str(name).split())
    if not name or not guards.valid_name(name):
        return f"{name or 'An empty name'} is not a usable name: use letters, digits, spaces, dots, dashes"
    if not speakable(name):
        return f"{name} cannot be told apart by voice: use the person's own name"
    if name.lower() == owner.lower():
        return f"{name} is this machine's owner"
    if any(name.lower() == t.lower() for t in taken):
        return f"A person called {name} is already on this machine"
    return None


def _vendors(value) -> list[str]:
    """The services a voice says it sends transcripts to: names only, cut, from a caller that proved nothing yet."""
    if not isinstance(value, list):
        return []
    return [_cut(" ".join(v.split()), 60) for v in value if isinstance(v, str) and v.strip()][:MAX_VENDORS]


def paired_line(paired: dict) -> str:
    """What the owner reads once a person's voice paired: who, from where, and the key both sides can compare."""
    where = f" ({paired['network']})" if paired.get("network") else ""
    return f"{paired['name']} paired from {paired['address'] or 'an unknown address'}{where}, key {paired['key_fp']}"


def vendors_line(name: str, vendors: list[str]) -> str:
    if not vendors:
        return f"{name}'s voice named no service it sends this machine's transcripts to."
    return f"{name}'s voice sends this machine's transcripts to: {', '.join(vendors)}."


class People:
    """$STATE/people.json, 0600: {people: {id: {id, name, key, grant, added, address, vendors}}, private: [session
    ids]}. It holds each person's key, and the sessions the owner keeps to themselves."""

    def __init__(self, path: Path):
        self.path = path
        self._load()
        self._read = self._on_disk()

    def _on_disk(self) -> tuple | None:
        try:
            st = self.path.stat()
        except OSError:
            return None
        return st.st_ino, st.st_mtime_ns, st.st_size

    def refresh(self) -> None:
        """people.json changed under the daemon (`pointe pair rotate` or `off` emptied it): only the people it lists
        now are on this machine. Before every lookup, so a signed-out person is refused at once and a later save
        cannot bring them back."""
        if self._on_disk() != self._read:
            self._load()
            self._read = self._on_disk()

    def _load(self) -> None:
        path = self.path
        self.people: dict[str, dict] = {}
        self.private: set[str] = set()
        self.settings: dict = {}  # only what the owner changed (settings_of fills in the rest)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except (ValueError, OSError) as e:
            return self._set_aside(e)
        listed = data.get("people")
        for person in (listed.values() if isinstance(listed, dict) else []):
            if self._usable(person):
                self.people[person["id"]] = person
        private = data.get("private")
        self.private = {s for s in private if isinstance(s, str)} if isinstance(private, list) else set()
        changed = settings_of(data.get("settings"))
        self.settings = {k: v for k, v in changed.items() if v != DEFAULTS[k]}

    @staticmethod
    def _usable(person) -> bool:
        if not isinstance(person, dict) or not all(isinstance(person.get(k), str) and person[k] for k in ("id", "name", "key")):
            return False
        if person.get("grant") not in GRANTS:
            person["grant"] = "watch"  # an unreadable grant is the lower one
        return True

    def _set_aside(self, error: Exception) -> None:
        """Move an unreadable people.json to people.json.broken-<time> for repair by hand. Nobody is on this machine
        until then: no key is guessed from a broken file."""
        aside = self.path.with_name(f"{self.path.name}.broken-{int(time.time())}")
        try:
            os.replace(self.path, aside)
        except OSError as e:
            aside = self.path
            logger.error(f"{self.path} could not be moved aside ({type(e).__name__})")
        logger.error(f"{self.path} is unreadable ({type(error).__name__}); kept as {aside}. No person can reach this "
                     f"machine until it is repaired and Pointe restarted, or each person is invited again")

    def save(self) -> None:
        _write_private(self.path, json.dumps({"people": self.people, "private": sorted(self.private),
                                              **({"settings": self.settings} if self.settings else {})}) + "\n")
        self._read = self._on_disk()

    def get(self, person_id) -> dict | None:
        self.refresh()
        return self.people.get(person_id) if isinstance(person_id, str) else None

    def by_name(self, name: str) -> dict | None:
        self.refresh()
        wanted = " ".join(str(name).split()).lower()
        return next((p for p in self.people.values() if p["name"].lower() == wanted), None)

    def names(self) -> list[str]:
        return [p["name"] for p in self.people.values()]

    def add(self, name: str, grant: str, address: str, vendors: list[str], now: float) -> dict:
        self.refresh()
        person_id = secrets.token_hex(8)
        while person_id in self.people:
            person_id = secrets.token_hex(8)
        person = {"id": person_id, "name": name, "key": nodelink.new_key(), "grant": grant, "added": now,
                  "address": address, "vendors": vendors}
        self.people[person_id] = person
        self.save()
        return person

    def remove(self, person_id: str) -> None:
        if self.people.pop(person_id, None):
            self.save()

    def set_private(self, session_id: str, private: bool, known: set[str]) -> None:
        """`known`: the ids of sessions that still exist. Others are dropped, so the list does not grow for ever."""
        self.private = {s for s in self.private if s in known}
        (self.private.add if private else self.private.discard)(session_id)
        self.save()


@dataclass
class Ask:
    """The request a session is working on, when a person sent it."""
    by: str
    by_id: str
    since: float


@dataclass
class Offer:
    """A session's permission prompt, while people may answer it. `spoken` and `readable` are computed here, from the
    unmasked request: what a person's voice must have read out for its yes to count (node.Held, for a node's hub)."""
    session_id: str
    request_id: str
    frame: dict  # the `permission.request`, masked: what every person offered it is sent
    readable: str | None
    spoken: str | None
    first: str  # the id of the person asked first: who started the session. "": the machine's owner
    first_name: str
    opens_at: float  # when the others may answer
    deadline: float  # when the harness takes it back
    summary: str  # for the journal: the tool and the start of its input, masked
    opened: bool = False
    sent: dict[str, dict] = field(default_factory=dict)  # link id: the frame that link was last sent
    by: dict | None = None  # the person whose verdict was taken: {id, name, how, verdict}
    gone_at: float | None = None  # monotonic: when it was first seen no longer pending
    alone_since: float | None = None  # since when nobody could answer it but the terminal
    away_since: float | None = None  # since when it is held with no call of the machine owner's: for people only
    done: bool = False


@dataclass
class Link:
    """One person's live link."""
    id: str  # the person's
    name: str
    ws: object
    address: str
    protocol: int
    features: list[str]
    heard: float  # monotonic: the last frame from the voice
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # one frame at a time
    syncing: asyncio.Lock = field(default_factory=asyncio.Lock)  # one comparison of the session list at a time
    tails: dict[str, Tail] = field(default_factory=dict)  # the sessions this voice was told of, and where each is
    call_up: bool = True  # this voice's call, as its welcome and its `call` frames say: with none, nobody hears a prompt
    approvals_terminal: bool = False  # this person answers prompts in terminals
    told: list[dict] = field(default_factory=list)  # the last `sessions` snapshot
    resume: dict[str, dict] = field(default_factory=dict)  # where the voice's mirror of each session ends
    tasks: set[asyncio.Task] = field(default_factory=set)


MAX_READS = 32  # reads kept for the other links of the same session: a few polls' worth


def _read_lines(path: str, offset: int, size: int) -> tuple[list[tuple[int, str | None]], int] | None:
    """A transcript's new lines from `offset`, masked, and the bytes before them that are a line too long to ship.
    Read and masked off the event loop, which also runs the owner's call, and once for every link at that offset
    (HostSide._lines). None when a line longer than one read is not written to its end yet."""
    read = shipping.read_new(path, offset, size)
    if read is None:
        return None
    data, skipped = read
    return masked_lines(data), skipped


class HostSide:
    """The machine's side of every person's link. The daemon lends what only it knows: `record(line)` writes one
    journal line, `on_sent(session, by, text, at)` tells the owner's own voice what a person sent, `working(session)`
    says a session is in a turn, and `owner_ask(session)` since when it works on the owner's own request (or None).

    For prompts and starts (phase 3): `answer(session, request_id, verdict, how, person, address)` delivers a
    person's verdict to the session and records it (True when the session took it); `release(session, request_id)`
    hands a prompt back to its terminal; `owner_hears(session)` says the owner's own voice can answer now;
    `open_owner(session, request_id)` puts a prompt of a person's session to the owner's voice once its window ended;
    `start(person, harness, folder, name, prompt, ask)` runs the owner's own start path and returns
    (True, {id, name}) or (False, {why, detail}); `start_options()` is what the owner's New session sheet lists."""

    def __init__(self, state_dir: Path, registry: Registry, host_id: Callable[[], str],
                 record: Callable[[str], None] | None = None, on_sent: Callable | None = None,
                 working: Callable[[Session], bool] | None = None,
                 owner_ask: Callable[[Session], float | None] | None = None,
                 clock: Callable[[], float] = time.time, monotonic: Callable[[], float] = time.monotonic,
                 answer: Callable | None = None, release: Callable | None = None,
                 owner_hears: Callable[[Session], bool] | None = None, open_owner: Callable | None = None,
                 start: Callable | None = None, start_options: Callable[[], dict] | None = None):
        self.state_dir, self.registry, self._host_id = state_dir, registry, host_id
        self._record, self._on_sent, self._owner_ask = record, on_sent, owner_ask
        self._answer, self._release, self._open_owner = answer, release, open_owner
        self._owner_hears = owner_hears or (lambda s: False)
        self._start, self._start_options = start, start_options
        self.offers: dict[str, Offer] = {}  # session id: its prompt, while people may answer it
        self.answered: dict[str, str] = {}  # request id: who answered it, for a verdict that comes late
        self.resolved: dict[str, dict] = {}  # session id: {name, verdict, at}, the last answer a person gave
        self.grace = nodelink.HOLD_GRACE_SECS
        self.offer_poll = OFFER_POLL_SECS
        self._starts = 0
        self._watching: asyncio.Task | None = None
        self._working = working or (lambda s: s.busy and not terminal_wait(s))
        self._clock, self._mono = clock, monotonic
        self.people = People(state_dir / "people.json")
        self.invites = Invites(monotonic)
        self.invite_grant = "send"
        self.links = nodelink.Links()
        self.live: dict[str, Link] = {}
        self.offline_since: dict[str, float] = {p: clock() for p in self.people.people}
        self.asks: dict[str, Ask] = {}
        self.notices: dict[str, str] = {}  # person id: one line about a link of theirs that cannot come up
        self.poll = POLL_SECS
        self._waiting: dict[str, int] = {}  # address: sockets there still before their hello
        self._tasks: set[asyncio.Task] = set()
        self._titles: dict[str, tuple[float, str | None]] = {}
        self._files: dict[str, tuple[str, list[str]]] = {}  # session id: (its transcript's path, tracked file names)
        self._reads: dict[tuple[str, int], tuple[int, asyncio.Future]] = {}  # (path, offset): (size then, its lines)
        self._saved_tails = self._load_tails()
        self._ticking = asyncio.Lock()  # one pass over the prompts at a time, and no frame about one out of order

    # ---------- small things ----------

    @property
    def host_id(self) -> str:
        return self._host_id()

    @property
    def owner(self) -> str:
        return owner_name(self.state_dir)

    @property
    def here(self) -> str:
        return _here(self.state_dir)

    def record(self, line: str) -> None:
        """One line in the machine's journal, with the person's name: every link, pairing, send, refusal, share
        change and removal. The daemon writes it (its journal takes lines logged there); alone, it goes to the log."""
        if self._record is None:
            return logger.info(f"people: {line}")
        try:
            self._record(line)
        except Exception as e:  # the record must never stop the link
            logger.warning(f"people: the journal line was not written ({type(e).__name__})")

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _load_tails(self) -> dict[str, dict]:
        try:
            saved = json.loads((self.state_dir / "people_tails.json").read_text())
        except (OSError, ValueError):
            return {}
        return {k: v for k, v in saved.items() if isinstance(v, dict)} if isinstance(saved, dict) else {}

    def _save_tails(self, link: Link | None = None) -> None:
        """Each person's {session: {path, gen}}: a voice that links again after this machine restarted resumes its
        mirror, and a transcript that moved meanwhile gets a new gen."""
        if link is not None:
            mine = self._saved_tails.setdefault(link.id, {})
            mine.update({sid: {"path": t.path, "gen": t.gen} for sid, t in link.tails.items()})
        try:
            _write_private(self.state_dir / "people_tails.json", json.dumps(self._saved_tails))
        except OSError as e:
            logger.warning(f"people: tails not saved ({type(e).__name__})")

    # ---------- what is shared ----------

    def _shared(self, session_id, person_id: str | None = None) -> Session | None:
        """The session, when this person may see it: one of this machine's own, not kept private. A private session
        is seen by the person who started it, and by nobody else. A session on one of this machine's nodes is never
        passed on."""
        session = self.registry.sessions.get(session_id) if isinstance(session_id, str) else None
        if session is None or session.machine:
            return None
        if session.id in self.people.private:
            starter = self.starter(session)
            if starter is None or starter["id"] != person_id:
                return None
        return session

    def _visible(self, link: Link | None = None) -> dict[str, Session]:
        person = link.id if link is not None else None
        return {s.id: s for s in list(self.registry.sessions.values()) if self._shared(s.id, person) is not None}

    def _sees(self, link: Link, session_id: str) -> bool:
        """This link may get a frame about this session now: it is live, its person is still on the machine, and the
        session is shared (or it is their own)."""
        return (link.ws is not None and self.live.get(link.id) is link and self.people.get(link.id) is not None
                and self._shared(session_id, link.id) is not None)

    def starter(self, session: Session) -> dict | None:
        """The person who started this session here (its owner), while they are still on this machine. None for a
        session of the machine's owner, and for one whose person was removed: it is the machine owner's then."""
        by = (session.harness_data or {}).get("started_by")
        return self.people.get(by.get("id")) if isinstance(by, dict) else None

    def started(self, session: Session, person: dict) -> None:
        """A session this person started here joined: it is theirs. The owner's name on it is theirs, everywhere."""
        session.harness_data["started_by"] = {"id": person["id"], "name": person["name"]}
        session.owner = person["name"]
        self.record(f"{person['name']} started {session.name} ({session.harness}) in {session.cwd}")

    @property
    def settings(self) -> dict:
        """{approve, start, sessions_ask, owner_first_secs}: the owner's, one set for everybody on the machine."""
        self.people.refresh()
        return settings_of(self.people.settings)

    def set_settings(self, changes: dict) -> dict | None:
        """The owner changes some settings: the settings now, or None when a value is not one a setting takes."""
        wanted = {k: v for k, v in changes.items() if k in DEFAULTS}
        merged = {**self.people.settings, **wanted}
        if not wanted or settings_of(merged) != {**DEFAULTS, **merged}:
            return None
        now = settings_of(merged)
        if now != self.settings:
            self.people.settings = {k: v for k, v in now.items() if v != DEFAULTS[k]}
            self.people.save()
            self.record("people's settings: " + ", ".join(f"{k} {now[k]}" for k in wanted))
        return now

    def _local_id(self, session_id: str) -> str:
        """This machine's own id for a session id from a voice, which may be its `<machine short>-<id>` form."""
        prefix = f"{self.host_id[:6]}-"
        if session_id not in self.registry.sessions and session_id.startswith(prefix):
            return session_id[len(prefix):]
        return session_id

    def _title(self, session: Session) -> str | None:
        at, title = self._titles.get(session.id, (None, None))
        if at is None or self._mono() - at >= TITLE_SECS:
            try:
                title = harnesses.of(session).title(session)
            except Exception:
                title = None
            self._titles[session.id] = (self._mono(), title)
        return title

    def _entry(self, session: Session, link: Link | None = None) -> dict:
        """A shared session in a `sessions` snapshot: what a node sends, less what stays on the machine (its pid, its
        account's folder), whose it is, and its prompt when this link's person is offered it (`pending`)."""
        adapter = harnesses.of(session)
        wait = wait_state(session)
        offer = self.offers.get(session.id)
        pending = offer.sent.get(link.id) if offer is not None and link is not None else None
        if session.permission_id and pending is None:  # not this person's to answer: their voice shows that it waits
            wait = {**wait, "blocked_on": "permission prompt", "blocked_since": session.permission_since}
        by = (session.harness_data or {}).get("started_by")
        starter = _cut(str(by.get("name") or ""), 40) if isinstance(by, dict) else ""
        approves = link is not None and self.may_approve(self.people.get(link.id)) and "approve" in link.features
        return {"id": session.id, "name": session.name, "name_given": session.named_by == "user", "cwd": session.cwd,
                "harness": session.harness, "title": self._title(session), "owner": starter or self.owner,
                **({"started_by": starter} if starter else {}),
                "capabilities": {**adapter.capabilities(), "side_questions": False, "approvals": approves},
                "files": self._files.get(session.id, ("", []))[1],
                "pending": {k: v for k, v in pending.items() if k != "t"} if pending else None, **wait}

    # ---------- frames out ----------

    async def _raw(self, link: Link, text: str) -> bool:
        ws = link.ws
        if ws is None:
            return False
        try:
            await ws.send_text(text)
            return True
        except Exception:  # the link went: its reader sees the disconnect
            return False

    async def _send(self, link: Link, text: str) -> bool:
        async with link.lock:
            return await self._raw(link, text)

    async def _about(self, link: Link, session_id: str, text: str) -> bool:
        """The one way a frame about a session leaves this machine. Whether the link may see the session is checked
        under the link's lock, right before the frame is written: a session that went private, or a person who was
        removed, gets nothing more from that moment, whatever was already read for them."""
        async with link.lock:
            if not self._sees(link, session_id):
                return False
            return await self._raw(link, text)

    async def _snapshot(self, link: Link) -> None:
        async with link.lock:
            entries = [e for e in link.told if self._sees(link, e["id"])]
            await self._raw(link, encode("sessions", sessions=entries))

    # ---------- pairing ----------

    def name_problem(self, name: str) -> str | None:
        return name_problem(name, self.people.names(), self.owner)

    def invite(self, name: str, grant: str, line: Callable[[str, str], str]) -> dict:
        """A one-time code for one person, replacing any other. `line(code, machine name)` builds the invite line
        (SystemExit with the fix when no address is paired)."""
        code = self.invites.make(name=name)
        try:
            self.invites.link = line(code, self.here)
        except SystemExit:
            self.invites.cancel()
            raise
        self.invite_grant = grant
        return {"code": code, "link": self.invites.link, "svg": qr(self.invites.link), "expires_in": INVITE_SECS,
                "name": name, "grant": grant}

    def invite_status(self) -> dict | None:
        status = self.invites.status()
        if not status:
            return None
        return {**status, "svg": qr(status.get("link") or ""), "name": self.invites.name, "grant": self.invite_grant}

    def pair(self, body, address: str) -> tuple[int, dict | str]:
        """POST /voice/host/pair: (status, the person's key and this machine's identity, or why not). The same
        refusals and attempt limits as a machine's pairing (hub_nodes.Hub.pair)."""
        invites = self.invites
        if not invites.outstanding:
            return 403, NO_SUCH_INVITE
        body = body if isinstance(body, dict) else {}
        refused = invites.check(body.get("code", ""), address)
        if refused:
            if invites.worth_logging(refused, address):
                logger.warning(f"a person's pairing from {address}: {refused[1]}")
            return refused if refused[0] == 429 else (403, NO_SUCH_INVITE)
        name = " ".join(str(invites.name or "").split())
        problem = self.name_problem(name)
        if problem:
            return 409, problem
        invites.cancel()
        vendors = _vendors(body.get("vendors"))
        person = self.people.add(name, self.invite_grant, address, vendors, self._clock())
        self.offline_since[person["id"]] = self._clock()
        invites.paired = {"name": name, "address": address, "network": network(address), "grant": person["grant"],
                          "key_fp": nodelink.fingerprint(person["key"]), "vendors": vendors}
        self.record(f"{paired_line(invites.paired)}, may {person['grant']}")
        return 200, {"person": {"id": person["id"], "name": name, "grant": person["grant"]}, "key": person["key"],
                     "host": {"id": self.host_id, "name": self.here, "os": _os()}, "owner": self.owner}

    # ---------- the owner's changes ----------

    async def grant(self, name: str, grant: str) -> bool:
        person = self.people.by_name(name)
        if person is None:
            return False
        if person["grant"] != grant:
            person["grant"] = grant
            self.people.save()
            self.record(f"{person['name']} may now {'send to the sessions' if grant == 'send' else 'watch only'}")
            link = self.live.get(person["id"])
            if link is not None:
                await self._send(link, encode("you", grant=grant))
        return True

    async def remove(self, name: str) -> bool:
        """The person's key goes first, so nothing more is sent to them; then `unpaired`, and their link closes with
        4401."""
        person = self.people.by_name(name)
        if person is None:
            return False
        self.people.remove(person["id"])
        self.offline_since.pop(person["id"], None)
        if self._saved_tails.pop(person["id"], None) is not None:
            self._save_tails()
        self.record(f"{person['name']} removed: their key is deleted")
        link = self.live.get(person["id"])
        if link is not None:
            await self._send(link, encode("unpaired"))
            ws, link.ws = link.ws, None
            await _close(ws, nodelink.CLOSE_UNAUTHORIZED, "removed")
        return True

    async def drop_removed(self) -> None:
        """People whose keys left people.json under the daemon (`pointe pair rotate` or `off`): their links close
        now, as a removal closes one."""
        self.people.refresh()
        for link in [x for x in self.live.values() if x.id not in self.people.people]:
            self.record(f"{link.name} signed out with this machine's certificate: their key is deleted")
            await self._send(link, encode("unpaired"))
            ws, link.ws = link.ws, None
            await _close(ws, nodelink.CLOSE_UNAUTHORIZED, "removed")

    def find(self, wanted: str) -> Session | None:
        """A session by its id, or by its name as the owner says it."""
        wanted = " ".join(str(wanted).split())
        sessions_ = list(self.registry.sessions.values())
        return self.registry.sessions.get(wanted) or next((s for s in sessions_ if s.name.lower() == wanted.lower()), None)

    async def share(self, session: Session, private: bool, by: str = "") -> None:
        """Keep a session to the owner, or share it again. Private takes effect before this returns: the flag is set
        first, and every link that saw the session is told it left. `by`: the person who started the session, when
        they change it for their own; it stays theirs to see."""
        was = session.id in self.people.private
        self.people.set_private(session.id, private, set(self.registry.sessions) | set(self.registry.departed))
        if was != private:
            self.record(f"{session.name} is now {'private' if private else 'shared with the people on this machine'}"
                        + (f", by {by}" if by else ""))
        await self.sync()

    async def sync(self) -> None:
        """Every link's session list, compared with what is shared now."""
        for link in list(self.live.values()):
            await self._sync(link)

    # ---------- the link ----------

    async def serve(self, ws) -> None:
        """The /voice/host WebSocket: a nonce, the voice's HMAC over it with its person's key, then frames until the
        link drops."""
        address = _peer(ws)
        if sum(self._waiting.values()) >= hub_nodes.MAX_WAITING \
                or self._waiting.get(address, 0) >= hub_nodes.MAX_WAITING_PER_ADDRESS:
            return await _close(ws, 1013, "too many connections waiting")
        self._waiting[address] = self._waiting.get(address, 0) + 1
        try:
            proven = await self._hello(ws)
        finally:
            self._waiting[address] -= 1
            if not self._waiting[address]:
                del self._waiting[address]
        if proven is not None:
            await self._linked(ws, address, *proven)

    async def _hello(self, ws) -> tuple[dict, dict, int] | None:
        """The challenge and the voice's answer: (the person, their hello, the protocol), or None once closed."""
        await ws.accept()
        nonce = nodelink.new_nonce()
        await ws.send_text(encode(
            "host.challenge", nonce=nonce, now=self._clock(), protocol=nodelink.PROTOCOL,
            protocol_min=HOST_MIN_PROTOCOL, features=list(nodelink.FEATURES),
            host={"id": self.host_id, "name": self.here, "os": _os(), "arch": platform.machine(),
                  "version": skew.version(), "harnesses": harnesses.names()}))
        try:
            hello = decode(await asyncio.wait_for(ws.receive_text(), hub_nodes.HELLO_WAIT_SECS), HUB_FRAMES)
        except Exception:  # silence, or it went
            return await _close(ws, nodelink.CLOSE_BAD_HELLO, "no hello")
        if hello is None or hello["t"] != "voice.hello":
            return await _close(ws, nodelink.CLOSE_BAD_HELLO, "hello first")
        chosen = nodelink.common(hello["protocol"], hello["protocol_min"], mine_min=HOST_MIN_PROTOCOL)
        if chosen is None:
            # No protocol both speak. The voice is the old side when its newest is under this link's first one.
            older = hello["protocol"] < HOST_MIN_PROTOCOL
            self._skewed(hello, nonce, older)
            return await _close(ws, nodelink.CLOSE_TOO_OLD, nodelink.too_old(
                "voice", HOST_MIN_PROTOCOL, hello["protocol"]) if older else nodelink.too_old(
                "host", min(hello["protocol_min"], hello["protocol"]), nodelink.PROTOCOL))
        person = self.people.get(hello["person"])
        if person is None or not nodelink.check(person["key"], nonce, self.host_id, hello["auth"]):
            logger.warning(f"a voice's link from {_peer(ws) or 'loopback'} refused: no such person, or a wrong key")
            return await _close(ws, nodelink.CLOSE_UNAUTHORIZED, "not on this machine")
        return person, hello, chosen

    def _skewed(self, hello: dict, nonce: str, older: bool) -> None:
        """A person whose voice shares no protocol with this machine stays listed, not linked, with one line that
        says which side to update. Only for a hello that proves it is theirs: a stranger marks nobody."""
        person = self.people.get(hello["person"])
        if person is None or not nodelink.check(person["key"], nonce, self.host_id, hello["auth"]):
            return
        name, version = person["name"], _cut(hello["voice"]["version"], 20)
        line = (f"{name}'s voice runs an older Pointe ({version}). {name} updates it with pointe update." if older else
                f"{name}'s voice runs a newer Pointe ({version}) than this machine. Update this machine with pointe update.")
        if self.notices.get(person["id"]) != line:
            self.notices[person["id"]] = line
            self.record(f"link refused: {line}")

    async def _linked(self, ws, address: str, person: dict, hello: dict, protocol: int) -> None:
        """A proven voice: one link per person, the welcome both ways, then frames until it drops."""
        if not self.links.claim(person["id"], ws) and not await self._replace_stale(person, ws):
            logger.warning(f"people: a second link with {person['name']}'s key refused")
            return await _close(ws, nodelink.CLOSE_ALREADY_CONNECTED, "already connected")
        link = Link(id=person["id"], name=person["name"], ws=ws, address=address, protocol=protocol,
                    features=nodelink.shared(hello.get("features")), heard=self._mono())
        try:
            await self._raw(link, encode("host.welcome", protocol=protocol, features=link.features, owner=self.owner,
                                         you={"id": person["id"], "name": person["name"], "grant": person["grant"]}))
            try:
                welcome = decode(await asyncio.wait_for(ws.receive_text(), hub_nodes.HELLO_WAIT_SECS), HUB_FRAMES)
            except Exception:
                welcome = None
            if welcome is None or welcome["t"] != "welcome":
                return await _close(ws, nodelink.CLOSE_BAD_HELLO, "welcome first")
            if self.people.get(person["id"]) is None:  # removed while the welcome crossed
                return await _close(ws, nodelink.CLOSE_UNAUTHORIZED, "removed")
            self._note_voice(person, address, _vendors(welcome["vendors"]) or _vendors(hello["vendors"]))
            link.resume, link.heard = dict(welcome["resume"]), self._mono()
            link.call_up, link.approvals_terminal = welcome["call_up"], welcome["approvals_terminal"]
            self.live[person["id"]] = link
            self.offline_since.pop(person["id"], None)
            self.notices.pop(person["id"], None)  # their voice was updated, or this machine was
            where = f" ({network(address)})" if network(address) else ""
            self.record(f"{person['name']}'s voice linked from {address or 'an unknown address'}{where}")
            await self._sync(link, first=True)
            link.tasks = {asyncio.create_task(self._read(link, ws)), asyncio.create_task(self._pump(link)),
                          asyncio.create_task(self._watchdog(link, ws))}
            try:
                await asyncio.wait(link.tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in link.tasks:
                    task.cancel()
        finally:
            self.links.release(person["id"], ws)
            if self.live.get(person["id"]) is link:
                del self.live[person["id"]]
                link.ws = None
                self._lost_offers(person["id"])
                if self.people.get(person["id"]) is not None:
                    self.offline_since[person["id"]] = self._clock()
                    self.record(f"{person['name']}'s voice is no longer linked")

    def _note_voice(self, person: dict, address: str, vendors: list[str]) -> None:
        """Where a person's voice links from and which services it uses, for the owner's People list."""
        if person.get("address") != address or person.get("vendors") != vendors:
            person["address"], person["vendors"] = address, vendors
            self.people.save()

    async def _replace_stale(self, person: dict, ws) -> bool:
        """A new connection proved it holds the key of a person whose link is still open. A live voice pings every
        PING_SECS, so a link heard from within STALE_SECS is alive and the new one is refused: a copied key cannot
        shadow it. A silent one (the voice crashed, slept or lost its network) gives way."""
        old = self.live.get(person["id"])
        if old is None or old.ws is None or self._mono() - old.heard < STALE_SECS:
            return False
        logger.warning(f"people: a new link with {person['name']}'s key, and the old one is silent: the old one is closed")
        stale, old.ws = old.ws, None
        for task in old.tasks:
            task.cancel()
        self.links.release(person["id"], stale)
        self.live.pop(person["id"], None)
        self._lost_offers(person["id"])
        self._spawn(_close(stale, nodelink.CLOSE_DEAD, "replaced by a new connection"))
        return self.links.claim(person["id"], ws)

    async def _watchdog(self, link: Link, ws) -> None:
        """The voice pings every PING_SECS: silence for DEAD_AFTER_SECS is a dead link."""
        while True:
            await asyncio.sleep(1)
            if self._mono() - link.heard > nodelink.DEAD_AFTER_SECS:
                logger.warning(f"people: {link.name}'s voice stopped answering: closing its link")
                return await _close(ws, nodelink.CLOSE_DEAD, "no pings")

    async def _read(self, link: Link, ws) -> None:
        while True:
            try:
                text = await ws.receive_text()
            except Exception:  # WebSocketDisconnect, or a receive after close
                return
            link.heard = self._mono()
            frame = decode(text, HUB_FRAMES)
            if frame is None:
                continue
            if frame["t"] == "bye":
                # The person took this machine off their voice, and their voice deleted its key. They stay listed,
                # not linked: taking them off this machine is its owner's to do.
                self.record(f"{link.name} took this machine off their voice")
                return await _close(ws, 1000, "bye")
            try:
                await self._on_frame(link, frame)
            except Exception:
                logger.exception(f"people: handling a {frame['t']!r} frame from {link.name}'s voice failed")

    async def _on_frame(self, link: Link, frame: dict) -> None:
        t = frame["t"]
        if t == "ping":
            await self._send(link, encode("pong", id=frame["id"]))
        elif t == "send":
            self._spawn(self._deliver(link, frame))
        elif t == "resume":
            await self._apply_resume(link, frame["resume"])
        elif t == "call":  # with no call, or approvals in terminals there, this person hears no prompt
            link.call_up, link.approvals_terminal = frame["up"], frame["approvals_terminal"]
            await self.tick()
        elif t == "permission.answer":
            await self._on_answer(link, frame)
        elif t == "start":
            self._spawn(self._on_start(link, frame))
        elif t == "folders":
            await self._on_folders(link, frame)
        elif t == "share":
            await self._on_share(link, frame)
        # A person is offered no session to add and no file to show: each is answered, with nothing.
        elif t == "discover":
            await self._send(link, encode("discovered", req=frame["req"], found=[]))
        elif t == "attach":
            await self._send(link, encode("attach.result", req=frame["req"], ok=False, why=NOT_OFFERED))
        elif t == "artifact.render":
            await self._send(link, encode("artifact.result", req=frame["req"]))

    # ---------- a person's send ----------

    def _names(self) -> list[str]:
        return [self.owner, *self.people.names()]

    def _current_ask(self, session: Session) -> Ask | None:
        """The person's request the session still works on: until its turn ends, with SETTLE_SECS for the turn to
        show."""
        ask = self.asks.get(session.id)
        if ask is None:
            return None
        if self._clock() - ask.since < SETTLE_SECS or self._working(session):
            return ask
        del self.asks[session.id]
        return None

    def busy(self, session: Session, person_id: str) -> dict | None:
        """{by, since} when the session works on somebody else's request: another person's, or the owner's (a turn
        nobody here asked for is the owner's, typed in its terminal). None when it is free, or works on this
        person's own."""
        ask = self._current_ask(session)
        if ask is not None:
            return None if ask.by_id == person_id else {"by": ask.by, "since": ask.since}
        if not self._working(session):
            return None
        since = self._owner_ask(session) if self._owner_ask is not None else None
        return {"by": self.owner, "since": since or session.last_delegation_at or self._clock()}

    def by(self, session: Session) -> dict | None:
        """Status `sessions[].by`: whose request the session works on, while it is a person's."""
        ask = self._current_ask(session)
        return {"name": ask.by, "since": ask.since} if ask is not None else None

    def refusal(self, person: dict | None, session: Session | None, frame: dict) -> tuple[str, dict | None] | None:
        """Why this machine does not deliver a person's send, in the contract's order, or None when it does. Decided
        from the link's person and this machine's own state: nothing the voice says about itself is read."""
        if person is None or session is None:
            return "private", None
        if person["grant"] != "send":
            return "watch", None
        if session.permission_id or session.blocked_on in PROMPTS:
            return "prompt", None
        if guards.claims_consent(frame["text"], self._names(), session.typed_approval):
            return "consent", None
        if frame.get("anyway") is not True and (busy := self.busy(session, person["id"])):
            return "busy", busy
        return None

    async def _deliver(self, link: Link, frame: dict) -> None:
        person = self.people.get(link.id)
        session = self._shared(self._local_id(frame["id"]), link.id)
        name = person["name"] if person else link.name
        refused = self.refusal(person, session, frame)
        if refused:
            why, busy = refused
            self.record(f"{name}'s request to {session.name if session else 'a session that is not shared'} "
                        f"refused: {why}")
            await self._send(link, encode("send.result", req=frame["req"], ok=False, why=why,
                                          **({"busy": busy} if busy else {})))
            return
        text, ok, held, began = frame["text"], False, {}, time.time()
        if text.strip():
            sender = sessions.SENDER.set(name)  # the tag the agent reads names this person (sessions.voice_message)
            try:
                ok = bool(await asyncio.wait_for(harnesses.of(session).send(session, text), nodelink.SEND_TIMEOUT_SECS))
            except asyncio.TimeoutError:
                logger.info(f"people: {name}'s send to {session.name} timed out")
            except Exception as e:
                logger.warning(f"people: {name}'s send to {session.name} failed ({type(e).__name__})")
            finally:
                sessions.SENDER.reset(sender)
            if not ok and (session.held_at or 0) >= began:
                held = {"held": "held"}
            elif not ok and (session.refused_at or 0) >= began:
                held = {"held": "refused"}
        if ok:
            at = self._clock()
            session.busy = True
            self.asks[session.id] = Ask(by=name, by_id=link.id, since=at)
            said = precise_mask(_cut(text, MAX_SENT_CHARS))  # as its transcript crosses: no credential in a frame or the journal
            self.record(f"{name} asked {session.name}: {_cut(said, 200)!r}")
            for other in [x for x in self.live.values() if x is not link]:
                await self._about(other, session.id, encode("sent", id=session.id, by=name, text=said, at=at))
            if self._on_sent is not None:
                try:
                    self._on_sent(session, name, text, at)
                except Exception as e:
                    logger.warning(f"people: the owner's voice was not told of {name}'s send ({type(e).__name__})")
        else:
            self.record(f"{name}'s request to {session.name} was not delivered")
        await self._send(link, encode("send.result", req=frame["req"], ok=ok, **held))

    # ---------- a session's permission prompt, put to people (phase 3) ----------

    def may_approve(self, person: dict | None) -> bool:
        """This person may answer a prompt: the send grant, and the owner has not turned people's approvals off."""
        return person is not None and person["grant"] == "send" and self.settings["approve"] != "off"

    def _eligible(self, link: Link, session_id: str) -> bool:
        """This link can be offered this session's prompt now: its person may approve, their voice speaks this part
        of the link, a call is up there (somebody hears and sees it), and they see the session."""
        return (self.may_approve(self.people.get(link.id)) and "approve" in link.features and link.call_up
                and not link.approvals_terminal and self._sees(link, session_id))

    def can_hold(self, session: Session) -> bool:
        """Somebody's voice can answer a prompt of this session now. The daemon asks before it holds a prompt with
        no call of the owner's own."""
        return not session.machine and any(self._eligible(link, session.id) for link in list(self.live.values()))

    def holds(self, session: Session) -> bool:
        """A prompt of this session is with people who can still answer it: the owner's call ending leaves it held."""
        offer = self.offers.get(session.id)
        return offer is not None and not offer.done and self.can_hold(session)

    def _lost_offers(self, person_id: str) -> None:
        """A person's link dropped: they lost every offer. A new link of theirs is sent each one again."""
        for offer in self.offers.values():
            offer.sent.pop(person_id, None)

    def _first_hears(self, offer: Offer, session: Session) -> bool:
        if not offer.first:
            return self._owner_hears(session)
        link = self.live.get(offer.first)
        return link is not None and self._eligible(link, session.id)

    async def offer(self, session: Session, request_id: str, tool_name: str, tool_input, description: str = "",
                    preview: str = "", run_in: str | None = None, deadline: float | None = None) -> bool:
        """A session of this machine asks for permission, and the daemon holds the prompt. Its owner is asked first
        (the person who started it, else the machine's owner); every other person who may approve and sees the
        session is sent it at the same moment, marked `first`, and may answer once the owner-first time is over or
        the owner cannot hear it. The read-out a spoken yes must match is computed here, from the unmasked request.
        True when the machine owner's own voice must wait too: the session is a person's, and they are asked first."""
        old = self.offers.get(session.id)
        if old is not None:
            await self._finish(old, "terminal")
        if session.machine or not self.people.people or self.settings["approve"] == "off":
            return False
        readable = spoken = None
        if isinstance(tool_input, dict):
            readable = guards.readable_request(tool_name, tool_input, session.cwd, run_in)
            spoken = readable or guards.verbatim_request(tool_name, tool_input)
        now = self._clock()
        shown = precise_mask(preview or json.dumps(tool_input if isinstance(tool_input, dict) else {}, ensure_ascii=False))
        frame = {"t": "permission.request", "id": session.id, "request_id": request_id, "tool": tool_name,
                 "description": precise_mask(str(description or "use this tool")), "preview": shown, "readable": spoken}
        starter = self.starter(session)
        link = self.live.get(starter["id"]) if starter else None
        first = starter if link is not None and self._eligible(link, session.id) else None
        secs = self.settings["owner_first_secs"]
        waits = secs > 0 and (first is not None or self._owner_hears(session))
        offer = Offer(session_id=session.id, request_id=request_id, frame=frame, readable=readable, spoken=spoken,
                      first=first["id"] if first else "", first_name=first["name"] if first else self.owner,
                      opens_at=now + (secs if waits else 0.0), opened=not waits,
                      deadline=deadline if deadline is not None else now + harnesses.of(session).permission_deadline,
                      summary=_cut(f"{tool_name}: {' '.join(shown.split())}", 300),
                      away_since=None if self._owner_hears(session) else now)
        self.offers[session.id] = offer
        self._spawn(self.tick())  # the frames go out apart: a slow link never delays the owner's own read-out
        self._watch()
        return first is not None and not offer.opened

    def _frame_for(self, offer: Offer, link: Link) -> dict:
        now = self._clock()
        frame = {**offer.frame, "deadline_ms": max(0, int((offer.deadline - now) * 1000))}
        if not (offer.opened or offer.first == link.id):
            frame["first"] = {"name": _cut(offer.first_name, nodelink.HELLO_CHARS)}
            frame["yours_in_ms"] = max(0, int((offer.opens_at - now) * 1000))
        return frame

    async def _reconcile(self, offer: Offer) -> None:
        """Each link is sent what holds for it now: the request when it became eligible (it linked, its call came
        up, its grant rose), the request again without `first` when it opened, and `permission.resolved` with
        `left` when it may no longer answer. A link that dropped has lost the offer."""
        for link in list(self.live.values()):
            if offer.done:
                return
            async with link.syncing:  # never between a snapshot's reading of `pending` and its sending
                sent = offer.sent.get(link.id)
                if self._eligible(link, offer.session_id):
                    if sent is None or ("first" in sent and (offer.opened or offer.first == link.id)):
                        frame = offer.sent[link.id] = self._frame_for(offer, link)
                        await self._about(link, offer.session_id, encode(
                            frame["t"], **{k: v for k, v in frame.items() if k != "t"}))
                elif sent is not None:
                    del offer.sent[link.id]
                    await self._send(link, encode("permission.resolved", id=offer.session_id,
                                                  request_id=offer.request_id, how="left"))
        for gone in [k for k in offer.sent if k not in self.live]:
            del offer.sent[gone]

    def _watch(self) -> None:
        if self.offer_poll and (self._watching is None or self._watching.done()):
            self._watching = self._spawn(self._watch_offers())

    async def _watch_offers(self) -> None:
        while self.offers:
            await asyncio.sleep(self.offer_poll)
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("people: a pass over the prompts people may answer failed")

    async def tick(self) -> None:
        """One pass over the prompts people may answer: open the ones whose owner-first time is over, follow who can
        be offered each, end the ones answered elsewhere, and hand back the ones nobody can answer."""
        async with self._ticking:
            for offer in list(self.offers.values()):
                await self._tick_one(offer)

    async def _tick_one(self, offer: Offer) -> None:
        if offer.done or offer.by is not None:  # a person's verdict is on its way to the session: its handler ends this
            return
        now = self._clock()
        session = self.registry.sessions.get(offer.session_id)
        if session is None:
            return await self._finish_locked(offer, "left")
        if session.permission_id != offer.request_id:
            # Answered by the machine's owner (owner_answered says so within a moment), in the terminal, or timed out.
            if offer.gone_at is None:
                offer.gone_at = self._mono()
            if self._mono() - offer.gone_at >= GONE_SECS:
                await self._finish_locked(offer, "timeout" if now >= offer.deadline else "terminal")
            return
        offer.gone_at = None
        if not offer.opened and (now >= offer.opens_at or not self._first_hears(offer, session)):
            offer.opened = True
            if offer.first and self._open_owner is not None:  # a person's session: the machine owner's voice reads it now
                self._spawn(_maybe(self._open_owner(session, offer.request_id)))
        await self._reconcile(offer)
        # Held for people only, with no call of the machine owner's: bounded, so an owner at the terminal sees it.
        offer.away_since = None if self._owner_hears(session) else now if offer.away_since is None else offer.away_since
        if self._held_too_long(offer):
            self.record(f"{session.name}'s request went back to its terminal: no person answered it in "
                        f"{self.settings['people_hold_secs']:g} seconds, and {self.owner} has no call")
            return await self._hand_back(offer, session)
        if self._owner_hears(session) or any(self._eligible(link, session.id) for link in list(self.live.values())):
            offer.alone_since = None
            return
        if offer.alone_since is None:
            offer.alone_since = now
        if now - offer.alone_since >= self.grace:
            self.record(f"{session.name}'s request went back to its terminal: nobody who may answer it is linked")
            await self._hand_back(offer, session)

    def _held_too_long(self, offer: Offer) -> bool:
        return offer.away_since is not None and self._clock() - offer.away_since >= self.settings["people_hold_secs"]

    async def _hand_back(self, offer: Offer, session: Session) -> None:
        """The prompt goes to its terminal, and every voice that was offered it is told."""
        if self._release is not None:
            self._release(session, offer.request_id)
        elif session.permission_answer is not None and not session.permission_answer.done():
            session.permission_answer.set_result(None)
        await self._finish_locked(offer, "terminal")

    async def _finish(self, offer: Offer, how: str, by: str = "", verdict: str | None = None, skip: str = "") -> None:
        async with self._ticking:
            await self._finish_locked(offer, how, by, verdict, skip)

    async def _finish_locked(self, offer: Offer, how: str, by: str = "", verdict: str | None = None,
                             skip: str = "") -> None:
        """The prompt is no longer anybody's to answer: every voice that was offered it is told, with who answered."""
        if offer.done:
            return
        offer.done = True
        if self.offers.get(offer.session_id) is offer:
            del self.offers[offer.session_id]
        if by:
            self.answered[f"{offer.session_id}/{offer.request_id}"] = by
            for old in list(self.answered)[:-ANSWERED_KEPT]:
                del self.answered[old]
        fields = {"by": _cut(by, nodelink.HELLO_CHARS), "verdict": verdict} if by and verdict else {}
        told, offer.sent = [k for k in offer.sent if k != skip], {}
        for link_id in told:
            link = self.live.get(link_id)
            if link is not None:
                await self._send(link, encode("permission.resolved", id=offer.session_id,
                                              request_id=offer.request_id, how=how, **fields))

    def owner_answered(self, session: Session, request_id: str, verdict: str) -> None:
        """The machine owner's own voice, tap or notification answered it: everybody it was offered to hears who.
        Marked at once, so no person's verdict is taken after it; the frames go out apart."""
        offer = self.offers.get(session.id)
        if offer is not None and offer.request_id == request_id and offer.by is None:
            offer.by = {"id": "", "name": self.owner, "how": "owner", "verdict": verdict}
            self._spawn(self._finish(offer, "answered", by=self.owner, verdict=verdict))

    async def _on_answer(self, link: Link, frame: dict) -> None:
        """A person's verdict. This machine re-checks it as a node re-checks its hub's (node.recheck, one table),
        after the checks only a machine with people has: who the link's person is, what they may do, whether they
        see the session, and whether it is their turn. The first verdict that passes is the only one taken."""
        request_id, how, verdict = frame["request_id"], frame["how"], frame["verdict"]
        sid = self._local_id(frame["id"])

        async def refuse(why: str, **more) -> None:
            logger.warning(f"people: refused {link.name}'s {how} {verdict} for {request_id}: {why}")
            self.record(f"{link.name}'s {'yes' if verdict == 'allow' else 'no'} by {how} was refused: {why}")
            await self._send(link, encode("permission.answered", request_id=request_id, ok=False, why=why, **more))

        person = self.people.get(link.id)
        if person is None or self.settings["approve"] == "off":
            return await refuse("not_offered")
        if person["grant"] != "send":
            return await refuse("watch")
        session = self._shared(sid, link.id)
        if session is None:
            return await refuse("private")
        offer = self.offers.get(sid)
        if offer is None or offer.request_id != request_id:
            by = self.answered.get(f"{sid}/{request_id}")
            return await refuse("answered", by=by) if by else await refuse("stale")
        if offer.by is not None:
            return await refuse("answered", by=offer.by["name"])
        if offer.done or session.permission_id != request_id or self._clock() >= offer.deadline \
                or (not self._owner_hears(session) and self._held_too_long(offer)):
            return await refuse("stale")
        if not self._eligible(link, sid):
            return await refuse("not_offered")
        if not (offer.opened or offer.first == link.id):
            return await refuse("not_yet")
        why = recheck(_config(self.state_dir), offer, frame)
        if why is not None:
            return await refuse(why)
        offer.by = {"id": person["id"], "name": person["name"], "how": how, "verdict": verdict}  # no second one is taken
        try:
            if self._answer is not None:
                took = bool(await self._answer(session, request_id, verdict, how, person, link.address))
            else:  # with no daemon behind it: the hook's own wait
                took = session.permission_answer is not None and not session.permission_answer.done()
                if took:
                    session.permission_answer.set_result(verdict)
                    session.permission_id = None
        except Exception as e:
            logger.warning(f"people: {link.name}'s verdict did not reach {session.name} ({type(e).__name__})")
            took = False
        if not took:
            offer.by = None
            return await refuse("stale")
        self.record(f"{person['name']} {'approved' if verdict == 'allow' else 'denied'} {session.name}'s request by "
                    f"{how}, from {link.address or 'an unknown address'}: {offer.summary}")
        self.resolved[sid] = {"name": person["name"], "verdict": verdict, "at": self._clock()}
        await self._send(link, encode("permission.answered", request_id=request_id, ok=True))
        await self._finish(offer, "answered", by=person["name"], verdict=verdict, skip=link.id)

    # ---------- a person starts a session here (phase 3) ----------

    def _start_refusal(self, person: dict | None) -> str | None:
        if person is None or person["grant"] != "send":
            return "watch"
        if self.settings["start"] == "off" or self._start is None:
            return "off"
        return None

    async def _on_start(self, link: Link, frame: dict) -> None:
        """`start`: the grant and the setting are checked here; the folder, the agent and how it starts are the
        owner's own start path's to check (the daemon's), with nothing taken from the voice but its words."""
        person = self.people.get(link.id)
        name = person["name"] if person else link.name
        why = self._start_refusal(person) or ("busy" if self._starts >= MAX_STARTS else None)
        if why:
            self.record(f"{name}'s start of a session refused: {why}")
            await self._send(link, encode("start.result", req=frame["req"], ok=False, why=why))
            return
        self._starts += 1
        try:
            ok, got = await asyncio.wait_for(self._start(
                person, frame["harness"], frame["folder"], frame.get("name") or None, frame.get("prompt") or "",
                self.settings["sessions_ask"] == "ask"), START_WAIT_SECS)
        except asyncio.TimeoutError:
            ok, got = False, {"why": "failed", "detail": "The session did not join in time."}
        except Exception as e:
            logger.warning(f"people: {name}'s start failed ({type(e).__name__}: {e})")
            ok, got = False, {"why": "failed", "detail": "The session did not start."}
        finally:
            self._starts -= 1
        if ok:
            await self._send(link, encode("start.result", req=frame["req"], ok=True, id=str(got["id"]),
                                          name=_cut(str(got.get("name") or ""), nodelink.HELLO_CHARS)))
            if (frame.get("prompt") or "").strip():
                # The first prompt is this person's request: delivered under the rules of any send of theirs, with
                # their name on it for the agent, the owner and the other voices.
                await self._deliver(link, {"req": nodelink.new_id(), "id": str(got["id"]), "text": frame["prompt"]})
            return
        why = _cut(str(got.get("why") or "failed"), 40)
        self.record(f"{name}'s start of a session was not done: {why}")
        await self._send(link, encode("start.result", req=frame["req"], ok=False, why=why,
                                      **({"detail": _cut(str(got["detail"]), 300)} if got.get("detail") else {})))

    async def _on_folders(self, link: Link, frame: dict) -> None:
        """`folders`: where a session may start here, exactly as the owner's own New session sheet lists it."""
        why = self._start_refusal(self.people.get(link.id))
        options = self._start_options() if why is None and self._start_options is not None else {}
        folders = [{"path": str(f["path"]), "name": str(f["name"])} for f in options.get("folders") or []][:200]
        more = {}
        if why is None:
            asks = self.settings["sessions_ask"] == "ask"
            more = {"harnesses": list(options.get("harnesses") or [])[:nodelink.MAX_FILES],
                    "permissions": "ask" if asks or options.get("permissions") != "skip" else "skip",
                    "account": _cut(account(), nodelink.HELLO_CHARS)}
        await self._send(link, encode("folders.result", req=frame["req"], folders=folders, **more,
                                      **({"why": why} if why else {})))

    async def _on_share(self, link: Link, frame: dict) -> None:
        """`share`: a person keeps a session they started private, or shares it again. Never somebody else's."""
        session = self._shared(self._local_id(frame["id"]), link.id)
        starter = self.starter(session) if session is not None else None
        why = "private" if session is None else "not_yours" if starter is None or starter["id"] != link.id else None
        if why is None:
            await self.share(session, frame["private"], by=link.name)
        else:
            self.record(f"{link.name}'s change of who sees a session refused: {why}")
        await self._send(link, encode("share.result", req=frame["req"], ok=why is None, **({"why": why} if why else {})))

    # ---------- sessions and transcripts, once per link ----------

    @staticmethod
    def _path(session: Session) -> str:
        return harnesses.of(session).transcript_path(session)

    async def _sync(self, link: Link, first: bool = False) -> None:
        """Tell the link what changed in the sessions it may see: `session.left` for one that exited or went private,
        `session.joined` for a new one, and the list itself when anything in it moved."""
        async with link.syncing:
            if self.live.get(link.id) is not link:
                return
            visible = self._visible(link)
            gone = [sid for sid in link.tails if sid not in visible]
            for sid in gone:
                tail = link.tails.pop(sid)
                exited = sid not in self.registry.sessions
                if exited:
                    self._saved_tails.get(link.id, {}).pop(sid, None)
                    link.resume.pop(sid, None)
                elif tail.offset is not None:  # private for now: shared again, it goes on from here
                    link.resume[sid] = {"gen": tail.gen, "offset": tail.offset}
                await self._send(link, encode("session.left", id=sid, why="exited" if exited else "disconnected"))
            new = [sid for sid in visible if sid not in link.tails]
            for sid in new:
                saved = self._saved_tails.get(link.id, {}).get(sid) or {}
                path = self._path(visible[sid])
                gen = int(saved.get("gen") or 0) + (1 if saved.get("path") and saved["path"] != path else 0)
                link.tails[sid] = Tail(path=path, gen=gen)
                if not first:
                    await self._about(link, sid, encode("session.joined", id=sid, joining=visible[sid].joining))
            if gone or new:
                self._save_tails(link)
            entries = [self._entry(s, link) for s in visible.values()]
            if first or gone or new or entries != link.told:
                link.told = entries
                await self._snapshot(link)
            if first:
                await self._apply_resume(link, link.resume, everyone=True)
            for sid in new:
                if not first:
                    await self._apply_resume(link, {sid: link.resume[sid]} if sid in link.resume else {}, only=sid)
                self._spawn(self._send_files(link, visible[sid]))

    async def _apply_resume(self, link: Link, resume: dict, everyone: bool = False, only: str | None = None) -> None:
        """Reseek to where this voice's mirror ends, as a node does for its hub (node.Node._apply_resume). A session
        the voice has no offset for starts at 0 in its current gen, and that is history, not news."""
        wanted = {self._local_id(k): v for k, v in resume.items()}
        link.resume.update(wanted)
        for sid, tail in list(link.tails.items()):
            if only is not None and sid != only:
                continue
            at = wanted.get(sid)
            if at is None:
                if everyone or only is not None:
                    tail.offset = 0
                    await self._about(link, sid, encode("transcript.repointed", id=sid, gen=tail.gen, history=True))
                continue
            if not shipping.resume_to(tail, at, _size(tail.path)):
                continue
            self._save_tails(link)
            await self._about(link, sid, encode("transcript.repointed", id=sid, gen=tail.gen, history=True))

    async def _pump(self, link: Link) -> None:
        while True:
            await asyncio.sleep(self.poll)
            try:
                await self._sync(link)
                for sid in list(link.tails):
                    session = self._shared(sid, link.id)
                    if session is not None:
                        await self._ship(link, session)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # one bad read must not stop a person's record for good
                logger.warning(f"people: shipping to {link.name}'s voice failed ({type(e).__name__}: {e})")

    async def _ship(self, link: Link, session: Session) -> None:
        """The session's new transcript lines to one link (node.Node._ship, with this link's own offset and gen)."""
        tail = link.tails.get(session.id)
        if tail is None:
            return
        path = self._path(session)
        if path != tail.path:
            tail.path, tail.gen, tail.offset = path, tail.gen + 1, 0
            self._save_tails(link)
            await self._about(link, session.id, encode("transcript.repointed", id=session.id, gen=tail.gen,
                                                       history=_size(path) > 0))
            self._spawn(self._send_files(link, session))
        if tail.offset is None:
            return
        size = _size(path)
        if size < tail.offset:  # rewritten in place: a new gen, from the start
            tail.gen, tail.offset = tail.gen + 1, 0
            self._save_tails(link)
            await self._about(link, session.id, encode("transcript.repointed", id=session.id, gen=tail.gen))
        if size <= tail.offset:
            return
        gen, start = tail.gen, tail.offset
        try:
            read = await self._lines(path, start, size)
        except OSError:
            return
        if read is None:
            return
        lines, skipped = read
        if skipped:
            logger.warning(f"{session.name}: a transcript line of {skipped} bytes not shipped")
        frames, nxt = frames_of(session.id, gen, start, lines, skipped)
        for frame in frames:
            if not await self._about(link, session.id, frame):
                return  # the link dropped, or the session is no longer this person's to see
        if tail.gen == gen and tail.offset == start:  # no resume moved it meanwhile
            tail.offset = nxt

    async def _lines(self, path: str, offset: int, size: int):
        """_read_lines, once for every link that is at this offset of this file: the links of several people on one
        session poll the same new bytes, and they are read and masked one time. A link at another offset (it resumes
        a backlog) gets its own read. The frames, with each link's own gen, are made per link."""
        key = (path, offset)
        kept = self._reads.get(key)
        if kept is None or kept[0] != size:
            for old in list(self._reads)[:max(0, len(self._reads) - MAX_READS + 1)]:
                del self._reads[old]
            kept = self._reads[key] = (size, asyncio.ensure_future(asyncio.to_thread(_read_lines, path, offset, size)))
        return await asyncio.shield(kept[1])  # one link going away does not take the read from the others

    async def _send_files(self, link: Link, session: Session) -> None:
        """Up to 40 tracked file names, for the voice's routing hints: at join and after each repoint. Listed once
        per transcript, whatever the number of links."""
        path = self._path(session)
        known = self._files.get(session.id)
        if known is None or known[0] != path:
            proc = None
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git", "-C", session.cwd, "ls-files", stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, env=childenv.child_env())
                out, _ = await asyncio.wait_for(proc.communicate(), 5)
            except (OSError, asyncio.TimeoutError):
                return
            finally:
                if proc is not None and proc.returncode is None:
                    proc.kill()
                    await proc.wait()
            known = self._files[session.id] = (path, out.decode(errors="replace").splitlines()[:nodelink.MAX_FILES])
        tail = link.tails.get(session.id)
        if tail is not None and known[1] != tail.files:
            tail.files = known[1]
            await self._about(link, session.id, encode("files", id=session.id, names=known[1]))

    # ---------- what the owner's screens read ----------

    def listed(self) -> list[dict]:
        """GET /voice/people. `since` is as a machine's: when the person's link dropped (or this Pointe started), and
        None while they are linked."""
        out = []
        for p in self.people.people.values():
            online = p["id"] in self.live
            out.append({"id": p["id"], "name": p["name"], "grant": p["grant"], "online": online,
                        "since": None if online else self.offline_since.get(p["id"]),
                        "address": p.get("address") or "", "key_fp": nodelink.fingerprint(p["key"]),
                        "vendors": list(p.get("vendors") or []), "added": p.get("added"),
                        **({"notice": self.notices[p["id"]]} if p["id"] in self.notices else {})})
        return out

    def status(self, show_invite: bool) -> dict:
        """What /voice/status adds on a machine with people: nothing at all with none, so a Pointe nobody was
        invited to answers as it always did."""
        out: dict = {}
        if self.people.people:
            out["people"] = [{k: p[k] for k in ("name", "grant", "online", "since", "vendors", "notice") if k in p}
                             for p in self.listed()]
            out["account"] = account()  # the account a person's requests run as, for the owner's screens
            out["people_settings"] = self.settings
        invite = self.invite_status() if show_invite else None
        if invite is not None:
            out["people_invite"] = invite
        return out

    def session_status(self, session: Session) -> dict:
        """What a session's entry in /voice/status adds: `private` on one kept private, `by` while it works on a
        person's request. Nothing else."""
        out: dict = {}
        if session.id in self.people.private:
            out["private"] = True
        by = self.by(session) if self.asks else None
        if by is not None:
            out["by"] = by
        started = (session.harness_data or {}).get("started_by")
        if isinstance(started, dict) and started.get("name"):
            out["started_by"] = started["name"]
        offer = self.offers.get(session.id)
        if offer is not None and session.permission_id == offer.request_id:
            if not offer.opened:  # who is asked first, and until when: the others see it, and wait
                out["asked"] = {"name": offer.first_name, "until": offer.opens_at}
            out["can_answer"] = True  # the machine's owner, at their own machine, always may
        resolved = self.resolved.get(session.id)
        if resolved is not None and self._clock() - resolved["at"] < RESOLVED_SHOWN_SECS:
            out["resolved_by"] = resolved
        return out


def invite_line(code: str, name: str) -> str:
    """The line a person's voice takes: the listener the phone uses, its certificate's fingerprint, a one-time code
    and this machine's name. SystemExit with the fix when no address is paired (pair._config)."""
    from pair import TLS_PORT, _config, fingerprint

    return nodelink.machine_invite(_config()["host"], TLS_PORT, fingerprint(), code, name)


def install(app, host: HostSide, link: Callable[[str, str], str] | None = None, remote_share: Callable | None = None) -> None:
    """The routes of docs/design/people-and-machines.md, "HTTP, on the machine that invites". In daemon.py, next to
    hub_nodes.install. `link(code, machine name)` builds the invite line."""
    from fastapi import Request, WebSocket
    from fastapi.responses import JSONResponse, PlainTextResponse

    from remote import Remote

    link = link or invite_line

    @app.websocket(nodelink.HOST_PATH)
    async def host_socket(websocket: WebSocket):
        await host.serve(websocket)

    @app.post(nodelink.HOST_PAIR_PATH)
    async def host_pair(request: Request):
        if not host.invites.outstanding:  # answered before a byte of the body is read
            return PlainTextResponse(NO_SUCH_INVITE, status_code=403)
        body = await pairing_body(request)
        if body is None:
            return PlainTextResponse("too large", status_code=413)
        status, answer = host.pair(body, request.client.host if request.client else "")
        return JSONResponse(answer) if status == 200 else PlainTextResponse(answer, status_code=status)

    def owner(request: Request) -> bool:
        """The page on this machine, a script with its token, or the owner's phone. Never a browser over the TLS
        listener, and never a person's key (hub_nodes.install's rule)."""
        return not Remote.on_tls_listener(request.scope) or bool(request.scope.get("state", {}).get("pointe_phone"))

    refused = PlainTextResponse("forbidden", status_code=403)

    async def body_of(request: Request) -> dict:
        try:
            body = await request.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    def no_person(name: str):
        return PlainTextResponse(f"Nobody called {name or '(no name)'} is on this machine.", status_code=404)

    @app.post("/voice/people/invite")
    async def people_invite(request: Request):
        """{"name": "Dana", "grant": "watch"} makes a code (replacing any other); {"cancel": true} ends it."""
        if not owner(request):
            return refused
        body = await body_of(request)
        if body.get("cancel"):
            host.invites.cancel()
            return {"ok": True}
        name = " ".join(str(body.get("name") or "").split())
        grant = body.get("grant", "send")
        if grant not in GRANTS:
            return PlainTextResponse("A person may send or watch: say which.", status_code=409)
        problem = host.name_problem(name)
        if problem:
            return PlainTextResponse(f"{problem}.", status_code=409)
        try:
            return host.invite(name, grant, link)
        except SystemExit as e:
            from pair import NOT_SET_UP
            return PlainTextResponse(str(e), status_code=409,
                                     headers={"x-pointe-fix": "phone"} if str(e) == NOT_SET_UP else None)

    @app.get("/voice/people/invite")
    async def people_invite_status(request: Request):
        if not owner(request):
            return refused
        return {**(host.invite_status() or {"code": None, "expires_in": 0, "name": None}),
                "paired": host.invites.paired, "ended": host.invites.ended}

    @app.get("/voice/people")
    async def people_list(request: Request):
        return {"people": host.listed()} if owner(request) else refused

    @app.post("/voice/people/grant")
    async def people_grant(request: Request):
        if not owner(request):
            return refused
        body = await body_of(request)
        name = str(body.get("name") or "")
        if body.get("grant") not in GRANTS:
            return PlainTextResponse("A person may send or watch: say which.", status_code=409)
        return {"ok": True} if await host.grant(name, body["grant"]) else no_person(name)

    @app.get("/voice/people/settings")
    async def people_settings(request: Request):
        return host.settings if owner(request) else refused

    @app.post("/voice/people/settings")
    async def people_settings_set(request: Request):
        """Any of {"approve": "anyone"|"off", "start": "on"|"off", "sessions_ask": "default"|"ask",
        "owner_first_secs": 0..120, "people_hold_secs": 10..280}: the settings now."""
        if not owner(request):
            return refused
        now = host.set_settings(await body_of(request))
        if now is None:
            return PlainTextResponse(SETTING_PROBLEM, status_code=409)
        await host.tick()  # approvals turned off: a prompt people hold leaves their voices now
        return now

    @app.post("/voice/people/remove")
    async def people_remove(request: Request):
        if not owner(request):
            return refused
        name = str((await body_of(request)).get("name") or "")
        return {"ok": True} if await host.remove(name) else no_person(name)

    @app.post("/voice/share")
    async def share(request: Request):
        if not owner(request):
            return refused
        body = await body_of(request)
        wanted = str(body.get("session") or "")
        session = host.find(wanted)
        if session is None:
            return PlainTextResponse(f"No session called {wanted or '(no name)'} is on the voice.", status_code=404)
        if not isinstance(body.get("private"), bool):
            return PlainTextResponse("Say whether the session is private: true or false.", status_code=409)
        if session.machine and remote_share is not None and not session.owner \
                and getattr(sessions.MACHINES.get(session.machine), "dialed", False):
            # A session this person started on a machine they were invited to: that machine decides, and changes it.
            ok, why = await remote_share(session, body["private"])
            if ok:
                return {"ok": True, "private": body["private"]}
            return PlainTextResponse(
                f"{session.name} is not a session you started on {session.machine}: only its owner changes who sees it."
                if why == "not_yours" else f"{session.machine} did not change it: it is offline or did not answer.",
                status_code=403 if why == "not_yours" else 502)
        if session.machine:
            return PlainTextResponse(f"{session.name} runs on {session.machine}: only this machine's own sessions "
                                     f"are shared with people.", status_code=404)
        await host.share(session, body["private"])
        return {"ok": True, "private": body["private"]}


# ---------- the command line: pointe people, pointe share ----------

def _people(argv: list[str]) -> None:
    from hub_nodes import _daemon

    command = argv[0] if argv else "list"
    if command == "list":
        people = _daemon("GET", "/voice/people")["people"]
        if not people:
            return print("Nobody is invited to this machine. Invite a person with: pointe people invite <name>")
        for p in people:
            state = "linked" if p["online"] else "not linked" + (
                f" since {time.strftime('%H:%M %b %d', time.localtime(p['since']))}" if p.get("since") else "")
            uses = f"  uses {', '.join(p['vendors'])}" if p["vendors"] else ""
            print(f"{p['name']}  may {p['grant']}  {state}  key {p['key_fp']}{uses}")
    elif command == "invite" and len(argv) > 1:
        name = " ".join(a for a in argv[1:] if not a.startswith("--"))
        made = _daemon("POST", "/voice/people/invite", {"name": name, "grant": "watch" if "--watch" in argv else "send"})
        print(made["link"])
        print(f"Valid once, for ten minutes. {name} adds this machine with it: pointe machine add '<the line above>'",
              flush=True)
        wrong = 0
        try:
            while True:
                time.sleep(1)
                now = _daemon("GET", "/voice/people/invite")
                if now.get("paired"):
                    print(paired_line(now["paired"]))
                    return print(vendors_line(now["paired"]["name"], now["paired"].get("vendors") or []))
                if not now.get("code"):
                    why = f"{now['ended'][0].upper()}{now['ended'][1:]}" if now.get("ended") else \
                        "The invite expired or was cancelled"
                    raise SystemExit(f"{why}: run pointe people invite again.")
                if now.get("wrong_codes", 0) > wrong:
                    wrong = now["wrong_codes"]
                    print(f"{wrong} wrong code{'s' if wrong > 1 else ''} tried against this invite (it ends at "
                          f"{PAIR_WRONG_PER_INVITE})", flush=True)
        except KeyboardInterrupt:
            print("\nThe invite stays valid until it expires.")
    elif command == "remove" and len(argv) > 1:
        name = " ".join(argv[1:])
        _daemon("POST", "/voice/people/remove", {"name": name})
        print(f"{name} is no longer on this machine: their key is deleted and their link is closed.")
    elif command == "grant" and len(argv) > 2 and argv[-1] in GRANTS:
        name = " ".join(argv[1:-1])
        _daemon("POST", "/voice/people/grant", {"name": name, "grant": argv[-1]})
        print(f"{name} may now send to this machine's sessions." if argv[-1] == "send" else f"{name} may now watch only.")
    elif command in _SETTING_WORDS and len(argv) == 2 and argv[1] in _SETTING_WORDS[command][1]:
        key, values, said = _SETTING_WORDS[command]
        _daemon("POST", "/voice/people/settings", {key: values[argv[1]]})
        print(said[argv[1]])
    elif command == "window" and len(argv) == 2 and argv[1].replace(".", "", 1).isdigit():
        now = _daemon("POST", "/voice/people/settings", {"owner_first_secs": float(argv[1])})
        print(f"A prompt waits {now['owner_first_secs']:g} seconds for its session's owner. Then the other people who "
              f"may send can answer it.")
    elif command == "hold" and len(argv) == 2 and argv[1].replace(".", "", 1).isdigit():
        now = _daemon("POST", "/voice/people/settings", {"people_hold_secs": float(argv[1])})
        print(f"With no call of yours, a prompt waits {now['people_hold_secs']:g} seconds for the people who may answer "
              f"it. Then it goes to its terminal.")
    else:
        print(__doc__.split("\n\n", 1)[1].rstrip())


# pointe people <word> <value>: the setting, the value each word means, and what is printed.
_SETTING_WORDS = {
    "approvals": ("approve", {"on": "anyone", "off": "off"}, {
        "on": "People who may send can answer a session's permission prompt. Its owner is asked first, and every "
              "answer is recorded with the person's name.",
        "off": "People no longer answer permission prompts on this machine. You answer them, by voice or in the terminal."}),
    "starts": ("start", {"on": "on", "off": "off"}, {
        "on": "People who may send can start a session on this machine, in the folders you work in.",
        "off": "People no longer start sessions on this machine."}),
    "sessions": ("sessions_ask", {"default": "default", "ask": "ask"}, {
        "default": "Sessions people start follow your setting for new sessions.",
        "ask": "Sessions people start always ask before actions."}),
}


def _share(argv: list[str]) -> None:
    from hub_nodes import _daemon

    name = " ".join(a for a in argv if not a.startswith("--"))
    if not name or ("--private" in argv and "--shared" in argv):
        return print(__doc__.split("\n\n", 1)[1].rstrip())
    private = "--shared" not in argv
    _daemon("POST", "/voice/share", {"session": name, "private": private})
    print(f"{name} is private: nothing about it reaches anybody's voice but yours." if private else
          f"{name} is shared with the people on this machine.")


def main(argv: list[str]) -> None:
    if argv[:1] == ["people"]:
        _people(argv[1:])
    elif argv[:1] == ["share"]:
        _share(argv[1:])
    else:
        print(__doc__.split("\n\n", 1)[1].rstrip())


if __name__ == "__main__":
    main(sys.argv[1:])
