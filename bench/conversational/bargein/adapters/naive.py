"""Keyword rules, ours. Speech to text (Soniox), then: "yes, approve, go ahead" allows a pending prompt; "no, deny,
don't" denies it; "stop, cancel" sends Escape; anything else is typed in. Expected to fail on purpose-built items; never
used in a headline delta."""

import re

from adapters.spoken import SpokenRef

YES = re.compile(r"\b(yes|approve|go ahead)\b", re.I)
NO = re.compile(r"\b(no|deny|don't)\b", re.I)
STOP = re.compile(r"\b(stop|cancel)\b", re.I)


class Naive(SpokenRef):
    name = "naive"
    pending_prompt = False  # bargein has no permission prompt: the settings file allows the job's commands

    def policy(self, text: str) -> list[tuple]:
        if not text.strip():
            return []
        if self.pending_prompt and YES.search(text):
            return [("approve",)]
        if self.pending_prompt and NO.search(text):
            return [("deny",)]
        if STOP.search(text):
            return [("escape",)]
        return [("type", text)]
