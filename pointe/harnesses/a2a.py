"""Any agent that serves the Agent2Agent protocol (A2A 1.0, JSON-RPC binding), the generic adapter (docs/design/agents.md).

    GET  /.well-known/agent-card.json      the card: its JSON-RPC address (supportedInterfaces, else url)
    SendMessage {message, configuration: {returnImmediately: true}}   a turn: a task, or a message straight back
    GetTask {id}                           until the task is in a terminal or interrupted state
    CancelTask {id}                        stop it

A server without the 1.0 names (-32601) is spoken to with the pre-1.0 ones (`message/send`, `tasks/get`,
`tasks/cancel`, lowercase roles and states, `kind: text` parts). One conversation per agent: contextId
`pointe-<name>`. Checked live against the A2A servers of OpenClaw 2026.11.10 and Hermes Agent v0.23.4.
A2A carries no approvals: the agent's own policy decides, and `approvals` is false.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import aiohttp

from .agent import AgentError, AgentHarness, Reply

DONE = {"TASK_STATE_COMPLETED", "completed"}
FAILED = {"TASK_STATE_FAILED", "failed", "TASK_STATE_REJECTED", "rejected", "TASK_STATE_CANCELED", "canceled", "cancelled"}
ASKS = {"TASK_STATE_INPUT_REQUIRED", "input-required", "TASK_STATE_AUTH_REQUIRED", "auth-required"}
OLD = {"SendMessage": "message/send", "GetTask": "tasks/get", "CancelTask": "tasks/cancel"}


class A2A(AgentHarness):
    name = "a2a"
    label = "a2a"
    agent = "the agent"
    interrupts = ""  # CancelTask is optional in A2A and some servers refuse it

    def __init__(self) -> None:
        super().__init__()
        self._http: aiohttp.ClientSession | None = None
        self._endpoint: dict[str, tuple[str, bool]] = {}  # agent url -> (JSON-RPC address, speaks pre-1.0 only)

    def http(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60, sock_connect=5))
        return self._http

    async def _card(self, agent) -> dict:
        base = agent.url.rstrip("/")
        for path in ("/.well-known/agent-card.json", "/.well-known/agent.json"):
            async with self.http().get(base + path, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    got = await r.json(content_type=None)
                    if isinstance(got, dict):
                        return got
        raise AgentError("That address serves no A2A agent card.")

    async def endpoint(self, agent) -> tuple[str, bool]:
        known = self._endpoint.get(agent.url)
        if known:
            return known
        card = await self._card(agent)
        rpc = next((i.get("url") for i in card.get("supportedInterfaces") or []
                    if isinstance(i, dict) and str(i.get("protocolBinding") or "").upper() in ("JSONRPC", "JSON-RPC")), None)
        rpc = str(rpc or card.get("url") or agent.url)
        old = not card.get("supportedInterfaces") and str(card.get("protocolVersion") or "").startswith("0.")
        self._endpoint[agent.url] = (rpc, old)
        return rpc, old

    async def rpc(self, agent, secret: str, method: str, params: dict, timeout: float = 60) -> dict:
        url, old = await self.endpoint(agent)
        for attempt in ((OLD[method],) if old else (method, OLD[method])):
            body = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": attempt,
                    "params": _old_params(params) if attempt != method else params}
            async with self.http().post(url, json=body, headers={"Authorization": f"Bearer {secret}", "A2A-Version": "1.0"},
                                        timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                r.raise_for_status()
                got = await r.json(content_type=None)
            error = (got or {}).get("error") if isinstance(got, dict) else {"code": 0}
            if error and error.get("code") == -32601 and attempt == method:
                self._endpoint[agent.url] = (url, True)
                continue
            if error:
                raise AgentError(f"{agent.name} refused it (A2A error {error.get('code')})")
            return got.get("result") or {}
        raise AgentError(f"{agent.name} does not speak A2A's SendMessage.")

    @staticmethod
    def context(session) -> str:
        return f"pointe-{session.id.removeprefix('agent-')}"

    async def health(self, session, agent) -> str:
        await self._card(agent)
        return ""

    async def check(self, agent, secret: str) -> None:
        await self.endpoint(agent)  # a card; the token is checked by the first turn (A2A has no free authenticated call)

    async def submit(self, session, agent, secret: str, message: str, turn: str) -> dict:
        got = await self.rpc(agent, secret, "SendMessage", {
            "message": {"messageId": f"pointe-{turn}", "role": "ROLE_USER", "contextId": self.context(session),
                        "parts": [{"text": message}]},
            "configuration": {"returnImmediately": True}}, timeout=120)
        task = got.get("task") or (got if got.get("kind") == "task" or "status" in got else None)
        if task and task.get("id"):
            return {"task": str(task["id"]), "_first": task}
        answer = got.get("message") or (got if got.get("parts") else None)
        if answer:
            return {"_answer": _parts_text(answer)}
        raise AgentError(f"{session.name} gave no task and no answer.")

    async def wait(self, session, agent, secret: str, handle: dict) -> Reply:
        if "_answer" in handle:
            return Reply(handle["_answer"])
        if "task" not in handle:
            raise AgentError("Pointe restarted before the answer was read, and the agent gave no task to ask about.")
        task, began = handle.get("_first") or {"status": {"state": "TASK_STATE_WORKING"}}, time.time()
        while True:
            state = str((task.get("status") or {}).get("state") or "")
            if state in DONE:
                return Reply(_task_text(task))
            if state in ASKS:
                return Reply(_task_text(task) or f"{session.name} needs more from you to go on.")
            if state in FAILED:
                raise AgentError(f"the task ended {state.removeprefix('TASK_STATE_').lower()}." +
                                 (f" {_task_text(task)}" if _task_text(task) else ""))
            elapsed = time.time() - began
            await asyncio.sleep(1.0 if elapsed < 60 else 3.0 if elapsed < 600 else 10.0)
            try:
                task = await self.rpc(agent, secret, "GetTask", {"id": handle["task"]})
                task = task.get("task") or task
            except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
                await asyncio.sleep(10)

    async def stop(self, session, agent, secret: str, handle: dict) -> bool:
        if "task" not in handle:
            return False
        try:
            await self.rpc(agent, secret, "CancelTask", {"id": handle["task"]})
            return True
        except AgentError:
            return False


def _parts_text(message: dict) -> str:
    return "\n".join(str(p.get("text") or "") for p in message.get("parts") or []
                     if isinstance(p, dict) and str(p.get("text") or "").strip()).strip()


def _task_text(task: dict) -> str:
    texts = [_parts_text(a) for a in task.get("artifacts") or [] if isinstance(a, dict)]
    text = "\n\n".join(t for t in texts if t)
    return text or _parts_text((task.get("status") or {}).get("message") or {})


def _old_params(params: dict) -> dict:
    """The pre-1.0 shapes: lowercase role, `kind` on parts and messages, `blocking: false` instead of returnImmediately."""
    message = params.get("message")
    if not isinstance(message, dict):
        return params
    old = {**message, "role": "user", "kind": "message",
           "parts": [{"kind": "text", "text": p.get("text", "")} for p in message.get("parts") or []]}
    return {"message": old, "configuration": {"blocking": False}}
