"""The notes stream: what the voice writes for the user to read instead of saying it (meeting thoughts, open questions,
answers it found, action items, a raised hand, session news it held back). Typed, append-only, in memory for the call.
The page and the phone read it with GET /voice/notes?since=<id>, or, to get only what changed, &changed_since=<version>.
A note written during a meeting carries that meeting's id, so one meeting's notes never reach another's prompts.
"""

import re
import time
from dataclasses import asdict, dataclass, field

KINDS = ("thought", "question", "answer", "action", "decision", "hand", "session_news", "brief", "summary", "speaker",
         "briefing")
STATES = ("open", "done", "dismissed")
MAX_NOTES = 2000
_STOP = set("the a an and or but of to in on for with is are was were be it this that we you i they he she at by as from "
            "של את על עם זה זו לא כן גם אבל".split())


def _content(text: str) -> set[str]:
    return {w for w in re.findall(r"[\w']+", text.lower()) if w not in _STOP and len(w) > 1}


def mostly_same(a: str, b: str) -> bool:
    """Two notes saying the same thing: 60% of the shorter one's content words are in the other."""
    ca, cb = _content(a), _content(b)
    if not ca or not cb:
        return a.strip().lower() == b.strip().lower()
    return len(ca & cb) / min(len(ca), len(cb)) >= 0.6


@dataclass
class Note:
    id: int
    kind: str
    text: str
    at: float
    state: str = "open"
    meta: dict = field(default_factory=dict)
    speakers: list = field(default_factory=list)
    session: str | None = None
    updated: float = 0.0
    meeting: str | None = None  # the meeting it was written in
    rev: int = 0  # the stream's version when it was written or last changed


class Notes:
    def __init__(self) -> None:
        self.items: list[Note] = []
        self.next_id = 1
        self.version = 0  # bumped on every change, so a client can poll cheaply
        self.meeting: str | None = None  # the meeting on now: new notes carry its id

    def add(self, kind: str, text: str, *, meta: dict | None = None, speakers: list | None = None,
            session: str | None = None, dedup: bool = True, meeting: str | None = None) -> Note:
        if kind not in KINDS:
            raise ValueError(f"unknown note kind {kind!r}")
        text = text.strip()
        meeting = meeting or self.meeting
        if dedup:
            for note in reversed(self.items[-200:]):
                if note.kind == kind and note.meeting == meeting and note.state != "dismissed" and mostly_same(note.text, text):
                    note.text, note.updated = text, time.time()  # the newer wording wins; the id stays
                    note.meta.update(meta or {})
                    self.version += 1
                    note.rev = self.version
                    return note
        self.version += 1
        note = Note(self.next_id, kind, text, time.time(), meta=dict(meta or {}), speakers=list(speakers or []),
                    session=session, meeting=meeting, rev=self.version)
        self.next_id += 1
        self.items.append(note)
        del self.items[:-MAX_NOTES]
        return note

    def get(self, note_id: int) -> Note | None:
        return next((n for n in self.items if n.id == note_id), None)

    def set_state(self, note_id: int, new_state: str) -> Note | None:
        if new_state not in STATES:
            raise ValueError(f"unknown state {new_state!r}")
        note = self.get(note_id)
        if note is not None:
            note.state, note.updated = new_state, time.time()
            self.version += 1
            note.rev = self.version
        return note

    def since(self, after: int = 0, kinds: set[str] | None = None, version: int | None = None,
              meeting: str | None = None) -> list[dict]:
        """Notes created after `after`, and older notes changed since; changed notes come back whole. Without `version`
        that is every older note ever changed (the original contract); with the `version` the client last saw, only
        those changed after it."""
        return [asdict(n) for n in self.items
                if (n.id > after or (n.rev > version if version is not None else n.updated))
                and (not kinds or n.kind in kinds) and (meeting is None or n.meeting == meeting)]

    def forget(self, meeting: str | None = None) -> int:
        """Drop one meeting's notes, or every meeting's when none is named. Notes written outside a meeting stay."""
        before = len(self.items)
        self.items[:] = [n for n in self.items if n.meeting is None or (meeting is not None and n.meeting != meeting)]
        if len(self.items) != before:
            self.version += 1
        return before - len(self.items)

    def clear(self) -> None:
        self.items.clear()
        self.version += 1
