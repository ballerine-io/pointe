"""A fake adapter for the offline tests: no agent, no keys. It "delivers" by calling a function on the repo (the
reference edit, a decoy edit, or nothing), so the runner and the scorer run end to end in a few milliseconds."""

import time
from pathlib import Path

from core.adapter import CAPABILITIES, Event, SpendRow


class Echo:
    name = "echo"
    capabilities = CAPABILITIES

    def __init__(self, edit=None):
        self.edit = edit  # edit(repo: Path) -> None
        self._events: list[Event] = []
        self.repos: dict[str, Path] = {}

    def start(self, sessions, env) -> None:
        self.repos = dict(sessions)

    def _act(self, text: str) -> None:
        name = next(iter(self.repos))
        self._events.append(Event("delivered", time.time(), name, text))
        if self.edit:
            self.edit(self.repos[name])
        self._events.append(Event("agent_turn_done", time.time(), name, "Done."))

    def say(self, pcm: bytes, rate: int):
        self._act("(audio)")
        now = time.time()
        return now, now

    def type(self, text: str, session=None) -> None:
        self._act(text)

    def key(self, name, session=None) -> None:
        pass

    def events(self):
        out, self._events = self._events, []
        return out

    def speech(self):
        return []

    def last_text(self, session=None) -> str:
        return "Done."

    def versions(self):
        return {"adapter": "echo"}

    def spend(self):
        return [SpendRow("none", 0.0, "computed")]

    def transcripts(self):
        return []

    def prompts_denied(self) -> int:
        return 0

    def init_info(self) -> dict:
        return {}

    def stop(self) -> None:
        pass
