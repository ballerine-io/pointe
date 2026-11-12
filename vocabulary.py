"""Self-learning vocabulary: names the user fixed once, or added, bias recognition from then on.

<state>/dictionary.json, 0600, only on this Mac. The terms go to the ears (Soniox `context.terms`, as session and folder
names already did), to the brain as a spelling line, and to the clean-up rewrite. Three rules hold in code here:

- A term biases recognition toward itself. No approval, refusal or interrupt word is ever a term, from any source
  (a correction, a hand add, an edit, a session's notes, a session or folder name, a hand-edited file): a bias toward
  "yes" could turn a non-answer into a yes.
- Nothing that looks like a credential is learned or kept: `readout.mask`, the one credential rule, decides.
- Learning is narrow: a correction teaches a name or an identifier it fixed, never grammar or wording. The daemon only
  calls `learn` for the owner's own correction of a turn that was heard (not typed), and never during a meeting.
"""

import difflib
import json
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from readout import mask

CAP = 400            # entries in the dictionary, and terms sent to the ears (Soniox caps its context near 8k tokens)
TERMS_CAP = 400
MAX_LEN = 40
PER_CORRECTION = 3
SOFT_PER_SESSION = 12  # names from a session's notes: recognition hints only, never stored
BRAIN_TERMS = 60
HIT_SAVE_SECS = 60.0
LANGS = ("en", "he", "both")
SOURCES = ("correction", "manual", "session")

_TOKEN = re.compile(r"\w[\w.\-/']*\w|\w")
_HEBREW = re.compile(r"[֐-׿]")
_HE_PREFIX = "והשבלמכ"
_SUFFIXES = ("s", "es", "ed", "d", "ing", "er", "ly", "'s", "n't")
# Words a correction may add or swap without teaching anything: the frequent ones, and the everyday words of coding.
COMMON = set("""
a about above after again all also always am an and another any are around as ask at away back be because been before
being below best better between big both but by call came can can't come could day did do does doing done don't down
each even every few find first for from full get give go goes going good got great had has have he her here him his how
i if in into is it its just keep kind know last least left less let like little long look made make many may me might
more most much must my need never new next no not now of off old on once one only or other our out over own part people
place put quite rather really right run said same say see seem she should show since small so some something still such
sure take tell than thank that the their them then there these they thing think this those though through time to too
try turn two under until up us use very want was way we well went were what when where which while who whole why will
with without word work would yes yet you your all add added answer before build bug change changes check code commit
commits config data deploy diff error errors file files fix fixed function home issue last line lines log logs main
make merge open page pass passed please pull push read release repo request review root script server service session
start status stop tell test tests then three today update user version wait write yesterday team whole new old plan
""".split())


@dataclass(frozen=True)
class Candidate:
    term: str
    lang: str


class Full(Exception):
    """The dictionary holds CAP entries: delete one first."""


def _consent() -> tuple[set[str], tuple[str, ...]]:
    import echo
    import guards
    words = guards._YES | guards._NO | guards._WEAK_YES | echo.INTERRUPT_WORDS | echo.ANSWER_WORDS
    phrases = guards._YES_PHRASES + guards._YES_DESPITE_NO
    return {w.lower() for w in words} | {w for p in phrases for w in p.split()}, phrases


def _is_consent_word(part: str, words: set[str]) -> bool:
    if part in words:
        return True
    return bool(_HEBREW.match(part)) and len(part) > 2 and part[0] in _HE_PREFIX and part[1:] in words


def refusal(term: str) -> str | None:
    """Why `term` may not be a recognition term, or None when it may."""
    term = (term or "").strip()
    if len(term) < 2:
        return "too short"
    if len(term) > MAX_LEN:
        return f"longer than {MAX_LEN} characters"
    if unicodedata.normalize("NFKC", term) != term or any(unicodedata.category(c).startswith("C") for c in term):
        return "hidden characters"
    if mask(term) != term:
        return "it looks like a credential"
    words, phrases = _consent()
    lowered = term.lower().replace("’", "'")
    if any(_is_consent_word(p, words) for p in re.split(r"[^\w']+|_", lowered) if p):
        return "a yes, no or stop word: it would bias what counts as an answer"
    if any(re.search(rf"(?<!\w){re.escape(p)}(?!\w)", lowered) for p in phrases):
        return "a yes or no phrase: it would bias what counts as an answer"
    return None


def lang_of(term: str, sentence: str = "") -> str:
    if _HEBREW.search(term):
        return "he"
    return "both" if _HEBREW.search(sentence) else "en"


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text)


def _squash(parts: list[str]) -> str:
    return re.sub(r"[\W_]", "", "".join(parts)).lower()


def _inflected(a: str, b: str) -> bool:
    a, b = a.lower().replace("'", ""), b.lower().replace("'", "")
    if a == b:
        return True
    short, long = sorted((a, b), key=len)
    return any(long == short + s.replace("'", "") for s in _SUFFIXES)


def _identifier(token: str) -> bool:
    return bool(re.search(r"\d|[-._/]", token) or re.search(r"[a-z][A-Z]", token))


def _capitalised(token: str) -> bool:
    return token[:1].isupper() and not _HEBREW.search(token)


def candidates(was: str, meant: str) -> list[Candidate]:
    """What a correction of `was` into `meant` teaches: the names and identifiers it fixed, at most three."""
    if not was or not meant or mask(meant) != meant:
        return []  # a correction that carries a credential teaches nothing at all
    old, new = _tokens(was), _tokens(meant)
    old_low, new_low = [t.lower() for t in old], [t.lower() for t in new]
    match = difflib.SequenceMatcher(None, old_low, new_low, autojunk=False)
    chars = difflib.SequenceMatcher(None, was.lower(), meant.lower(), autojunk=False).ratio()
    if match.ratio() < 0.34 and chars < 0.5 and max(len(old), len(new)) > 3:
        return []  # a different sentence, not a fix of what was heard
    out: list[Candidate] = []
    for op, i1, i2, j1, j2 in match.get_opcodes():
        if op not in ("replace", "insert"):
            continue
        # A name the user also capitalised next to the fix belongs to it: "liver lantern" -> "River Lantern".
        while j1 > 0 and i1 > 0 and _capitalised(new[j1 - 1]) and old[i1 - 1] != new[j1 - 1] and j2 - j1 < 3:
            i1, j1 = i1 - 1, j1 - 1
        while j2 < len(new) and i2 < len(old) and _capitalised(new[j2]) and old[i2] != new[j2] and j2 - j1 < 3:
            i2, j2 = i2 + 1, j2 + 1
        before, after = old[i1:i2], new[j1:j2]
        if before and _squash(before) == _squash(after):
            # "blue bell" -> "bluebell", "orbit api" -> "orbit-api": a spelling the ears split. The other way round is
            # spacing, not a name.
            found = after if len(after) == 1 else []
        elif 2 <= len(after) <= 3 and all(_capitalised(t) for t in after) and op == "replace":
            found = [" ".join(after)]
        else:
            found = [t for k, t in enumerate(after) if _teaches(t, before, op, first=(j1 + k == 0))]
        for term in found:
            if refusal(term) is None and not _HEBREW.search(term) and term.lower() not in {c.term.lower() for c in out}:
                out.append(Candidate(term, lang_of(term, meant)))
    return out[:PER_CORRECTION]


def _teaches(token: str, before: list[str], op: str, first: bool) -> bool:
    if _HEBREW.search(token) or any(_inflected(token, b) for b in before):
        return False  # Hebrew has no capitals and rich inflection: a name is added by hand
    if _identifier(token):
        return True
    if _capitalised(token) and not first:
        return token.lower() not in COMMON or op == "replace"
    return op == "replace" and token.lower() not in COMMON


class Dictionary:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: list[dict] = []
        self.ignored: list[str] = []
        self.problem: str | None = None
        self._saved_at = 0.0
        try:
            raw = path.read_text()
        except OSError:
            return
        try:
            loaded = json.loads(raw)
            self.entries = [e for e in (_entry(x) for x in loaded.get("entries", [])) if e]
            self.ignored = [t for t in loaded.get("ignored", []) if isinstance(t, str) and refusal(t) is None]
        except (ValueError, AttributeError, TypeError):
            self.entries, self.ignored = [], []
            os.replace(path, path.with_name(path.name + ".bad"))
            self.problem = "The dictionary file was damaged. It was set aside and a new one started."

    @property
    def full(self) -> bool:
        return len(self.entries) >= CAP

    def find(self, term: str) -> dict | None:
        key = term.strip().casefold()
        return next((e for e in self.entries if e["term"].casefold() == key), None)

    def add(self, term: str, lang: str | None = None, source: str = "manual", sentence: str = "") -> dict:
        term = (term or "").strip()
        if why := refusal(term):
            raise ValueError(why)
        if lang is not None and lang not in LANGS:
            raise ValueError("lang is en, he or both")
        if self.find(term):
            raise ValueError("already in the dictionary")
        if self.full:
            raise Full(f"the dictionary is full ({CAP}): delete one first")
        entry = {"term": term, "lang": lang or lang_of(term, sentence), "source": source, "hits": 0,
                 "added_at": time.time(), "confirmed": True}
        self.entries.append(entry)
        self.ignored = [t for t in self.ignored if t.casefold() != term.casefold()]
        self.save()
        return entry

    def edit(self, term: str, to: str | None = None, lang: str | None = None) -> dict:
        entry = self.find(term)
        if entry is None:
            raise KeyError(term)
        if to is not None:
            to = to.strip()
            if why := refusal(to):
                raise ValueError(why)
            if (other := self.find(to)) is not None and other is not entry:
                raise ValueError("already in the dictionary")
            entry["term"] = to
        if lang is not None:
            if lang not in LANGS:
                raise ValueError("lang is en, he or both")
            entry["lang"] = lang
        self.save()
        return entry

    def delete(self, term: str) -> bool:
        entry = self.find(term)
        if entry is None:
            return False
        self.entries.remove(entry)
        self.save()
        return True

    def ignore(self, term: str) -> None:
        term = term.strip()
        if term and term.casefold() not in {t.casefold() for t in self.ignored}:
            self.ignored.append(term)
            self.save()

    def unignore(self, term: str) -> bool:
        kept = [t for t in self.ignored if t.casefold() != term.strip().casefold()]
        changed = len(kept) != len(self.ignored)
        self.ignored = kept
        if changed:
            self.save()
        return changed

    def learn(self, was: str, meant: str) -> list[dict]:
        learned = []
        for c in candidates(was, meant):
            if self.full:
                break
            if self.find(c.term) is None:
                learned.append(self.add(c.term, c.lang, source="correction"))
        return learned

    def heard(self, text: str) -> None:
        """A final transcript: each term in it counts a hit, which orders what the cap keeps. Never adds a term."""
        lowered = text.casefold()
        changed = False
        for e in self.entries:
            if re.search(rf"(?<!\w){re.escape(e['term'].casefold())}(?!\w)", lowered):
                e["hits"] += 1
                changed = True
        if changed and time.time() - self._saved_at >= HIT_SAVE_SECS:
            self.save()

    def ranked(self) -> list[str]:
        return [e["term"] for e in sorted(self.entries, key=lambda e: -e["hits"])]

    def learned_since(self, at: float) -> list[dict]:
        return [{"term": e["term"], "at": e["added_at"]} for e in self.entries
                if e["source"] == "correction" and e["added_at"] >= at]

    def suggestions(self, brief_names: dict[str, list[str]], session_names: list[str] = ()) -> list[dict]:
        """Names from the sessions' notes, not yet known, ignored or a session's own name (that is a hint already)."""
        seen = ({e["term"].casefold() for e in self.entries} | {t.casefold() for t in self.ignored}
                | {n.casefold() for n in session_names})
        out = []
        for session, names in brief_names.items():
            for name in names[:SOFT_PER_SESSION]:
                name = soft_name(name)
                if refusal(name) is None and name.casefold() not in seen:
                    seen.add(name.casefold())
                    out.append({"term": name, "session": session, "lang": lang_of(name)})
        return out

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"entries": self.entries, "ignored": self.ignored}, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)
        self._saved_at = time.time()


def _entry(x) -> dict | None:
    if not isinstance(x, dict) or not isinstance(x.get("term"), str) or refusal(x["term"]) is not None:
        return None
    return {"term": x["term"].strip(), "lang": x.get("lang") if x.get("lang") in LANGS else lang_of(x["term"]),
            "source": x.get("source") if x.get("source") in SOURCES else "manual",
            "hits": x["hits"] if isinstance(x.get("hits"), int) and x["hits"] >= 0 else 0,
            "added_at": float(x["added_at"]) if isinstance(x.get("added_at"), (int, float)) else 0.0, "confirmed": True}


def soft_name(name) -> str:
    """A name from a session's notes, without the reader's remarks: "Kestrelbay (the build bot)" -> "Kestrelbay"."""
    return re.sub(r"\s*[(\[][^)\]]*[)\]]", "", str(name)).strip()


def terms_for(book: Dictionary, session_names: list[str], brief_names: dict[str, list[str]], folders: list[str]) -> list[str]:
    """What the ears are told, most important first: the dictionary (most heard first), session names, names from the
    sessions' notes (soft, a few each), folder names. Consent words and credentials are dropped from every source."""
    ordered = [*book.ranked(), *session_names]
    for names in brief_names.values():
        ordered += [soft_name(n) for n in names[:SOFT_PER_SESSION]]
    ordered += folders
    out, seen = [], set()
    for term in ordered:
        term = term.strip()
        if term.casefold() in seen or refusal(term) is not None:
            continue
        seen.add(term.casefold())
        out.append(term)
    return out[:TERMS_CAP]


def brain_line(book: Dictionary) -> str | None:
    terms = book.ranked()[:BRAIN_TERMS]
    return f"[names the user uses, spell them this way in anything you send] {', '.join(terms)}" if terms else None

