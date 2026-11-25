"""What the voice adds to a message it relays, so a misheard name reaches the agent as heard, not as an invented one.

The brain writes a brief, and from misheard words it wrote code names that do not exist: "past moon phase" became
`pastMoonPhase` and "get tied table" `getTiedTable`, and the agent found nothing to change. The words as heard led the
agent to `parseMoonPhase` and `getTideTable` (the Spoken Identifiers benchmark). So a code name the brain built from the
user's words goes back to those words, the words as heard ride along when the user named something, and a spoken
homophone hint ("right, as in writing") is resolved here, never by a model.
"""

import re

# A name the brain may have built: camelCase with an inner capital, or snake_case.
_IDENT = re.compile(r"(?<![\w./-])(?:[a-z][a-z0-9]*(?:[A-Z][a-z0-9]+)+|[A-Za-z][a-z0-9]*(?:_[A-Za-z0-9]+)+)(?![\w/-])")
# The user said how a name is written, or spelled a part of it: the words as heard are what the agent should match.
_NAMING_CUE = re.compile(r"\b(?:camel ?case|snake ?case|kebab ?case|pascal ?case|upper ?case|lower ?case|all caps|dunder|"
                         r"underscore|as in|spell(?:ed|s)?|capital|dash dash|dot py|singular|plural)\b", re.I)
# Words a recognizer swaps, in groups. "<heard> as in <hint>" picks the member the hint begins like.
HOMOPHONES = [
    {"right", "write", "rite"}, {"peak", "peek", "pique"}, {"tide", "tied"}, {"past", "passed"}, {"read", "red"},
    {"wait", "weight"}, {"cell", "sell"}, {"site", "sight", "cite"}, {"role", "roll"}, {"plain", "plane"},
    {"brake", "break"}, {"sum", "some"}, {"hole", "whole"}, {"new", "knew"}, {"pair", "pear", "pare"},
    {"mail", "male"}, {"by", "buy", "bye"}, {"four", "for"}, {"two", "to", "too"}, {"seen", "scene"},
    {"base", "bass"}, {"cache", "cash"}, {"sort", "sought"}, {"key", "quay"}, {"route", "root"}, {"suite", "sweet"},
]
_HINT = re.compile(r"\b(?P<heard>[a-z]+)\s*,?\s+as in\s+(?P<hint>[a-z]+)", re.I)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _split(name: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", name.replace("_", " "))]


def _contains(words: list[str], part: list[str]) -> bool:
    n = len(part)
    return n > 0 and any(words[i:i + n] == part for i in range(len(words) - n + 1))


def homophone_hints(said: str) -> list[tuple[str, str, str]]:
    """("right", "write", "writing") for "right, as in writing": the word heard, the one its hint means, the hint."""
    out = []
    for m in _HINT.finditer(said):
        heard, hint = m["heard"].lower(), m["hint"].lower()
        group = next((g for g in HOMOPHONES if heard in g), None)
        if not group:
            continue
        meant = [w for w in group if hint == w or len(w) >= 3 and hint.startswith(w[:max(3, len(w) - 1)])]
        if len(meant) == 1 and meant[0] != heard:
            out.append((heard, meant[0], hint))
    return out


_STYLES = {"camelcase", "snake_case", "pascalcase", "kebab_case", "camel_case", "screaming_snake_case"}


def keep_lines(message: str, said: str) -> str:
    """Typed words that span lines keep their line breaks to the session. When the brain's message carries the typed
    words whole, flattened to one line, they are put back as typed; a message in the brain's own words is left alone.
    Spoken words have no line breaks: nothing changes for them."""
    if "\n" not in said.strip() or "\n" in message:
        return message
    flat_said, flat = " ".join(said.split()), " ".join(message.split())
    at = flat.find(flat_said)
    if at < 0:
        return message
    return flat[:at] + said.strip() + flat[at + len(flat_said):]


def as_heard(message: str, said: str, known: set[str] = frozenset()) -> str:
    """The message with each code name the brain built from the user's words marked with those words as heard, and,
    when the user named something, what the recognizer heard and how to read a homophone hint. The name stays: it may
    be a new name the user asked for ("rename it to compute tax"). `known`: this session's own vocabulary; a name in it,
    or one the user said or spelled, is left alone."""
    words = _words(said)
    spoken = {w.lower() for w in re.findall(r"[\w]+", said)}
    marked: set[str] = set()

    def mark(m: re.Match) -> str:
        name = m.group(0)
        parts = _split(name)
        if name in known or name.lower() in spoken | _STYLES or name in marked or len(parts) < 2 \
                or not _contains(words, parts):
            return name
        marked.add(name)
        closing = '"' if m.end() < len(message) and message[m.end()] == '"' else ""
        if closing:  # "getTiedTable" stays one quoted name, with the words after it
            return name
        return f'{name} (heard as "{" ".join(parts)}")'

    message = _IDENT.sub(mark, message)
    for name in list(marked):  # a quoted name gets its words after the closing quote
        message = message.replace(f'"{name}"', f'"{name}" (heard as "{" ".join(_split(name))}")', 1)
    hints = homophone_hints(said)
    if not (marked or hints or _NAMING_CUE.search(said)):
        return message
    note = f'\n\n(Said by voice. The speech recognizer heard: "{said.strip()}". A name in it may be misheard: a name ' \
           f'that should already exist means the closest one in the code.'
    for heard, meant, hint in hints:
        note += f' "{heard}, as in {hint}" means the word "{meant}".'
        named = sorted(k for k in known if meant in _split(k))
        if named:
            note += f" This session's names with it: {', '.join(named[:3])}."
    return message + note + ")"


# ---------- names as the code has them ----------

_SOURCE = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rb", ".rs", ".java", ".kt", ".swift", ".sh")
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "target"}
_DEFINES = re.compile(r"^\s*(?:async\s+)?(?:def|class|function|func|fn|const|let|var|type|interface|struct|enum)\s+"
                      r"([A-Za-z_][A-Za-z0-9_]{2,})", re.M)
_CODE_NAMES: dict[str, tuple[float, dict[str, set[str]]]] = {}
CODE_NAMES_SECS = 60.0  # how long one folder's index is reused
MAX_FILES, MAX_BYTES = 1500, 200_000


def _key(name: str) -> str:
    return re.sub(r"[_\-\s]+", "", name).lower()


def code_names(folder: str | None) -> dict[str, set[str]]:
    """The names a project's code defines (functions, classes, constants) and its source files' names, by key: lower
    case with underscores, dashes and spaces dropped. Read from disk, a bounded walk, kept for a minute."""
    import os
    import time
    if not folder or not os.path.isdir(folder):
        return {}
    now = time.time()
    cached = _CODE_NAMES.get(folder)
    if cached and now - cached[0] < CODE_NAMES_SECS:
        return cached[1]
    index: dict[str, set[str]] = {}
    seen = 0
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for f in files:
            if not f.endswith(_SOURCE):
                continue
            seen += 1
            if seen > MAX_FILES:
                break
            stem = f.rsplit(".", 1)[0]
            index.setdefault(_key(stem), set()).add(stem)
            try:
                with open(os.path.join(root, f), errors="ignore") as fh:
                    text = fh.read(MAX_BYTES)
            except OSError:
                continue
            for name in _DEFINES.findall(text):
                index.setdefault(_key(name), set()).add(name)
        if seen > MAX_FILES:
            break
    _CODE_NAMES[folder] = (now, index)
    return index


_CAMEL_OR_SNAKE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[A-Z][a-z0-9]+|_[A-Za-z0-9]+)+\b")
# Where a spoken name stands: after "function"/"class", or after a preposition ("a docstring to dedupe rows").
_NAME_CUES = (re.compile(r"\b(?:function|method|class|constant|variable|helper)\s+((?:[a-z][a-z0-9]*\s+){0,2}[a-z][a-z0-9]*)\b"),
              re.compile(r"\b(?:to|in|into|above|below|for|of|on|from|inside)\s+(?:the\s+)?"
                         r"(?!(?:function|method|class|file)\b)((?:[a-z][a-z0-9]*\s+){0,2}[a-z][a-z0-9]*)\b"))


# The recognizer's spellings of words of the trade (tester round 5: "dark string", "unitist", "Uniris", "UNIREST").
_TRADE_SPELLINGS = {"docstring": r"\b(?:dark|doc|dock) ?strings?\b", "unittest": r"\b(?:uni(?:tist|ris|rest|t ?test)|unit ?tist)\b"}


def trade_words(message: str, known: set[str]) -> str:
    """The message with a recognizer's spelling of a word of the trade written as the trade writes it ("dark string" is
    docstring), unless the session's own code uses the heard word (`known`, lower case)."""
    for word, pattern in _TRADE_SPELLINGS.items():
        def fix(m: re.Match, word: str = word) -> str:
            heard = m.group(0)
            if heard.lower().replace(" ", "") in known or heard.lower() in known:
                return heard
            return word + ("s" if heard.lower().endswith("strings") else "")
        message = re.sub(pattern, fix, message, flags=re.I)
    return message


def repo_names(message: str, names: dict[str, set[str]]) -> str:
    """The message with each code name it spells otherwise ("loadBatches", "the function dedupe rows") written as the
    code has it, when exactly one name in the code matches it. Names the code does not have are left alone."""
    if not names:
        return message

    def exact(word: str) -> str | None:
        found = names.get(_key(word))
        return next(iter(found)) if found and len(found) == 1 else None

    def camel(m: re.Match) -> str:
        real = exact(m.group(0))
        return real if real and real != m.group(0) else m.group(0)

    out = _CAMEL_OR_SNAKE.sub(camel, message)

    def cued(m: re.Match) -> str:
        phrase = m.group(1)
        words = phrase.split()
        for n in range(len(words), 1, -1):  # the longest run of the words after "function" that names one thing
            real = exact(" ".join(words[:n]))
            if real:
                start = m.start(1) - m.start(0)
                return m.group(0)[:start] + real + (" " + " ".join(words[n:]) if words[n:] else "")
        return m.group(0)

    for cue in _NAME_CUES:
        out = cue.sub(cued, out)
    return out
