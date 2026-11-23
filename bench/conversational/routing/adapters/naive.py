"""naive, labelled "keyword rules, ours": the first word that matches a session name picks it (the longest name that
starts at that word, so "tariff web" is tariff-web), else the session used last; the transcript is typed in as heard.
It never asks. Expected to fail ambiguous turns by construction; never used in a headline delta."""

import re

from .spoken import SpokenArm


def route(transcript: str, names: list[str], last: str) -> str:
    words = re.findall(r"[a-z]+", transcript.lower())
    for i in range(len(words)):
        for name in sorted(names, key=len, reverse=True):
            parts = name.split("-")
            if words[i:i + len(parts)] == parts:
                return name
    return last


class NaiveArm(SpokenArm):
    name = "naive"
    wait_after_say = 25.0

    async def start(self, conv_id, repos):
        await super().start(conv_id, repos)
        self.last = list(repos)[-1]

    async def handle(self, transcript: str) -> None:
        if not transcript.strip():
            return
        self.last = route(transcript, list(self.repos), self.last)
        self.type_into(self.last, transcript)
