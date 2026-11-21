"""Starting a new coding-agent session from Pointe (docs/design/new-session.md): where one may start, what it is
called, and the record of a start until its session joins. No Pipecat and no HTTP here; daemon.py holds the tool, the
routes and the read-back.

A folder is never taken from a request as a path to trust. It is looked up in the list built here: folders of the
sessions on the voice, folders of sessions that joined in the last 30 days, and folders the user added in Settings.
"""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

RECENT_SECS = 30 * 24 * 3600
MAX_RECENT = 40
MAX_ADDED = 50
MAX_PROMPT = 4000
JOIN_SECS = 90.0  # how long a session that registers itself (Claude Code, from its new terminal window) is waited for
FAILED_SHOWN_SECS = 120.0  # a failed start stays on the screens this long, with its reason
CONFIRM_SECS = 60.0  # how long a read-back can still be answered yes


def real(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


def valid_folders(value) -> bool:
    """`sessions.folders` in prefs: a short list of absolute paths, each a folder that is not the whole disk."""
    return (isinstance(value, list) and len(value) <= MAX_ADDED
            and all(isinstance(p, str) and 1 < len(p) <= 1024 and os.path.isabs(os.path.expanduser(p)) and real(p) != "/"
                    for p in value))


class Recent:
    """Folders sessions joined from, with when: STATE/folders.json, 0600. A damaged file is an empty list."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.seen: dict[str, float] = {}
        try:
            loaded = json.loads(path.read_text())
            self.seen = {str(k): float(v) for k, v in loaded.items() if isinstance(v, (int, float))}
        except (OSError, ValueError, AttributeError):
            pass

    def note(self, folder: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if not folder or not os.path.isabs(folder):
            return
        self.seen[real(folder)] = now
        kept = sorted(((at, p) for p, at in self.seen.items() if now - at < RECENT_SECS), reverse=True)[:MAX_RECENT]
        self.seen = {p: at for at, p in kept}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.touch(mode=0o600)
            tmp.write_text(json.dumps(self.seen))
            os.replace(tmp, self.path)
        except OSError:
            pass

    def folders(self, now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        return [p for at, p in sorted(((at, p) for p, at in self.seen.items() if now - at < RECENT_SECS), reverse=True)]


def allowed(sessions: list, recent: Recent, added: list[str]) -> list[dict]:
    """Where a session may start on this Mac, most useful first: {path, name, source}. `source` is "session" (one is on
    the voice there now), "recent" or "added". Only folders that exist; each once, by its real path."""
    out: dict[str, dict] = {}
    for source, paths in (("session", [s.cwd for s in sessions if not s.machine]), ("recent", recent.folders()),
                          ("added", added)):
        for path in paths:
            key = real(path) if path else ""
            if key and key != "/" and key not in out and os.path.isdir(key):
                out[key] = {"path": key, "name": Path(key).name or key, "source": source}
    return list(out.values())


def find(folder: str, folders: list[dict]) -> dict | None:
    """The entry of the list a request's folder names, or None: the only way a path becomes a place to start in."""
    if not isinstance(folder, str) or not folder:
        return None
    key = real(folder)
    return next((f for f in folders if f["path"] == key), None)


def places(sessions: list, folders: list[dict]) -> list[tuple[str, str]]:
    """What a folder can be called by voice: its own name, and the name of a session on the voice there."""
    paths = {f["path"] for f in folders}
    out = [(f["name"], f["path"]) for f in folders]
    for s in sessions:
        if not s.machine and s.cwd and real(s.cwd) in paths and (s.name, real(s.cwd)) not in out:
            out.append((s.name, real(s.cwd)))
    return out


def said_folder(entry: dict, folders: list[dict]) -> str:
    """How the read-back names a folder: its name, with its parent when two folders in the list share the name."""
    twins = [f for f in folders if f["name"].lower() == entry["name"].lower()]
    if len(twins) < 2:
        return entry["name"]
    return f"{entry['name']} in {Path(entry['path']).parent.name or '/'}"


@dataclass
class Start:
    """One start, from the Start button or the spoken yes until its session is on the voice (or it failed)."""
    id: str
    harness: str
    folder: str
    name: str
    prompt: str = ""
    how: str = ""  # "voice", "page", "phone"
    since: float = field(default_factory=time.time)
    state: str = "starting"  # starting | waiting (it runs, and has not joined yet) | joined | failed
    detail: str = ""
    session_id: str = ""
    ended: float | None = None

    def view(self, label: str) -> dict:
        return {"id": self.id, "name": self.name, "harness": self.harness, "label": label, "folder": Path(self.folder).name,
                "state": self.state, "detail": self.detail, "since": self.since}

    def fail(self, why: str) -> None:
        self.state, self.detail, self.ended = "failed", why, time.time()


def shown(starts: dict[str, Start], now: float | None = None) -> list[Start]:
    """The starts the screens list: under way, and failed in the last two minutes. Joined ones are sessions now."""
    now = time.time() if now is None else now
    for key in [k for k, s in starts.items() if s.ended and now - s.ended > FAILED_SHOWN_SECS]:
        del starts[key]
    return [s for s in starts.values() if s.state != "joined"]
