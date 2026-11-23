"""The scripted user's question detector and its slot answers (design 4.4).

A harness turn is a question when its last sentence starts with a wh-word or an auxiliary, or holds "which one",
"did you mean", "do you want" or "want me to". A matched question gets its slot's answer and counts as a
clarification, never as a penalty; an unmatched one gets the generic line.
"""

import re

WH = r"(what|which|who|whom|whose|when|where|why|how)"
AUX = r"(is|are|was|were|do|does|did|can|could|should|shall|will|would|may|might|have|has|had|am)"
PHRASES = re.compile(r"\b(which one|did you mean|do you want|want me to|would you like|should i|shall i)\b", re.I)
CONFIRM = re.compile(r"\b(want me to|should i|shall i|do you want|would you like|ask (it|them|kiln|quarry)|"
                     r"go ahead|confirm|stop it|okay to)\b", re.I)
GENERIC = "Please go on with what I asked."
LINES = {"yes": "Yes, please.", "no": "No, keep going.", "generic": GENERIC}


def last_sentence(text: str) -> str:
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
    return parts[-1] if parts else ""


def is_question(text: str) -> bool:
    last = last_sentence(text).lower().lstrip("\"' ")
    if not last:
        return False
    words = re.findall(r"[a-z']+", last)
    if words and (re.fullmatch(WH, words[0]) or re.fullmatch(AUX, words[0])):
        return True
    if words and words[0] in ("so", "and", "but", "okay", "ok", "alright") and len(words) > 1 and \
            (re.fullmatch(WH, words[1]) or re.fullmatch(AUX, words[1])):
        return True
    return bool(PHRASES.search(last)) or last.endswith("?")


def answer(text: str, wants_stop_or_answer: bool) -> tuple[str, str]:
    """The slot and the line the scripted user says back. wants_stop_or_answer: the item wants the harness to act
    (a stop, an undo, a redirect, a question to answer); False for a backchannel, which wants nothing changed."""
    if CONFIRM.search(text):
        return ("confirm", LINES["yes"] if wants_stop_or_answer else LINES["no"])
    return ("generic", GENERIC)


# The labelled set for the detector test: (line, is it a question). Synthetic lines in the register of a voice
# harness's replies.
LABELLED = [
    ("I don't know yet. Want me to ask it?", True), ("Which session do you mean?", True),
    ("Do you want me to stop the job?", True), ("Should I delete the step files too?", True),
    ("Did you mean the out folder?", True), ("Is that the kiln session?", True),
    ("What would you like me to do with them?", True), ("Shall I put the rest in out?", True),
    ("Can you say that again?", True), ("Would you like me to ask quarry?", True),
    ("Okay, so which one?", True), ("Where should the files go?", True),
    ("How many steps should it run?", True), ("Are you sure you want to stop it?", True),
    ("Was that a yes?", True), ("I can ask it. Do you want that?", True),
    ("Kiln is still running. Should I interrupt it?", True), ("Who should I send this to?", True),
    ("Why do you want it stopped?", True), ("Could you repeat the folder name?", True),
    ("I asked kiln to stop the long job.", False), ("Seven tests failed.", False),
    ("The build did not pass.", False), ("Kiln is running the long job now.", False),
    ("Done. The files are in out.", False), ("Quarry says the port is eighty eighty.", False),
    ("It hasn't confirmed yet.", False), ("The last deploy was on Tuesday.", False),
    ("I sent that to quarry.", False), ("There are twelve lint errors.", False),
    ("Okay.", False), ("Got it, stopping now.", False), ("The garden service is waiting for your review.", False),
    ("You're on the cedar branch.", False), ("I'll ask it and let you know.", False),
    ("Coverage is sixty four percent.", False), ("Most failures are in test voucher.", False),
    ("Kiln stopped after step three.", False), ("Nothing else is running.", False),
    ("Sure, putting them in out.", False),
]
