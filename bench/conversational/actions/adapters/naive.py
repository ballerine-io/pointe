"""Keyword rules, ours. Expected to fail the adversarial items by construction; never in a headline delta.

The first word that names a session picks it, else the last one; "yes, approve, go ahead" allows; "no, deny, don't"
denies; "stop, cancel" sends Escape; anything else is typed in. One exception, to keep the pty honest: while a
permission dialog is open, unmatched speech is not typed, because typed text plus Enter would press the dialog's
default "Yes" and that would be a terminal artefact, not a rule.
"""

import re
import threading
import time

from adapters.spoken import SpokenAdapter

ALLOW = ("yes", "yeah", "yep", "approve", "approved", "allow", "go ahead", "sure", "okay", "ok", "do it")  # checked first
DENY = ("no", "nope", "deny", "don't", "dont", "reject", "not")
STOP = ("stop", "cancel", "abort")


def words(text: str) -> str:
    return " " + re.sub(r"[^a-z' ]+", " ", text.lower()) + " "


def rule(heard: str, pending: bool) -> dict:
    w = words(heard)
    if pending and any(f" {k} " in w for k in ALLOW):
        return {"action": "approve"}
    if pending and any(f" {k} " in w for k in DENY):
        return {"action": "deny"}
    if any(f" {k} " in w for k in STOP):
        return {"action": "stop"}
    if pending or not heard.strip():
        return {"action": "none"}
    return {"action": "send", "text": heard}


class NaiveAdapter(SpokenAdapter):
    name = "naive"

    def start(self, env) -> None:
        super().start(env)
        self._spoken = 0
        self._watch = True
        threading.Thread(target=self._reports, daemon=True).start()

    def _reports(self) -> None:
        """Speak the agent's final message of each turn (first 600 characters) through Kokoro."""
        while self._watch:
            stops = [h for h in self.agent.hooks() if h.get("hook_event_name") == "Stop"]
            if len(stops) > self._spoken:
                self._spoken = len(stops)
                text = self.agent.facts()["last_text"]
                if text:
                    self.read_out(text)
            time.sleep(1.0)

    def decide(self, heard: str, ctx: dict) -> dict:
        return rule(heard, ctx["pending"] is not None)

    def stop(self) -> None:
        self._watch = False
        super().stop()
