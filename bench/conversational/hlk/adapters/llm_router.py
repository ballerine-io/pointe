"""llm-router: the baseline the headline deltas use. The same recognizer as Pointe's default setup (Soniox real-time),
then one call per user utterance to the same brain model Pointe's default setup uses (resolved at run time from Pointe's
own vendor order and the keys present, and recorded), with the published prompt in llm_router_prompt.txt. Speech out
through local Kokoro. Written by Pointe's team; a pull request with a better prompt is welcome."""

import json
import re
import sys
import time
from pathlib import Path

from adapters.voice_base import VoiceBase
from core.adapter import Event, SpendRow
from core.ledger import token_cost

HERE = Path(__file__).resolve().parent
PROMPT = (HERE / "llm_router_prompt.txt").read_text()


def default_brain(pointe: Path, present: set) -> str:
    """vendor:model of the brain role when no setup is chosen: the first vendor in Pointe's BRAIN_ORDER whose key exists."""
    sys.path[:0] = [str(pointe / "pointe"), str(pointe)]  # 0.8: the daemon's modules live in pointe/
    import vendors
    for choice in vendors.BRAIN_ORDER:
        if choice.split(":")[0] in present:
            return choice
    raise RuntimeError("no brain key")


class LLMRouter(VoiceBase):
    name = "llm-router"

    def __init__(self, soniox_model: str, brain: str):
        super().__init__(soniox_model)
        self.brain = brain
        self.last_action = "none yet"
        self.calls: list = []
        self._client = None

    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self.env.keys["anthropic"], max_retries=3)
        return self._client

    async def decide(self, text: str) -> dict:
        session, ap = self.pending()
        waiting = "none" if not ap else json.dumps({"session": session, "tool": ap.get("tool_name"),
                                                     "input": ap.get("tool_input")})[:800]
        user = json.dumps({"sentence": text, "sessions": list(self.agents), "permission_prompt": waiting,
                           "last_action": self.last_action})
        vendor, model = self.brain.split(":", 1)
        assert vendor == "anthropic", f"router supports the Anthropic brain only, got {self.brain}"
        t0 = time.time()
        resp = await self.client().messages.create(model=model, max_tokens=2000, system=PROMPT,
                                                   messages=[{"role": "user", "content": user}],
                                                   output_config={"effort": "low"})
        u = resp.usage
        usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                 "cache_read_input_tokens": u.cache_read_input_tokens or 0,
                 "cache_creation_input_tokens": u.cache_creation_input_tokens or 0}
        out = "".join(b.text for b in resp.content if b.type == "text")
        self.calls.append({"model": resp.model, "usage": usage, "ms": int((time.time() - t0) * 1000)})
        m = re.search(r"\{.*\}", out, re.S)
        try:
            return json.loads(m.group(0)) if m else {"action": "none"}
        except json.JSONDecodeError:
            return {"action": "none"}

    async def handle(self, text: str) -> None:
        if not text.strip():
            return
        act = await self.decide(text)
        action, session, body = act.get("action"), act.get("session"), (act.get("text") or "").strip()
        if session not in self.agents:
            session = self.last_session
        now = time.time()
        pend_session, ap = self.pending()
        if action in ("approve", "deny") and ap:
            self.agents[pend_session].key(action)
            self._events.append(Event("approval_decision", now, pend_session, "allow" if action == "approve" else "deny"))
        elif action == "stop":
            self.agents[session].key("escape")
            self._events.append(Event("stopped", now, session))
        elif action == "send" and body:
            if re.match(r"\s*(stop|wait|hold on)\b", text, re.I):
                self.agents[session].key("escape")
                time.sleep(1.5)
            self.agents[session].type(body)
            self.last_session = session
            self._events.append(Event("delivered", now, session, body))
        elif action == "ask" and body:
            self._events.append(Event("asked", now, session, body))
            await self.speak(body)
        self.last_action = json.dumps({"action": action, "session": session, "text": body[:200]})

    def versions(self):
        return {"adapter": self.name, "brain": self.brain, "ears": f"soniox:{self.soniox_model}"}

    def spend(self):
        rows = super().spend()
        usd = sum(token_cost(c["model"], c["usage"]) for c in self.calls)
        rows.append(SpendRow("anthropic", usd, "computed", f"{len(self.calls)} router calls, usage from the API"))
        return rows
