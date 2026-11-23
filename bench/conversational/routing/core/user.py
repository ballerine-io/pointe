"""The scripted user's answer to a question from the harness, chosen by fixed rules (no model).

The which_session slot: a question that offers several sessions or asks which one gets the turn's answer line; a
confirmation that names exactly the intended sessions gets "yes"; one that names other sessions gets "No, <answer>"; anything else
gets the generic line. A matched question is a clarification, not a penalty; both counts are published.
"""

import re

CONFIRM = re.compile(r"\b(should i|shall i|do you want|want me to|send (it|that|this)|is that|okay to|ok to|correct|right)\b",
                     re.I)
WHICH = re.compile(r"\b(which|what|where|session|one|repo|mean|or)\b", re.I)


def named(text: str, sessions: list[str]) -> set[str]:
    """Sessions a sentence names, the longest name first so "tariff web" is not also "tariff"."""
    low = " " + re.sub(r"[^a-z]+", " ", text.lower()) + " "
    found = set()
    for name in sorted(sessions, key=len, reverse=True):
        spoken = " " + name.replace("-", " ") + " "
        if spoken in low:
            found.add(name)
            low = low.replace(spoken, " ")
    return found


def reply(question: str, intended: set[str], sessions: list[str]) -> str:
    """One of: answer, yes, correct, generic."""
    hits = named(question, sessions)
    if hits and hits == intended and CONFIRM.search(question):
        return "yes"
    if hits and hits == intended:
        return "answer"
    if len(hits) >= 2 or (hits and hits < intended):  # a choice offered, or only part of a two-session request
        return "answer"
    if hits:
        return "correct"
    return "answer" if WHICH.search(question) else "generic"
