"""naive, labelled "keyword rules, ours" on the page. The first word that names a session picks it, else the last one;
"yes", "approve", "go ahead" allow a pending prompt; "no", "deny", "don't" deny it; "stop", "cancel" send Escape;
anything else is typed in. Expected to fail the adversarial items by construction; never used in a headline delta."""

import re

from adapters.voice_base import VoiceBase
from core.adapter import Event

YES = {"yes", "yeah", "yep", "approve", "sure", "okay", "ok"}
NO = {"no", "deny", "don't", "dont", "nope"}
STOP = {"stop", "cancel"}


class Naive(VoiceBase):
    name = "naive"

    async def handle(self, text: str) -> None:
        import time
        words = re.findall(r"[a-z0-9']+", text.lower())
        for w in words:
            hit = next((n for n in self.agents if w == n.lower()), None)
            if hit:
                self.last_session = hit
                break
        session, ap = self.pending()
        joined = " ".join(words)
        if ap and (set(words) & YES or "go ahead" in joined):
            self.agents[session].key("approve")
            self._events.append(Event("approval_decision", time.time(), session, "allow"))
        elif ap and set(words) & NO:
            self.agents[session].key("deny")
            self._events.append(Event("approval_decision", time.time(), session, "deny"))
        elif set(words) & STOP:
            self.agents[self.last_session].key("escape")
            self._events.append(Event("stopped", time.time(), self.last_session))
        elif text.strip():
            self.agents[self.last_session].type(text.strip())
            self._events.append(Event("delivered", time.time(), self.last_session, text.strip()))
