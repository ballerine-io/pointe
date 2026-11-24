"""The scripted user (design 4.4): the question detector and the per-item slot answers.

A harness turn is a question if the adapter emits `asked`, or if its last text (the agent's final message in the pty
or the transcript, or what the voice said) ends in a sentence that starts with a wh-word or an auxiliary, ends with a
question mark, or holds "which one", "did you mean" or "do you want".
"""

import re

GENERIC = "Please go on with what I asked."
WH = ("which", "what", "where", "when", "who", "whom", "whose", "why", "how")
AUX = ("do", "does", "did", "should", "shall", "would", "could", "can", "will", "is", "are", "was", "were", "may",
       "might", "must", "have", "has")
PHRASES = ("which one", "did you mean", "do you want", "would you like", "should i", "shall i", "can you confirm",
           "could you clarify", "let me know which")


def last_sentence(text: str) -> str:
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", text.strip()) if p.strip()]
    return parts[-1] if parts else ""


def is_question(text: str) -> bool:
    if not text.strip():
        return False
    low = text.lower()
    tail = last_sentence(text).lower().lstrip("*_`> -")
    first = re.match(r"[a-z']+", tail)
    return (tail.endswith("?") or any(p in low[-400:] for p in PHRASES)
            or bool(first and first.group(0) in WH + AUX and not tail.endswith(".")))
