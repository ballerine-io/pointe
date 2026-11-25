"""Addressed speech: the microphone setting between Always on and Push to talk, "Only when I say Pointe"
(docs/features/addressed-speech.md).

With an open microphone at a desk, Pointe hears a phone call, or a colleague at the door, as a turn. In this mode a
spoken turn is acted on only when its words address Pointe or a session by name. Everything else is side talk: it is
not remembered, not sent to any model or session, and never an answer to a permission request. The rule reads the
recognizer's text only (no second model, no audio), so it costs nothing and adds no wait.

What addresses Pointe:
- the name where a name is called: first ("Pointe, what's billing doing", after "hey", "okay", "so"), or last after a
  comma ("approve it, Pointe"). The name inside a sentence is not a call ("the point is…", "that's a good point").
- the recognizer often writes the name "point", "pointy": taken as the name only at the start with a comma, a full
  stop or a question mark after it, or after "hey" or "okay". "Point taken" and "point of order" are not.
- the name alone ("Pointe?") opens a window of WINDOW_SECS for the next words, which need no name.

What addresses a session: its name first with a comma or a colon ("billing, run the tests"), or after a verb that
hands it work, at the start ("tell docs to…", "ask billing…", "switch to harbor"). A session named for an everyday
word is why the comma or the verb is needed: "docs are in the shared drive" is not for docs.

The name is taken off words for Pointe ("Pointe, yes" is "yes" to everything after it); words for a session go on
whole, since the name is what routes them.

Not gated: typed words, a press (push to talk is its own setting), and the modes that hear everything once started
with the name: a brain dump, a hold ("don't interrupt me"), a challenge, a meeting.
"""

import re
from dataclasses import dataclass

MODE = "addressed"
WINDOW_SECS = 6.0  # after the name alone, the next words are for Pointe

# The words, on the page (ui_addressed.html) and in both apps (AddressedCopy), word for word.
COPY = {
    "setting": "Only when I say Pointe",
    "short": "Say “Pointe”",
    "hint": "Pointe hears everything and acts only on words that start with its name, or a session's: “Pointe, what's billing doing”, "
            "“billing, run the tests”. Anything else is dropped, and its words are not kept.",
    "idle": "Say “Pointe” to talk",
    "open": "Listening",
}

_GREET = r"(?:hey|hay|hi|hello|ok|okay|yo|היי|הי)"  # what follows a greeting is a name ("hay": how "hey" is sometimes written)
_LEAD = rf"(?:(?:{_GREET}|so|um|uh|and|now|alright|right|well|אוקיי|טוב)\b[\s,.!]*)*"
_NAME = r"(?:pointe|פוינט)"
_NEAR = r"(?:pointy|pointee|pointa|pwant|point)"  # how a recognizer without the name in its vocabulary writes it
# After the name with no comma, these make it a sentence about a point, not a call: "point is", "point of order",
# "point one", "point taken", "pointe shoes".
_CONTINUES = {"is", "was", "of", "to", "at", "out", "being", "taken", "that", "about", "where", "in", "on", "shoes", "work",
              "blank", "by", "and", "are", "were", "for", "made", "well", "one", "two", "three", "four", "five", "number",
              "me", "him", "her", "them", "it", "us", "a", "an", "the", "this", "noted", "has", "had", "here", "there"}
# Before the name at the end with no comma, these make it a noun: "a good point", "at this point", "my point".
_BEFORE_A_NOUN = {"a", "an", "the", "my", "your", "his", "her", "their", "our", "its", "good", "fair", "great", "main", "whole",
                  "some", "this", "that", "one", "no", "any", "to", "in", "at", "of", "same", "valid", "key", "starting",
                  "turning", "selling", "breaking", "each", "every", "certain", "what", "which", "en", "on", "by", "another",
                  "data", "bullet", "match", "set", "game", "break", "boiling", "freezing", "melting", "focal", "check", "power",
                  "decimal", "floating", "entry", "end", "access", "talking", "sticking", "pain", "price", "vantage", "view",
                  "tipping", "reference", "mid", "high", "low", "strong", "weak", "moot", "fine", "single", "last", "first",
                  "next", "second", "third", "final", "important", "interesting", "other", "only", "exact", "per", "zero"}
_PUNCT = ",.:;!?"
_FIRST = re.compile(rf"^\W*(?P<lead>{_LEAD})(?P<name>{_NAME}|{_NEAR})\b(?P<sep>[\s,.:;!?—–-]*)(?P<rest>.*)$", re.I | re.S)
_LAST = re.compile(rf"^(?P<rest>.+?)(?P<comma>,?)\s*(?P<name>{_NAME}|{_NEAR}|pointer)(?P<end>[\s.!?]*)$", re.I | re.S)
_VERBS = r"(?:tell|ask|have|get|switch(?: to)?|focus on|go to|back to|תגיד|תגידי|תבקש|תבקשי|תשאל|תשאלי|תעבור)"
# A session's name first with no comma is a call only when what follows is said to someone: a question to "you", or
# an order. "Docs are in the shared drive" and "billing was wrong last month" are about the word.
_TO_SOMEONE = (r"(?:(?:are|did|have|can|could|will|would|do|were) you\b|(?:please|run|rerun|open|update|fix|rebase|stop|continue|add|"
               r"write|check|show|push|pull|commit|revert|test|try|start|finish|read|look|go|make|create|delete|remove|rename|"
               r"merge|deploy|build|review|explain|summarize|summarise|status|what|how|why|where|when)\b)")


@dataclass(frozen=True)
class Address:
    who: str  # "pointe", or the session's name
    rest: str  # the words to act on: for Pointe, the turn with the name off; for a session, the turn whole


def _spoken_forms(name: str) -> list[str]:
    """How a session's name is said: "billing/main" is "billing main" or "billing"; "river-lantern" is "river lantern"."""
    whole = re.sub(r"[\W_]+", " ", name).strip().lower()
    first = re.sub(r"[\W_]+", " ", name.split("/")[0]).strip().lower()
    return [f for f in dict.fromkeys((whole, first)) if f]


def _one_letter_off(a: str, b: str) -> bool:
    """One letter changed, added or dropped, as a recognizer does to a name ("dogs" for "docs", "harbour" for
    "harbor"). Only for names of four letters or more, and only where a name is called."""
    if min(len(a), len(b)) < 4 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long = sorted((a, b), key=len)
    return any(long[:i] + long[i + 1:] == short for i in range(len(long)))


def _session(text: str, sessions) -> str | None:
    forms = sorted(((form, name) for name in sessions for form in _spoken_forms(name)), key=lambda x: -len(x[0]))
    for form, name in forms:
        said = r"[\s-]+".join(re.escape(part) for part in form.split())
        if re.match(rf"^\W*{_LEAD}{said}\s*(?:[,:]|\s{_TO_SOMEONE})", text, re.I):
            return name
        if re.match(rf"^\W*{_LEAD}{_VERBS}\s+(?:the\s+|ל|את\s+)?{said}\b", text, re.I):
            return name
    # "Dogs, what did you change?", "Tell Harbour to rebase": a name one letter off, where a name is called
    called = re.match(rf"^\W*{_LEAD}(?:(?P<first>[^\W\d_]+)\s*[,:]|{_VERBS}\s+(?:the\s+)?(?P<after>[^\W\d_]+)\b)", text, re.I)
    if called:
        word = (called["first"] or called["after"]).lower()
        for form, name in forms:
            if " " not in form and _one_letter_off(word, form):
                return name
    return None


def address(text: str, sessions=()) -> Address | None:
    """Whom these words are for, when they say so; None for side talk. `sessions`: the names on the voice."""
    text = (text or "").strip()
    if not text:
        return None
    m = _FIRST.match(text)
    if m:
        called = bool(re.search(rf"{_GREET}\b", m["lead"], re.I))
        marked = any(c in _PUNCT for c in m["sep"])
        rest = m["rest"].strip()
        first = re.split(r"\W+", rest.lower(), maxsplit=1)[0] if rest else ""
        about_a_point = first in _CONTINUES and not marked and not called  # "Pointe is…", "point of order"
        if not about_a_point and (marked or not rest or bool(m["sep"])):
            return Address("pointe", rest)
    m = _LAST.match(text)
    if m:
        before = re.split(r"\W+", m["rest"].lower().strip())[-1] if m["rest"].strip() else ""
        # ", Pointe" always; with no comma, unless the word before makes it a noun ("a good point", "data point")
        said_no = before == "no" and bool(re.fullmatch(_NAME, m["name"], re.I))  # "No Pointe.": the name as spelled; a no is safe
        if m["comma"] or (before and before not in _BEFORE_A_NOUN) or said_no:
            return Address("pointe", m["rest"].rstrip(" ,") + m["end"].strip()[-1:])
    name = _session(text, sessions)
    return Address(name, text) if name else None


def status(mode: str, open_until: float, now: float, dropped: int) -> dict | None:
    """Status `addressed`: None unless the mode is on. `open`: the name was just said alone, and the next words count."""
    if mode != MODE:
        return None
    return {"on": True, "open": now < open_until, "dropped": dropped}
