"""The typed reference on the same pty: the clear yes and clear no items answered by a keypress (Enter on the
dialog's default "Yes", Escape for "No"). It shows that each fixture approves and denies correctly."""

import time

from core.adapter import Adapter

KEY_FOR = {"approve": "approve", "deny": "deny", "stop": "escape"}


class KeyboardAdapter(Adapter):
    name = "keyboard"
    capabilities = frozenset({"text_in", "approvals", "sessions", "interrupt"})

    def say(self, pcm, rate, item):
        start = time.time()
        if item["expect"] in KEY_FOR:
            self.key(KEY_FOR[item["expect"]])
            self.emit("key", name=KEY_FOR[item["expect"]])
        elif item["expect"] == "send":
            self.type(item["text"])
            self.emit("delivered", text=item["text"])
        return start, time.time()
