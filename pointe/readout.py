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
    "cat": (set("-n".split()), set(), set(), set()),
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
_URL_PATH = 60  # a URL's path longer than this is not read out: it is said whole or not at all
_SAFE_VARIABLES = {"CI", "NODE_ENV", "DEBUG", "TZ", "LANG", "LC_ALL", "NO_COLOR", "FORCE_COLOR", "TERM"}
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


def place(path: str, cwd: str | None) -> str:
    """Plainly inside the project: its name. Anywhere else, through a hidden folder, or through a symlink that leaves the
    project: the whole path."""
    if ":" in path or "@" in path:
        return path  # host:path is another machine
    full = os.path.normpath(os.path.join(cwd or "/", os.path.expanduser(path))) if cwd else None
    if not full or not cwd:
        return path
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


_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_EMPTY_FILE = re.compile(r"^\s*(?::|true)?\s*>\s*(?P<file>[^\s;&|<>]+)\s*$")


def _python_calls(code: str, cwd: str | None) -> list[str] | None:
    """`python3 -c` code that only imports the project's own modules and calls their functions with literal arguments
    that hold no string, printed or not: the functions it calls, in order. None for anything else (the tap answers it)."""
    if not cwd:
        return None
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return None
    local, calls = {}, []

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

    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for a in stmt.names:
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
        elif isinstance(stmt, ast.Expr):
            node = stmt.value
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print" \
                    and "print" not in local and not node.keywords:
                inner = [call(a) or ("" if literal(a) else None) for a in node.args]
            else:
                inner = [call(node)]
            if None in inner:
                return None
            calls += [c for c in inner if c]
        else:
            return None
    return calls or None


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
    if run_in and (not cwd or os.path.normpath(run_in) != os.path.normpath(cwd)):
        here = os.path.normpath(run_in)
        words.append(f"in {place(here, cwd)},")
    moved = False  # a cd has been read as taken: from here on only "&&" may follow, or what runs may not be where it says
    unsure = False  # an "||" or "|" came before: a cd after it may not run, or runs in a subshell
    echoed: list[str] = []
    positionals, pattern_given = 0, False  # grep and rg: the first positional is the pattern unless -e gave one

    def at(path: str) -> str:
        if here == cwd or path.startswith(("/", "~")) or not here:
            return place(path, cwd)
        return place(os.path.join(here, path), cwd)
  # what to do with this word, set by the flag before it
    for token, was_quoted in zip(tokens, quoted):
        if was_quoted and token.startswith("-"):
            return None  # a flag in quotes is still a flag: never "some text"
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
            if token == "-I" and not was_quoted:
                continue  # isolated mode: less is loaded, nothing more runs
            if token not in ("-m", "-c") or was_quoted:
                return None
            sub = token
            continue
        if program in ("python", "python3") and sub == "-c":  # never read out: which project functions it calls
            calls = _python_calls(token, cwd) if was_quoted and here == cwd else None
            if not calls:
                return None
            named = list(dict.fromkeys(calls))
            words.append(f"code calling {', '.join(named[:4])}" + (f" and {len(named) - 4} more" if len(named) > 4 else ""))
            sub = "code"
            continue
        if program in ("python", "python3") and sub == "code":
            return None  # arguments to the code: sys.argv can steer it
        if program in ("python", "python3") and sub == "-m":
            if token not in ("pytest", "unittest"):
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
            if program in ("grep", "rg") and token.split("=", 1)[0] in ("-e", "--regexp"):
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
            if program not in ("grep", "rg") or positionals > 1 or pattern_given:
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
    if redirect or then or program is None:
        return None
    text = " ".join(w for w in words if w)
    return text if len(text.split()) <= WORDS else None
