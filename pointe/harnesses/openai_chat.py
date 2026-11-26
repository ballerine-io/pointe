"""Any agent behind an OpenAI-compatible chat completions endpoint, the second generic adapter (docs/design/agents.md).

    GET  <url>/models                 the credential works, and the model to name when none is configured
    POST <url>/chat/completions       {model, messages: the conversation so far, user: pointe-<name>}

Standard chat completions are stateless: Pointe sends the conversation from its own record (the last turns, capped),
and a stable `user`, which some servers key a session on (OpenClaw). A server that keeps its own session from the
request (Hermes derives one from the first messages) sees the same opening every time. No approvals on this surface:
Hermes denies a dangerous command there, OpenClaw falls back to deny. Checked live against both.
"""

from __future__ import annotations

import json

import aiohttp

from .agent import AgentError, AgentHarness, Reply, _final_text

HISTORY_TURNS = 20
HISTORY_CHARS = 60_000
TURN_SECS = 3600.0  # one request holds the whole turn: an agent may work for long


class OpenAIChat(AgentHarness):
    name = "openai"
    label = "openai"
    agent = "the agent"

    def __init__(self) -> None:
        super().__init__()
        self._http: aiohttp.ClientSession | None = None
        self._bodies: dict[str, list[dict]] = {}  # turn -> its messages: in memory only, never in sessions.json

    def http(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TURN_SECS, sock_connect=5))
        return self._http

    @staticmethod
    def base(agent) -> str:
        from urllib.parse import urlparse

        url = agent.url.rstrip("/")
        return url + "/v1" if urlparse(url).path in ("", "/") else url

    async def models(self, agent, secret: str) -> list[str]:
        async with self.http().get(self.base(agent) + "/models", headers={"Authorization": f"Bearer {secret}"},
                                   timeout=aiohttp.ClientTimeout(total=10)) as r:
            r.raise_for_status()
            got = await r.json(content_type=None)
        return [str(m.get("id")) for m in (got or {}).get("data") or [] if isinstance(m, dict) and m.get("id")]

    async def health(self, session, agent) -> str:
        import asyncio

        from .agent import SECRET

        secret = await asyncio.to_thread(SECRET, agent)
        await self.models(agent, secret or "")
        return ""

    async def check(self, agent, secret: str) -> None:
        if not await self.models(agent, secret):
            raise AgentError("That server lists no model to talk to.")

    def history(self, session, message: str) -> list[dict]:
        """The conversation from the record: the user's turns and the agent's finished replies, newest last."""
        turns: list[dict] = []
        try:
            lines = self.mirror_path(session.id).read_text().splitlines()
        except OSError:
            lines = []
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("type") == "user" and isinstance((entry.get("message") or {}).get("content"), str):
                turns.append({"role": "user", "content": entry["message"]["content"]})
            elif entry.get("pointeAgentReply") and not entry.get("pointeError"):
                turns.append({"role": "assistant", "content": _final_text(line) or ""})
        turns = turns[-HISTORY_TURNS:]
        while turns and (sum(len(t["content"]) for t in turns) > HISTORY_CHARS or turns[0]["role"] != "user"):
            turns.pop(0)
        return turns + [{"role": "user", "content": message}]

    async def submit(self, session, agent, secret: str, message: str, turn: str) -> dict:
        model = agent.agent or next(iter(await self.models(agent, secret)), "")
        if not model:
            raise AgentError(f"{session.name} lists no model to talk to.")
        self._bodies[turn] = self.history(session, message)
        return {"model": model}

    async def wait(self, session, agent, secret: str, handle: dict) -> Reply:
        messages = self._bodies.pop(handle["turn"], None)
        if messages is None:  # a turn from before a restart: a blocking request cannot be picked up again
            raise AgentError("Pointe restarted while it worked, and this kind of agent cannot be asked for the answer again.")
        body = {"model": handle["model"], "messages": messages, "user": f"pointe-{session.id.removeprefix('agent-')}",
                "stream": False}
        async with self.http().post(self.base(agent) + "/chat/completions", json=body,
                                    headers={"Authorization": f"Bearer {secret}"}) as r:
            r.raise_for_status()
            got = await r.json(content_type=None)
        choice = ((got or {}).get("choices") or [{}])[0]
        text = str((choice.get("message") or {}).get("content") or "").strip()
        if choice.get("finish_reason") in ("error", "cancelled") and not text:
            raise AgentError("the turn failed.")
        return Reply(text)
