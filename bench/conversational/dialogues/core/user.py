"""The question detector, the same as HLK's (bench/conversational/hlk/core/user.py, tested there on 48 labelled
lines): a reply counts as a question by its last sentence."""

import re

WH = re.compile(r"^(what|which|where|when|who|whom|whose|why|how)\b")
AUX = re.compile(r"^(do|does|did|should|shall|can|could|would|will|is|are|was|were|have|has|may|might|want|"
                 r"ok|okay|any|anything)\b")
PHRASES = re.compile(r"\b(which one|did you mean|do you want|would you like|should i|shall i|want me to|"
                     r"can you confirm|could you confirm|please confirm|which (file|function|session|name|test|one))\b")


def sentences(text: str) -> list:
    parts = re.split(r"(?<=[.!?])\s+|\n+", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def is_question(text: str) -> bool:
    """A harness turn is a question when its final sentence ends with "?", starts with a wh-word or an auxiliary,
    or the last two sentences hold "which one", "did you mean", "do you want" and the like."""
    sents = sentences(re.sub(r"[*_`#>]", "", text or ""))
    if not sents:
        return False
    last = sents[-1].lower().strip(" \"'")
    if last.endswith("?"):
        return True
    first = re.sub(r"^(so|and|but|okay|ok|great|alright|sure|also),?\s+", "", last)
    if WH.match(first) or AUX.match(first):
        return True
    return any(PHRASES.search(s.lower()) for s in sents[-2:])
