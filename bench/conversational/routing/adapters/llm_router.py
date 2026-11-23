"""llm-router: the baseline headline deltas use. Same audio and recognizer as the naive arm; one call per user
utterance to the brain model Pointe's default setup resolves to here (recorded per row), with the prompt in
llm_router_prompt.txt and the same effort Pointe's brain uses by default."""

import json
import subprocess
from pathlib import Path

from ..core import ledger
from .spoken import SpokenArm

PROMPT = (Path(__file__).parent / "llm_router_prompt.txt").read_text()
SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["send", "ask", "approve", "deny", "stop", "none"]},
        "sessions": {"type": "array", "items": {"type": "string"}},
        "text": {"type": "string"},
        "question": {"type": "string"},
    },
    "required": ["action", "sessions", "text", "question"],
    "additionalProperties": False,
}
_key: list[str] = []


def anthropic_key() -> str:
    """From the Keychain into this process only, for the router's own client; never in the environment."""
    if not _key:
        for item in ("pointe.anthropic-api-key", "anthropic-api-key"):
            got = subprocess.run(["security", "find-generic-password", "-s", item, "-w"], capture_output=True, text=True)
            if got.returncode == 0 and got.stdout.strip():
                _key.append(got.stdout.strip())
                break
        else:
            raise RuntimeError("no Anthropic key in the Keychain")
    return _key[0]


class LLMRouterArm(SpokenArm):
    name = "llm-router"
    wait_after_say = 30.0

    def __init__(self, env, model: str, effort: str = "low"):
        super().__init__(env)
        self.model, self.effort = model, effort

    async def start(self, conv_id, repos):
        await super().start(conv_id, repos)
        import anthropic

        self.client = anthropic.AsyncAnthropic(api_key=anthropic_key())
        self.recent: list[dict] = []
        self.pending_question = self.pending_request = None
        self.calls: list[dict] = []

    async def decide(self, transcript: str) -> dict:
        payload = {"transcript": transcript, "sessions": list(self.repos), "pending_question": self.pending_question,
                   "pending_request": self.pending_request, "recent": self.recent[-5:], "pending_prompt": None}
        resp = await self.client.messages.create(
            model=self.model, max_tokens=2000, system=PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload)}],
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": SCHEMA}})
        u = resp.usage
        usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                 "cache_read_input_tokens": u.cache_read_input_tokens or 0,
                 "cache_creation_input_tokens": u.cache_creation_input_tokens or 0}
        text = "".join(b.text for b in resp.content if b.type == "text")
        try:
            action = json.loads(text)
        except ValueError:
            action = {"action": "none", "sessions": [], "text": "", "question": "", "unparsed": text[:200]}
        self.calls.append({"input": payload, "output": action, "usage": usage, "model": resp.model,
                           "stop_reason": resp.stop_reason})
        self.emit("router", input=payload, output=action, model=resp.model)
        return action

    async def handle(self, transcript: str) -> None:
        action = await self.decide(transcript)
        if action["action"] == "send":
            names = [n for n in action.get("sessions", []) if n in self.repos]
            for name in names:
                self.type_into(name, action.get("text") or transcript)
            self.recent.append({"action": "send", "sessions": names, "text": action.get("text", "")})
            self.pending_question = self.pending_request = None
        elif action["action"] == "ask":
            self.emit("asked", text=action.get("question") or "Which session?")
            self.pending_request = self.pending_request or transcript
            self.pending_question = action.get("question")
            self.recent.append({"action": "ask", "question": action.get("question", "")})
        else:
            self.recent.append({"action": action["action"]})

    def spend(self):
        rows = super().spend()
        usd = sum(ledger.anthropic_usd(self.model, c["usage"]) for c in getattr(self, "calls", []))
        if usd:
            rows.append({"vendor": "anthropic", "what": "router", "model": self.model, "how": "computed from usage",
                         "usd": round(usd, 6), "calls": len(self.calls)})
        return rows

    def versions(self):
        return {"router_model": self.model, "router_effort": self.effort}
