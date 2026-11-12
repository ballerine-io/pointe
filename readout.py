"""What a spoken yes approves: a shell command in short form, or nothing.

An allowlist, by design. Bash is too rich to describe by listing what is dangerous (a review found 13 ways around that):
here only known programs, with known flags, in plain pipelines, are said. Anything else is approved in the terminal.
Said: every program, every file written, every redirect target, every URL, and the flags that change what is lost.
Dropped: flags that only change output, and paths shortened to their name when they sit plainly inside the project.
"""

import os
import re
from urllib.parse import urlparse
import shlex
import unicodedata

WORDS = 25  # about ten seconds of speech

# program -> (flags that are dropped, flags that are said, flags whose value is said, flags whose value is dropped)
_GREP_SAFE = set("-n -i -l -L -c -v -w -x -o -h -H -s -q -E -F -r -R -I -m -A -B -C --color=never".split())
_PROGRAMS: dict[str, tuple[set, set, set, set]] = {
    "ls": (set("-l -a -la -al -lh -lah -1 -R -t -S -d -F -h".split()), set(), set(), set()),
    "cat": (set("-n".split()), set(), set(), set()),
    "head": (set(), set(), set(), set("-n -c".split())),
    "tail": (set("-f".split()), set(), set(), set("-n -c".split())),
    "wc": (set("-l -w -c -m".split()), set(), set(), set()),
    "grep": (_GREP_SAFE, set(), set(), set("-e -m -A -B -C --include --exclude --exclude-dir".split())),
    "rg": (set("-n -i -l -c -v -w -F -S --hidden -uu -u --files".split()), set(), set(), set("-g -t -e -A -B -C --glob --type".split())),
    "pwd": (set(), set(), set(), set()),
    "cd": (set(), set(), set(), set()),
    "echo": (set("-n".split()), set(), set(), set()),
    "mkdir": (set("-p".split()), set(), set(), set()),
    "touch": (set(), set(), set(), set()),
    "rm": (set(), set("-r -R -f -rf -fr -Rf -fR -d -i".split()), set(), set()),
    "rmdir": (set(), set(), set(), set()),
    "cp": (set("-p".split()), set("-r -R -f -rf -a -n".split()), set(), set()),
    "mv": (set(), set("-f -n".split()), set(), set()),
    "sort": (set("-u -n -r -k".split()), set(), set(), set()),
    "uniq": (set("-c".split()), set(), set(), set()),
    "diff": (set("-u -r -q".split()), set(), set(), set()),
    "which": (set(), set(), set(), set()),
    "make": (set(), set(), set(), set()),
    "pytest": (set("-q -x -v -s --tb=short --tb=no -vv".split()), set(), set(), set("-k -m".split())),
    "go": (set("-v -race".split()), set(), set(), set("-run".split())),
    "cargo": (set("--release -q".split()), set(), set(), set()),
    "sleep": (set(), set(), set(), set()),
    "date": (set(), set(), set(), set()),
    "curl": (set("-s -S -f -L -sS -fsSL -sSL -I -i -v".split()), set("-X --data -d".split()), set("-o -O --output".split()), set()),  # -H can read a file (@file): unknown, so refused
}
_SUBCOMMANDS = {
    "git": {"status", "diff", "log", "show", "add", "commit", "push", "pull", "fetch", "checkout", "switch", "branch",
            "restore", "stash", "rebase", "merge", "reset", "clean", "rm", "mv", "tag", "blame", "rev-parse"},
    "npm": {"test", "run", "install", "ci", "ls"}, "pnpm": {"test", "run", "install", "ls"}, "yarn": {"test", "run", "install"},
    "go": {"test", "build", "vet"}, "cargo": {"test", "build", "check", "clippy"},
    "gh": {"pr", "run", "issue"}, "kubectl": {"get", "describe", "logs"},
}
_GIT_QUIET = set("-q --oneline --stat -p --name-only --name-status --short -s -b --cached --staged --graph --decorate "
                 "--porcelain --no-pager".split())  # only change what is printed
_GIT_QUIET_BY_SUB = {"log": {"-n", "--format", "--pretty", "--author", "--since", "--until"}, "show": {"--format", "--pretty"},
                     "commit": {"-m"}, "tag": {"-m"}}  # flags whose value is dropped, for that subcommand only
_GIT_SAID_BY_SUB = {
    "commit": {"-a", "-n", "--no-verify", "--amend", "--all"},
    "push": {"--force", "-f", "--force-with-lease", "--all", "--mirror", "--tags", "--delete", "-d", "--no-verify", "-u",
             "--set-upstream", "--prune"},
    "branch": {"-d", "-D", "-m", "-M", "-f", "--force", "--delete"},
    "reset": {"--hard", "--soft", "--mixed"}, "clean": {"-f", "-d", "-x", "-X", "-n", "--force"},
    "checkout": {"-f", "--force", "-b", "-B"}, "switch": {"-c", "-C", "-f", "--force", "--discard-changes"},
    "stash": set(), "rebase": {"--onto", "-i"}, "merge": {"--no-verify", "--squash"}, "add": {"-A", "--all", "-f", "-u"},
    "rm": {"-r", "-f", "--cached"}, "restore": {"--staged", "--source", "-s", "--worktree"}, "tag": {"-d", "-f"},
    "pull": {"--rebase", "--force"}, "fetch": {"--prune", "--force", "--all"},
}
_GIT_REMOTE = {"push", "pull", "fetch"}  # their arguments name remotes and refs: said whole, never shortened
_SAFE_VARIABLES = {"CI", "NODE_ENV", "DEBUG", "TZ", "LANG", "LC_ALL", "NO_COLOR", "FORCE_COLOR", "TERM"}
_JOIN = {"|": "into", "&&": "then", ";": "then", "||": "or else"}
_REDIRECT = {">": "writing to", ">>": "appending to", "<": "reading"}
_WORD = re.compile(r"~?[\w@%+=:,./-]+")  # a literal word: no glob, brace, quote, variable or substitution
_QUIET = re.compile(r"\s+2>\s*/dev/null|\s+2>&1(?=\s|$|[;|&])")
# Showing only the end or the start of the output changes nothing: "pytest -q 2>&1 | tail -15" is said "pytest".
_TRIM = re.compile(r"\s*\|\s*(?:tail|head)(?:\s+-n\s*\d+|\s+-\d+)?(?=\s*(?:$|&&|;|\|\|))")


_CREDENTIAL = re.compile(
    r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"          # OpenAI, Stripe and the like
    r"|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}"              # Slack
    r"|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}"   # AWS, Google
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)\s*[=:]"
    r"|\bbearer\s+\S+"
    r"|(?=[A-Za-z0-9+=]*\d)(?=[A-Za-z0-9+=]*[A-Za-z])[A-Za-z0-9+=]{32,}",  # letters and digits run together: a key or a hash
    re.IGNORECASE)


def redact(text: str) -> str | None:
    """The text, or None when it carries a credential-like value (a key, a token, a password=...). Withheld whole, never
    masked: a masked command approved by ear approves a value nobody heard, so such a request goes to a tap, as any
    request that cannot be read out does. The one rule for what is said aloud and what a notification shows."""
    return None if _CREDENTIAL.search(text or "") else text


def _hidden(text: str) -> bool:
    if unicodedata.normalize("NFKC", text) != text:
        return True
    return any(unicodedata.category(c).startswith("C") or unicodedata.name(c, "").startswith(("CYRILLIC", "GREEK"))
               for c in text)


def place(path: str, cwd: str | None) -> str:
    """Plainly inside the project: its name. Anywhere else, or through a hidden folder: the whole path."""
    if ":" in path or "@" in path:
        return path  # host:path is another machine
    full = os.path.normpath(os.path.join(cwd or "/", os.path.expanduser(path))) if cwd else None
    if not full or not cwd:
        return path
    inside = os.path.relpath(full, cwd)
    if inside.startswith("..") or path.startswith(("~", "/")) and not full.startswith(cwd.rstrip("/") + "/"):
        return full if not path.startswith("~") else path
    parts = inside.split(os.sep)
    if any(p.startswith(".") and p not in (".", "..") or p == "node_modules" for p in parts):
        return inside  # .git/hooks/x and node_modules/.bin/x run code: say where
    return parts[-1] if inside != "." else "."


def _flag(program: str, sub: str | None, token: str, at) -> tuple[str, str | None] | None:
    """(what to say, what to do with the next word: "drop", "say" or None) for a known flag; None for an unknown one."""
    name, _, value = token.partition("=")
    if program == "git":
        if token in _GIT_QUIET or sub == "log" and re.fullmatch(r"-\d+", token):
            return "", None
        if name in _GIT_QUIET_BY_SUB.get(sub or "", ()):
            return "", None if value else "drop"
        if token in _GIT_SAID_BY_SUB.get(sub or "", ()):
            return token, None
        return None
    safe, said, value_said, value_dropped = _PROGRAMS[program]
    if token in safe or program in ("head", "tail") and re.fullmatch(r"-\d+", token):
        return "", None
    if token in said or name in said:
        return token, None
    if name in value_said:
        return (f"{name} {at(value)}", None) if value else (name, "say")
    if name in value_dropped:
        return "", None if value else "drop"
    letters = re.fullmatch(r"-([a-zA-Z]{2,})", token)  # -rn is -r and -n
    if letters and all(f"-{c}" in safe | said for c in letters[1]):
        return (token if any(f"-{c}" in said for c in letters[1]) else ""), None
    attached = re.fullmatch(r"(-[oO])(.+)", token)
    if attached and "-o" in value_said:
        return f"{attached[1]} {at(attached[2])}", None
    return None


def spoken(command: str, cwd: str | None) -> str | None:
    if not command.strip() or _hidden(command) or "\n" in command.strip() or "\r" in command:
        return None
    command = _TRIM.sub("", _QUIET.sub(" ", command))
    lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;<>")
    lexer.whitespace_split, lexer.commenters = True, ""
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    raw = shlex.shlex(command, posix=False, punctuation_chars="|&;<>")
    raw.whitespace_split, raw.commenters = True, ""
    try:
        raws = list(raw)
    except ValueError:
        return None
    if len(raws) != len(tokens) or re.search(r"\d[<>]", command):
        return None
    quoted = []
    for word in raws:  # single quotes are literal; double quotes still expand $ and backticks; bare words expand much more
        if word[:1] == "'":
            quoted.append(True)
        elif word[:1] == '"':
            if any(c in word.replace("$?", "") for c in "$`\\!"):
                return None
            quoted.append(True)
        elif any(c in word for c in "$`{}()!*?[]#\\'\"") or "~" in word[1:]:
            return None
        else:
            quoted.append(False)
    words: list[str] = []
    program = sub = redirect = cd_to = None
    then = None
    here = cwd
    echoed: list[str] = []

    def at(path: str) -> str:
        if here == cwd or path.startswith(("/", "~")) or not here:
            return place(path, cwd)
        return place(os.path.join(here, path), cwd)
  # what to do with this word, set by the flag before it
    for token, was_quoted in zip(tokens, quoted):
        if then:
            if then == "say":
                if was_quoted or not _WORD.fullmatch(token):
                    return None
                words.append(at(token))
            then = None
            continue
        if token in _JOIN and not was_quoted:
            if redirect or program is None or program == "cd" and cd_to is None:
                return None
            if program == "cd":  # what follows runs there: its paths are said from there, in full outside the project
                here = os.path.normpath(os.path.join(here or "/", os.path.expanduser(cd_to))) if here else None
                cd_to = None
            echoed = []  # echo printing to the screen: not said
            words.append(_JOIN[token])
            program = sub = None
            continue
        if token in _REDIRECT and not was_quoted:
            if program is None or redirect:
                return None
            redirect = _REDIRECT[token]
            continue
        if re.fullmatch(r"[|&;<>]+", token) and not was_quoted:
            return None
        if redirect:
            if was_quoted or not _WORD.fullmatch(token):
                return None
            words.extend(echoed)  # what echo writes into a file is said
            echoed = []
            words.append(f"{redirect} {at(token)}")
            redirect = None
            continue
        if program == "uv" and sub is None:
            if token != "run":
                return None
            sub = "run"
            words.append("run")
            continue
        if program == "uv" and sub == "run":
            if was_quoted or token not in _PROGRAMS and token not in ("python", "python3"):
                return None
            program, sub = token, None
            words.append(token)
            continue
        if program in ("python", "python3") and sub is None:
            if token != "-m":
                return None
            sub = "-m"
            continue
        if program in ("python", "python3") and sub == "-m":
            if token != "pytest":
                return None
            program, sub = "pytest", None
            words.append("pytest")
            continue
        if program is None and not was_quoted and re.fullmatch(r"[A-Za-z_]\w*=[\w.:/-]*", token):
            variable = token.split("=", 1)[0]
            if variable not in _SAFE_VARIABLES:  # PATH, HOME, LD_PRELOAD, RUSTC_WRAPPER...: too many load code
                return None
            words.append(f"with {variable} set")
            continue
        if program == "sed":  # only printing lines: sed -n '10,20p' file
            if sub is None:
                if token != "-n":
                    return None
                sub = "-n"
                continue
            if sub == "-n":
                if not re.fullmatch(r"\d+(,\d+)?p", token):
                    return None
                sub = "print"
                continue
            if token.startswith("-") or not _WORD.fullmatch(token):
                return None
            words.append(at(token))
            continue
        if program is None:
            if token == "sed" and not was_quoted:
                program = "sed"
                words.append("sed")
                continue
            if token in ("python", "python3", "uv") and not was_quoted:
                program = token
                words.append(token)
                continue
            name = token if was_quoted else os.path.basename(token)
            if was_quoted or name != token or name not in _PROGRAMS and name not in _SUBCOMMANDS:  # a bare name: no path to a lookalike
                return None
            program = name
            words.append(name)
            continue
        if program in _SUBCOMMANDS and sub is None:
            if token not in _SUBCOMMANDS[program]:
                return None
            sub = token
            words.append(token)
            continue
        if program == "echo":
            if was_quoted:
                echoed.append("some text")
            elif _WORD.fullmatch(token):
                echoed.append(token)
            else:
                return None
            continue
        if token.startswith("-") and not was_quoted:
            if program not in _PROGRAMS and program != "git":
                return None
            known = _flag(program, sub, token, at)
            if known is None:
                return None
            said, then = known
            if said:
                words.append(said)
            continue
        if not was_quoted and token.startswith("~") and token != "~" and not token.startswith("~/"):
            return None  # ~- and ~+ are other directories, ~user another home
        if program == "make" and "=" in token:
            return None
        if program == "cd":
            if cd_to is not None or was_quoted or not _WORD.fullmatch(token):
                return None
            cd_to = token
        if program in ("npm", "pnpm", "yarn") and sub == "install" and re.search(r"[/:@]", token):
            return None  # owner/repo, git URLs and scoped names install other people's code with its scripts
        if was_quoted:
            words.append("some text")
        elif not _WORD.fullmatch(token):
            return None
        elif program == "curl" or "://" in token:
            try:
                url = urlparse(token if "://" in token else f"https://{token}")
                host = url.hostname
            except ValueError:
                return None
            if not host or "@" in url.netloc:
                return None
            words.append(host + (url.path if len(url.path) <= 30 else ""))
        elif program == "git" and sub in _GIT_REMOTE:
            words.append(token)
        else:
            words.append(at(token))
    if redirect or then or program is None:
        return None
    text = " ".join(w for w in words if w)
    return text if len(text.split()) <= WORDS else None
