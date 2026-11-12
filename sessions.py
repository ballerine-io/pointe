"""The Claude Code sessions the voice can talk to.

The registry outlives browser connections: sessions register once (from `/voice` or the
launcher's SessionStart hook) and stay until their process exits. Each connection turns
the registry into Pipecat bus workers, one per session.
"""

import asyncio
import json
import os
import re
import secrets
import subprocess
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

from brief import FINAL_MARK, agent_finding, excerpt, human_text
from echo import NUMBERS
from guards import strip_tasks
from pipecat.workers.base_worker import BaseWorker

Feed = Callable[["Session", str, bool], Awaitable[None]]

VOICE_PREFIX = "[Voice request from the user, relayed by their voice assistant"
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
    permission_full: str = ""
    permission_since: float | None = None  # when it arrived: a background session can wait on it for long
    last_delegation_at: float = 0.0
    busy: bool = False
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

    def alive(self) -> bool:
        import harnesses

        return harnesses.get(self.harness).alive(self)


PERSISTED = ("id", "name", "named_by", "cwd", "pid", "transcript", "inbox_socket", "inbox_token", "channel_url",
             "permission_id", "permission_text", "permission_since", "permission_cut", "permission_full", "permission_spoken",
             "harness", "home", "harness_data")  # Claude Code still waits after a restart
MAX_DEPARTED = 20


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
        self.active_id = session_id
        self.save()

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
                if session.harness == "claude-code" and not (session.pid and session.transcript):
                    raise TypeError("a Claude Code session needs its process and transcript")
            except (TypeError, AttributeError):
                logger.error(f"skipping a bad session entry in {path}")
                continue
            if session.alive():
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

    def rename_check(self, session_id: str, new_name: str) -> str | None:
        """Why new_name cannot be used for this session, or None if it can."""
        new_name = " ".join(new_name.split())
        others = [o for o in self.sessions.values() if o.id != session_id]
        if any(o.name.lower() == new_name.lower() for o in others):
            return f"another session is already called {new_name}"
        if not speakable(new_name):
            return f"{new_name} cannot be picked by voice"
        mine = {w for w in _name_words(new_name) if _distinctive(w)}
        inside = next((o for o in others if mine <= set(_name_words(o.name))), None)
        return f"{new_name} is part of {inside.name}" if inside else None

    def rename(self, session_id: str, new_name: str) -> str | None:
        """Rename a session; returns an error message, or None on success."""
        new_name = " ".join(new_name.split())
        others = [o for o in self.sessions.values() if o.id != session_id]
        if any(o.name.lower() == new_name.lower() for o in others):
            return f"another session is already called {new_name}"
        if not speakable(new_name):
            return (f"{new_name} cannot be picked by voice: words like dev, main or session never select a "
                    f"session on their own. Use a name with a distinctive word")
        mine = {w for w in _name_words(new_name) if _distinctive(w)}
        inside = next((o for o in others if mine <= set(_name_words(o.name))), None)
        if inside:
            return f"{new_name} is part of {inside.name}, so voice could not tell them apart"
        self.sessions[session_id].name = new_name
        self.save()
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
    """(label, said-by-name) pairs: its name, and its folder when a rename left the folder out of the name."""
    folder = Path(s.cwd).name
    out = [(s.name, 1)]
    if folder and not set(_name_words(folder)) <= set(_name_words(s.name)):
        out.append((folder, 0))
    if s.harness != "claude-code":  # "the opencode one": another harness's name picks its sessions out. Never "claude",
        import harnesses             # which every "ask Claude Code to ..." would match

        out.append((harnesses.get(s.harness).label, 0))
    return out


def _score(s: Session, tokens: list[str], idx: list[int]) -> tuple[tuple, set[int]] | None:
    """(score, distinctive token positions heard) for the best way the user said this session, or None.

    Score: name words heard, whole repo heard, whole name heard, said by its name (not its folder).
    """
    best = None
    for label, by_name in _aliases(s):
        words = _name_words(label)
        repo = _name_words(label.split("/")[0])
        heard, where = set(), set()
        for w in words:
            hits = {i for i in idx if _hears(w, tokens[i])}
            if hits:
                heard.add(w)
                if _distinctive(w):
                    where |= hits
        if not where:
            continue
        score = (len(heard), bool(repo) and all(w in heard for w in repo), all(w in heard for w in words), by_name)
        if best is None or score > best[0]:
            best = (score, where)
    return best


def name_groups(utterance: str, sessions: list[Session], addressed: bool = False) -> list[list[Session]]:
    """The sessions the user named, one group per name they said. A group of several is a tie: ask.

    Words inside a task ("tell X to fix the voice settings") are not names, nor are negated ones. When the
    words say where something goes ("tell X", "in X"), only those count. Among sessions heard in the same
    words, the one that accounts for more of what was said wins ("bluebell crm" names bluebell-crm, not
    bluebell); a generic branch word ("dev", "main") never selects a session on its own. `addressed` counts only
    the words that say where something goes, never a name word inside a request ("fix the voice settings").
    """
    tokens = _tokens(strip_tasks(utterance))
    vocab = {w for s in sessions for label, _ in _aliases(s) for w in _name_words(label)}
    negated = _negated(tokens, vocab)
    live = [i for i in range(len(tokens)) if i not in negated]
    address = sorted(set(live) & _address(tokens, vocab))
    found = {}
    for idx in ((address,) if addressed else (address, live)):
        found = {k: sc for k, s in enumerate(sessions) if (sc := _score(s, tokens, idx))}
        if found:
            break
    components: list[set[int]] = []
    for k in found:
        touching = [c for c in components if any(found[k][1] & found[o][1] for o in c)]
        components = [c for c in components if c not in touching] + [{k}.union(*touching)]
    groups = []
    for c in components:
        top = max(found[k][0] for k in c)
        groups.append(sorted(k for k in c if found[k][0] == top))
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
    vocab = {w for s in sessions for label, _ in _aliases(s) for w in _name_words(label)}
    negated = sorted(_negated(tokens, vocab))
    return [s for s in sessions if negated and _score(s, tokens, negated)]


# ---------- delivery ----------

def voice_message(text: str) -> str:
    """Identical lines in quick succession are dropped by Claude Code; a tag keeps repeats distinct."""
    return f"{VOICE_PREFIX} #{secrets.token_hex(2)}] {text}"


async def post_inbox(session: Session, text: str) -> bool:
    if not session.inbox_socket:  # registered without one (an older plugin, a test): not delivered, never a crash
        logger.error(f"inbox post to {session.name} failed: it has no inbox socket")
        return False
    try:
        _, writer = await asyncio.open_unix_connection(session.inbox_socket)
        lines = []
        if session.inbox_token:
            lines.append({"type": "auth", "token": session.inbox_token})
        lines.append({"type": "user", "message": {"role": "user", "content": voice_message(text)}})
        writer.write("".join(json.dumps(line) + "\n" for line in lines).encode())
        await writer.drain()
        writer.close()
        return True
    except OSError as e:
        logger.error(f"inbox post to {session.name} failed: {e}")
        return False


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


def current_transcript(session: Session) -> str:
    """Where this session writes now: its harness knows (Claude Code moves a session to a new file on /clear)."""
    import harnesses

    return harnesses.get(session.harness).transcript_path(session)


async def follow_transcript(session: Session, feed: Feed, on_turn_end: Callable[[], None]) -> None:
    """Claude Code's activity, read from the session transcript (works for any session, no hooks)."""
    while True:
        await _follow_one(session, feed, on_turn_end)


async def _follow_one(session: Session, feed: Feed, on_turn_end: Callable[[], None]) -> None:
    """Follows the session's current file; returns when the session has moved to another one."""
    import harnesses
    from harnesses.base import finished_tag

    harness = harnesses.get(session.harness)
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
        while True:
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
            if entry["type"] == "user":
                if _text(content).strip().startswith("[Request interrupted by user"):
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
                    if VOICE_PREFIX not in typed:  # a relay can answer one question of several: they last until the next report
                        session.open_questions, session.typed_approval = [], ""
                if typed and VOICE_PREFIX not in typed:
                    await feed(session, f"[the user typed this straight to {who}, which already has it: nothing to send] {typed}", False)
                continue
            for block in content if isinstance(content, list) else []:
                if block.get("type") == "tool_use":
                    session.busy = True
                    session.idle_since, session.needs = None, None
                    await feed(session, f"[{who} is using {block.get('name')}, perhaps still waiting for approval] {_tool_detail(block.get('input') or {})}",
                               False)
                elif block.get("type") == "text" and block.get("text", "").strip():
                    text = block["text"].strip()
                    if message.get("stop_reason") == "end_turn":
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
    """Since when the session has been stuck on the user: a question at turn end, or a permission."""
    times = [t for t in (s.idle_since if s.needs else None, s.permission_since if s.permission_id else None)
             if t is not None]
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
                   max_bytes: int = TAIL_MAX_BYTES) -> str:
    """The session's recent conversation as plain text.

    Read backwards from the end: transcripts grow to hundreds of megabytes, and routing reads several.
    """
    return "\n".join(_recent_lines(session, max_entries, max_chars, line_cap, max_bytes)[0])[-max_chars:]


def _recent_lines(session: Session, max_entries: int, max_chars: int, line_cap: int,
                  max_bytes: int) -> tuple[list[str], int]:
    """The newest history lines, oldest first, and the file offset where they start."""
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


# ---------- the bus worker ----------

class ClaudeSessionWorker(BaseWorker):
    """One Claude Code session on the voice bus: follows its transcript and feeds its activity to the voice
    model, tagged with the session name. Requests are delivered directly, so the sender knows if they arrived."""

    def __init__(self, session: Session, feed: Feed):
        super().__init__(name=f"session:{session.id}")
        self.session = session
        self._feed = feed
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        import harnesses

        await super().start()
        self._tasks = [asyncio.create_task(c) for c in harnesses.get(self.session.harness).watch(self.session, self._feed)]

    async def stop(self) -> None:
        """Stops this worker only. BaseWorker.end() would end the whole bus session."""
        for task in self._tasks:
            task.cancel()
        await super().stop()


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


def session_title(transcript: str) -> str | None:
    """The name Claude Code shows for the session: a /rename title, else an agent name, else its own AI title.

    Read from the end of the transcript, where the latest title record is; cleaned into a speakable name.
    """
    try:
        with open(transcript, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - TITLE_TAIL_BYTES))
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
