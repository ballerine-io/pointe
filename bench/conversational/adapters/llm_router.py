"""The baseline the headline deltas use: the same recognizer as Pointe's default setup (Soniox), then one call per
utterance to the same brain model Pointe's default setup resolves to, with the public prompt in llm_router_prompt.txt.
Written by the team whose product is under test; a pull request with a better prompt is welcome."""

import json
import re
from pathlib import Path

from adapters.spoken import SpokenAdapter

PROMPT = (Path(__file__).resolve().parent / "llm_router_prompt.txt").read_text()
ACTIONS = ("approve", "deny", "send", "stop", "answer", "ask", "none")


def parse_reply(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    try:
        reply = json.loads(m.group(0)) if m else {}
    except ValueError:
        reply = {}
    if reply.get("action") not in ACTIONS:
        return {"action": "none", "invalid": True}
    return {"action": reply["action"], "session": reply.get("session"), "text": reply.get("text")}


class RouterAdapter(SpokenAdapter):
    name = "llm-router"
    model = None  # set by the runner from Pointe's default setup (vendors.resolve().brain), recorded in every row

    def __init__(self):
        super().__init__()
        self._usd = 0.0
        self._calls = 0

    def decide(self, heard: str, ctx: dict) -> dict:
        import anthropic

        vendor, model = self.model.split(":", 1)
        assert vendor == "anthropic", f"router expects an Anthropic brain, got {self.model}"
        payload = {"heard": heard, "sessions": [self.env.session], "pending": ctx["pending"], "agent": ctx["agent"],
                   "last_action": self.last_action}
        client = anthropic.Anthropic(api_key=self.env.secrets["anthropic"], max_retries=3)
        resp = client.messages.create(model=model, max_tokens=8000, system=PROMPT,
                                      output_config={"effort": "low"},
                                      messages=[{"role": "user", "content": json.dumps(payload)}])
        u = resp.usage
        p = self.env.prices["anthropic"][model]
        self._usd += (u.input_tokens * p["input"] + u.output_tokens * p["output"]
                      + (u.cache_creation_input_tokens or 0) * p["cache_write"]
                      + (u.cache_read_input_tokens or 0) * p["cache_read"]) / 1e6
        self._calls += 1
        text = "".join(b.text for b in resp.content if b.type == "text")
        return {**parse_reply(text), "raw": text[:300]}

    def spend(self) -> dict:
        out = super().spend()
        out["anthropic-router"] = [round(self._usd, 6), "computed"]
        return out

    def versions(self) -> dict:
        return {"router_model": self.model, "router_calls": self._calls}
