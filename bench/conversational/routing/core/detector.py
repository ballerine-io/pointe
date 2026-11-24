"""Is a harness turn a question? One fixed rule list, tested on labelled lines (tests/test_conversational_bench.py).

Applied to the text an arm said (Pointe's `speak:` log line, the router's question, a pty's last message), never to
anything the arm labels for itself.
"""

import re

WH = ("which", "what", "where", "who", "whom", "whose", "when", "why", "how")
AUX = ("is", "are", "was", "were", "do", "does", "did", "should", "shall", "can", "could", "would", "will", "want",
       "may", "have", "has", "am")
PRONOUNS = ("you", "i", "it", "that", "this", "we", "they")
PHRASES = ("which one", "did you mean", "do you want", "do you mean", "would you like", "should i", "shall i")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def is_question(text: str) -> bool:
    parts = sentences(text)
    if not parts:
        return False
    if any(s.endswith("?") for s in parts):
        return True
    last = parts[-1].lower()
    words = re.findall(r"[a-z']+", last)
    if not words:
        return False
    if any(p in last for p in PHRASES):
        return True
    # A final sentence that starts like a question but lost its mark (a recognizer transcript): "which one tariff or web"
    starts = words[0] in WH or (words[0] in AUX and len(words) > 2 and words[1] in PRONOUNS)
    return starts and not last.endswith((".", "!"))
