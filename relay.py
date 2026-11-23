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
