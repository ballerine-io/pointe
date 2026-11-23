"""The baseline the headline deltas use: Soniox ears (Pointe's default recognizer), one call per utterance to the brain
model of Pointe's default setup with the published prompt (llm_router_prompt.txt), one JSON action, local Kokoro out."""

import json
import re
import sys
from pathlib import Path

from core import keys, ledger
from core.adapter import Event, SpendRow, now
from adapters.spoken import SpokenRef

PROMPT = (Path(__file__).parent / "llm_router_prompt.txt").read_text()
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))


def default_brain() -> str:
    """The brain Pointe's default setup resolves to: the first of vendors.BRAIN_ORDER whose key is present."""
    import vendors

    return vendors.BRAIN_ORDER[0].split(":", 1)[1]  # anthropic:claude-sonnet-5-5 (the run asserts the key is present)


class LlmRouter(SpokenRef):
    name = "llm-router"

    def start(self, sessions, env):
        import anthropic

        self.model = default_brain()
        self.client = anthropic.Anthropic(api_key=keys.get("ANTHROPIC_API_KEY"), max_retries=2, timeout=30)
        self.router_usage: list[dict] = []
        super().start(sessions, env)

    def policy(self, text: str) -> list[tuple]:
        if not text.strip():
            return []
        context = {"utterance": text, "sessions": [self.session], "pending_prompt": None,
                   "agent_working": self.working(), "last_action": self.last_action}
        t0 = now()
        reply = self.client.messages.create(model=self.model, max_tokens=300, system=PROMPT,
                                            messages=[{"role": "user", "content": json.dumps(context)}])
        self.router_usage.append({"input_tokens": reply.usage.input_tokens, "output_tokens": reply.usage.output_tokens,
                                  "cache_read_input_tokens": getattr(reply.usage, "cache_read_input_tokens", 0) or 0,
                                  "cache_creation_input_tokens": getattr(reply.usage, "cache_creation_input_tokens", 0) or 0})
        raw = "".join(b.text for b in reply.content if getattr(b, "type", "") == "text")
        found = re.search(r"\{.*\}", raw, re.S)
        try:
            action = json.loads(found.group(0)) if found else {"action": "none"}
        except ValueError:
            action = {"action": "none"}
        self._events.append(Event(now(), "action", self.session, raw[:300], {"ms": round((now() - t0) * 1000)}))
        kind, msg = action.get("action"), (action.get("text") or "").strip()
        if kind == "stop":
            return [("escape",)]
        if kind == "send" and msg:
            return ([("escape",)] if action.get("interrupt") else []) + [("type", msg)]
        if kind == "ask" and msg:
            return [("say", msg)]
        if kind in ("approve", "deny"):
            return [(kind,)]
        return []

    def spend(self):
        usd = sum(ledger.anthropic_usd(self.model, u) for u in self.router_usage)
        return super().spend() + [SpendRow(f"anthropic:{self.model}:router", round(usd, 6), "computed",
                                           f"{len(self.router_usage)} calls")]

    def versions(self):
        return {**super().versions(), "router_model": self.model}
