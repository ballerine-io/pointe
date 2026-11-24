"""The baseline that headline deltas use (design 4.3): the same recognizer as Pointe's default setup (Soniox
real-time), then one call per utterance to the brain model of Pointe's default setup, with the published prompt in
llm_router_prompt.txt. Output: one JSON action. Written by the team whose product is under test; a pull request with
a better prompt is welcome."""

import json
import re
import sys
import time
from pathlib import Path

from adapters.base import AgentAdapter
from core import ears
from core.adapter import Event, SpendRow
from core.ledger import PRICES, tokens_usd

HERE = Path(__file__).resolve().parent
PROMPT = (HERE / "llm_router_prompt.txt").read_text()
MAX_TOKENS = 8000
sys.path[0:0] = [str(HERE.parents[3] / "pointe"), str(HERE.parents[3])]


def brain_model() -> str:
    """Pointe's default brain, resolved as vendors.py resolves it: the first of BRAIN_ORDER whose vendor key exists.
    Read from the code, not from ~/.claude-voice (the owner's live state is never read)."""
    import vendors

    from core import keys

    for entry in vendors.BRAIN_ORDER:
        vendor, model = entry.split(":", 1)
        if vendor in keys.ITEMS:
            try:
                keys.get(vendor)
                return model
            except SystemExit:
                continue
    raise SystemExit("no key for any brain in vendors.BRAIN_ORDER that this arm can call")


class LlmRouter(AgentAdapter):
    name = "llm-router"
    capabilities = frozenset({"audio_in", "text_in", "approvals", "sessions", "interrupt"})

    def __init__(self, model: str | None = None):
        super().__init__()
        self.model = model or brain_model()
        self.audio_seconds = 0.0
        self.usage = {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0, "calls": 0}
        self.earlier: list[dict] = []
        self.last_action = None

    def route(self, transcript: str) -> dict:
        import anthropic

        client = anthropic.Anthropic(api_key=self.env.secrets["anthropic"], max_retries=4)
        payload = {"transcript": transcript, "sessions": list(self.agents), "pending_prompt": None,
                   "last_action": self.last_action, "earlier": self.earlier[-6:]}
        # The model thinks before it answers by default: a small max_tokens is spent on thinking and cuts the JSON off
        # (seen on 2026-11-23: 400 left about one call in two as "none"). 8000 is what Pointe's own text calls allow
        # (vendors._anthropic_text). This model takes no temperature.
        resp = client.messages.create(model=self.model, max_tokens=MAX_TOKENS, system=PROMPT,
                                      messages=[{"role": "user", "content": json.dumps(payload)}])
        u = resp.usage
        self.usage["input"] += u.input_tokens
        self.usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        self.usage["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
        self.usage["output"] += u.output_tokens
        self.usage["calls"] += 1
        raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            action = json.loads(m.group(0)) if m else {"action": "none", "unparsed": raw[:200]}
        except ValueError:
            action = {"action": "none", "unparsed": raw[:200]}
        action["stop_reason"] = resp.stop_reason
        self.earlier.append({"transcript": transcript, "action": action})
        self.last_action = action
        return action

    def say(self, pcm: bytes, rate: int) -> tuple[float, float]:
        start = time.time()
        heard = ears.transcribe(pcm, rate, self.env.secrets["soniox"])
        end = start + len(pcm) / (2 * rate)
        self.audio_seconds += heard["seconds"]
        self._events.append(Event("heard", time.time(), None, heard["text"]))
        if not heard["text"]:
            return start, end
        action = self.route(heard["text"])
        self._events.append(Event("note", time.time(), None, "router", {"action": action}))
        kind = action.get("action")
        session = action.get("session") if action.get("session") in self.agents else next(iter(self.agents))
        if kind == "send" and action.get("text"):
            self.type(str(action["text"]), session)
        elif kind == "ask":
            self._events.append(Event("asked", time.time(), None, str(action.get("text", ""))))
        elif kind in ("approve", "deny"):
            self.key(kind, session)
        elif kind == "stop":
            self.key("escape", session)
        return start, end

    def versions(self) -> dict:
        return {**super().versions(), "recognizer": f"soniox:{ears.MODEL}", "router_model": self.model}

    def spend(self) -> list[SpendRow]:
        soniox = self.audio_seconds / 3600 * PRICES["soniox_rt_per_stream_hour"]
        return super().spend() + [
            SpendRow("anthropic-router", tokens_usd(self.model, self.usage), "computed",
                     {"usage": dict(self.usage), "from": "metered token counts in each response"}),
            SpendRow("soniox", soniox, "computed", {"seconds": round(self.audio_seconds, 1)})]
