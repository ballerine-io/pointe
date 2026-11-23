"""echo: a fake adapter for the offline tests. No agent, no keys, no network: its fake sessions apply the instance's
reference solution when told anything, and answer the final question truthfully. It proves the runner and the scorer
end to end, and that a perfect harness scores a pass on every item."""

import time

from adapters.base import Base
from core.adapter import CAPABILITIES
from hlk import score
from hlk.common import FINAL_QUESTION


class FakeAgent:
    def __init__(self, name, repo, owner):
        self.name, self.repo, self.owner = name, repo, owner
        self.hook_events: list = []
        self.texts: list = []

    def start(self):
        pass

    def type(self, text: str) -> None:
        now = time.time()
        self.hook_events.append({"hook_event_name": "UserPromptSubmit", "prompt": text, "_t": now})
        if FINAL_QUESTION.split(",")[0] in text:
            reply = "Yes, it is done and the tests pass." if self.owner.inst.expect_done else "No. It cannot be done as stated."
        else:
            for name, files in self.owner.inst.solved.items():
                if name == self.name:
                    score.apply_solution(self.owner.inst, {name: self.owner.repos[name]}) if files else None
            reply = "Done: I made the change."
        self.texts.append((now + 0.01, reply))
        self.hook_events.append({"hook_event_name": "Stop", "_t": now + 0.02})

    def key(self, name: str) -> None:
        pass

    def hooks(self):
        return self.hook_events

    def busy(self):
        return False

    def pending_approval(self):
        return None

    def stops(self):
        return sum(1 for e in self.hook_events if e["hook_event_name"] == "Stop")

    def texts_since(self, t):
        return "\n".join(x for at, x in self.texts if at >= t)

    def last_text(self, since=0):
        return self.texts[-1][1] if self.texts else ""

    def tool_inputs(self):
        return [{"tool": "Edit", "input": {"file_path": str(self.repo / "x.py")}}]

    def usage(self):
        return []

    def flat(self):
        return ""

    def stop(self):
        pass


class Echo(Base):
    name = "echo"
    kind = "typed"
    capabilities = frozenset(CAPABILITIES)

    def __init__(self, inst):
        super().__init__()
        self.inst = inst
        self.repos: dict = {}

    def start(self, sessions, env):
        self.env = env
        self.repos = dict(sessions)
        self.agents = {name: FakeAgent(name, repo, self) for name, repo in sessions.items()}
