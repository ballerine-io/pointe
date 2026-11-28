"""What a spoken yes approves: a shell command in short form, or nothing.

An allowlist, by design. Bash is too rich to describe by listing what is dangerous (a review found 13 ways around that):
here only known programs, with known flags, in plain pipelines, are said. Anything else is approved in the terminal.
Said: every program, every file written, every redirect target, every URL, and the flags that change what is lost.
Dropped: flags that only change output, and paths shortened to their name when they sit plainly inside the project.
"""

import ast
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
    "cat": (set("-n -A -b -e -s -t -v".split()), set(), set(), set()),
    "head": (set(), set(), set(), set("-n -c".split())),
    "tail": (set("-f".split()), set(), set(), set("-n -c".split())),
    "wc": (set("-l -w -c -m".split()), set(), set(), set()),
    "tee": (set(), set("-a".split()), set(), set()),  # every file it writes is said; -a (it adds, not replaces) too
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
    "unittest": (set("-q -v -f -b -c --locals --quiet --verbose --failfast --buffer".split()), set(),
                 set("-s -t -p --start-directory --top-level-directory --pattern".split()), set("-k".split())),
    "go": (set("-v -race".split()), set(), set(), set("-run".split())),
    "cargo": (set("--release -q".split()), set(), set(), set()),
    "sleep": (set(), set(), set(), set()),
    "date": (set(), set(), set(), set()),
    "curl": (set("-s -S -f -L -sS -fsSL -sSL -I -i -v".split()), set("-X --data -d".split()), set("-o -O --output".split()), set()),  # -H can read a file (@file): unknown, so refused
    "du": (set("-s -h -sh -hs -a -c -k -m -x".split()), set(), set(), set("-d".split())),
    "chmod": (set(), set("-R".split()), set(), set()),  # the mode is said, as every positional is
    "ln": (set(), set("-s -f -sf -fs".split()), set(), set()),
    "py_compile": (set(), set(), set(), set()),  # python3 -m py_compile: each file it compiles is said
    "sh": (set(), set(), set(), set()), "bash": (set(), set(), set(), set()),  # a script file, said; no flag (-c runs text)
}
_POSITIONALS = {"sh": (1, 99), "bash": (1, 99), "ln": (2, 2), "chmod": (2, 99)}  # how many each needs, at least and at most
_SUBCOMMANDS = {
    "git": {"status", "diff", "log", "show", "add", "commit", "push", "pull", "fetch", "checkout", "switch", "branch",
            "restore", "stash", "rebase", "merge", "reset", "clean", "rm", "mv", "tag", "blame", "rev-parse", "grep",
            "check-ignore", "ls-files"},
    "npm": {"test", "run", "install", "ci", "ls"}, "pnpm": {"test", "run", "install", "ls"}, "yarn": {"test", "run", "install"},
    "go": {"test", "build", "vet"}, "cargo": {"test", "build", "check", "clippy"},
    "gh": {"pr", "run", "issue"}, "kubectl": {"get", "describe", "logs"},
}
_GIT_QUIET = set("-q --oneline --stat -p --name-only --name-status --short -s -b --cached --staged --graph --decorate "
                 "--porcelain --no-pager".split())  # only change what is printed
_GIT_QUIET_BY_SUB = {"log": {"-n", "--format", "--pretty", "--author", "--since", "--until"}, "show": {"--format", "--pretty"},
                     "commit": {"-m"}, "tag": {"-m"}, "grep": {"-e"}}  # flags whose value is dropped, for that subcommand only
_GIT_LISTING_BY_SUB = {  # flags that only change what is printed or matched, for that subcommand only; git grep -O runs a program
    "grep": set("-n -i -I -l -L -w -E -F -c -h -H -q -v -o --cached --untracked --line-number --ignore-case --count "
                "--files-with-matches --word-regexp".split()),
    "check-ignore": set("-v --verbose -n --non-matching -q".split()),
    "ls-files": set("-m -o -d -c -s --others --modified --deleted --cached --stage --exclude-standard".split()),
    "branch": set("-a -r -v -vv --list --all --show-current".split()),
}
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
_URL_PATH = 60  # a URL's path longer than this is not read out: it is said whole or not at all
_SAFE_VARIABLES = {"CI", "NODE_ENV", "DEBUG", "TZ", "LANG", "LC_ALL", "NO_COLOR", "FORCE_COLOR", "TERM",
                   "PYTHONDONTWRITEBYTECODE"}
_JOIN = {"|": "into", "&&": "then", ";": "then", "||": "or else"}
_REDIRECT = {">": "writing to", ">>": "appending to", "<": "reading"}
_WORD = re.compile(r"~?[\w@%+=:,./-]+")  # a literal word: no glob, brace, quote, variable or substitution
_QUIET = re.compile(r"\s+2>\s*/dev/null|\s+2>&1(?=\s|$|[;|&])")
# Showing only the end or the start of the output changes nothing: "pytest -q 2>&1 | tail -15" is said "pytest".
_TRIM = re.compile(r"\s*\|\s*(?:tail|head)(?:\s+-n\s*\d+|\s+-\d+)?(?=\s*(?:$|&&|;|\|\|))")


MASK = "••••••"
_SECRET_SHAPES = [
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)"),
    re.compile(r"\b(?:sk|rk|pk)[-_](?:live|test|ant|proj|or)?[-_]?[A-Za-z0-9_-]{12,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b|\bgithub_pat_\w{20,}"),
    re.compile(r"\bxox[abprs]-[\w-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}"),
    re.compile(r"\bglpat-[\w-]{16,}"),
    re.compile(r"(?i)\bbearer\s+[\w.~+/=-]{6,}"),
]
_URL_PASSWORD = re.compile(r"(://[^:/\s@]+:)([^@\s/]+)(@)")
_NAMED = (r"[\w.-]*(?:secret|token|passw(?:or)?d|pwd|api[_-]?key|apikey|access[_-]?key|private[_-]?key|auth[_-]?key|"
          r"credential|client[_-]?secret|[_-]key)[\w.-]*")
_ASSIGNED_QUOTED = re.compile(rf"(?i)(\b{_NAMED}\b[\"']?\s*(?:[:=]|=>|:=)\s*)([\"'])([^\"'\n]{{4,}})\2")
_ASSIGNED_ENV = re.compile(rf"(?im)^(\s*(?:export\s+)?{_NAMED}\s*=\s*)([^\s\"'#]{{4,}})")
_ASSIGNED_INLINE = re.compile(rf"(?i)(\b{_NAMED}=)([^\s\"';|&]{{4,}})")
# Unquoted, anywhere in a line, spaces allowed around the separator: "password: hunter2", "Secret= abc123".
_ASSIGNED_BARE = re.compile(rf"(?i)(\b{_NAMED}[ \t]*(?:=>|:=|[:=])[ \t]*)([^\s\"'#,;|&]{{4,}})")
# Said or written in words: "my password is hunter22x", "הסיסמה היא Kite-4412". Only a value with a digit, so "the token
# is expired" stays readable.
_SPOKEN_VALUE = re.compile(r"(?i)((?<!\w)(?:password|passcode|passphrase|secret|token|api key|ה?סיסמ[הא])"
                           r"\s*(?:is|was|:|=|היא|הוא|זה)?\s*)((?=[^\s\"']*\d)[^\s\"']{4,})")
_FLAG_VALUE = re.compile(r"(?i)(--?(?:token|password|passwd|secret|api-?key|key)[= ])([^\s\"']{4,})")


def _live_values() -> list[str]:
    """The values of this machine's own secrets, wherever they appear."""
    try:
        import vendors
        names, held = set(vendors.KEY_ENVS), vendors.known_keys()  # held: the Keychain's, which os.environ never sees
    except Exception:
        names, held = set(), []
    names |= {k for k in os.environ if re.search(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", k, re.I)}
    values = {os.environ.get(k, "") for k in names} | set(held)
    return sorted({v for v in values if len(v) >= 8}, key=len, reverse=True)


def mask(text: str) -> str:
    """Secret-looking values replaced. Errs on the side of hiding: a masked string in code costs nothing."""
    if not text:
        return text
    for value in _live_values():
        text = text.replace(value, MASK)
    for shape in _SECRET_SHAPES:
        text = shape.sub(MASK, text)
    text = _URL_PASSWORD.sub(lambda m: m.group(1) + MASK + m.group(3), text)
    text = _ASSIGNED_QUOTED.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}{m.group(2)}", text)
    text = _ASSIGNED_ENV.sub(lambda m: m.group(1) + MASK, text)
    text = _ASSIGNED_INLINE.sub(lambda m: m.group(1) + MASK, text)
    text = _ASSIGNED_BARE.sub(lambda m: m.group(1) + (m.group(2) if m.group(2) == MASK else MASK), text)
    text = _SPOKEN_VALUE.sub(lambda m: m.group(1) + MASK, text)
    return _FLAG_VALUE.sub(lambda m: m.group(1) + MASK, text)


def redact(text: str) -> str | None:
    """The text, or None when it carries a credential-like value (mask() would change it). Withheld whole, never masked:
    a masked command approved by ear approves a value nobody heard, so such a request goes to a tap, as any request that
    cannot be read out does. The one rule for what is said aloud and what a notification shows."""
    return None if text and mask(text) != text else text


def _hidden(text: str) -> bool:
    if unicodedata.normalize("NFKC", text) != text:
        return True
    return any(unicodedata.category(c).startswith("C") or unicodedata.name(c, "").startswith(("CYRILLIC", "GREEK"))
               for c in text)


def visible(value):
    """Text, or a tool input's strings, with every format and control character but a line break and a tab written as
    \\uXXXX: a bidi override or a zero-width space on an approval card shows what runs reordered or as a look-alike."""
    if isinstance(value, str):
        return "".join(c if c in "\n\t" or not unicodedata.category(c).startswith("C") else f"\\u{ord(c):04x}"
                       for c in value)
    if isinstance(value, dict):
        return {visible(k): visible(v) for k, v in value.items()}
    if isinstance(value, list):
        return [visible(v) for v in value]
    return value


PROJECT = "the project folder"
ROOT = "the whole disk"  # "/" read as "slash" says nothing of how far a search or a delete reaches


def beside(full: str, cwd: str) -> str | None:
    """A place in a project next to this one ("tariff-api, next to the project"), when nothing on the way is hidden or
    looks like a secret: its name says where it is as well as its full path, in a breath instead of twenty seconds. For a
    read-only look (looking); what a command acts on outside the project is said whole (place)."""
    real, home = os.path.realpath(full), os.path.realpath(cwd)
    rel = os.path.relpath(real, os.path.dirname(home))
    if rel.startswith("..") or os.path.isabs(rel) or rel == "." or not os.path.relpath(real, home).startswith(".."):
        return None  # outside the folder above, the folder above itself, or inside the project
    if any(p.startswith(".") or p == "node_modules" for p in rel.split(os.sep)) or _SENSITIVE.search(rel):
        return None
    return f"{rel}, next to the project"


def place(path: str, cwd: str | None) -> str:
    """Plainly inside the project: its name. Anywhere else, through a hidden folder, or through a symlink that leaves the
    project: the whole path."""
    if ":" in path or "@" in path:
        return path  # host:path is another machine
    full = os.path.normpath(os.path.join(cwd or "/", os.path.expanduser(path))) if cwd else None
    if not full or not cwd:
        return path
    if full == "/":
        return ROOT
    inside = os.path.relpath(full, cwd)
    if inside.startswith("..") or path.startswith(("~", "/")) and not full.startswith(cwd.rstrip("/") + "/"):
        # The same folder spelled through another link (/tmp is /private/tmp on a Mac) is still inside: read on.
        real_inside = os.path.relpath(os.path.realpath(full), os.path.realpath(cwd))
        if real_inside == ".":
            return PROJECT  # the session's own folder, by its full path: said as that, not as twenty seconds of path
        if real_inside.startswith("..") or os.path.isabs(real_inside):
            return full if not path.startswith("~") else path
        inside = real_inside
    # Through a symlink (a cloned repo's docs -> ~/.ssh), where it really goes. Run on the disk the session runs on: a
    # node builds its own read-out, and the hub never rebuilds one for a remote session.
    real = os.path.realpath(full)
    real_inside = os.path.relpath(real, os.path.realpath(cwd))
    if real_inside.startswith(".."):
        return real
    for rel in (inside, real_inside):
        if any(p.startswith(".") and p not in (".", "..") or p == "node_modules" for p in rel.split(os.sep)):
            return rel  # .git/hooks/x and node_modules/.bin/x run code: say where
    parts = inside.split(os.sep)
    return parts[-1] if inside != "." else "."


def _flag(program: str, sub: str | None, token: str, at) -> tuple[str, str | None] | None:
    """(what to say, what to do with the next word: "drop", "say" or None) for a known flag; None for an unknown one."""
    name, _, value = token.partition("=")
    if program == "git":
        if token in _GIT_QUIET or sub == "log" and re.fullmatch(r"-\d+", token) or token == "--":
            return "", None  # "--" only ends the options: "git checkout -- notes.txt" is said "git checkout notes.txt"
        if name in _GIT_QUIET_BY_SUB.get(sub or "", ()):
            return "", None if value else "drop"
        if token in _GIT_LISTING_BY_SUB.get(sub or "", ()):
            return "", None
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


_FIND_TESTS = {"-name": "named", "-iname": "named", "-path": "path", "-ipath": "path", "-wholename": "path",
               "-iwholename": "path", "-regex": "matching", "-iregex": "matching"}  # said with their pattern
_FIND_TYPES = {"f": "files", "d": "folders", "l": "links"}
_FIND_DEPTH = {"-maxdepth": "at most {} deep", "-mindepth": "at least {} deep"}
_FIND_TIMES = {"-mtime", "-mmin", "-atime", "-amin", "-ctime", "-cmin", "-size"}
_FIND_LISTING = {"-print", "-print0", "-ls", "-depth"}
_FIND_GROUPING = {"-o", "-or", "(", ")", "-prune"}  # fine for a find that only lists; with an action, which files it acts on
_FIND_PATTERN = re.compile(r"[\w.*?\[\]/@%+=:~-]+")  # no space or comma: a pattern cannot pass for words of the read-out
_FOUND = "pointe-each-found"  # stands for {} while what -exec runs is read
_SED_REPLACE = re.compile(r"s/((?:[^/\\\n]|\\.)*)/((?:[^/\\\n]|\\.)*)/[gIi0-9]*")  # no e (runs), w (writes), p, m


def _find(args: list[tuple[str, bool]], at, cwd: str | None, here: str | None) -> list[str] | None:
    """find, said: where it looks, and when it deletes or runs something, which files it picks and what it does to each.
    A find that only lists drops its tests, as looking() does. None for an action other than -delete and -exec, a test
    after an action, "-o" or brackets around what an action acts on, or anything unknown."""
    paths, i = [], 0
    while i < len(args) and not args[i][0].startswith("-") and args[i][0] not in ("(", "!"):
        token, was_quoted = args[i]
        if not _WORD.fullmatch(token) or token.startswith("~") and (was_quoted or not (token == "~" or token[:2] == "~/")):
            return None
        paths.append(at(token))
        i += 1
    tests: list[str] = []
    acts: list[str] = []
    grouped = negated = False
    while i < len(args):
        token, was_quoted = args[i]
        i += 1
        if was_quoted and token not in ("(", ")", "!", ";") or not was_quoted and token in ("(", ")", "!", ";"):
            return None  # a test is a bare word; a bracket or "!" is quoted for the shell
        if token in ("-not", "!"):
            negated = True
            tests.append("not")
            continue
        if token in ("-a", "-and"):
            continue
        if acts and token not in {"-delete", "-exec", *_FIND_LISTING}:
            return None  # a test after an action: the action has already run on what came before it
        if negated and token not in {*_FIND_TESTS, "-type", "-empty", "-newer", *_FIND_TIMES}:
            return None
        negated = False
        if token in _FIND_GROUPING:
            grouped = True
        elif token in _FIND_LISTING:
            pass
        elif token == "-empty":
            tests.append("empty")
        elif token == "-delete":
            acts.append("deleting each")
        elif token == "-exec":
            inner: list[str] = []
            while i < len(args):
                word, quoted_word = args[i]
                i += 1
                if word == ";" and quoted_word or word == "+" and not quoted_word and inner[-1:] == ["{}"]:
                    break
                if "{}" in word and word != "{}" or _FOUND in word:
                    return None  # "{}.bak": find puts the name inside the word, which is not said as such
                inner.append(word)
            else:
                return None
            if not inner or inner[0] in ("{}", "find", "cd"):
                return None
            runs = spoken(shlex.join(_FOUND if w == "{}" else w for w in inner), cwd, here)
            lead = f"in {place(here, cwd)}, " if here and cwd and os.path.normpath(here) != os.path.normpath(cwd) else ""
            if not runs or not runs.startswith(lead) or " then " in runs or " into " in runs:
                return None
            acts.append("on each: " + re.sub(rf"\S*{_FOUND}", "it", runs[len(lead):]))
        elif i >= len(args):
            return None  # every test below takes a value
        else:
            value, _ = args[i]
            i += 1
            if token in _FIND_TESTS and _FIND_PATTERN.fullmatch(value) and not value.startswith("-"):
                tests.append(f"{_FIND_TESTS[token]} {value}")
            elif token == "-type" and value in _FIND_TYPES:
                tests.append(_FIND_TYPES[value])
            elif token in _FIND_DEPTH and value.isdigit():
                tests.append(_FIND_DEPTH[token].format(value))
            elif token in _FIND_TIMES and re.fullmatch(r"[+-]?\d+[ckMGwb]?", value):
                tests.append(f"{token} {value}")
            elif token == "-newer" and _WORD.fullmatch(value) and not value.startswith("~"):
                tests.append(f"newer than {at(value)}")
            else:
                return None
    if negated or acts and grouped:
        return None
    where = [p for p in paths if p != "."]
    words = ["find"] + (["everything"] if acts and not tests else []) + ([f"in {' '.join(where)}"] if where else [])
    if not acts:
        return words
    picked = words + tests
    return picked[:-1] + [f"{picked[-1]},", ", ".join(acts)]


def _sed(args: list[tuple[str, bool]], at) -> list[str] | None:
    """sed, said: every file it rewrites in place, and what it replaces when both sides are plain words. Only a
    substitution (s/a/b/, no e or w flag) may rewrite a file; printing lines (-n '10,20p') only reads. None otherwise."""
    in_place = quiet = given = False
    scripts: list[str] = []
    files: list[str] = []
    i = 0
    while i < len(args):
        token, was_quoted = args[i]
        i += 1
        if not was_quoted and token in ("-i", "--in-place"):
            in_place = True
            if args[i:i + 1] == [("", True)]:
                i += 1  # BSD: -i '' keeps no backup
        elif not was_quoted and token in ("-E", "-r"):
            pass
        elif not was_quoted and token == "-n":
            quiet = True
        elif not was_quoted and token == "-e":
            if i >= len(args) or scripts and not given:
                return None  # after a script with no -e, an -e makes that script a file name to sed
            scripts.append(args[i][0])
            given = True
            i += 1
        elif token.startswith("-"):
            return None
        elif not scripts:
            scripts.append(token)
        elif not _WORD.fullmatch(token) or token.startswith("~") and (was_quoted or token[:2] != "~/"):
            return None
        else:
            files.append(at(token))
    replacing = [_SED_REPLACE.fullmatch(script) for script in scripts]
    if not scripts or in_place and (quiet or not files or not all(replacing)):
        return None
    if not in_place:
        printing = quiet and all(re.fullmatch(r"\d+(,\d+)?p", script) for script in scripts)
        return ["sed"] + files if printing or all(replacing) and not quiet else None
    old, new = (re.sub(r"\\[b<>]", "", replacing[0][1]), replacing[0][2]) if len(scripts) == 1 else ("", "")
    what = f"{old} with {new}" if re.fullmatch(r"\w+", old) and re.fullmatch(r"\w+", new) else "text"
    return ["sed", f"replacing {what} in"] + files


def _escaped_words(command: str) -> str:
    """The command with a whole word \\; \\( \\) or \\! outside quotes written ';' '(' ')' '!': the same word to the shell,
    and the way find's terminator and brackets are usually written."""
    out, quote, i = [], None, 0
    while i < len(command):
        c = command[i]
        if quote is None and c == "\\" and command[i + 1:i + 2] in (";", "(", ")", "!") and (i == 0 or command[i - 1] in " \t") \
                and command[i + 2:i + 3] in ("", " ", "\t"):
            out.append(f"'{command[i + 1]}'")
            i += 2
            continue
        if c == "\\" and quote != "'":
            out.append(command[i:i + 2])
            i += 2
            continue
        if quote is None and c in "'\"":
            quote = c
        elif c == quote:
            quote = None
        out.append(c)
        i += 1
    return "".join(out)


_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_EMPTY_FILE = re.compile(r"^\s*(?::|true)?\s*>\s*(?P<file>[^\s;&|<>]+)\s*$")


def _python_calls(code: str, cwd: str | None) -> tuple[list[str], list[str]] | None:
    """`python3 -c` code that only imports the project's own modules and calls their functions with literal arguments
    that hold no string, printed or not, or checks files' syntax (ast.parse(open('a.py').read()), which runs nothing):
    the functions it calls, in order, and the files it checks, as said. None for anything else (the tap answers it)."""
    if not cwd:
        return None
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return None
    local, calls, checked = {}, [], []

    def project(module: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z_]\w*", module)) and not module.startswith("_") and (
            os.path.isfile(os.path.join(cwd, f"{module}.py")) or os.path.isfile(os.path.join(cwd, module, "__init__.py")))

    def literal(node) -> bool:
        """Numbers, booleans, None and containers of them. Not a string: one can carry a command or a path that the
        read-out does not say, and the call it is passed to may run it (`run("curl … | sh")`)."""
        try:
            ast.literal_eval(node)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            return False
        return not any(isinstance(n, ast.Constant) and isinstance(n.value, (str, bytes)) for n in ast.walk(node))

    def call(node) -> str | None:
        if not isinstance(node, ast.Call) or not all(literal(a) for a in node.args) or \
                not all(k.arg and literal(k.value) for k in node.keywords):
            return None
        f = node.func
        if isinstance(f, ast.Name) and local.get(f.id, ("", ""))[0] == "name":
            return local[f.id][1]
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and local.get(f.value.id, ("", ""))[0] == "module" \
                and not f.attr.startswith("_"):
            return f"{local[f.value.id][1]}.{f.attr}"
        return None

    def parsed(node, var: str | None = None) -> str | None:
        """ast.parse(open(F).read()), F also allowed as its second argument: F, a string, or the name `var`."""
        if not (isinstance(node, ast.Call) and not node.keywords and 1 <= len(node.args) <= 2
                and isinstance(node.func, ast.Attribute) and node.func.attr == "parse"
                and isinstance(node.func.value, ast.Name) and local.get(node.func.value.id) == ("stdlib", "ast")):
            return None
        read = node.args[0]
        if not (isinstance(read, ast.Call) and not read.args and not read.keywords and isinstance(read.func, ast.Attribute)
                and read.func.attr == "read" and isinstance(read.func.value, ast.Call)):
            return None
        opened = read.func.value  # open(F) with no mode: it only reads
        if not (isinstance(opened.func, ast.Name) and opened.func.id == "open" and "open" not in local
                and len(opened.args) == 1 and not opened.keywords):
            return None
        target = opened.args[0]
        if len(node.args) == 2 and ast.dump(node.args[1]) != ast.dump(target):
            return None
        if var is not None:
            return var if isinstance(target, ast.Name) and target.id == var else None
        return target.value if isinstance(target, ast.Constant) and isinstance(target.value, str) else None

    def files_checked(node) -> list[str] | None:
        """The files one statement's syntax check reads: ast.parse(open('a.py').read()), or the same in a list
        comprehension over a list of strings."""
        if isinstance(node, ast.ListComp) and len(node.generators) == 1:
            loop = node.generators[0]
            if not (isinstance(loop.target, ast.Name) and not loop.ifs and not loop.is_async
                    and isinstance(loop.iter, (ast.List, ast.Tuple)) and parsed(node.elt, loop.target.id)
                    and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in loop.iter.elts)):
                return None
            names = [e.value for e in loop.iter.elts]
        else:
            names = [parsed(node)] if parsed(node) else None
        if not names or not all(_WORD.fullmatch(n) and not n.startswith("~") for n in names):
            return None  # open() does not expand ~: a folder named ~, which the read-out would say as home
        return [place(n, cwd) for n in names]

    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for a in stmt.names:
                if a.name in ("ast", "sys") and not a.asname and not project(a.name):
                    local[a.name] = ("stdlib", a.name)  # sys is imported only: any use of it is refused below
                    continue
                if not project(a.name) or a.asname and not re.fullmatch(r"[A-Za-z]\w*", a.asname):
                    return None
                local[a.asname or a.name] = ("module", a.name)
        elif isinstance(stmt, ast.ImportFrom):
            if stmt.level or not stmt.module or not project(stmt.module):
                return None
            for a in stmt.names:
                if a.name == "*" or a.name.startswith("_"):
                    return None
                local[a.asname or a.name] = ("name", f"{stmt.module}.{a.name}")
        elif isinstance(stmt, ast.Assert) and stmt.msg is None and isinstance(stmt.test, ast.Compare) \
                and len(stmt.test.ops) == 1 and isinstance(stmt.test.ops[0], (ast.Eq, ast.NotEq, ast.Is, ast.IsNot)) \
                and call(stmt.test.left) and literal(stmt.test.comparators[0]):
            calls.append(call(stmt.test.left))  # "assert f('300S') == 300": a check of one call against a literal
        elif isinstance(stmt, ast.Expr) and files_checked(stmt.value):
            checked += files_checked(stmt.value)
        elif isinstance(stmt, ast.Expr):
            node = stmt.value
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print" \
                    and "print" not in local and not node.keywords:
                # A string printed is only shown: print('syntax ok') runs nothing.
                inner = [call(a) or ("" if literal(a) or isinstance(a, ast.Constant) and isinstance(a.value, str) else None)
                         for a in node.args]
            else:
                inner = [call(node)]
            if None in inner:
                return None
            calls += [c for c in inner if c]
        else:
            return None
    return (calls, checked) if calls or checked else None


def spoken(command: str, cwd: str | None, run_in: str | None = None) -> str | None:
    """The short form of a shell command, or None. `cwd` is the session's folder, `run_in` the folder the command runs
    in when the harness reports it (a shell that cd'd earlier, a Codex command given its own folder): from another one,
    the read-out starts with where, and its paths are said from there."""
    if not command.strip() or _hidden(command.replace("\n", "").replace("\t", "")) or "\r" in command:
        return None  # a newline is a line of code below; anywhere else it is refused further down
    emptied = _EMPTY_FILE.match(command)
    if emptied:  # ": > data.csv" empties a file: said as that, the file in full outside the project
        return f"empty {place(emptied['file'], cwd)}" if _WORD.fullmatch(emptied["file"]) else None
    if "\n" in _QUOTED.sub("", command.strip()):
        return None  # a newline outside quotes is a second command; inside, a line of python -c code (checked below)
    command = _escaped_words(_TRIM.sub("", _QUIET.sub(" ", command)))
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
        elif word == "{}":
            quoted.append(False)  # not a brace expansion: what find -exec puts each name in
        elif word[:1] == '"':  # a backslash there stays, but before $ ` " \ and a line end: as shlex reads it
            if any(c in word.replace("$?", "") for c in "$`!"):
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
    if run_in and (not cwd or os.path.normpath(run_in) != os.path.normpath(cwd)):
        here = os.path.normpath(run_in)
        words.append(f"in {place(here, cwd)},")
    moved = False  # a cd has been read as taken: from here on only "&&" may follow, or what runs may not be where it says
    unsure = False  # an "||" or "|" came before: a cd after it may not run, or runs in a subshell
    echoed: list[str] = []
    positionals, pattern_given = 0, False  # grep and rg: the first positional is the pattern unless -e gave one
    gathered: list[tuple[str, bool]] | None = None  # find's or sed's words, read together when the command ends

    def ended() -> bool:
        """The simple command being read is whole: find's and sed's words read, and each program's positionals there."""
        nonlocal gathered
        if gathered is not None:
            said = _find(gathered, at, cwd, here) if program == "find" else _sed(gathered, at)
            if said is None:
                return False
            words.extend(said)
            gathered = None
        least, most = _POSITIONALS.get(program, (0, 99))
        return least <= positionals <= most

    def at(path: str) -> str:
        if here == cwd or path.startswith(("/", "~")) or not here:
            return place(path, cwd)
        return place(os.path.join(here, path), cwd)
  # what to do with this word, set by the flag before it
    for token, was_quoted in zip(tokens, quoted):
        if gathered is not None and (was_quoted or not re.fullmatch(r"[|&;<>]+", token)):
            gathered.append((token, was_quoted))
            continue
        if not was_quoted and re.fullmatch(r"[|&;<>]+", token) and program is not None and not ended():
            return None
        if was_quoted and token.startswith("-") and not (program == "echo" and not re.fullmatch(r"-[neE]+", token)):
            return None  # a flag in quotes is still a flag: never "some text" (echo prints "--- notes:" as text)
        if then:
            if re.fullmatch(r"[|&;<>]+", token) and not was_quoted or token.startswith("-"):
                return None  # "git commit -m ; rm x": the flag's value is missing, and what follows is not its value
            if then == "say":
                if was_quoted or not _WORD.fullmatch(token):
                    return None
                words.append(at(token))
            then = None
            continue
        if was_quoted and _WORD.fullmatch(token) and not token.startswith("~") and not (program is None and "=" in token):
            was_quoted = False  # 'main' is main: said, and checked, as if unquoted ('~/x' is a folder named ~, not home)
        if token in _JOIN and not was_quoted:
            if redirect or program is None or program == "cd" and cd_to is None:
                return None
            if moved and token in (";", "||"):
                return None  # "cd x && ls ; rm src": rm runs in the project when the cd failed
            if program == "cd":  # what follows runs there: its paths are said from there, in full outside the project
                if token != "&&" or unsure:
                    return None  # "cd x ; rm src", "cd x | rm src", "ls || cd x && rm src": rm may run where it started
                here = os.path.normpath(os.path.join(here or "/", os.path.expanduser(cd_to))) if here else None
                cd_to, moved = None, True
            unsure = unsure or token in ("||", "|")
            echoed = []  # echo printing to the screen: not said
            words.append(_JOIN[token])
            program = sub = None
            positionals, pattern_given = 0, False
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
            if token in ("-I", "-B") and not was_quoted:
                continue  # isolated mode: less is loaded, nothing more runs; -B: no bytecode written
            if token not in ("-m", "-c") or was_quoted:
                return None
            sub = token
            continue
        if program in ("python", "python3") and sub == "-c":  # never read out: which project functions it calls
            calls = _python_calls(token, cwd) if was_quoted and here == cwd else None
            if not calls:
                return None
            named, files = list(dict.fromkeys(calls[0])), list(dict.fromkeys(calls[1]))
            what = [f"calling {', '.join(named[:4])}" + (f" and {len(named) - 4} more" if len(named) > 4 else "")] if named else []
            what += [f"checking the syntax of {', '.join(files)}"] if files else []
            words.append(f"code {', '.join(what)}")
            sub = "code"
            continue
        if program in ("python", "python3") and sub == "code":
            return None  # arguments to the code: sys.argv can steer it
        if program in ("python", "python3") and sub == "-m":
            if token not in ("pytest", "unittest", "py_compile"):
                return None
            program, sub = token, None
            words.append(token)
            continue
        if program is None and not was_quoted and re.fullmatch(r"[A-Za-z_]\w*=[\w.:/-]*", token):
            variable = token.split("=", 1)[0]
            if variable not in _SAFE_VARIABLES:  # PATH, HOME, LD_PRELOAD, RUSTC_WRAPPER...: too many load code
                return None
            words.append(f"with {variable} set")
            continue
        if program is None:
            if token in ("find", "sed") and not was_quoted:
                program, gathered = token, []
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
            if (program in ("grep", "rg") or program == "git" and sub == "grep") and token.split("=", 1)[0] in ("-e", "--regexp"):
                pattern_given = True  # the positionals are all files now
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
        positionals += 1
        if was_quoted:
            if program not in ("grep", "rg") and (program, sub) != ("git", "grep") or positionals > 1 or pattern_given:
                return None  # a quoted path, URL, ref or target is never "some text": only a search pattern is
            words.append("some text")
        elif not _WORD.fullmatch(token):
            return None
        elif program == "curl" or "://" in token:
            try:
                url = urlparse(token if "://" in token else f"https://{token}")
                host = url.hostname
            except ValueError:
                return None
            if not host or "@" in url.netloc or len(url.path) > _URL_PATH:
                return None  # the path picks what is fetched, and for a git remote whose repository: never dropped
            words.append(host + url.path)
        elif program == "git" and sub in _GIT_REMOTE:
            words.append(token)
        elif program == "uniq" and positionals == 2:
            words.append(f"writing to {at(token)}")  # uniq in out: out is overwritten
        elif program == "uniq" and positionals > 2:
            return None
        else:
            words.append(at(token))
    if redirect or then or program is None or not ended():
        return None
    text = " ".join(w for w in words if w)
    return text if len(text.split()) <= WORDS else None


# ---------- a command that only looks ----------

ABOVE = "the folder above the project"
LOOK = "look around, read only:"  # what a read-out of commands that change nothing starts with
_LOOK_PROGRAMS = {"pwd", "ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "rg", "file", "stat", "du", "df", "which",
                  "echo", "true", "test", "[", "basename", "dirname", "realpath", "readlink", "nl", "cut", "tr", "uniq",
                  "cd", "sort", "find", "date", "git", "python", "python3", "pip", "pip3"}
_LOOK_GIT = {"status", "diff", "log", "show", "ls-files", "rev-parse", "branch", "remote", "blame", "describe", "ls-tree",
             "shortlog"}
_LOOK_GIT_BRANCH = set("-a -r -v -vv --show-current --list --all".split())
_FIND_ACTS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}
_FIND_PATTERNS = {"-name", "-iname", "-path", "-ipath", "-wholename", "-regex", "-iregex", "-type", "-maxdepth", "-mindepth"}
_LOOK_SILENT = {"echo", "true", "test", "["}  # they read nothing: not worth a word of the read-out
_LOOK_QUIET = re.compile(r"\s*(?:[12]?>|&>)\s*/dev/null|\s*2>&1")
_SENSITIVE = re.compile(r"secret|credential|passw|token|\.pem$|\.key$|id_rsa|id_ed25519|\.env|keychain|\.aws|\.ssh|\.netrc", re.I)
_LOOK_MAX_PROGRAMS, _LOOK_MAX_PLACES = 8, 3
_LITERAL_DOLLAR = "\ue000"  # a "$" the shell does not expand (single-quoted), while the variable checks run


def _single_quoted_dollars(command: str) -> str:
    """The command with each "$" inside single quotes, where the shell expands nothing, marked as literal. Quotes are
    followed as the shell does: a ' inside double quotes is a character there, and $'...' is C quoting, not this."""
    out, quote, i = [], None, 0
    while i < len(command):
        c = command[i]
        if c == "\\" and quote != "'":
            out.append(command[i:i + 2])
            i += 2
            continue
        if quote is None:
            if c == "'":
                quote = "C" if i and command[i - 1] == "$" else "'"
            elif c == '"':
                quote = '"'
        elif c == ("'" if quote in ("'", "C") else '"'):
            quote = None
        elif quote == "'" and c == "$":
            c = _LITERAL_DOLLAR
        out.append(c)
        i += 1
    return "".join(out)


def looking(command: str, cwd: str | None, run_in: str | None = None) -> str | None:
    """The short form of a command that only looks: "look around, read only: pwd, ls, git status and find", and where,
    when it looks outside the project or at a file that may hold a secret. A session exploring a project asks for long
    lists of these ("pwd && ls -la && git status --short && find . -name 'test*.py' | head"); read word for word, one
    took forty seconds. Said: every program, every place outside the project, every hidden or secret-looking file.
    Dropped: the patterns and the flags, which here cannot change what is read into what is written.

    An allowlist again, and a narrow one. None, so the command is read word for word, for: any program not known to
    only read; a redirect to anything but /dev/null; a substitution, a variable other than $? and $PWD, a background
    job; find with an action, sort to a file, git with anything but its reading subcommands; and anything this cannot
    parse. `cwd` and `run_in` as for `spoken`."""
    if not cwd or not command.strip() or _hidden(command.replace("\n", "").replace("\t", "")) or "\r" in command:
        return None
    if "\n" in command or "$(" in command or "`" in command or "<(" in command or ">(" in command or "<<" in command:
        return None
    command = _LOOK_QUIET.sub(" ", command)
    # Inside single quotes the shell expands nothing: "grep 'total$'" is a pattern's end anchor, not a variable. $'...'
    # (C quoting) is not single quoting, and still refuses below.
    command = _single_quoted_dollars(command)
    if re.search(r"\$(?!\?|PWD\b|\{PWD\})", command):
        return None
    lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;<>()")
    lexer.whitespace_split, lexer.commenters = True, ""
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    here = os.path.normpath(run_in or cwd)
    programs: list[str] = []
    places: list[str] = []

    def note_place(path: str) -> None:
        path = path.replace(_LITERAL_DOLLAR, "$")
        if path not in places:
            places.append(path)

    def seen(token: str) -> bool:
        """A word that may be a path: said when it is outside the project, hidden, or looks like a secret. False: refuse."""
        token = token.replace("${PWD}", here).replace("$PWD", here)
        if "$" in token or re.match(r"~[^/]", token):
            return False  # another variable; another user's home ("~other")
        base = token.split("*")[0].split("?")[0].split("[")[0]  # a glob looks where its fixed start is
        if token.startswith("-") or not ("/" in token or token.startswith(("~", ".")) or _SENSITIVE.search(token)):
            return True  # a flag, a pattern, a bare name in the folder it runs in
        full = os.path.normpath(os.path.join(here, os.path.expanduser(base or ".")))
        said = place(full if base else here, cwd)
        if os.path.realpath(full) == os.path.dirname(os.path.realpath(cwd)):
            note_place(ABOVE)  # ".." from the project: said as that, not as the long path the project sits in
        elif said == ROOT:
            note_place(ROOT)
        elif next_door := beside(full, cwd):  # only looking: a place an action reaches is still said whole (place)
            note_place(next_door)
        elif said.startswith(("/", "~")) or said == full:
            note_place(base if token.startswith("~") else full)  # outside the project: where, in full
        else:
            inside = os.path.relpath(os.path.realpath(full), os.path.realpath(cwd))
            if any(p.startswith(".") and p not in (".", "..") for p in inside.split(os.sep)) or _SENSITIVE.search(token):
                note_place(inside)
        return True

    words: list[str] = []  # the simple command being read

    def close() -> bool:
        nonlocal here
        if not words:
            return True
        program, args = words[0], words[1:]
        if program not in _LOOK_PROGRAMS or "=" in program:
            return False
        name = program
        if program == "git":
            while args[:1] == ["-C"] and len(args) >= 2:
                if not seen(args[1]):
                    return False
                args = args[2:]
            if args[:1] == ["--no-pager"]:
                args = args[1:]
            if not args or args[0] not in _LOOK_GIT:
                return False
            sub, rest = args[0], args[1:]
            if any(a == "-o" or a.startswith("--output") or a.startswith("--ext-diff") for a in rest):
                return False
            if sub == "branch" and any(a not in _LOOK_GIT_BRANCH for a in rest):
                return False
            if sub == "remote" and any(a != "-v" for a in rest):
                return False
            name, args = f"git {sub}", rest
        elif program in ("python", "python3"):
            if args not in (["--version"], ["-V"]) and args[:3] not in (["-m", "pip", "show"], ["-m", "pip", "list"]):
                return False
            name = "pip" if args[:1] == ["-m"] else program
            args = []
        elif program in ("pip", "pip3"):
            if args[:1] not in (["show"], ["list"], ["--version"]):
                return False
            args = []
        elif program == "find":
            if any(a in _FIND_ACTS for a in args):
                return False
            # What follows -name or -path is a pattern to match, not a place it looks in: "-path ./.git -prune".
            args = [a for i, a in enumerate(args) if i == 0 or args[i - 1] not in _FIND_PATTERNS]
        elif program == "sort" and any(a == "-o" or a.startswith("--output") for a in args):
            return False
        elif program == "date" and any(not a.startswith("+") for a in args):
            return False
        elif program == "cd":
            if len(args) != 1 or args[0].startswith("-") or not seen(args[0]):
                return False  # "cd -" goes back to a folder this cannot know
            here = os.path.normpath(os.path.join(here, os.path.expanduser(args[0].replace("$PWD", here))))
            del words[:]
            return True  # where it goes is said if it is outside; "cd" itself is not a thing to approve
        if program == "echo":
            args = []  # printed to the screen: nothing is read
        if not all(seen(a) for a in args):
            return False
        if name not in programs and name not in _LOOK_SILENT:
            programs.append(name)
        del words[:]
        return True

    for token in tokens:
        if token in ("|", "&&", "||", ";"):
            if not close():
                return None
        elif token in ("(", ")"):
            continue  # a group, or find's own brackets: neither changes what is read
        elif re.fullmatch(r"[|&;<>()]+", token):
            return None  # a redirect, a background job, a here-string
        else:
            words.append(token)
    if not close() or not programs or len(programs) > _LOOK_MAX_PROGRAMS or len(places) > _LOOK_MAX_PLACES:
        return None
    listed = programs[0] if len(programs) == 1 else ", ".join(programs[:-1]) + " and " + programs[-1]
    where = f", also in {', '.join(places)}" if places else ""
    return f"{LOOK} {listed}{where}"
