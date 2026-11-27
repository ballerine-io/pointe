"""Moving the call to another machine the client holds (docs/design/multi-machine-clients.md, 1.4), decided in code.

A client that holds several machines lists them in its call's hello: {"machines": [{"id", "name"}]}, names only, never
an address or a key. "Call kite", "move the call to kite", "hand me to kite" then end this call and make the client dial
kite: the daemon says one line and sends {"type": "handoff", "machine": {"id", "name"}} on the call's socket. "Switch
to kite" and "go to kite" mean that too, unless this voice links kite: then they keep their old meaning, a session on
kite. A client that lists nothing (an older app, the page) is never moved.
"""

import re

MAX_MACHINES = 20
_ID = re.compile(r"[\w-]{1,64}")
# A strong verb names the call itself; a weak one is the session switch's word, and only moves the call when this voice
# has no machine of that name.
_STRONG = r"call|move\s+(?:the\s+call|me|us)\s+(?:over\s+)?to|hand\s+(?:me|us|the\s+call)\s+(?:over\s+)?to|take\s+(?:me|us)\s+to"
_WEAK = r"switch\s+(?:over\s+)?to|go\s+(?:over\s+)?to|move\s+to"
_LEAD = r"^\W*(?:(?:ok(?:ay)?|hey|so|now|please|pointe)\W+)*"


def machines(raw) -> list[dict]:
    """The client's list from its hello, cleaned: plain ids, short names, at most MAX_MACHINES."""
    out = []
    for m in raw if isinstance(raw, list) else []:
        if isinstance(m, dict) and isinstance(m.get("id"), str) and _ID.fullmatch(m["id"]) and isinstance(m.get("name"), str):
            name = " ".join(re.sub(r"[^\w .-]+", " ", m["name"]).split())[:60]
            if name:
                out.append({"id": m["id"], "name": name})
        if len(out) == MAX_MACHINES:
            break
    return out


def _words(name: str) -> str:
    return r"\W+".join(re.escape(w) for w in re.split(r"[\s._-]+", name.lower()) if w)


def _named(text: str, verbs: str, name: str) -> bool:
    return bool(re.fullmatch(rf"{_LEAD}(?:{verbs})\s+(?:the\s+)?{_words(name)}(?:\s+machine)?\W*", text))


def intent(text: str, client: list[dict], linked: set[str], here: str) -> tuple[str, dict] | None:
    """("move", machine), ("here", machine) for the one on this call, ("unpaired", {name}) for a machine this voice
    links but the client does not hold, or None: not about moving the call."""
    if not client:
        return None
    lowered = text.lower().strip()
    for m in client:
        strong = _named(lowered, _STRONG, m["name"])
        if strong or (_named(lowered, _WEAK, m["name"]) and m["name"].lower() not in {n.lower() for n in linked}):
            return ("here" if m["id"] == here else "move"), m
    for name in linked:
        if _named(lowered, _STRONG, name):
            return "unpaired", {"id": "", "name": name}
    return None


def line(kind: str, name: str) -> str:
    return {"move": f"Moving you to {name}.", "here": f"You're on {name} already.",
            "unpaired": f"This phone is not paired with {name}. Add it in Machines, on the phone."}[kind]
