"""What `naive` and `llm-router` share: Soniox ears on the clip, one decision, then the action on the same pty, and
speech out through local Kokoro. Only `decide()` differs between them."""

import asyncio
import threading
import time

from core import corpus, ears
from core.adapter import CAPABILITIES, Adapter

SONIOX_USD_PER_HOUR = 0.12  # prices.json, "soniox"


class SpokenAdapter(Adapter):
    capabilities = CAPABILITIES
    voice = "bf_emma"  # the arm's own voice out; never one of the user's turn voices matters here (no one listens)

    def __init__(self):
        super().__init__()
        self.last_action = None
        self._soniox_seconds = 0.0

    # ----- what the harness knows, from the same signals Pointe gets -----
    def context(self) -> dict:
        hooks = self.agent.hooks()
        facts = self.agent.facts()
        decided = {c["id"] for c in facts["calls"] if "decided_at" in c}
        undecided = [c for c in facts["calls"] if c["id"] not in decided]
        requests = [h for h in hooks if h.get("hook_event_name") == "PermissionRequest"]
        pending = None
        if requests and undecided and any(c.get("name") == requests[-1].get("tool_name") for c in undecided):
            r = requests[-1]
            pending = {"tool": r.get("tool_name"), "input": r.get("tool_input")}
        stops = [h["_t"] for h in hooks if h.get("hook_event_name") == "Stop"]
        prompts = [h["_t"] for h in hooks if h.get("hook_event_name") == "UserPromptSubmit"]
        working = bool(undecided) or bool(prompts and (not stops or prompts[-1] > stops[-1]))
        return {"pending": pending, "agent": {"state": "working" if working else "idle",
                                              "last_message": facts["last_text"][:300]}}

    def decide(self, heard: str, ctx: dict) -> dict:
        raise NotImplementedError

    def say(self, pcm, rate, item):
        start = time.time()
        got = asyncio.run(ears.transcribe(pcm, self.env.secrets["soniox"]))
        self._soniox_seconds += got["seconds"]
        heard = got["text"]
        self.emit("heard", text=heard)
        ctx = self.context()
        action = self.decide(heard, ctx)
        self.emit("decided", **action)
        self.act(action)
        self.last_action = action.get("action")
        return start, got.get("speech_end", time.time())

    def act(self, action: dict) -> None:
        kind, text = action.get("action"), (action.get("text") or "").strip()
        if kind == "approve":
            self.key("approve")
        elif kind == "deny":
            self.key("deny")
        elif kind == "stop":
            self.key("escape")
            self.emit("stopped")
        elif kind == "send" and text:
            self.type(text)
            self.emit("delivered", text=text)
        elif kind in ("answer", "ask") and text:
            corpus.synth(text, self.voice)  # rendered as a person would hear it; nothing plays it here
            self.emit("said", text=text, reply=True)

    def read_out(self, text: str) -> None:
        """Speak an agent report (naive). Not a reply to the user, so it is a `read_out` event, not `said`."""
        threading.Thread(target=lambda: (corpus.synth(text[:600], self.voice), self.emit("read_out", chars=len(text[:600]))),
                         daemon=True).start()

    def spend(self) -> dict:
        out = dict(self._spend)
        out["soniox"] = [round(self._soniox_seconds / 3600 * SONIOX_USD_PER_HOUR, 6), "computed"]
        return out
