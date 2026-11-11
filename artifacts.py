"""Show while it says: the files a turn edited or read and the test it ran, shown on screen while the voice reports.

Code is never read aloud (brain.speech_problem); it is shown instead. Three rules hold everything here:

- Only what ran. A tool use is recorded when its result arrives and was not refused: a tool still waiting for approval
  is the permission prompt's business, never shown here.
- Only inside the project, never anything secret-looking. `refused()` decides on the path; `render()` reads the file
  from disk again, under the session's folder after resolving symlinks, text only, capped in size.
- Secrets are masked in everything shown: file lines, the diff, test output and commands.

Diffs compare the working file with `HEAD` read by `git cat-file`, in Python: `git diff` would run a repository's own
clean filters and diff drivers, which are code.
"""

import difflib
import fnmatch
import os
import re
import subprocess
import time
from collections import deque
from pathlib import Path

from readout import _hidden

MAX_ARTIFACTS = 8
MAX_FILE_BYTES = 512 * 1024
OUTPUT_CAP = 4000
CONTEXT_LINES = 20
MAX_DIFF_CHARS = 64_000
NO_RANGE_LINES = 60  # a file shown without a range: its first lines
SHOWN_SECS = 60  # after the voice stops talking about it
KEEP_SETS = 10  # "Shown earlier", and what /voice/artifact can still render
GIT_TIMEOUT = 3.0

_EDITS = {"edit", "write", "multiedit", "notebookedit", "patch"}
_TEST = re.compile(r"(?:^|[\s;&|(/])(?:py\.?test|(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test\b|(?:\./)?nx\s+(?:run\s+\S+:)?test\b|"
                   r"go\s+test|cargo\s+(?:test|nextest)|jest|vitest|mocha|rspec|phpunit|tox|make\s+(?:test|check)\b|"
                   r"python3?\s+-m\s+unittest|swift\s+test|xcodebuild\s.*\btest\b|gradlew?\s+test|mvn\s+test|dotnet\s+test)")
_REFUSED_RESULT = re.compile(r"doesn't want to proceed|tool use was rejected|permission (?:to use \S+ )?(?:was )?denied|"
                             r"user (?:denied|rejected|declined)", re.I)
_FAILED = re.compile(r"\b\d+ (?:failed|failing|errors?)\b|\bFAILED\b|\bFAIL\b|--- FAIL|AssertionError|\bpanicked\b|"
                     r"npm ERR!|Tests?:\s+\d+ failed|\berror(?:\[E\d+\])?:|^E\s{2,}", re.M)
_FAIL_LINE = re.compile(r"AssertionError|^E\s{2,}|\bFAILED\b|--- FAIL|\bFAIL\b|\bfailing\b|panicked|Error:|\bfailed\b", re.M)
# Same idea as brain._UNSPEAKABLE: a file name with a known extension, maybe with folders.
_PATH = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*[\w-][\w.-]*\.(?:py|ts|tsx|js|jsx|mjs|cjs|go|rb|rs|java|kt|swift|c|h|cc|cpp|"
                   r"cs|php|json|yaml|yml|toml|sql|sh|md|html|css|scss|vue|svelte))\b")
# Secret-looking names (any folder or the file): the plan's list plus the usual credential stores.
_SECRET_NAMES = (".env*", "*.pem", "*secret*", "*key*", "id_*", "*credential*", "*password*", "*.p12", "*.pfx",
                 "*.keystore", "*.jks", "*.kdbx", "*.ovpn", ".netrc", ".npmrc", ".pgpass", "*.gpg", "*.asc")


# ---------- collecting a turn ----------

def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(c.get("text", "")) for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


def _path_of(tool_input: dict, cwd: str) -> str:
    raw = tool_input.get("file_path") or tool_input.get("filePath") or tool_input.get("notebook_path") or tool_input.get("path")
    if not raw or not isinstance(raw, str):
        return ""
    return os.path.normpath(os.path.join(cwd or "/", os.path.expanduser(raw)))


def _snippets(tool_input: dict) -> list[str]:
    edits = tool_input.get("edits") if isinstance(tool_input.get("edits"), list) else [tool_input]
    return [str(e.get("new_string") or e.get("newString") or "") for e in edits if isinstance(e, dict)
            and (e.get("new_string") or e.get("newString"))]


def tail(text: str, cap: int = OUTPUT_CAP) -> str:
    if len(text) <= cap:
        return text
    cut = text[-cap:]
    return cut.split("\n", 1)[1] if "\n" in cut[:200] else cut


class Turn:
    """What one turn of a session touched, from its transcript's tool blocks. Reset when the turn ends."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._waiting: dict[str, dict] = {}  # tool_use_id -> what it will be once its result arrives
        self.found: list[dict] = []

    def use(self, block: dict, cwd: str) -> None:
        name = str(block.get("name") or "").lower()
        tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
        drafts: list[dict] = []
        if name in _EDITS:
            files = tool_input.get("files") if isinstance(tool_input.get("files"), list) else None
            paths = [os.path.normpath(os.path.join(cwd or "/", str(p))) for p in files] if files else [_path_of(tool_input, cwd)]
            drafts = [{"kind": "edit", "path": p, "snippets": _snippets(tool_input),
                       "whole": name in ("write",)} for p in paths if p]
        elif name == "read":
            path = _path_of(tool_input, cwd)
            if path:
                rng = None
                if isinstance(tool_input.get("offset"), int) and tool_input["offset"] > 0:
                    start = tool_input["offset"]
                    limit = tool_input.get("limit") if isinstance(tool_input.get("limit"), int) and tool_input["limit"] > 0 else 40
                    rng = [start, start + limit - 1]
                drafts = [{"kind": "read", "path": path, "range": rng}]
        elif name in ("bash", "shell"):
            command = str(tool_input.get("command") or "")
            if _TEST.search(command):
                drafts = [{"kind": "test", "path": "", "command": command[:400]}]
        if not drafts:
            return
        tool_id = block.get("id")
        if tool_id:
            self._waiting[str(tool_id)] = {"drafts": drafts}
        elif name != "bash":  # a mirror writes a tool only once it finished; a test with no result has no output
            self.found.extend(drafts)

    def result(self, block: dict) -> None:
        waiting = self._waiting.pop(str(block.get("tool_use_id") or ""), None)
        if waiting is None:
            return
        text = _content_text(block.get("content"))
        if _REFUSED_RESULT.search(text[:600]):
            return
        for draft in waiting["drafts"]:
            if draft["kind"] == "test":
                draft["output"] = tail(text)
                draft["failed"] = bool(block.get("is_error")) or bool(_FAILED.search(draft["output"]))
            elif block.get("is_error"):
                continue  # an edit that did not apply, a read that failed
            self.found.append(draft)

    def finish(self, final: str, cwd: str) -> list[dict]:
        """The turn's artifacts, de-duplicated and ordered: failing tests, edited files, passing tests, read files."""
        found, self.found, self._waiting = self.found, [], {}
        now = time.time()
        known = {a["path"] for a in found if a.get("path")}
        for match in _PATH.finditer(final or ""):
            path = os.path.normpath(os.path.join(cwd or "/", match.group(1)))
            if path in known or not cwd:
                continue
            by_name = [p for p in known if Path(p).name == Path(path).name]
            if by_name:
                continue  # "pricing.py" in the message is the one it edited in a subfolder
            if os.path.isfile(path):
                found.append({"kind": "read", "path": path, "range": None})
                known.add(path)
        merged: dict[tuple, dict] = {}
        for a in found:
            key = ("test", a["command"]) if a["kind"] == "test" else ("file", a["path"])
            had = merged.get(key)
            if had is None:
                merged[key] = dict(a)
            elif a["kind"] == "test":
                merged[key] = dict(a)  # the latest run of the same command
            elif a["kind"] == "edit" or had["kind"] == "edit":
                had["kind"] = "edit"
                had["snippets"] = had.get("snippets", []) + a.get("snippets", [])
                had["whole"] = had.get("whole") or a.get("whole")
        out = list(merged.values())
        for a in out:
            a["at"] = now
            a.setdefault("failed", False)
            a.setdefault("range", None)
            if a["kind"] == "edit":
                a["range"] = _edited_range(a["path"], a.pop("snippets", []), a.pop("whole", False))
        rank = {"test": 0, "edit": 1, "read": 3}
        out.sort(key=lambda a: 0 if a["kind"] == "test" and a["failed"] else 2 if a["kind"] == "test" else rank[a["kind"]])
        return out[:MAX_ARTIFACTS]


def _read_text(path: str) -> str | None:
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None
        data = Path(path).read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _edited_range(path: str, snippets: list[str], whole: bool) -> list[int] | None:
    """The lines an edit's new text now occupies, or None (a new file, or text no longer there)."""
    if whole and not snippets:
        return None
    text = _read_text(path)
    if text is None:
        return None
    found: list[int] = []
    for snippet in snippets:
        at = text.find(snippet)
        if at < 0:
            continue
        first = text.count("\n", 0, at) + 1
        found += [first, first + snippet.rstrip("\n").count("\n")]
    return [min(found), max(found)] if found else None


# ---------- what may be shown ----------

def _real(path: str) -> str:
    return os.path.realpath(path)


def refused(path: str, cwd: str) -> str | None:
    """Why a path is never shown, or None. Outside the project (after symlinks), hidden, or secret-looking."""
    if not path or not cwd:
        return "no project folder: not shown"
    if _hidden(path):
        return "a name with hidden characters: not shown"
    root = _real(cwd)
    normal = os.path.normpath(path)
    real = _real(normal)  # a symlink is judged by where it leads
    if not real.startswith(root.rstrip(os.sep) + os.sep):
        return "outside the project: not shown"
    # Both spellings are checked: a link named "notes.py" may lead to ".env", and ".env" may be a link to "notes.py".
    parts = Path(os.path.relpath(real, root)).parts + Path(os.path.relpath(normal, os.path.normpath(cwd))).parts
    for part in parts:
        low = part.lower()
        if part.startswith(".") and part not in (".", ".."):
            return "a hidden file: not shown"
        if any(fnmatch.fnmatch(low, pattern) for pattern in _SECRET_NAMES):
            return "a secret-looking name: not shown"
    return None


_MASK = "••••••"
_SECRET_SHAPES = [
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)"),
    re.compile(r"\b(?:sk|rk|pk)[-_](?:live|test|ant|proj|or)?[-_]?[A-Za-z0-9_-]{12,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b|\bgithub_pat_\w{20,}"),
    re.compile(r"\bxox[abprs]-[\w-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}"),
    re.compile(r"\bglpat-[\w-]{16,}"),
]
_URL_PASSWORD = re.compile(r"(://[^:/\s@]+:)([^@\s/]+)(@)")
_NAMED = (r"[\w.-]*(?:secret|token|passw(?:or)?d|pwd|api[_-]?key|apikey|access[_-]?key|private[_-]?key|auth[_-]?key|"
          r"credential|client[_-]?secret)[\w.-]*")
_ASSIGNED_QUOTED = re.compile(rf"(?i)(\b{_NAMED}\b[\"']?\s*(?:[:=]|=>|:=)\s*)([\"'])([^\"'\n]{{4,}})\2")
_ASSIGNED_ENV = re.compile(rf"(?im)^(\s*(?:export\s+)?{_NAMED}\s*=\s*)([^\s\"'#]{{4,}})")
_ASSIGNED_INLINE = re.compile(rf"(?i)(\b{_NAMED}=)([^\s\"';|&]{{4,}})")
_FLAG_VALUE = re.compile(r"(?i)(--?(?:token|password|passwd|secret|api-?key|key)[= ])([^\s\"']{4,})")


def _live_values() -> list[str]:
    """The values of this machine's own secrets, wherever they appear."""
    try:
        import vendors
        names = set(vendors.KEY_ENVS)
    except Exception:
        names = set()
    names |= {k for k in os.environ if re.search(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", k, re.I)}
    return sorted({v for k in names if len(v := os.environ.get(k, "")) >= 8}, key=len, reverse=True)


def mask(text: str) -> str:
    """Secret-looking values replaced. Errs on the side of hiding: a masked string in code costs nothing."""
    if not text:
        return text
    for value in _live_values():
        text = text.replace(value, _MASK)
    for shape in _SECRET_SHAPES:
        text = shape.sub(_MASK, text)
    text = _URL_PASSWORD.sub(lambda m: m.group(1) + _MASK + m.group(3), text)
    text = _ASSIGNED_QUOTED.sub(lambda m: f"{m.group(1)}{m.group(2)}{_MASK}{m.group(2)}", text)
    text = _ASSIGNED_ENV.sub(lambda m: m.group(1) + _MASK, text)
    text = _ASSIGNED_INLINE.sub(lambda m: m.group(1) + _MASK, text)
    return _FLAG_VALUE.sub(lambda m: m.group(1) + _MASK, text)


def safe_command(command: str) -> str:
    if _hidden(command):
        return "a command with hidden characters (not shown)"
    return mask(command)


# ---------- rendering ----------

def _git(cwd: str, *args: str) -> subprocess.CompletedProcess:
    """A repo's own config can run code (core.fsmonitor), and any folder may register: that code gets no keys."""
    try:
        import vendors
        strip = set(vendors.KEY_ENVS)
    except Exception:
        strip = set()
    env = {k: v for k, v in os.environ.items() if k not in strip and not k.startswith("GIT_")}
    return subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", "core.quotepath=false", *args], cwd=cwd, env=env,
                          capture_output=True, timeout=GIT_TIMEOUT)


def _diff(path: str, cwd: str, now_text: str) -> str | None:
    """The file against HEAD, or None when it is not in a repository."""
    folder = os.path.dirname(path)
    try:
        inside = _git(folder, "rev-parse", "--is-inside-work-tree")
        if inside.returncode != 0 or inside.stdout.strip() != b"true":
            return None
        old = _git(folder, "cat-file", "blob", f"HEAD:./{os.path.basename(path)}")
    except (OSError, subprocess.SubprocessError):
        return None
    before = ""
    if old.returncode == 0:
        if b"\0" in old.stdout[:8192]:
            return None
        before = old.stdout.decode("utf-8", "replace")
    name = os.path.relpath(path, cwd)
    lines = difflib.unified_diff(before.splitlines(), now_text.splitlines(), f"a/{name}" if old.returncode == 0 else "/dev/null",
                                 f"b/{name}", lineterm="", n=3)
    return "\n".join(lines)


def _size(path: str) -> str:
    try:
        return f"{max(1, round(os.path.getsize(path) / 1024))} kB"
    except OSError:
        return "unknown size"


def _public(a: dict, cwd: str) -> dict:
    out = {"id": a.get("id", ""), "kind": a["kind"], "range": a.get("range"), "failed": bool(a.get("failed"))}
    if a["kind"] == "test":
        out.update(name="test output", path="")
    else:
        problem = refused(a["path"], cwd)
        rel = os.path.relpath(a["path"], cwd) if cwd and not (problem or "").startswith("outside") else a["path"]
        out.update(name=Path(a["path"]).name if not _hidden(a["path"]) else "(hidden name)",
                   path=rel if not _hidden(rel) else "(hidden name)")
        if problem:
            out["refused"] = problem
    return out


def render(a: dict, cwd: str) -> dict:
    """What the page and the app show for one artifact: file lines at the range, the diff, or the test output."""
    view = _public(a, cwd)
    if a["kind"] == "test":
        output = mask(a.get("output", ""))
        lines = output.splitlines()
        focus = next((i for i, line in enumerate(lines) if _FAIL_LINE.search(line)), max(0, len(lines) - 1)) if lines else 0
        if a.get("failed"):  # the first assertion, not the summary line, when there is one
            focus = next((i for i, line in enumerate(lines) if re.search(r"AssertionError|^E\s{2,}|assert ", line)), focus)
        view.update(command=safe_command(a.get("command", "")), output=output, focus=focus,
                    truncated=len(a.get("output", "")) >= OUTPUT_CAP - 200)
        return view
    if view.get("refused"):
        view["problem"] = view.pop("refused")
        return view
    path = a["path"]
    if not os.path.isfile(path):
        view["problem"] = "no longer there"
        return view
    text = _read_text(path)
    if text is None:
        size = _size(path)
        view["problem"] = (f"too large to show ({size})" if os.path.getsize(path) > MAX_FILE_BYTES
                           else f"binary: not shown ({size})")
        return view
    lines = text.splitlines()
    rng = a.get("range")
    if rng:
        first, last = max(1, rng[0]), max(rng[0], rng[1])
        start, end = max(1, first - CONTEXT_LINES), min(len(lines), last + CONTEXT_LINES)
    else:
        first, last = 0, -1
        start, end = 1, min(len(lines), NO_RANGE_LINES)
    view["lines"] = [{"n": n, "text": mask(lines[n - 1]), "hl": first <= n <= last} for n in range(start, end + 1)]
    view["total"] = len(lines)
    view["truncated"] = end < len(lines) or start > 1
    try:
        view["changed_since"] = os.path.getmtime(path) > a.get("at", 0) + 1
    except OSError:
        view["changed_since"] = False
    if a["kind"] == "edit":
        diff = _diff(path, cwd, text)
        if diff is not None:
            diff = mask(diff)
            view["diff"] = diff[:MAX_DIFF_CHARS]
            view["truncated_diff"] = len(diff) > MAX_DIFF_CHARS
    return view


# ---------- what the voice says and which one is current ----------

def _stem_words(path: str) -> list[str]:
    stem = Path(path).stem.lower()
    words = " ".join(w for w in re.split(r"[_\-.\s]+", stem) if w)
    plain = re.sub(r"^(?:test )|(?: test|spec)$", "", words).strip()
    return [w for w in {words, plain} if len(w) >= 3]


def pick_current(arts: list[dict], spoken: str) -> int:
    """The artifact the voice named last; the first one until it names any."""
    said = re.sub(r"[_\-]+", " ", spoken.lower())
    best, where = 0, -1
    for i, a in enumerate(arts):
        if a["kind"] == "test":
            hits = [m.start() for m in re.finditer(r"\btests?\b|\bfail", said)]
        else:
            hits = [m.start() for w in _stem_words(a["path"]) for m in re.finditer(rf"\b{re.escape(w)}", said)]
        if hits and max(hits) > where:
            best, where = i, max(hits)
    return best


def label(arts: list[dict]) -> str:
    """For the voice: "the failing test output, pricing.py lines 40–62"."""
    parts = []
    for a in arts:
        if a["kind"] == "test":
            parts.append("the failing test output" if a.get("failed") else "the test output")
        elif a.get("path") and not _hidden(a["path"]):
            rng = a.get("range")
            parts.append(Path(a["path"]).name + (f" lines {rng[0]}–{rng[1]}" if rng and rng[1] > rng[0]
                                                  else f" line {rng[0]}" if rng else ""))
    return ", ".join(parts)


def summary(arts: list[dict]) -> str:
    """For a card: "pricing.py · edited 40–62 · 1 failing test"."""
    edits = [a for a in arts if a["kind"] == "edit"]
    parts = []
    if edits:
        rng = edits[0].get("range")
        parts += [Path(edits[0]["path"]).name, f"edited {rng[0]}–{rng[1]}" if rng else "edited"]
        if len(edits) > 1:
            parts.append(f"+{len(edits) - 1} more")
    failing = sum(1 for a in arts if a["kind"] == "test" and a.get("failed"))
    if failing:
        parts.append(f"{failing} failing test" + ("s" if failing > 1 else ""))
    elif any(a["kind"] == "test" for a in arts):
        parts.append("tests ran")
    if not parts:
        parts.append(Path(arts[0]["path"]).name if arts and arts[0].get("path") else "")
    return " · ".join(p for p in parts if p)


class Shows:
    """What is on screen now, and the last few sets shown, so the page and the app can fetch an artifact by id."""

    def __init__(self) -> None:
        self._offered: dict[str, tuple[str, str, list[dict]]] = {}  # report text -> (session, cwd, artifacts)
        self.sets: deque = deque(maxlen=KEEP_SETS)  # {id, session, cwd, artifacts, at, summary}
        self.now: dict | None = None  # the set on screen: the newest of `sets`, while it lasts
        self.spoken = ""
        self.last_at = 0.0
        self._next = 0
        self._seen: dict[str, float] = {}  # "page" / "phone": when that client last asked for status

    def watched(self, who: str, now: float) -> None:
        self._seen[who] = now

    def watching(self, who: str, now: float, within: float = 5.0) -> bool:
        return now - self._seen.get(who, 0.0) < within

    def offer(self, text: str, session: str, cwd: str, arts: list[dict]) -> None:
        """A report that will be spoken: when it is, these go on screen."""
        if not arts:
            return
        self._offered[text] = (session, cwd, arts)
        while len(self._offered) > 20:
            self._offered.pop(next(iter(self._offered)))

    def on_respond(self, text: str, now: float | None = None) -> bool:
        offered = self._offered.pop(text, None)
        if offered is None:
            return False
        session, cwd, arts = offered
        self._next += 1
        set_id = f"s{self._next}"
        shown = [{**a, "id": f"{set_id}a{i}"} for i, a in enumerate(arts)]
        entry = {"id": set_id, "session": session, "cwd": cwd, "artifacts": shown, "at": now or time.time(),
                 "summary": summary(shown)}
        self.sets.append(entry)
        self.now, self.spoken, self.last_at = entry, "", entry["at"]
        return True

    def heard(self, text: str, now: float | None = None) -> None:
        if self.now is not None:
            self.spoken = (self.spoken + text)[-4000:]
            self.last_at = now or time.time()

    def clear(self) -> None:
        self.now, self.spoken = None, ""

    def view(self, now: float, speaking: bool) -> dict | None:
        if self.now is None:
            return None
        if not speaking and now - self.last_at > SHOWN_SECS:
            return None
        arts = self.now["artifacts"]
        return {"id": self.now["id"], "session": self.now["session"], "since": self.now["at"], "summary": self.now["summary"],
                "current": arts[pick_current(arts, self.spoken)]["id"],
                "artifacts": [_public(a, self.now["cwd"]) for a in arts]}

    def earlier(self) -> list[dict]:
        return [{"id": s["id"], "session": s["session"], "at": s["at"], "summary": s["summary"],
                 "artifacts": [_public(a, s["cwd"]) for a in s["artifacts"]]} for s in reversed(self.sets)]

    def find(self, artifact_id: str) -> tuple[dict, str] | None:
        for s in self.sets:
            for a in s["artifacts"]:
                if a["id"] == artifact_id:
                    return a, s["cwd"]
        return None
