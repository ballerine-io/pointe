"""The Claude Code sessions the voice can talk to.

The registry outlives browser connections: sessions register once (from `/voice` or the
launcher's SessionStart hook) and stay until their process exits. Each connection turns
the registry into Pipecat bus workers, one per session (daemon.ClaudeSessionWorker). No Pipecat here: a node imports this.
"""

import asyncio
import json
import math
import os
import re
import secrets
import subprocess
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

from artifacts import Turn
from brief import FINAL_MARK, agent_finding, excerpt, human_text
from echo import NUMBERS
from progress import step_of
from guards import _NO, _WEAK_YES, _YES, strip_tasks

Feed = Callable[["Session", str, bool], Awaitable[None]]

VOICE_PREFIX = "[Voice request from the user, relayed by their voice assistant"
# A person the owner invited to this machine, while the machine delivers their send (guests.py): the tag names them,
# so the agent never takes their words for the owner's. "" is the owner, whose tag is VOICE_PREFIX, unchanged.
SENDER: ContextVar[str] = ContextVar("pointe_sender", default="")
_PERSON_RELAY = re.compile(r"\[Voice request from [^\[\]\n]{1,60}, a person invited to this machine, relayed by ")


def person_prefix(name: str) -> str:
    return f"[Voice request from {name}, a person invited to this machine, relayed by {name}'s voice assistant"


def from_a_voice(text: str) -> bool:
    """The line is a relay from a voice, the owner's or a person's: not something typed in the session's terminal."""
    return VOICE_PREFIX in text or bool(_PERSON_RELAY.search(text))


LIVENESS_SECS = 5


@dataclass
class Session:
    id: str
    name: str
    cwd: str
    pid: int = 0  # 0: a harness whose sessions are not a local process (a service, a remote thread)
    transcript: str = ""
    home: str = ""  # Claude Code: the config dir (CLAUDE_CONFIG_DIR) it runs under, for a second account; "" is ~/.claude
    harness_data: dict = field(default_factory=dict)  # what one harness keeps per session; persisted
    inbox_socket: str | None = None
    inbox_token: str | None = None
    channel_url: str | None = None  # launch mode: its voice channel, with permission relay
    # Per-session state, so two sessions never share a permission prompt or a request gate.
    permission_id: str | None = None
    permission_text: str | None = None
    permission_delivered_at: float = float("inf")
    permission_read_at: float = 0.0
    joining: bool = False  # registered in the middle of the turn that ran /pointe:voice
    permission_cut: bool = False
    permission_spoken: str = ""  # the exact words a yes approves; empty: only the terminal can approve
    permission_answer: object = None  # a future, while Claude Code's PermissionRequest hook waits on the voice
    permission_full: str = ""  # what a tap approves: the tool, then its input, never the model's description
    permission_note: str = ""  # the session model's description: one line, capped, shown apart as its note
    permission_truncated: bool = False  # the preview came cut short: a tap may deny it, never approve it
    permission_since: float | None = None  # when it arrived: a background session can wait on it for long
    permission_until: float = 0.0  # when the voice lets go of it: far off for a session on a night shift (nightshift.PARK_SECS)
    tone: int | None = None  # its sound before a report (tones.py): given at its first report, then kept
    last_delegation_at: float = 0.0
    busy: bool = False
    # The prompt it waits at in its own terminal, in its harness's word ("permission prompt"), read from the harness
    # (Claude Code: `claude agents --json`). The voice does not hold that prompt and cannot answer it. "" when none.
    blocked_on: str = ""
    blocked_since: float | None = None
    active_at: float = 0.0  # when its record last moved: a prompt read before that is stale
    followed: bool = False  # follow_transcript runs for it (on the hub while a call is up) and keeps busy and active_at
    followed_to: tuple[str, int, float] | None = None  # (transcript, offset, when): where the last follower stopped
    # Claude Code set the voice's last message aside instead of giving it to Claude (post_inbox reads its receipt):
    # held for approval in its terminal, or refused by its settings. None when not, or no longer.
    held_at: float | None = None
    refused_at: float | None = None
    stop_asked_at: float | None = None  # the user said stop and the harness ends the turn at its next step: not yet ended
    # Idle tracking for orchestrator nudges: set at turn end, cleared when it works again.
    idle_since: float | None = None
    needs: dict | None = None  # {"need": what it waits for, "unblock": what the user could say}
    nudged_at: float = 0.0
    dismissed_wait: float | None = None  # the wait the user waved off; a new wait is nudged again
    named_by: str = "folder"  # "folder", "title" (Claude Code's session title) or "user"; a user's name is never replaced
    brief: dict | None = None  # the voice's notes on this session (brief.py); kept in STATE_DIR/briefs
    brief_size: int = 0  # how much of the transcript those notes have read
    open_questions: list[str] = field(default_factory=list)  # what its last report left to the user
    deadlines: list[str] = field(default_factory=list)
    urgency: str = "normal"
    typed_approval: str = ""
    on_hold: bool = False  # the user said to hold this session: a broadcast skips it, and only its name reaches it
    noise: int = 0  # harness messages kept out of the feed: "how much was junk" has an answer
    harness: str = "claude-code"  # which coding agent runs it: harnesses/ (claude-code, opencode)
    machine: str = ""  # the node it runs on; "" is this machine. Its adapter is harnesses.of(session), never get()
    # Whose session it is, when not this person's: a name, on a machine somebody invited this voice to
    # (docs/design/people-and-machines.md). "" is mine. Somebody else's never wins a name against mine (name_groups).
    owner: str = ""
    turn_mine: bool = False  # this voice sent it a request and no report has come since: that report is said, not held
    # The machine refused this voice's last send: {"why", "busy": {by, since}, "at"} (hub_nodes.Hub.send). None when not.
    turned_down: dict | None = None
    turn: Turn = field(default_factory=Turn)  # what the turn in progress touched (show while it says)
    artifacts: list = field(default_factory=list)  # what the last finished turn touched, for its report
    step: tuple[float, str] | None = None  # (when, what): its newest tool use, in progress.step_of's fixed words

    def alive(self) -> bool:
        import harnesses

        return harnesses.of(self).alive(self)


PERSISTED = ("id", "name", "named_by", "cwd", "pid", "transcript", "inbox_socket", "inbox_token", "channel_url",
             "permission_id", "permission_text", "permission_since", "permission_cut", "permission_full", "permission_spoken",
             "permission_note", "permission_truncated",
             "harness", "home", "harness_data", "machine", "tone", "owner")  # Claude Code still waits after a restart
MAX_DEPARTED = 20


@dataclass
class Machine:
    """A paired machine whose sessions this hub voices (a node). The node link (hub_nodes.py) keeps these current in
    MACHINES, keyed by name; routing, the brain's context and the status read them."""
    name: str
    id: str = ""
    os: str = ""
    online: bool = False
    since: float | None = None  # offline since, epoch seconds; None while online
    rtt_ms: int | None = None
    key_fp: str = ""
    skew: float = 0.0  # the hub's clock minus the node's, measured at its hello: node stamps are shifted by it
    link: int = 0  # links accepted since this hub started: a prompt a node re-offers on a new link is asked again
    notice: str = ""  # one line for the owner about its link (a takeover from another address), shown with the machine
    # A machine somebody invited this voice to, which this voice dials (machines.py): its owner's name, what this
    # person may do there ("send" or "watch"), and this person's name there. All empty on a machine of one's own.
    dialed: bool = False
    owner: str = ""
    grant: str = ""
    me: str = ""


MACHINES: dict[str, Machine] = {}


def online(session: "Session") -> bool:
    """A session on this machine always is; one on a node, while its node's link is up. Offline sessions stay listed
    (until RemoteHarness.alive gives up on them) but cannot be sent to or approved."""
    if not session.machine:
        return True
    m = MACHINES.get(session.machine)
    return bool(m and m.online)


def machine(name: str) -> Machine | None:
    return MACHINES.get(name)


def owner_of(machine_name: str, said) -> str:
    """Whose session this is, from the `owner` its machine's snapshot gave it: "" when it is this person's. Only a
    machine this voice dialed has other people's sessions: a node of one's own cannot make a session somebody else's.
    There, a session with no owner named is the machine owner's, and one named as this person is theirs."""
    m = MACHINES.get(machine_name)
    if m is None or not m.dialed:
        return ""
    said = " ".join(re.sub(r"[^\w ./-]+", " ", said if isinstance(said, str) else "").split())[:40].strip(" ./-")
    if said and m.me and said.lower() == m.me.lower():
        return ""
    return said or m.owner or m.name


def machines() -> list[Machine]:
    return list(MACHINES.values())


def this_machine() -> str:
    """This Mac's name among the machines; the daemon sets it (daemon._here). "" on a node."""
    return ""


def _machine_names(sessions) -> set[str]:
    return {n.lower() for n in MACHINES} | {s.machine.lower() for s in sessions if s.machine}


@dataclass
class Registry:
    sessions: dict[str, Session] = field(default_factory=dict)
    active_id: str | None = None
    path: Path | None = None  # registrations survive a daemon restart
    recent: list[str] = field(default_factory=list)  # previously active, most recent last
    mode: str = "orchestrator"  # or "session": every request goes to the active session only
    departed: dict[str, Session] = field(default_factory=dict)  # exited, so a request naming one is not rerouted

    def set_active(self, session_id: str) -> None:
        if self.active_id and self.active_id != session_id:
            self.recent = [i for i in self.recent if i != self.active_id] + [self.active_id]
        if self.active_id != session_id:
            self._close_yes_windows()
        self.active_id = session_id
        self.save()

    def _close_yes_windows(self) -> None:
        """The active session changed: a yes now may answer something said about another session, so no read-out's
        window stays open. Each pending request is read out again before a yes can approve it."""
        for s in self.sessions.values():
            if s.permission_id:
                s.permission_delivered_at = float("inf")

    def save(self) -> None:
        if self.path is None:
            return
        data = {"active": self.active_id, "mode": self.mode, "recent": self.recent,
                "sessions": [{k: getattr(s, k) for k in PERSISTED} for s in self.sessions.values()]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.chmod(0o600)  # holds inbox tokens
        tmp.replace(self.path)

    def load(self, path: Path) -> None:
        """A damaged file or entry is skipped, never fatal: the sessions re-register on their own."""
        self.path = path
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
        except (ValueError, OSError) as e:
            logger.error(f"{path} unreadable ({type(e).__name__}); starting with no sessions")
            data = {}
        if not isinstance(data, dict):
            data = {}
        for raw in data.get("sessions", []):
            if isinstance(raw, dict) and "named_by" not in raw and raw.get("name") and raw.get("cwd"):
                folder = Path(str(raw["cwd"])).name  # saved before names were tracked: anything else was chosen
                raw["named_by"] = "folder" if raw["name"] == folder or raw["name"].startswith(folder + "/") else "user"
            try:
                session = Session(**{k: v for k, v in raw.items() if k in PERSISTED})
                if session.harness == "claude-code" and not session.machine and not (session.pid and session.transcript):
                    raise TypeError("a Claude Code session needs its process and transcript")
            except (TypeError, AttributeError):
                logger.error(f"skipping a bad session entry in {path}")
                continue
            if session.machine:  # its pid is the node's: kept, offline until the node reconnects (or its grace ends)
                MACHINES.setdefault(session.machine, Machine(name=session.machine, since=time.time()))
                self.sessions[session.id] = session
            elif session.alive():
                self.sessions[session.id] = session
        self.active_id = data.get("active") if data.get("active") in self.sessions else next(iter(self.sessions), None)
        self.recent = [i for i in data.get("recent", []) if i in self.sessions and i != self.active_id]
        self.mode = data.get("mode", "orchestrator")
        self.save()

    @property
    def active(self) -> Session | None:
        return self.sessions.get(self.active_id) if self.active_id else None

    def add(self, session: Session) -> None:
        taken = {s.name.lower() for s in self.sessions.values() if s.id != session.id}
        base, n = session.name, 2
        while session.name.lower() in taken:  # the bus skips duplicate worker names silently
            session.name, n = f"{base}-{n}", n + 1
        self.sessions[session.id] = session
        self.departed.pop(session.id, None)
        for sid in [i for i, s in self.departed.items() if s.name.lower() == session.name.lower()]:
            del self.departed[sid]
        if self.active is None:
            self.active_id = session.id
        self.save()

    def rename_check(self, session_id: str, new_name: str, machine: str = "") -> str | None:
        """Why new_name cannot be used for this session, or None if it can. `machine` is the session's when it is
        not registered yet."""
        why = self._why_not(session_id, new_name, machine)
        return why[0] if why else None

    def rename(self, session_id: str, new_name: str) -> str | None:
        """Rename a session; returns an error message, or None on success."""
        new_name = " ".join(new_name.split())
        why = self._why_not(session_id, new_name)
        if why:
            return why[1]
        self.sessions[session_id].name = new_name
        self.save()
        return None

    def _why_not(self, session_id: str, new_name: str, machine: str = "") -> tuple[str, str] | None:
        """(short, spoken) reasons new_name cannot be used, or None."""
        new_name = " ".join(new_name.split())
        others = [o for o in self.sessions.values() if o.id != session_id]
        if any(o.name.lower() == new_name.lower() for o in others):
            why = f"another session is already called {new_name}"
            return why, why
        if new_name.lower() in _machine_names(self.sessions.values()):
            return (f"{new_name} is the name of a machine",
                    f"{new_name} is the name of a machine, so voice could not tell the session from the machine")
        if not speakable(new_name):
            return (f"{new_name} cannot be picked by voice",
                    f"{new_name} cannot be picked by voice: words like dev, main or session never select a "
                    f"session on their own. Use a name with a distinctive word")
        if answers_a_prompt(new_name):
            return (f"{new_name} has a yes or no word in it",
                    f"{new_name} has a yes or no word in it, so a yes or no to an approval could be taken as aimed "
                    f"at the session")
        mine = {w for w in _name_words(new_name) if _distinctive(w)}
        inside = next((o for o in others if mine <= set(_name_words(o.name))), None)
        if inside:
            return (f"{new_name} is part of {inside.name}",
                    f"{new_name} is part of {inside.name}, so voice could not tell them apart")
        own = self.sessions[session_id].machine if session_id in self.sessions else machine
        clash = self.cross_machine_problem(session_id, new_name, own)
        return (clash, f"{clash}, so voice could not tell them apart") if clash else None

    def cross_machine_problem(self, session_id: str, name: str, machine: str) -> str | None:
        """Why a session on `machine` ("" is this Mac) may not be called `name` beside sessions on other machines, or
        None. A name another machine's session already uses a word of ("shop deploy" beside "shop"), or one letter off
        ("shops"), would take requests meant for it or tie every one, so a node's title could capture this Mac's
        sessions. The machine suffix that tells two equal names apart ("shop devbox" beside "shop",
        daemon._tell_apart) is allowed. A remote session never takes a word of this Mac's own name: "go to studio"
        must mean this Mac."""
        name = " ".join(name.split())
        words = [w for w in _name_words(name) if _distinctive(w)]
        if machine and set(words) & set(_name_words(this_machine())):
            return f"{name} has this Mac's name in it"
        across = [o for o in self.sessions.values() if o.id != session_id and (o.machine or "") != (machine or "")]
        if machine and name.lower().endswith(" " + machine.lower()):
            base = name[:-len(machine) - 1].lower()
            if any(base == o.name.lower() or base.startswith(o.name.lower() + "/")
                   or o.name.lower().startswith(base + "/") for o in across):
                return None
        for o in across:
            if o.machine and o.name.lower() == f"{name} {o.machine}".lower():
                continue  # its twin there, already told apart by that machine's name
            theirs = [w for w in _name_words(o.name) if _distinctive(w)]
            if any(_alike(a, b) for a in words for b in theirs):
                return f"{name} is too close to {o.name}, on {o.machine or 'this Mac'}"
        return None

    def remove(self, session_id: str) -> Session | None:
        session = self.sessions.pop(session_id, None)
        if session:
            self.departed[session_id] = session
            for sid in list(self.departed)[:-MAX_DEPARTED]:
                del self.departed[sid]
        self.recent = [i for i in self.recent if i in self.sessions]
        if self.active_id == session_id:  # back to the one used last, not the first registered
            self.active_id = self.recent.pop() if self.recent else next(iter(self.sessions), None)
            self._close_yes_windows()
        self.save()
        return session


REGISTRY = Registry()


# ---------- matching spoken session names (code decides, never the model) ----------

def _words(text: str) -> list[str]:
    return re.findall(r"[\w]+", text.lower().replace("-", " ").replace("_", " "))


# "claude" and "code": everyone says "tell Claude to ..." for whichever session is meant, so they never name one.
GENERIC_WORDS = {"main", "master", "dev", "develop", "staging", "prod", "the", "and", "session", "claude", "code"}
ADDRESS_NOUNS = {"session", "branch", "one", "worktree", "repo", "tab"}
WORD_MATCH = 0.8


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _name_words(name: str) -> list[str]:
    return [w for w in _words(name) if len(w) >= 2 or w.isdigit()]


def _distinctive(w: str) -> bool:
    return w not in GENERIC_WORDS and not w.isdigit()


def answers_a_prompt(name: str) -> bool:
    """A word of the name is a yes or a no: a session called "yes" would take the user's yes to a prompt as aimed at
    it, and nothing would answer."""
    return bool(set(_words(name.replace("'", "").replace("\u2019", ""))) & (_YES | _WEAK_YES | _NO))


def _alike(a: str, b: str) -> bool:
    """Two name words voice could take for each other: equal, or one letter off ("shops", "shop")."""
    return a == b or (min(len(a), len(b)) >= 3 and _similar(a, b) >= WORD_MATCH)


def speakable(name: str) -> bool:
    """A name voice can select: one word that is not generic ("dev", "main") or a bare number."""
    return any(_distinctive(w) for w in _name_words(name))


def _hears(word: str, spoken: str) -> bool:
    if word.isdigit():
        return NUMBERS.get(spoken, spoken) == word
    if len(spoken) < 3:  # "we" is not "web": a short word can only match exactly
        return word == spoken
    return _similar(word, spoken) >= WORD_MATCH


_SCRIPT_EDGE = re.compile(r"(?<=[\u0590-\u05ff])(?=[a-z0-9])|(?<=[a-z0-9])(?=[\u0590-\u05ff])")
_DOTTED = re.compile(r"\b[a-z](?:\.[a-z])+\b\.?")


def _spelled(token: str) -> bool:
    return (len(token) == 1 and token.isascii() and token.isalnum()) or token.isdigit() or token in NUMBERS


def _tokens(text: str) -> list[str]:
    """Words and clause marks. "Claude Code" is who the user talks to, never a session, so it becomes a mark.

    Spelled-out letters and numbers join: "S.D.K.", "A P I" and "v two" are sdk, api and v2.
    """
    text = _SCRIPT_EDGE.sub(" ", text.lower().replace("\u2019", "'"))
    text = _DOTTED.sub(lambda m: m.group(0).replace(".", ""), text)
    text = re.sub(r"\bclaude\s*code\b", " ; ", text)
    raw = re.findall(r"[^\W_]+(?:'[^\W_]+)*|[,.;:!?]", text)
    out: list[str] = []
    i = 0
    while i < len(raw):
        j = i
        while j < len(raw) and _spelled(raw[j]):
            j += 1
        run = raw[i:j]
        if len(run) >= 2 and any(t.isalpha() and len(t) == 1 for t in run):
            out.append("".join(NUMBERS.get(t, t) for t in run))
            i = j
        else:
            out.append(raw[i])
            i += 1
    return out


_NEGATORS = [("don't", "tell"), ("don't", "ask"), ("do", "not"), ("not",), ("never",), ("except",), ("but", "not"),
             ("other", "than"), ("leave",), ("ignore",), ("skip",), ("לא",), ("חוץ", "מ"), ("חוץ", "מה"), ("מלבד",),
             ("בלי",)]
_NEGATION_SKIP = {"tell", "ask", "the", "to", "about", "ל", "מ", "את"}


def _negated(tokens: list[str], vocab: set[str]) -> set[int]:
    """The session-name words right after a negation: "not the bluebell crm one", "don't tell lantern"."""
    out: set[int] = set()
    for i in range(len(tokens)):
        trigger = next((t for t in _NEGATORS if tuple(tokens[i:i + len(t)]) == t), None)
        if trigger is None:
            continue
        j = i + len(trigger)
        while j < len(tokens) and tokens[j] in _NEGATION_SKIP:
            j += 1
        while j < len(tokens) and (tokens[j] in ADDRESS_NOUNS or any(_hears(v, tokens[j]) for v in vocab)):
            out.add(j)
            j += 1
    return out


_TELL = {"tell", "ask", "get", "remind", "instruct", "תגיד", "תגידי", "תבקש", "תבקשי", "תשאל", "תשאלי",
         "ותגיד", "ותגידי", "ותבקש", "ותבקשי", "ותשאל", "ותשאלי"}
_MOVE = {"switch", "go", "back", "move", "jump", "change", "talk", "over", "head", "come", "work", "focus", "pin",
         "only"}
_PREPOSITIONS = {"in", "inside", "for", "on", "at"}
_ENDS = {",", ".", ";", ":", "!", "?", "and"}
_CLAUSE_ENDS = {".", ";", ":", "!", "?"}


_LEAD = {"the", "ל", "מ"}
_JOIN = {"and", "ו", "ול", "ומ", ","}


def _address(tokens: list[str], vocab: set[str]) -> set[int]:
    """Where the words say where something goes: "tell X", "switch to X", "in X", "the X session", "X, ..."."""
    slot: set[int] = set()

    def take(j: int, ends: set[str]) -> None:
        while j < len(tokens) and tokens[j] not in ends:
            slot.add(j)
            j += 1

    def name(j: int) -> bool:
        return j < len(tokens) and (tokens[j] in ADDRESS_NOUNS or any(_hears(v, tokens[j]) for v in vocab))

    def names(j: int) -> int:
        """Takes the name words from j ("bluebell and river lantern"); returns where they end. "tell lantern the
        bluebell build is broken" names only lantern: what follows the name is the message."""
        while j < len(tokens) and tokens[j] in _LEAD:
            j += 1
        while name(j) or (tokens[j:j + 1] and tokens[j] in _JOIN and j > 0 and name(j - 1) and name(j + 1)):
            if name(j):
                slot.add(j)
            j += 1
        return j

    for i, t in enumerate(tokens):
        if t in _TELL:
            names(i + 1)
        elif t in _JOIN - {","} and ";" in tokens[:i]:  # "tell X to A and lantern to B": a second target
            end = names(i + 1)
            if end == i + 1 or not (end == len(tokens) or tokens[end] in (";", "to", "should")
                                    or tokens[end][0] in "לש"):
                slot.difference_update(range(i + 1, end))
        elif t in ("to", "on", "onto", "ל") and i and tokens[i - 1] in _MOVE:
            take(i + 1, _ENDS)
        elif t in _PREPOSITIONS:
            take(i + 1, _ENDS)
        elif t in ADDRESS_NOUNS:
            j = i - 1
            while j >= max(0, i - 3) and tokens[j] not in _ENDS:
                slot.add(j)
                j -= 1
    if "," in tokens[:4]:
        slot.update(range(tokens.index(",")))
    return slot


def _aliases(s: Session) -> list[tuple[str, int]]:
    """(label, said-by-name) pairs: its name, and its folder when a rename left the folder out of the name and the
    folder has no yes or no word in it (answers_a_prompt) nor, on another machine, a word of this Mac's name."""
    folder = Path(s.cwd).name
    out = [(s.name, 1)]
    if (folder and not set(_name_words(folder)) <= set(_name_words(s.name)) and not answers_a_prompt(folder)
            and not (s.machine and set(_name_words(folder)) & set(_name_words(this_machine())))):
        out.append((folder, 0))
    if s.harness != "claude-code":  # "the opencode one": another harness's name picks its sessions out. Never "claude",
        import harnesses             # which every "ask Claude Code to ..." would match

        out.append((harnesses.of(s).label, 0))
    if s.machine:  # "go to devbox", "the devbox one": scored only where the words say who it is for (_score)
        out.append((s.machine, 0))
    return out


def _vocab(sessions: list[Session]) -> set[str]:
    return {w for s in sessions for label, _ in _aliases(s) for w in _name_words(label)}


def _score(s: Session, tokens: list[str], idx: list[int], address=()) -> tuple[tuple, set[int]] | None:
    """(score, distinctive token positions heard) for the best way the user said this session, or None.

    Score: name words heard, whole repo heard, whole name heard, said by its name (not its folder). Its machine's words
    count only at `address` positions, also inside a name suffixed with the machine ("shop devbox"): "fix the devbox
    config" names nothing.
    """
    best = None
    machine = set(_name_words(s.machine)) if s.machine else set()
    # This Mac's name, said where the words say who it is for, tells its own session from a remote twin ("shop on
    # studio"); it is no alias, so it adds to a name heard and never selects a session alone.
    here = set() if s.machine else {w for w in _name_words(this_machine()) if _distinctive(w)}
    here = {w for w in here if any(_hears(w, tokens[i]) for i in address)}
    for label, by_name in _aliases(s):
        words = _name_words(label)
        repo = _name_words(label.split("/")[0])
        heard, where = set(), set()
        for w in words:
            hits = {i for i in (address if w in machine else idx) if _hears(w, tokens[i])}
            if hits:
                heard.add(w)
                if _distinctive(w):
                    where |= hits
        if not where:
            continue
        heard |= here
        score = (len(heard), bool(repo) and all(w in heard for w in repo), all(w in heard for w in words), by_name)
        if best is None or score > best[0]:
            best = (score, where)
    return best


def _joined(tokens: list[str], vocab: set[str]) -> list[str]:
    """Two words the ears split that make one name word: "pen test" is pentest when a session is called pentest-recon.
    Only when neither half is a name word itself."""
    out: list[str] = []
    i = 0
    while i < len(tokens):
        pair = tokens[i] + tokens[i + 1] if i + 1 < len(tokens) else ""
        if pair in vocab and tokens[i] not in vocab and tokens[i + 1] not in vocab and pair.isalnum():
            out.append(pair)
            i += 2
        else:
            out.append(tokens[i])
            i += 1
    return out


def name_groups(utterance: str, sessions: list[Session], addressed: bool = False) -> list[list[Session]]:
    """The sessions the user named, one group per name they said. A group of several is a tie: ask.

    Words inside a task ("tell X to fix the voice settings") are not names, nor are negated ones. When the
    words say where something goes ("tell X", "in X"), only those count. Among sessions heard in the same
    words, the one that accounts for more of what was said wins ("bluebell crm" names bluebell-crm, not
    bluebell); a generic branch word ("dev", "main") never selects a session on its own. `addressed` counts only
    the words that say where something goes, never a name word inside a request ("fix the voice settings").
    """
    vocab = _vocab(sessions)
    tokens = _joined(_tokens(strip_tasks(utterance)), vocab)
    negated = _negated(tokens, vocab)
    live = [i for i in range(len(tokens)) if i not in negated]
    address = sorted(set(live) & _address(tokens, vocab))
    found = {}
    for idx in ((address,) if addressed else (address, live)):
        found = {k: sc for k, s in enumerate(sessions) if (sc := _score(s, tokens, idx, address))}
        if found:
            break
    components: list[set[int]] = []
    for k in found:
        touching = [c for c in components if any(found[k][1] & found[o][1] for o in c)]
        components = [c for c in components if c not in touching] + [{k}.union(*touching)]
    groups = []
    for c in components:
        top = max(found[k][0] for k in c)
        tied = sorted(k for k in c if found[k][0] == top)
        if any(not sessions[k].owner for k in tied):  # somebody else's session never ties one of mine: mine it is
            tied = [k for k in tied if not sessions[k].owner]
        groups.append(tied)
    return [[sessions[k] for k in g] for g in sorted(groups)]


def named_sessions(utterance: str, sessions: list[Session]) -> list[Session]:
    """Every session the user clearly named, for "tell bluebell and lantern to ..."; ties are left out."""
    return [g[0] for g in name_groups(utterance, sessions) if len(g) == 1]


def match_session(utterance: str, sessions: list[Session]) -> Session | None:
    """The one session the user named, or None if none, several, or a tie (ask instead of guessing)."""
    groups = name_groups(utterance, sessions)
    return groups[0][0] if len(groups) == 1 and len(groups[0]) == 1 else None


def mentions(utterance: str, sessions: list[Session]) -> bool:
    return bool(name_groups(utterance, sessions))


def excluded_sessions(utterance: str, sessions: list[Session]) -> list[Session]:
    """Sessions the user ruled out: "everyone except beta"."""
    tokens = _tokens(strip_tasks(utterance))
    negated = sorted(_negated(tokens, _vocab(sessions)))
    return [s for s in sessions if negated and _score(s, tokens, negated, negated)]


def machines_named(utterance: str, sessions: list[Session]) -> list[str]:
    """The machines the words say something is for ("tell everyone on devbox", "everyone on the laptop, ..."), never
    one ruled out ("except the laptop") or one inside the request ("pull the devbox branch")."""
    tokens = _tokens(strip_tasks(utterance))
    vocab = _vocab(sessions)
    address = sorted(_address(tokens, vocab) - _negated(tokens, vocab))
    found = []
    for machine in sorted({s.machine for s in sessions if s.machine}):
        words = [w for w in _name_words(machine) if _distinctive(w)]
        if words and all(any(_hears(w, tokens[i]) for i in address) for w in words):
            found.append(machine)
    return found


# ---------- delivery ----------

_DETAIL_ASKED = re.compile(r"\b(?:explain|in detail|details?|walk me through|step by step|everything|all of)\b", re.I)


def voice_message(text: str) -> str:
    """Identical lines in quick succession are dropped by Claude Code; a tag keeps repeats distinct. A short question
    asks for a short answer: it is read aloud, and a long one is cut or reworded before the user hears it."""
    # A question, also one the model relayed with a note after it ("…? Please answer from NOTES.md.")
    short = "?" in text and len(text) <= 300 and not _DETAIL_ASKED.search(text)
    hint = ("; the answer is read aloud: one or two short sentences, the answer first, not where you read it, and a "
            "caveat only if it changes the answer") if short else ""
    who = SENDER.get()
    return f"{person_prefix(who) if who else VOICE_PREFIX} #{secrets.token_hex(2)}{hint}] {text}"


RECEIPT_SECS = 1.5  # Claude Code answers a held or refused message in about 0.2 s; an accepted one gets no answer
HELD_WATCH_SECS = 600.0  # how long a held message's reply address stays open for the user's answer in the terminal


async def post_inbox(session: Session, text: str, receipt: bool = False) -> bool:
    """True when Claude Code took the message for Claude. With `receipt`, the message carries a reply address so Claude
    Code can say it held or refused it (`peer_message_status`); nothing is ever written back on the inbox connection
    itself. The address is offered only when asked: a session that has one tries to answer through it."""
    if not session.inbox_socket:  # registered without one (an older plugin, a test): not delivered, never a crash
        logger.error(f"inbox post to {session.name} failed: it has no inbox socket")
        return False
    reply = await _Receipts.open(session.inbox_socket) if receipt else None
    try:
        _, writer = await asyncio.open_unix_connection(session.inbox_socket)
        lines = []
        if session.inbox_token:
            lines.append({"type": "auth", "token": session.inbox_token})
        line = {"type": "user", "message": {"role": "user", "content": voice_message(text)}}
        if reply is not None:
            line.update({"from": f"uds:{reply.path}", "msg_id": reply.msg_id})
        lines.append(line)
        writer.write("".join(json.dumps(line) + "\n" for line in lines).encode())
        await writer.drain()
        writer.close()
    except OSError as e:
        logger.error(f"inbox post to {session.name} failed: {e}")
        if reply is not None:
            reply.close()
        return False
    if reply is None:
        return True
    status = await reply.next(RECEIPT_SECS)
    if status == "held":
        session.held_at = held = time.time()
        logger.warning(f"{session.name}: Claude Code held the voice's message for approval in its terminal")
        asyncio.create_task(_watch_held(session, reply, held))
        return False
    reply.close()
    if status in ("refused", "denied", "expired", "dropped"):
        session.refused_at = time.time() if status == "refused" else None
        logger.warning(f"{session.name}: Claude Code did not deliver the voice's message ({status})")
        return False
    session.held_at = session.refused_at = None
    return True  # no answer (accepted) or "delivered"


async def _watch_held(session: Session, reply: "_Receipts", held: float) -> None:
    """The user answers a held message in the terminal; Claude Code says how, and then it is not held any more."""
    try:
        status = await reply.next(HELD_WATCH_SECS)
    finally:
        reply.close()
    logger.info(f"{session.name}: the held message was {status or 'not answered in time'}")
    if session.held_at == held:
        session.held_at = None


class _Receipts:
    """A reply address for one message: a socket beside the session's own (Claude Code answers only an address in its
    socket's directory), and the statuses Claude Code sends to it, oldest first."""

    def __init__(self, path: str, msg_id: str):
        self.path, self.msg_id = path, msg_id
        self.statuses: asyncio.Queue[str] = asyncio.Queue()
        self.server: asyncio.AbstractServer | None = None

    @classmethod
    async def open(cls, inbox_socket: str) -> "_Receipts | None":
        path = os.path.join(os.path.dirname(inbox_socket), f"pointe-{os.getpid()}-{secrets.token_hex(4)}.sock")
        receipts = cls(path, str(uuid.uuid4()))
        try:
            receipts.server = await asyncio.start_unix_server(receipts._read, path)
        except OSError as e:  # a path too long for a socket, a directory it may not write: send without one
            logger.warning(f"no reply address beside {inbox_socket}: {e}")
            return None
        return receipts

    async def _read(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while line := await asyncio.wait_for(reader.readline(), 5):
                try:
                    frame = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(frame, dict) or frame.get("orig_msg_id") != self.msg_id:
                    continue  # not about this message: a reply the session tried to send here is not a receipt
                if frame.get("type") == "control" and frame.get("action") == "peer_message_status":
                    status = frame.get("status")
                    self.statuses.put_nowait("refused" if frame.get("status_detail") == "refused" else str(status))
        except (OSError, asyncio.TimeoutError, ValueError):
            pass
        finally:
            writer.close()

    async def next(self, secs: float) -> str | None:
        try:
            return await asyncio.wait_for(self.statuses.get(), secs)
        except asyncio.TimeoutError:
            return None

    def close(self) -> None:
        if self.server is not None:
            self.server.close()
            self.server = None
        try:
            os.unlink(self.path)
        except OSError:
            pass


# ---------- following a transcript ----------

def _tool_detail(tool_input: dict) -> str:
    keys = ("description", "command", "file_path", "pattern", "prompt")
    return next((str(tool_input[k]) for k in keys if k in tool_input), "")[:200]


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


# What a harness says a session waits for at a prompt in its terminal, in the words the voice and the screens use. Fixed
# words: the harness's own string is never said or shown as it came.
TERMINAL_WAITS = {"permission prompt": "a permission prompt", "input needed": "a question", "sandbox request": "a sandbox request",
                  "worker request": "a request from one of its workers", "dialog open": "an open dialog"}
HELD_WAIT = "a message from the voice, held for approval"
# The one setting that lets the voice's messages through (Claude Code's cross-session messaging docs).
INBOX_FIX = "Set crossSessionInbound to accept in that session's Claude Code settings to let the voice through."
HELD_NEED = f"A message from the voice, held for approval in its terminal. Approve it there. {INBOX_FIX}"
REFUSED_NEED = f"Its Claude Code refuses messages from other sessions, so the voice's message did not reach it. {INBOX_FIX}"
REFUSED_SHOW_SECS = 300.0  # how long the screens say so: as long as Claude Code keeps a held message by default


# The prompts the agent itself put up. An open dialog may be one the user opened, at the keyboard: it is state, not news.
ASKED_WAITS = ("permission prompt", "input needed", "sandbox request")
TERMINAL_NEWS_AFTER_SECS = 15.0  # a prompt answered at the keyboard within this never alerts


def terminal_wait(session: Session) -> str:
    """What the session waits for at a prompt in its own terminal, or "". A request the voice holds is not one: that
    wait is the permission itself."""
    if session.permission_id:
        return ""
    if message_held(session):
        return f"{HELD_WAIT} in its terminal"
    if not session.blocked_on:
        return ""
    return f"{TERMINAL_WAITS.get(session.blocked_on, 'a prompt')} in its terminal"


def message_held(session: Session, now: float | None = None) -> bool:
    """Claude Code holds the voice's last message for approval in the session's terminal. Its own receipt ends that
    (post_inbox); past HELD_WATCH_SECS nothing here knows, so it is not claimed."""
    return session.held_at is not None and (time.time() if now is None else now) - session.held_at < HELD_WATCH_SECS


def inbox_need(session: Session, now: float) -> str:
    """What the screens say when Claude Code set the voice's message aside, with the setting that fixes it; or ""."""
    if message_held(session, now) and not session.permission_id:
        return HELD_NEED
    if session.refused_at is not None and now - session.refused_at < REFUSED_SHOW_SECS:
        return REFUSED_NEED
    return ""


def terminal_wait_since(session: Session, now: float) -> float | None:
    """Since when it has stood at a prompt of its own in its terminal, once that is worth telling the user who is not
    there: an alert and, later, a nudge. None before that, and for a dialog."""
    if message_held(session, now) and not session.permission_id:
        since = session.held_at
    elif session.blocked_on not in ASKED_WAITS:
        return None
    else:
        since = session.blocked_since
    if not terminal_wait(session) or since is None:
        return None
    return since if now - since >= TERMINAL_NEWS_AFTER_SECS else None


def wait_state(session: Session) -> dict:
    """What a node ships in its `sessions` snapshot about a wait in the session's own terminal, in the node's clock: the
    harness's word for the prompt (`blocked_on`, which the hub maps to fixed words like this machine does), and a message
    from the voice Claude Code holds there."""
    return {"blocked_on": session.blocked_on, "blocked_since": session.blocked_since if session.blocked_on else None,
            "held_at": session.held_at if message_held(session) else None}


def _node_time(value, skew: float) -> float | None:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    return value + skew if ok else None


def apply_wait_state(session: Session, entry: dict, skew: float) -> None:
    """A node's `wait_state` on the hub's copy of the session, its times shifted by the clock skew measured at the
    node's hello. An unchanged wait keeps the time the hub gave it, so an alert keeps its id. An entry from a node older
    than pre-release 1.12.0 carries none of it and changes nothing."""
    if "blocked_on" not in entry:
        return
    blocked = entry.get("blocked_on")
    blocked = blocked[:64] if isinstance(blocked, str) else ""
    if blocked != session.blocked_on:
        session.blocked_on = blocked
        session.blocked_since = (_node_time(entry.get("blocked_since"), skew) or time.time()) if blocked else None
    held = _node_time(entry.get("held_at"), skew)
    if held is None:
        session.held_at = None
    elif session.held_at is None:
        session.held_at = min(held, time.time())


def _moved(session: Session) -> None:
    """Its record moved, so the prompt it stood at was answered: a tool ran, the turn went on or ended."""
    session.active_at = time.time()
    session.blocked_on, session.blocked_since = "", None


def _turn_ended(session: Session) -> None:
    """A pending permission cannot outlive the turn: it was answered in the terminal."""
    session.busy = False
    session.idle_since = time.time()
    if session.permission_id:
        session.permission_id, session.permission_since = None, None
        if session.permission_answer is not None and not session.permission_answer.done():
            session.permission_answer.set_result(None)
        REGISTRY.save()


REPOINT_EVERY_SECS = 5.0
RESUME_FOLLOW_SECS = 120.0  # a follower within this long of the last one on the same file reads what it missed


def current_transcript(session: Session) -> str:
    """Where this session writes now: its harness knows (Claude Code moves a session to a new file on /clear)."""
    import harnesses

    return harnesses.of(session).transcript_path(session)


async def follow_transcript(session: Session, feed: Feed, on_turn_end: Callable[[], None]) -> None:
    """Claude Code's activity, read from the session transcript (works for any session, no hooks)."""
    session.followed = True
    try:
        while True:
            await _follow_one(session, feed, on_turn_end)
    finally:
        session.followed = False


async def _follow_one(session: Session, feed: Feed, on_turn_end: Callable[[], None]) -> None:
    """Follows the session's current file; returns when the session has moved to another one."""
    import harnesses
    from harnesses.base import finished_tag

    harness = harnesses.of(session)
    who = harness.label  # "claude-code", "opencode": how the feed names the agent, read back by the daemon
    session.transcript = current_transcript(session)
    path = Path(session.transcript)
    while not path.exists():
        await asyncio.sleep(1)
        session.transcript = current_transcript(session)
        path = Path(session.transcript)
    checked = time.time()
    with path.open() as f:
        f.seek(0, os.SEEK_END)
        last = session.followed_to
        # A follower stopped on this file a moment ago (the call dropped): what was written since is news, not history.
        if last and last[0] == str(path) and time.time() - last[2] < RESUME_FOLLOW_SECS and last[1] <= f.tell():
            f.seek(last[1])
        while True:
            session.followed_to = (str(path), f.tell(), time.time())
            line = f.readline()
            if not line:
                await asyncio.sleep(0.3)
                if time.time() - checked > REPOINT_EVERY_SECS:
                    checked = time.time()
                    if current_transcript(session) != session.transcript:
                        logger.info(f"{session.name} moved to a new transcript")
                        return
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("isSidechain") or entry.get("type") not in ("user", "assistant"):
                continue
            message = entry.get("message") or {}
            content = message.get("content")
            _moved(session)
            if entry["type"] == "user":
                for block in content if isinstance(content, list) else []:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        session.turn.result(block)
                if _text(content).strip().startswith("[Request interrupted by user"):
                    session.turn.reset()
                    _turn_ended(session)
                    on_turn_end()
                    await feed(session, f"[{who} was interrupted by the user and stopped]", False)
                    continue
                finding = agent_finding(content) if isinstance(content, str) else ""
                if finding:
                    await feed(session, f"[a background agent of {who} reported, keep this in mind, say nothing yet] {finding[:3000]}", False)
                if isinstance(content, str) and entry.get("isCompactSummary"):
                    await feed(session, f"[{who} compacted its context; its own summary, keep this in mind, say nothing] {content[:4000]}", False)
                typed = harness.noise(content) if isinstance(content, str) else ""
                if isinstance(content, str) and content.strip() and not typed:
                    session.noise += 1
                if typed:
                    session.idle_since, session.needs = None, None
                    session.turn.reset()  # a new turn begins
                    if not from_a_voice(typed):  # a relay can answer one question of several: they last until the next report
                        session.open_questions, session.typed_approval = [], ""
                if typed and not from_a_voice(typed):
                    await feed(session, f"[the user typed this straight to {who}, which already has it: nothing to send] {typed}", False)
                continue
            for block in content if isinstance(content, list) else []:
                if block.get("type") == "tool_use":
                    session.turn.use(block, session.cwd)
                    session.step = (time.time(), step_of(block.get("name"), block.get("input")))
                    session.busy = True
                    session.idle_since, session.needs = None, None
                    await feed(session, f"[{who} is using {block.get('name')}, perhaps still waiting for approval] {_tool_detail(block.get('input') or {})}",
                               False)
                elif block.get("type") == "text" and block.get("text", "").strip():
                    text = block["text"].strip()
                    if message.get("stop_reason") == "end_turn":
                        session.artifacts = session.turn.finish(text, session.cwd, local=not session.machine)
                        _turn_ended(session)
                        on_turn_end()
                        await feed(session, f"{finished_tag(who)} {FINAL_MARK}{text}", True)
                    else:
                        await feed(session, f"[{who} wrote]\n{text}", False)


NUDGE_AFTER_SECS = 45
NUDGE_REPEAT_SECS = 300
QUIET_USER_SECS = 20
QUIET_BOT_SECS = 10


def waiting_since(s: Session) -> float | None:
    """Since when the session has been stuck on the user: a question at turn end, a permission, or a prompt of its own
    in its terminal."""
    times = [t for t in (s.idle_since if s.needs else None, s.permission_since if s.permission_id else None,
                         terminal_wait_since(s, time.time())) if t is not None]
    return min(times) if times else None


def pick_nudge(sessions: list[Session], now: float, last_user_speech: float, last_bot_speech: float) -> Session | None:
    """The session most worth a spoken nudge: stuck on the user longest, and only when the room is quiet."""
    if now - last_user_speech < QUIET_USER_SECS or now - last_bot_speech < QUIET_BOT_SECS:
        return None
    stuck = []
    for s in sessions:
        since = waiting_since(s)
        if since is None or now - since < NUDGE_AFTER_SECS or s.dismissed_wait == since:
            continue
        if s.nudged_at > since and now - s.nudged_at < NUDGE_REPEAT_SECS:
            continue
        stuck.append((since, s))
    return min(stuck, key=lambda x: x[0])[1] if stuck else None


TAIL_BLOCK = 256 * 1024
TAIL_MAX_BYTES = 8 * 1024 * 1024


def recent_history(session: Session, max_entries: int, max_chars: int, line_cap: int = 1500,
                   max_bytes: int = TAIL_MAX_BYTES, since: float | None = None) -> str:
    """The session's recent conversation as plain text; with `since`, only entries stamped at or after it.

    Read backwards from the end: transcripts grow to hundreds of megabytes, and routing reads several. A remote
    session's record carries its node's clock, so `since` is shifted by that node's measured skew.
    """
    if since is not None and session.machine and (m := MACHINES.get(session.machine)):
        since -= m.skew
    return "\n".join(_recent_lines(session, max_entries, max_chars, line_cap, max_bytes, since)[0])[-max_chars:]


_STAMP = re.compile(rb'"timestamp"\s*:\s*"([0-9T:.+-]+Z?)"')


def _stamped_before(raw: bytes, since: float) -> bool:
    """An entry whose timestamp is older than `since`. Entries without one are kept."""
    found = _STAMP.search(raw)
    if not found:
        return False
    try:
        return datetime.fromisoformat(found.group(1).decode().replace("Z", "+00:00")).timestamp() < since
    except ValueError:
        return False


def _recent_lines(session: Session, max_entries: int, max_chars: int, line_cap: int,
                  max_bytes: int, since: float | None = None) -> tuple[list[str], int]:
    """The newest history lines, oldest first, and the file offset where they start. With `since`, the walk back stops
    at the first entry stamped before it."""
    path = Path(session.transcript or "")
    if not session.transcript or not path.is_file():  # an empty path is ".", a folder: opening it crashed the call
        return [], 0
    lines: list[str] = []  # newest first
    size, start = 0, 0
    with path.open("rb") as f:
        pos = f.seek(0, os.SEEK_END)
        end, partial = pos, b""
        while pos > 0 and len(lines) < max_entries and size < max_chars and end - pos < max_bytes:
            step = min(TAIL_BLOCK, pos)
            pos -= step
            f.seek(pos)
            chunk = f.read(step) + partial
            raws = chunk.split(b"\n")
            partial = raws.pop(0) if pos > 0 else b""  # may be cut mid-line; finished by the next block
            offset = pos + len(chunk) + 1  # walking back: each line starts len(raw) + 1 before the previous one
            for raw in reversed(raws):
                offset -= len(raw) + 1
                if since is not None and _stamped_before(raw, since):
                    return list(reversed(lines)), start
                line = _history_line(raw, line_cap)
                if line:
                    lines.append(line)
                    start = offset
                    size += len(line) + 1
                    if len(lines) >= max_entries or size >= max_chars:
                        break
    return list(reversed(lines)), start


SUMMARY_MARK = b'"isCompactSummary"'


def how_it_began(session: Session, lines: int = 3, read: int = 256_000) -> str:
    """Its first few things the user typed: a goal stated long ago, ready before the notes are, and cheap at any file size."""
    try:
        with Path(session.transcript).open("rb") as f:
            raws = f.read(read).split(b"\n")[:-1]
    except OSError:
        return ""
    found = [line for line in (_history_line(raw, 800) for raw in raws) if line.startswith("[user]")]
    return "\n".join(found[:lines])


def older_mentions(session: Session, before: int, question: str, limit: int = 30_000) -> str:
    """Lines older than `before` that share a distinctive word with the question: a constraint said on day one must not
    read as "never mentioned" because tool noise pushed it out of the window."""
    keys = {w for w in re.findall(r"[\w-]{5,}", question.lower())} - {"about", "which", "there", "their", "where", "would", "could", "should", "session", "claude"}
    if not keys:
        return ""
    found, size, offset = [], 0, 0
    with Path(session.transcript).open("rb") as f:
        for raw in f:
            if offset >= before or size > limit:
                break
            offset += len(raw)
            lowered = raw.lower()
            if any(k.encode() in lowered for k in keys):
                line = _history_line(raw, 2000)
                if line:
                    found.append(line)
                    size += len(line)
    return "\n".join(found)


def session_record(session: Session, max_chars: int = 400_000, question: str = "") -> str:
    """What a question about a session is answered from: its newest messages whole, and, when they do not reach
    back far enough, Claude Code's own latest compaction summary of everything before them, plus older lines that
    mention the question's words. Blocking: reads up to the whole transcript, so call it off the event loop."""
    lines, start = _recent_lines(session, max_entries=100_000, max_chars=max_chars, line_cap=20_000,
                                 max_bytes=256 * 1024 * 1024)
    if start == 0:
        return "\n".join(lines)
    summary = ""
    with Path(session.transcript).open("rb") as f:
        offset = 0
        for raw in f:
            if offset >= start:
                break
            offset += len(raw)
            if SUMMARY_MARK in raw:
                try:
                    entry = json.loads(raw)
                except ValueError:
                    continue
                if entry.get("isCompactSummary") is True:
                    summary = (entry.get("timestamp", "")[:16], _text((entry.get("message") or {}).get("content")))
    head = (f"[earlier work, Claude Code's own summary from {summary[0]}]\n{summary[1][:60_000]}\n"
            "[the newest messages follow]\n") if summary else ""
    older = older_mentions(session, start, question) if question else ""
    gap = ("[this record does not hold every older message: \"not in the transcript\" means not in what was read]\n"
           + (f"[older lines that mention the question's words]\n{older}\n" if older else ""))
    return gap + head + "\n".join(lines)


def _history_line(raw: bytes, cap: int = 1500) -> str:
    try:
        entry = json.loads(raw)
    except ValueError:
        return ""
    if not isinstance(entry, dict) or entry.get("isSidechain") or entry.get("type") not in ("user", "assistant"):
        return ""
    text = _text((entry.get("message") or {}).get("content")).strip()
    if entry["type"] == "user" and not entry.get("isCompactSummary"):
        finding = agent_finding(text)
        text = human_text(text)
        if finding:
            return f"[background agent] {excerpt(finding, cap)}"
    if not text:
        return ""
    return f"[{'user' if entry['type'] == 'user' else 'claude-code'}] {excerpt(text, cap)}"


_TITLE_KINDS = (("custom-title", "customTitle"), ("agent-name", "agentName"), ("ai-title", "aiTitle"))
TITLE_TAIL_BYTES = 512_000


_JOIN_COMMANDS = re.compile(r"<command-name>/(?:pointe:)?voice</command-name>|claude-voice-attach")


def _joined_first(transcript: str) -> bool:
    """Was joining the voice the session's first prompt? Then Claude Code titles the session after that."""
    try:
        with open(transcript, encoding="utf-8", errors="replace") as f:
            for _, line in zip(range(400), f):
                if '"type":"user"' not in line.replace(" ", ""):
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                content = (record.get("message") or {}).get("content")
                if record.get("isMeta") or not isinstance(content, str):
                    continue
                return bool(_JOIN_COMMANDS.search(content))
    except OSError:
        pass
    return False


def session_title(transcript: str, tail_bytes: int = TITLE_TAIL_BYTES) -> str | None:
    """The name Claude Code shows for the session: a /rename title, else an agent name, else its own AI title.

    Read from the end of the transcript, where the latest title record is; cleaned into a speakable name.
    """
    try:
        with open(transcript, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - tail_bytes))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    found: dict[str, str] = {}
    keys = dict(_TITLE_KINDS)
    for line in tail.splitlines():
        if "title" not in line and "agent-name" not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue  # the first line of the tail can be cut mid-record
        kind = record.get("type") if isinstance(record, dict) else None
        if kind in keys:
            found[kind] = str(record.get(keys[kind]) or "")
    if found.get("ai-title") and _joined_first(transcript):
        del found["ai-title"]  # it describes joining the voice, the same for every session that started that way
    for kind, _ in _TITLE_KINDS:
        name = " ".join(re.sub(r"[^\w ./-]+", " ", found.get(kind, "")).split())
        if len(name) > 40:
            name = name[:40].rsplit(" ", 1)[0]
        name = name.strip(" ./-")
        if name:
            return name
    return None
