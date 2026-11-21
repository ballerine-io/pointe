"""How to use Pointe, answered on this Mac from product_help.json (docs/design/product-help.md). No network, no model.

The file is written by tools/product_help.py from the UI code and a few hand-written topics. `answer` gives the brain's
how_to_use_pointe tool the one to three entries that fit a question, with the path on the surface the user is on.
`about_pointe` tells the send gate that the user's words ask how to use Pointe, so they are not relayed to a session.
"""

import difflib
import json
import re
from functools import lru_cache
from pathlib import Path

HELP = Path(__file__).resolve().parent / "product_help.json"
MAX_ENTRIES = 3

_STOP = set("a an the to of in on at for and or is are be it its this that my me i you your we do does did how can could "
            "where what which why when there here with from by as so up out off get turn use using make let just please "
            "pointe app page iphone phone voice want would should will".split())
_HE_STOP = {"את", "של", "על", "אני", "איך", "מה", "זה", "לי", "לך", "אם", "גם", "יש", "אפשר", "איפה", "אותך", "אותו"}
_HE_PREFIX = "הבלמשכ"
_HEBREW = re.compile(r"[֐-׿]")


def _stem(word: str) -> str:
    """English: "sessions", "renaming", "paired" and "mute" reduce to one form; the same on both sides is all it needs."""
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    if len(word) > 4 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 3 and word.endswith("ed"):
        word = word[:-2]
    return word[:-1] if len(word) > 3 and word.endswith("e") else word


def _he_root(word: str) -> str:
    """Hebrew: one leading ו and one of ה ב ל מ ש כ come off, when three letters stay ("ולהשתיק" is "השתיק")."""
    if word.startswith("ו") and len(word) > 3:
        word = word[1:]
    return word[1:] if word[:1] in _HE_PREFIX and len(word) > 3 else word


def _tokens(text: str) -> list[str]:
    text = text.lower().replace("’", "'").replace("'", "")
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", text)]


@lru_cache(maxsize=1)
def _load() -> tuple:
    data = json.loads(HELP.read_text())
    index = []
    for e in data["entries"]:
        en, he = [], []
        for phrase in e["ask"]:
            if _HEBREW.search(phrase):
                roots = [_he_root(w) for w in re.findall(r"[֐-׿]+", phrase) if w not in _HE_STOP]
                he.append(tuple(r for r in roots if len(r) >= 2))
            else:
                en.append(tuple(_tokens(phrase)))
        labels = " ".join([e["title"]] + e.get("iphone", []) + e.get("page", []))
        index.append((e, en, he, {t for t in _tokens(labels) if t not in _STOP and len(t) > 2}))
    return data, index


def _contains(seq: list[str], part: tuple) -> bool:
    n = len(part)
    return n > 0 and any(tuple(seq[i:i + n]) == part for i in range(len(seq) - n + 1))


def _scored(question: str) -> list[tuple[float, bool, dict]]:
    """(score, strong, entry), best first. A phrase found whole scores two per word; "strong" means a phrase of two
    words or more was found. A word of an entry's title or path adds a half; a near spelling ("enroll") of a one-word
    phrase adds one."""
    _data, index = _load()
    words = _tokens(question)
    hebrew = " ".join(re.findall(r"[֐-׿]+", question))
    content = {w for w in words if w not in _STOP and len(w) > 2}
    out = []
    for e, en, he, labels in index:
        score, strong = 0.0, False
        for part in en:
            if _contains(words, part):
                score += 2 * len(part)
                strong |= len([w for w in part if w not in _STOP]) >= 2
        for roots in he:
            if roots and all(r in hebrew for r in roots):
                score += 2 * len(roots)
                strong |= len(roots) >= 2
        score += 0.5 * len(content & labels)
        singles = {p[0] for p in en if len(p) == 1 and len(p[0]) >= 5}
        for w in content - {p[0] for p in en if len(p) == 1}:
            if len(w) >= 5 and difflib.get_close_matches(w, singles, n=1, cutoff=0.85):
                score += 1
        if score:
            out.append((score, strong, e))
    out.sort(key=lambda x: -x[0])
    return out


def lookup(question: str, n: int = MAX_ENTRIES) -> list[dict]:
    """The entries that fit, best first: at most `n`, each scoring at least two and half the best."""
    scored = _scored(question)
    if not scored or scored[0][0] < 2:
        return []
    return [e for score, _strong, e in scored[:n] if score >= max(2.0, scored[0][0] / 2)]


_ASKS = re.compile(r"^\W*(?:(?:so|and|ok(?:ay)?|hey|um|tell me)\W+)*(?:how|where|what|which|can|could|is there|why|do you know how)\b"
                   r"|\?\s*$|(?:^|\s)(?:איך|איפה|מאיפה|כיצד|אפשר|יש דרך|מה עושים|למה)(?:\s|$)", re.I)
_CODE = re.compile(r"\b(?:code|function|endpoint|files?|tests?|bug|repo|branch|pr|commit|implement|refactor|daemon|api|"
                   r"class|module|swift|python|deploy|build|fix|cookie|database|schema)\b|קוד|באג", re.I)


def about_pointe(text: str) -> bool:
    """The words ask how to use Pointe itself ("how do I turn off push to talk?", "איפה נעילת קול?"): a question, about
    a feature by a phrase of two words or more or by Pointe's name, and not about code."""
    if not text or not _ASKS.search(text) or _CODE.search(text):
        return False
    scored = _scored(text)
    if not scored or scored[0][0] < 2:
        return False
    return scored[0][1] or bool(re.search(r"\bpointe\b|פוינט", text, re.I))


def answer(question: str, surface: str) -> dict:
    """The tool's result: the entries for `question`, each with where it is on `surface` ("iphone" or "page"), what
    the user can say instead, and the tool that does it when they ask."""
    data, _ = _load()
    names, other = data["surfaces"], "page" if surface == "iphone" else "iphone"
    found = lookup(question)
    if not found:
        return {"screen": names[surface], "found": "nothing",
                "say": "Say you are not sure, and that the settings are in " + (
                    "Settings, the ••• button at the top right." if surface == "iphone" else "Settings, in the Sessions panel.")}
    items = []
    for i, e in enumerate(found):
        item = {"topic": e["title"]}
        if e["how"]:
            item["how"] = e["how"]
        if i == 0 and e.get("about"):
            item["about"] = e["about"]
        if e.get(surface):
            item["where"] = "; or ".join(e[surface])
        elif e.get(other):
            item["where"] = f"not on {names[surface]}; on {names[other]}: " + "; or ".join(e[other])
        if note := e.get(f"{surface}_note"):
            item["note"] = note
        if e.get("voice"):
            item["say_instead"] = e["voice"]
        if e.get("tool"):
            item["your_tool"] = e["tool"]
        items.append(item)
    out = {"screen": names[surface], "answers": items}
    if surface == "page" and any("Settings →" in item.get("where", "") for item in items):
        out["settings_are"] = "the Settings button at the bottom of the Sessions panel on the left"
    return out
