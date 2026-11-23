"""Finding sessions the user already runs, or ran lately, so the voice can join or reopen them
(docs/design/attach-by-voice.md). No Pipecat and no HTTP here: the adapters list what their harness exposes, this
module holds the record they share and reads Claude Code's own files; daemon.py does the read-back and the joining.

What is read, and nothing more: the config dirs of this OS user that Pointe already knows, `claude agents --json`
for each, a session's own record (`sessions/<pid>.json`) for its inbox socket, and the head and tail of transcripts.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

WINDOW_SECS = 7 * 24 * 3600  # recent closed sessions: the last week
CAP = 40  # at most this many recent sessions per account and harness, newest first
HEAD_BYTES = TAIL_BYTES = 64 << 10  # what is read of any one transcript
TEXT_CHARS = 160  # a first or last request as kept for the screens and the matcher
KEYWORDS = 12
HOMES_ENV = "CLAUDE_VOICE_CLAUDE_HOMES"  # replaces the accounts read: tests and the e2e point it at a throwaway one


@dataclass
class Found:
    """A session a harness lists: open (running now) or recent (closed, or idle long enough to count as closed)."""

    harness: str
    id: str
    name: str
    cwd: str
    state: str  # "open" or "recent"
    when: float  # its last activity, epoch seconds
    title: str = ""
    branch: str = ""
    first: str = ""  # the first thing the user asked it
    last: str = ""  # the last thing the user asked it
    keywords: list[str] = field(default_factory=list)  # a local summary: distinctive words of those requests
    machine: str = ""  # "" for this machine
    pid: int = 0
    home: str = ""  # Claude Code: the config dir it runs under ("" is the default account)
    transcript: str = ""
    socket: str = ""  # Claude Code: its inbox socket
    kind: str = ""  # Claude Code: interactive or background
    status: str = ""  # busy, waiting, idle, when the harness says
    name_given: bool = False  # the user named it in the harness: the voice keeps that name
    approvals: bool = True  # the voice can answer its permission prompts once it joins
    joinable: bool = True
    why: str = ""  # why it cannot join (or reopen), in words for the user
    data: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.machine or '-'}|{self.harness}|{self.id}"

    def to_dict(self) -> dict:
        out = asdict(self)
        out["key"] = self.key
        return out

    @classmethod
    def from_dict(cls, raw: dict) -> "Found | None":
        """A record from a node: only known fields of the right kind; None for one that cannot be used."""
        if not isinstance(raw, dict):
            return None
        try:
            found = cls(harness=str(raw["harness"]), id=str(raw["id"]), name=str(raw["name"])[:80], cwd=str(raw["cwd"])[:4096],
                        state="open" if raw.get("state") == "open" else "recent", when=float(raw.get("when") or 0))
        except (KeyError, TypeError, ValueError):
            return None
        for key in ("title", "branch", "first", "last", "kind", "status", "why"):
            setattr(found, key, str(raw.get(key) or "")[:TEXT_CHARS])
        found.keywords = [str(k)[:40] for k in raw.get("keywords") or [] if isinstance(k, str)][:KEYWORDS]
        found.approvals, found.joinable = bool(raw.get("approvals", True)), bool(raw.get("joinable", True))
        found.name_given = bool(raw.get("name_given"))
        return found


# ---------- reading a Claude Code transcript ----------

_STOP = set("""a an the and or but if then so of to in on at for with from by about into over under is are was were be been
being do does did done have has had this that these those it its i me my we our you your he she they them their what which
who whom when where why how can could should would will shall may might must not no yes just also please let lets make
sure some any all each more most other such only own same than too very now here there up down out off again further once
want need like look check run fix add use get got see tell ask session sessions claude code voice pointe okay ok thanks
reply only word word""".split())
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{3,}")


def keywords(*texts: str, most: int = KEYWORDS) -> list[str]:
    """The distinctive words of what the user asked, in order of first use: the local summary a match reads, and the
    only words of a session (beside its title) that may go to the brain."""
    out: list[str] = []
    for text in texts:
        for word in _WORD.findall(text or ""):
            w = word.lower().strip("-_")
            if w not in _STOP and w not in out and not w.isdigit():
                out.append(w)
            if len(out) >= most:
                return out
    return out


def _clean(text: str) -> str:
    from brief import human_text

    text = human_text(text or "")
    return " ".join(text.split())[:TEXT_CHARS]


def _user_text(entry: dict) -> str:
    """What the user typed in a transcript entry: "" for anything else (meta, tool results, commands, interruptions)."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return ""
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return ""
        content = " ".join(str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(content, str):
        return ""
    stripped = content.strip()
    if not stripped or stripped.startswith(("<command-", "<local-command", "[Request interrupted", "Caveat:", "<system-reminder")):
        return ""
    return _clean(stripped)


def _lines(path: str, head: bool) -> list[dict]:
    try:
        with open(path, "rb") as f:
            if head:
                raw = f.read(HEAD_BYTES)
            else:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - TAIL_BYTES))
                raw = f.read()
    except (OSError, TypeError):
        return []
    out = []
    for line in raw.split(b"\n"):
        try:
            entry = json.loads(line)
        except ValueError:
            continue  # a cut line at either end
        if isinstance(entry, dict):
            out.append(entry)
    return out


def read_claude_transcript(path: str) -> dict:
    """What a Claude Code transcript says about its session, from its head and tail only: cwd, branch, title, the first
    and last request, and keywords. Empty strings where it does not say."""
    from sessions import session_title

    head, tail = _lines(path, True), _lines(path, False)
    cwd = branch = first = last = ""
    for entry in head:
        cwd = cwd or str(entry.get("cwd") or "")
        branch = branch or str(entry.get("gitBranch") or "")
        first = first or _user_text(entry)
        if cwd and first:
            break
    for entry in reversed(tail):
        if entry.get("type") == "last-prompt" and isinstance(entry.get("lastPrompt"), str):
            last = _clean(entry["lastPrompt"])
        else:
            last = _user_text(entry)
        if last:
            break
    for entry in reversed(tail):
        cwd = cwd or str(entry.get("cwd") or "")
        if entry.get("gitBranch"):
            branch = str(entry["gitBranch"])
            break
    title = session_title(path, TAIL_BYTES) or ""  # Claude Code writes its title records again after each turn
    return {"cwd": cwd, "branch": "" if branch == "HEAD" else branch, "title": title, "first": first,
            "last": "" if last == first else last, "keywords": keywords(title, first, last)}


# ---------- Claude Code accounts, records and sockets ----------

def own(path: Path) -> bool:
    """A file or folder of this OS user: another user's config dir or socket is never read or used."""
    try:
        return path.stat().st_uid == os.getuid()
    except OSError:
        return False


def claude_homes(default: Path, known: list[str]) -> list[str]:
    """The config dirs discovery reads: the default account ("") and those sessions registered from. Each must exist
    and belong to this user. CLAUDE_VOICE_CLAUDE_HOMES, when set, is the whole list."""
    override = os.environ.get(HOMES_ENV)
    candidates = [p for p in override.split(os.pathsep) if p] if override else ["", *known]
    out: list[str] = []
    for home in candidates:
        path = Path(home).expanduser() if home else default
        if not path.is_absolute() or not path.is_dir() or not own(path):
            continue
        key = "" if path == default else str(path)
        if key not in out:
            out.append(key)
    return out


def session_record(home: Path, pid: int, session_id: str) -> dict | None:
    """Claude Code's record of a running process, when it is the session the roster named. Not a documented
    interface (docs/design/attach-by-voice.md): read only to find the inbox socket, and checked."""
    path = home / "sessions" / f"{pid}.json"
    try:
        record = json.loads(path.read_text()) if own(path) else None
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("pid") != pid or record.get("sessionId") != session_id:
        return None
    return record


def usable_socket(path: str) -> bool:
    """A Unix socket of this user, not a link to one."""
    try:
        st = os.lstat(path)
    except (OSError, TypeError, ValueError):
        return False
    return stat.S_ISSOCK(st.st_mode) and st.st_uid == os.getuid()


def ours(pid: int) -> bool:
    """A live process this user may signal: another user's session is not listed."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def claude_transcript(home: Path, session_id: str, cwd: str) -> str:
    """Where Claude Code keeps the session's record: the file if it exists, else where it will appear (each character
    of the folder's path that is not a letter or digit becomes a dash)."""
    found = next((home / "projects").glob(f"*/{session_id}.jsonl"), None)
    if found:
        return str(found)
    return str(home / "projects" / re.sub(r"[^A-Za-z0-9]", "-", cwd) / f"{session_id}.jsonl")


def claude_open(home: Path, entries: list, home_key: str = "") -> list[Found]:
    """The sessions `claude agents --json` lists for an account, as Found records. One whose inbox socket cannot be
    found is listed, not joinable, with the reason."""
    out: list[Found] = []
    for e in entries:
        if not isinstance(e, dict) or e.get("kind") not in ("interactive", "background"):
            continue
        pid, sid, cwd = e.get("pid"), e.get("sessionId"), e.get("cwd")
        if not isinstance(pid, int) or not isinstance(sid, str) or not re.fullmatch(r"[\w-]{1,128}", sid) \
                or not isinstance(cwd, str) or not ours(pid):
            continue
        record = session_record(home, pid, sid) or {}
        sock = record.get("messagingSocketPath") if isinstance(record.get("messagingSocketPath"), str) else ""
        transcript = claude_transcript(home, sid, cwd)
        about = read_claude_transcript(transcript)
        name = str(e.get("name") or about["title"] or Path(cwd).name)
        started = float(e.get("startedAt") or 0) / 1000
        try:
            when = max(started, os.stat(transcript).st_mtime)
        except OSError:
            when = started
        found = Found(harness="claude-code", id=sid, name=name, cwd=cwd, state="open", when=when, title=about["title"],
                      branch=about["branch"], first=about["first"], last=about["last"], keywords=about["keywords"],
                      pid=pid, home=home_key, transcript=transcript, socket=sock if usable_socket(sock) else "",
                      kind=str(e.get("kind")), status=str(e.get("status") or ""),
                      name_given=record.get("nameSource") == "user")
        if not found.socket:
            found.joinable = False
            found.why = "Pointe cannot find how to type into it. Run /pointe:voice in that session."
        out.append(found)
    return out


def claude_recent(home: Path, since: float, skip: set[str], home_key: str = "", cap: int = CAP) -> list[Found]:
    """Closed sessions of an account: transcripts touched since `since`, newest first, at most `cap`. Sub-agent
    records and sessions in `skip` (open ones, ones on the voice) are left out."""
    files = []
    for path in (home / "projects").glob("*/*.jsonl"):
        if path.name.startswith("agent-") or path.stem in skip:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime >= since:
            files.append((mtime, path))
    out: list[Found] = []
    for mtime, path in sorted(files, reverse=True):
        about = read_claude_transcript(str(path))
        if not about["cwd"] or not (about["first"] or about["title"]):
            continue  # nothing the user said: a session that never had a turn
        found = Found(harness="claude-code", id=path.stem, name=about["title"] or Path(about["cwd"]).name,
                      cwd=about["cwd"], state="recent", when=mtime, title=about["title"], branch=about["branch"],
                      first=about["first"], last=about["last"], keywords=about["keywords"], home=home_key,
                      transcript=str(path), name_given=bool(about["title"]))
        if not os.path.isdir(found.cwd):
            found.joinable, found.why = False, "Its folder is no longer there."
        out.append(found)
        if len(out) >= cap:
            break
    return out


# ---------- does Pointe's PermissionRequest hook run in that session? ----------

def _pointe_enabled(path: Path) -> bool | None:
    try:
        plugins = json.loads(path.read_text()).get("enabledPlugins")
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(plugins, dict):
        return None
    values = [bool(v) for k, v in plugins.items() if isinstance(k, str) and k.split("@")[0] == "pointe"]
    return any(values) if values else None


def _plugin_dir_is_pointe(args: str) -> bool:
    for m in re.finditer(r"--plugin-dir[ =](\S+)", args):
        try:
            manifest = json.loads((Path(m.group(1)) / ".claude-plugin" / "plugin.json").read_text())
        except (OSError, ValueError):
            continue
        if isinstance(manifest, dict) and manifest.get("name") == "pointe":
            return True
    return False


def process_args(pid: int) -> str:
    """The command line of a process (visible to any user through ps; never its environment)."""
    if not pid:
        return ""
    try:
        return subprocess.run(["ps", "-o", "args=", "-p", str(pid)], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def hook_applies(home: Path, cwd: str, args: str, managed: Path) -> bool:
    """Whether the plugin's PermissionRequest hook runs in a Claude Code session, as far as can be seen from outside:
    `pointe@…` enabled in its settings, by Claude Code's precedence (managed, then the folder's local, then the
    folder's shared, then the account's), or `--plugin-dir` pointing at Pointe on its command line. A plugin enabled
    after the session started does not count there, and that cannot be seen: such a prompt stays in its terminal, and
    the roster tells the user so."""
    if _plugin_dir_is_pointe(args):
        return True
    folder = Path(cwd or ".") / ".claude"
    for path in (managed, folder / "settings.local.json", folder / "settings.json", home / "settings.json"):
        value = _pointe_enabled(path)
        if value is not None:
            return value
    return False


# ---------- spoken times ----------

def ago(when: float, now: float | None = None) -> str:
    """How long ago, in a few spoken words: "5 minutes ago", "from yesterday", "from Monday", "from 3 weeks ago"."""
    now = time.time() if now is None else now
    secs = max(0.0, now - when)
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{round(secs / 60)} minutes ago"
    today = time.localtime(now)
    day = time.localtime(when)
    days = (time.mktime((today.tm_year, today.tm_mon, today.tm_mday, 0, 0, 0, 0, 0, -1))
            - time.mktime((day.tm_year, day.tm_mon, day.tm_mday, 0, 0, 0, 0, 0, -1))) / 86400
    if days < 0.5:
        hours = round(secs / 3600)
        return "an hour ago" if hours <= 1 else f"{hours} hours ago"
    if days < 1.5:
        return "from yesterday"
    if days < 6.5:
        return "from " + time.strftime("%A", day)
    weeks = round(days / 7)
    return "from last week" if weeks <= 1 else f"from {weeks} weeks ago"
