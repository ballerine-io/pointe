"""Drive & walk mode: short answers, no screen, and voice approvals only for what is safe to approve from the road.

The mode narrows plain conversation and never widens it (modes.DRIVE, tested with modes.narrows). A spoken yes approves
a request in drive mode only when every rule below holds, on top of every rule that already binds a yes (a bound yes to
that exact request, begun after the daemon's own read-out ended, within its window, nothing else said, never typed,
never the bot's own words heard back):

1. The read-out allowlist can say it whole (guards.readable_request): readout.redact withholds anything that looks
   like a credential, so such a request is never read out and waits for a tap.
2. It is not destructive (road_safe below, an allowlist of its own): deleting, moving, overwriting, force-pushing,
   rewriting history, sending data, or writing outside the project waits for a tap.
3. With a voiceprint stored, the yes itself is a strong owner match (speaker.strong), at any lock level, Off included.
   A weaker match, or the lock unable to score, counts as not the owner.

A no counts from any voice, as everywhere. A tap on the page or in the app answers any request, as always (a passenger,
or the owner parked). The mode is entered only by the user (a phrase or a button) and leaves when the call ends: at
once on a hang-up or the idle timer, and after DROP_GRACE_SECS when the link drops (a tunnel), unless the call came back.
"""

import os
import re
import shlex
import time

import readout

DROP_GRACE_SECS = 5 * 60  # a dropped link (a tunnel) keeps the mode this long; a hang-up ends it at once
MAX_WORDS = 25  # a reply longer than this is sent back: "Shorter: they are driving"

RULES = ("Drive mode: the user is driving or walking and cannot look at a screen. Twenty words at most, one thing at a "
         "time, no lists, never refer to the screen, the page or the app. A report is one line.")

# ---------- what may be approved from the road ----------

# Programs that only read, or that add without losing anything. Everything not here waits for a tap.
_READS = {"ls", "cat", "head", "tail", "wc", "grep", "rg", "pwd", "cd", "echo", "sort", "uniq", "diff", "which", "sleep",
          "date", "sed", "pytest", "mkdir", "touch", "python", "python3"}
_SUBS = {
    "git": {"status", "diff", "log", "show", "blame", "rev-parse", "fetch", "pull", "add", "commit", "push"},
    "go": {"test", "vet", "build"}, "cargo": {"test", "build", "check", "clippy"},
    "npm": {"test"}, "pnpm": {"test"}, "yarn": {"test"}, "kubectl": {"get", "describe", "logs"},
}
# Flags that lose work, rewrite history, skip the safety hooks, or send data: never by voice from the road.
_GIT_REFUSED = {
    "push": {"--force", "-f", "--force-with-lease", "--force-if-includes", "--delete", "-d", "--mirror", "--prune",
             "--all", "--tags", "--no-verify"},
    "pull": {"--rebase", "-r", "--force", "-f"}, "fetch": {"--force", "-f", "--prune", "-p"},
    "commit": {"--amend", "--no-verify", "-n"},
    "add": {"--force", "-f"},  # -f adds what .gitignore keeps out, where secrets live; push would then publish it
}
# Options before the subcommand (-c config, -C dir, --git-dir), aliases, abbreviated (--forc) and bundled (-Af) flags
# never reach this check: none is in _SUBS["git"] or in readout's exact-token flag list, so they are never read out.
_CURL_REFUSED = {"-X", "--request", "-d", "--data", "--data-binary", "--data-raw", "--data-urlencode", "--json", "-o", "-O",
                 "--output", "-T", "--upload-file", "-F", "--form", "-K", "--config"}
_GIT_RUNS = {"--upload-pack", "--receive-pack", "--exec", "-c"}  # run a program or set config: refused on every subcommand
_ONE_FILE = {"uniq"}  # a second positional is the file it writes
_FILE_TOOLS = {"Edit", "MultiEdit", "NotebookEdit", "Write"}


def _inside(path: str, cwd: str | None) -> bool:
    """Plainly inside the project, through no hidden folder (.git/hooks runs code) and no node_modules."""
    if not cwd or not path or ":" in path or "@" in path:
        return False
    root = os.path.realpath(cwd)
    full = os.path.realpath(os.path.join(root, os.path.expanduser(path)))
    rel = os.path.relpath(full, root)
    if rel == "." or rel.startswith(".."):
        return False
    return not any(p.startswith(".") or p == "node_modules" for p in rel.split(os.sep))


def _segments(command: str) -> list[list[str]] | None:
    """The simple commands of a pipeline or list, or None when anything writes through a redirect."""
    command = readout._TRIM.sub("", readout._QUIET.sub(" ", command))
    lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;<>")
    lexer.whitespace_split, lexer.commenters = True, ""
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    segments, current = [], []
    for token in tokens:
        if token in ("|", "&&", ";", "||"):
            segments.append(current)
            current = []
        elif token in (">", ">>") or re.fullmatch(r"[|&;<>]+", token) and token != "<":
            return None  # a redirect overwrites or appends to a file
        else:
            current.append(token)
    segments.append(current)
    return segments


def _flags_known(program: str, sub: str | None, args: list[str]) -> bool:
    """Every flag is one the read-out's own table knows for this program (readout._flag): an allowlist, so a flag nobody
    listed waits for a tap. The value a known flag takes is skipped, as the read-out skips it."""
    skip = False
    for word in args:
        if skip:
            skip = False
            continue
        if not word.startswith("-") or word == "-":
            continue
        if word.split("=", 1)[0] in (_GIT_RUNS if program == "git" else ()):
            return False
        known = readout._flag(program, sub, word, lambda path: path) if program in readout._PROGRAMS or program == "git" else None
        if known is None:
            return False
        skip = known[1] is not None
    return True


def _command_safe(words: list[str]) -> bool:
    while words and re.fullmatch(r"[A-Za-z_]\w*=\S*", words[0]):
        words = words[1:]  # "CI=1 pytest": readout already allowed only harmless variables
    if not words:
        return False
    if words[0] == "uv":  # uv run pytest
        words = words[2:] if words[1:2] == ["run"] else []
        if not words:
            return False
    program = words[0]
    if program in ("python", "python3"):  # readout allows only "python -m pytest"
        return words[1:3] == ["-m", "pytest"] and _flags_known("pytest", None, words[3:])
    if program == "curl":
        return not any(w.split("=", 1)[0] in _CURL_REFUSED for w in words[1:]) and _flags_known("curl", None, words[1:])
    if program in ("echo", "sed"):
        return True  # echo only prints (a redirect never gets here); the read-out allows sed only as "sed -n 'Np' file"
    if program in _READS:
        if program in _ONE_FILE and len([w for w in words[1:] if not w.startswith("-") or w == "-"]) > 1:
            return False  # uniq in out: out is overwritten
        return _flags_known(program, None, words[1:])
    if program not in _SUBS or len(words) < 2 or words[1] not in _SUBS[program]:
        return False  # rm, mv, cp, make, gh, git reset/clean/rebase/checkout/stash..., npm run/install
    if program != "git":
        return _flags_known(program, words[1], words[2:])
    sub, rest = words[1], words[2:]
    if not _flags_known("git", sub, rest):
        return False
    if any(w.split("=", 1)[0] in _GIT_REFUSED.get(sub, ()) for w in rest):
        return False
    if sub == "push" and any(w.startswith("+") or ":" in w for w in rest if not w.startswith("-")):
        return False  # +main force-pushes, :main deletes the remote branch
    return True


def road_safe(tool: str, tool_input: dict, cwd: str | None, remote: bool = False) -> bool:
    """May a spoken yes approve this from the road? Only for requests the read-out allowlist can say whole; this narrows
    that further to what loses nothing. Fails closed: anything unknown is not road safe. `remote`: the session runs on
    a node, so its folder cannot be resolved on this disk (_inside follows symlinks here): a file tool is not road safe."""
    if not isinstance(tool_input, dict):
        return False
    if tool == "Bash":
        command = str(tool_input.get("command") or "")
        if not command.strip() or readout.spoken(command, cwd) is None:
            return False
        segments = _segments(command)
        return bool(segments) and all(_command_safe(list(s)) for s in segments)
    if tool == "Read":
        return True
    if tool in _FILE_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        return not remote and isinstance(path, str) and _inside(path, cwd)
    return False


# ---------- the mode ----------

class Drive:
    """The mode's state, owned by the daemon and shown to both clients through /voice/status."""

    def __init__(self) -> None:
        self.since: float | None = None
        self.dropped_at: float | None = None
        self.how = ""  # "voice" | "button"
        self.road: dict[str, bool] = {}  # request id -> road safe; a request not noted here is not (fail closed)

    def on(self, now: float | None = None) -> bool:
        if self.since is None:
            return False
        if self.dropped_at is not None and (now or time.time()) - self.dropped_at >= DROP_GRACE_SECS:
            self.leave()  # the call did not come back: it ended
            return False
        return True

    def enter(self, how: str, now: float | None = None) -> bool:
        """True when this turned it on."""
        if self.on(now):
            return False
        self.since, self.dropped_at, self.how = now or time.time(), None, how
        return True

    def leave(self) -> bool:
        was = self.since is not None
        self.since, self.dropped_at, self.how = None, None, ""
        return was

    def dropped(self, now: float | None = None) -> None:
        if self.since is not None and self.dropped_at is None:
            self.dropped_at = now or time.time()

    def reconnected(self, now: float | None = None) -> None:
        if self.on(now):
            self.dropped_at = None

    def note(self, request_id: str, tool: str, tool_input, cwd: str | None, remote: bool = False) -> None:
        self.road[request_id] = road_safe(tool, tool_input, cwd, remote)
        while len(self.road) > 50:
            self.road.pop(next(iter(self.road)))

    def is_road_safe(self, request_id: str | None) -> bool:
        return bool(request_id) and self.road.get(request_id, False)

    def status(self, now: float | None = None) -> dict:
        return {"on": self.on(now), "since": self.since, "how": self.how,
                "dropped_at": self.dropped_at if self.since is not None else None}


# ---------- what is said ----------

_ON = re.compile(r"^\W*(?:(?:ok(?:ay)?|so|hey|pointe)\W+)?(?:(?:switch\s+to|start|turn\s+on|enter)\s+)?"
                 r"(?:drive|driving|walk|walking|car)\s+mode(?:\s+on)?\W*$|^\W*(?:I'?m|I\s+am)\s+(?:driving|walking)\W*$"
                 r"|^\W*(?:מצב\s+(?:נהיגה|הליכה)|אני\s+(?:נוהג|נוהגת|הולך|הולכת))\W*$", re.I)
_OFF = re.compile(r"^\W*(?:(?:ok(?:ay)?|so|hey|pointe)\W+)?(?:back\s+to\s+normal(?:\s+mode)?|normal\s+mode|"
                  r"(?:exit|leave|stop|end|turn\s+off)\s+(?:drive|driving|walk|walking|car)\s+mode|"
                  r"(?:drive|driving|walk|walking|car)\s+mode\s+off|I'?ve\s+stopped|I\s+have\s+stopped|I'?m\s+parked)\W*$"
                  r"|^\W*(?:חזרה\s+לרגיל|חזור\s+לרגיל|מצב\s+רגיל|צא\s+ממצב\s+(?:נהיגה|הליכה)|עצרתי|חניתי)\W*$", re.I)


def intent(text: str) -> str | None:
    """"drive mode" -> "on", "back to normal" -> "off": a whole short utterance, or None."""
    text = text.strip()
    if len(text.split()) > 7:
        return None
    if _OFF.match(text):
        return "off"
    if _ON.match(text):
        return "on"
    return None


def entered(hebrew) -> str:
    return ("מצב נהיגה. תשובות קצרות, ואאשר בקול רק מה שאפשר להקריא בבטחה." if hebrew else
            "Drive mode. Short answers, and I'll only approve by voice what's safe to read out.")


def left(hebrew) -> str:
    return "חזרה לרגיל." if hebrew else "Back to normal."


def waits_unreadable(name: str, hebrew) -> str:
    return (f"{name} צריך אישור שאני לא יכול להקריא. הוא ממתין עד שתעצור, או אמור לא." if hebrew else
            f"{name} needs an approval I can't read out. It waits until you stop, or say no.")


def waits_not_for_the_road(name: str, spoken: str, hebrew) -> str:
    return (f"{name} מבקש: {spoken}. את זה לא אאשר בזמן נהיגה. זה ממתין עד שתעצור, או אמור לא." if hebrew else
            f"{name} wants to {spoken}. I won't approve that while you drive. It waits until you stop, or say no.")


def unsure(hebrew) -> str:
    # No consent word in it: the bot's own voice heard back must never sound like an answer.
    return ("לא הייתי בטוח שזה אתה. ענה במשפט שלם וארוך יותר. " if hebrew else
            "I couldn't be sure that was you. Answer in a longer, full sentence. ")


def length_problem(said: str) -> str | None:
    return "Shorter: they are driving. Twenty words at most." if len(said.split()) > MAX_WORDS else None
