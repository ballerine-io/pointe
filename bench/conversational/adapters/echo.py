"""Offline tests only: a perfect policy over the FakeAgent (no model, no keys). It acts on each item's `expect`, so
the runner and the scorer must give it every item right."""

import time

from core.adapter import CAPABILITIES, Adapter


class EchoAdapter(Adapter):
    name = "echo"
    capabilities = CAPABILITIES

    def say(self, pcm, rate, item):
        start = time.time()
        expect = item["expect"]
        if expect in ("approve", "deny"):
            self.key(expect)
        elif expect == "stop":
            self.key("escape")
            self.emit("stopped")
        elif expect == "send":
            self.type(item["text"])
        elif expect == "answer":
            self.emit("said", text="It is idle.")
        return start, time.time()
