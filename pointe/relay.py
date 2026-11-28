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


_CODE_PLACE = re.compile(r"\b(?:above|below|before|after|in|inside|into|to|from|of|on)\s+(?:the\s+)?([a-z]{3,})\s+([a-z]{3,})\b",
                         re.I)


def _near_names(message: str, known: set[str]) -> list[tuple[str, str]]:
    """("group rows", "dedupe_rows"): two words in a code place ("above the group rows") that are no name in the code,
    when exactly one name there ends with the second word. rec-03 in tester round 6: "dedupe rows" heard in babble."""
    names = {k.lower() for k in known if "_" in k}
    found = []
    for m in _CODE_PLACE.finditer(message):
        first, last = m.group(1).lower(), m.group(2).lower()
        if f"{first}_{last}" in names or f"{first}{last}" in {k.lower() for k in known}:
            continue
        ends = sorted(n for n in names if n.endswith(f"_{last}") and not n.startswith(f"{first}_"))
        if len(ends) == 1:
            found.append((f"{m.group(1)} {m.group(2)}", ends[0]))
    return found


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
    naming = _NAMING_CUE.search(said) or re.search(r"\b(?:renam\w*|call (?:it|that)|name (?:it|that))\b", said, re.I)
    near = [] if naming else _near_names(message, known)  # "rename it to compute tax" names a new one
    if not (marked or hints or near or _NAMING_CUE.search(said)):
        return message
    note = f'\n\n(Said by voice. The speech recognizer heard: "{said.strip()}". A name in it may be misheard: a name ' \
           f'that should already exist means the closest one in the code.'
    for heard, meant, hint in hints:
        note += f' "{heard}, as in {hint}" means the word "{meant}".'
        named = sorted(k for k in known if meant in _split(k))
        if named:
            note += f" This session's names with it: {', '.join(named[:3])}."
    for heard, name in near:
        note += f' "{heard}" is not a name in this code; {name} is the closest: if that is what was meant, use it, ' \
                f'and if unsure, ask.'
    return message + note + ")"


# ---------- names as the code has them ----------

_SOURCE = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rb", ".rs", ".java", ".kt", ".swift", ".sh")
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "target"}
_DEFINES = re.compile(r"^\s*(?:async\s+)?(?:def|class|function|func|fn|const|let|var|type|interface|struct|enum)\s+"
                      r"([A-Za-z_][A-Za-z0-9_]{2,})", re.M)
_CODE_NAMES: dict[str, tuple[float, tuple[dict[str, set[str]], set[str]]]] = {}
CODE_NAMES_SECS = 60.0  # how long one folder's index is reused
MAX_FILES, MAX_BYTES = 1500, 200_000


def _key(name: str) -> str:
    return re.sub(r"[_\-\s]+", "", name).lower()


def _index(folder: str | None) -> tuple[dict[str, set[str]], set[str]]:
    """One bounded walk of a project's source files, kept for a minute: the names its code defines, by key (code_names),
    and every word in it (code_words)."""
    import os
    import time
    if not folder or not os.path.isdir(folder):
        return {}, set()
    now = time.time()
    cached = _CODE_NAMES.get(folder)
    if cached and now - cached[0] < CODE_NAMES_SECS:
        return cached[1]
    index: dict[str, set[str]] = {}
    words: set[str] = set()
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
            words.add(stem)
            try:
                with open(os.path.join(root, f), errors="ignore") as fh:
                    text = fh.read(MAX_BYTES)
            except OSError:
                continue
            for name in _DEFINES.findall(text):
                index.setdefault(_key(name), set()).add(name)
            words.update(_WORD.findall(text))
        if seen > MAX_FILES:
            break
    _CODE_NAMES[folder] = (now, (index, words))
    return index, words


_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def code_names(folder: str | None) -> dict[str, set[str]]:
    """The names a project's code defines (functions, classes, constants) and its source files' names, by key: lower
    case with underscores, dashes and spaces dropped. Read from disk, a bounded walk, kept for a minute."""
    return _index(folder)[0]


def code_words(folder: str | None) -> set[str]:
    """Every word in a project's source, case kept: names, and the words inside its strings ('record["ts"]' has ts)."""
    return _index(folder)[1]


# ---------- letters said aloud ----------

# The user said the case: then a capital is theirs.
_CASE_CUE = re.compile(r"\b(?:capital|capitals|capitali[sz]ed|upper ?case|all caps|in caps|caps)\b", re.I)
_SAID_TOKEN = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)*")  # "it's" is one word, not "it" and a letter s
_SPELLED_IN_MESSAGE = re.compile(r"(?<![\w-])[A-Z](?:(?:-|, ?| )[A-Z](?![\w]))+")
_CAPITALS = re.compile(r"(?<![\w-])(\d*)([A-Z][A-Z_]*)(?![\w])|(?<=_)([A-Z]+)(?=_)")


def _spelled(said: str) -> tuple[set[str], set[str]]:
    """What the user said letter by letter: the words of runs of single letters ("G, I, M, B, A, L" is gimbal, "t s"
    is ts) and the letters said on their own ("ends in s", "90 S", "90s"), in lower case."""
    tokens = _SAID_TOKEN.findall(said)
    runs: set[str] = set()
    alone: set[str] = set()
    run: list[str] = []
    for token in tokens + [""]:
        if len(token) == 1 and token.isalpha():
            run.append(token.lower())
            continue
        if len(run) == 1:
            alone.add(run[0])
        elif run:
            runs.add("".join(run))
        run = []
        if m := re.fullmatch(r"\d+([A-Za-z])", token):
            alone.add(m.group(1).lower())
    return runs, alone


def letter_case(message: str, said: str, words: set[str]) -> str:
    """The message with each letter the user said aloud written in lower case: speech has no case, and the recognizer
    writes a letter said on its own as a capital ("ends in s" heard "ends in S"). A capital stays when the user said the
    case ("all caps", "capital"), when the code has the word in capitals, and for a word nobody spelled ("JPY") unless
    the code has it only in lower case ("TS" for the code's ts). `words`: the session's code words (code_words)."""
    if _CASE_CUE.search(said):
        return message
    runs, alone = _spelled(said)
    lower_words = {w for w in words if w.islower()}

    def run(m: re.Match) -> str:  # "G-I-M-B-A-L" in the brain's words, for gimbal spelled
        letters = re.sub(r"[^A-Z]", "", m.group(0))
        return m.group(0).lower() if letters.lower() in runs else m.group(0)

    message = _SPELLED_IN_MESSAGE.sub(run, message)

    def capitals(m: re.Match) -> str:
        if m.group(3):  # GIMBAL inside __GIMBAL__
            digits, letters = "", m.group(3)
        else:
            digits, letters = m.group(1), m.group(2)
        word = digits + letters
        if word in words or letters in words or (not digits and letters in ("I", "A")):
            return m.group(0)
        core = letters.strip("_").lower()
        # The code's case settles a short word of letters ("TS" for its ts), never a file name or a longer word that
        # is written in capitals by convention (README.md, TODO).
        as_code = len(word) <= 3 and word.lower() in lower_words and not re.match(r"\.\w", m.string[m.end():])
        if as_code or core in runs or (len(core) == 1 and core in alone):
            return m.group(0).lower()
        return m.group(0)

    return _CAPITALS.sub(capitals, message)


_CAMEL_OR_SNAKE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[A-Z][a-z0-9]+|_[A-Za-z0-9]+)+\b")
# Where a spoken name stands: after "function"/"class", or after a preposition ("a docstring to dedupe rows").
_NAME_CUES = (re.compile(r"\b(?:function|method|class|constant|variable|helper)\s+((?:[a-z][a-z0-9]*\s+){0,2}[a-z][a-z0-9]*)\b"),
              re.compile(r"\b(?:to|in|into|above|below|for|of|on|from|inside)\s+(?:the\s+)?"
                         r"(?!(?:function|method|class|file)\b)((?:[a-z][a-z0-9]*\s+){0,2}[a-z][a-z0-9]*)\b"))


# The recognizer's spellings of words of the trade (tester round 5: "dark string", "unitist", "Uniris", "UNIREST").
_TRADE_SPELLINGS = {"docstring": r"([\"'“‘])?\b(?:dark|doc|dock)\b[\"'”’]? ?strings?\b(?(1)[\"'”’]?)", "unittest": r"\b(?:uni(?:tist|ris|rest|t ?test)|unit ?tist)\b"}
# "Convert hero dot png to webp" is heard "to web" (lat-04, by Soniox and by Whisper): an image converted to "web" is WebP,
# and "web" that is a place ("move it to web", "web folder") or a thing of the web ("a web app", "web-safe") stays.
_IMAGE_TO_WEB = re.compile(
    r"\b((?:convert|re-?encode|encode|transcode)\w*\b[^.?!]{0,60}?"
    r"(?:\.(?:png|jpe?g|gif|tiff?|bmp)\b|\b(?:pngs?|jpe?gs?|gifs?|images?|pictures?|photos?|screenshots?)\b)"
    r"[^.?!]{0,30}?\b(?:to|into|as)\s+)web\b(?![-\w])(?!\s+(?:folder|dir|directory|page|site|app|server)s?\b)", re.I)


def trade_words(message: str, known: set[str]) -> str:
    """The message with a recognizer's spelling of a word of the trade written as the trade writes it ("dark string" is
    docstring), unless the session's own code uses the heard word (`known`, lower case), and an image converted to "web"
    converted to WebP (whatever the code calls "web")."""
    for word, pattern in _TRADE_SPELLINGS.items():
        def fix(m: re.Match, word: str = word) -> str:
            heard = re.sub(r"[\"'“”‘’]", "", m.group(0))  # the model may quote the misheard word: 'a "dark" string'
            if heard.lower().replace(" ", "") in known or heard.lower() in known:
                return m.group(0)
            return word + ("s" if heard.lower().endswith("strings") else "")
        message = re.sub(pattern, fix, message, flags=re.I)
    return _IMAGE_TO_WEB.sub(r"\1WebP", message)


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
