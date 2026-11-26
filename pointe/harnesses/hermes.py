"""Hermes Agent (Nous Research) through its API server's Runs API (docs/design/agents.md).

    POST /v1/runs {input, session_id}        a turn; Idempotency-Key makes a retry safe
    GET  /v1/runs/{id}                       status, output, pending_controls (approvals), tool in progress
    POST /v1/runs/{id}/approval              {request_id, execution_generation, choice: once | deny}
    POST /v1/runs/{id}/stop                  stop the turn
    GET  /api/sessions/{id}/messages         the conversation, when a finished run is no longer kept

Checked against Hermes Agent v0.23.4 (`/v1/capabilities`), live in the agents lab. One Hermes session per agent:
`pointe-<name>`, so Hermes keeps the conversation and its memory as for any of its own channels.
"""

from __future__ import annotations

import asyncio
import time

import aiohttp

from .agent import AgentError, AgentHarness, Reply

TERMINAL = {"completed", "failed", "cancelled", "interrupted", "unknown"}
POLL_SECS = (1.0, 3.0, 10.0)  # under a minute, under ten, then: an agent's turn may take hours


class Hermes(AgentHarness):
    name = "hermes"
    label = "hermes"
    agent = "Hermes"
    approvals = True  # dangerous-command approvals come as pending controls on the run
    interrupts = "now"  # POST /v1/runs/{id}/stop

    def __init__(self) -> None:
        super().__init__()
        self._http: aiohttp.ClientSession | None = None
        self._asking: set[str] = set()

    def http(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30, sock_connect=5))
        return self._http

    async def _call(self, method: str, agent, secret: str, path: str, body: dict | None = None,
                    headers: dict | None = None) -> dict:
        async with self.http().request(method, agent.url.rstrip("/") + path, json=body,
                                       headers={"Authorization": f"Bearer {secret}", **(headers or {})}) as r:
            if r.status == 404:
                raise LookupError(path)
            r.raise_for_status()
            got = await r.json(content_type=None)
            return got if isinstance(got, dict) else {}

    @staticmethod
    def conversation(session) -> str:
        return f"pointe-{session.id.removeprefix('agent-')}"

    async def health(self, session, agent) -> str:
        async with self.http().get(agent.url.rstrip("/") + "/health", timeout=aiohttp.ClientTimeout(total=3)) as r:
            return "" if r.status == 200 else f"{session.name} answered with an error ({r.status})"

    async def check(self, agent, secret: str) -> None:
        """The credential works: /v1/capabilities needs it and costs no model turn."""
        got = await self._call("GET", agent, secret, "/v1/capabilities")
        if not (got.get("features") or {}).get("run_submission"):
            raise AgentError("That server has no Runs API: is it Hermes Agent's API server (API_SERVER_ENABLED=true)?")

    async def submit(self, session, agent, secret: str, message: str, turn: str) -> dict:
        got = await self._call("POST", agent, secret, "/v1/runs", {"input": message, "session_id": self.conversation(session)},
                               headers={"Idempotency-Key": f"pointe-{turn}"})
        if not got.get("run_id"):
            raise AgentError(f"{session.name} did not start the turn.")
        return {"run": got["run_id"]}

    async def wait(self, session, agent, secret: str, handle: dict) -> Reply:
        began, tools, seen_tool = time.time(), [], None
        while True:
            try:
                run = await self._call("GET", agent, secret, f"/v1/runs/{handle['run']}")
            except LookupError:  # kept only briefly after it ended: the conversation still has the answer
                return Reply(await self._last_message(agent, secret, session), tools)
            except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
                await asyncio.sleep(10)  # Hermes restarting, a network blip: the run is still there
                continue
            status = str(run.get("status") or "")
            if run.get("tool") and run.get("tool") != seen_tool:
                seen_tool = run["tool"]
                tools.append({"name": str(seen_tool), "input": {}})
            for control in run.get("pending_controls") or []:
                if control.get("kind") == "approval" and str(control.get("prompt_id")) not in self._asking:
                    asyncio.get_running_loop().create_task(self._approve(session, agent, secret, handle["run"], control))
            if status == "completed":
                return Reply(str(run.get("output") or ""), tools)
            if status in TERMINAL:
                words = {"cancelled": "the turn was stopped", "interrupted": "Hermes restarted during the turn",
                         "unknown": "Hermes lost track of the turn when it restarted"}.get(status, "the turn failed")
                partial = str(run.get("output") or "").strip()
                raise AgentError(f"{words}." + (f" What it had: {partial}" if partial else ""))
            elapsed = time.time() - began
            await asyncio.sleep(POLL_SECS[0] if elapsed < 60 else POLL_SECS[1] if elapsed < 600 else POLL_SECS[2])

    async def _last_message(self, agent, secret: str, session) -> str:
        got = await self._call("GET", agent, secret, f"/api/sessions/{self.conversation(session)}/messages")
        messages = got.get("messages") or got.get("data") or []
        for m in reversed(messages if isinstance(messages, list) else []):
            if isinstance(m, dict) and m.get("role") == "assistant" and isinstance(m.get("content"), str) and m["content"].strip():
                return m["content"]
        raise AgentError("its answer is no longer kept by Hermes.")

    async def _approve(self, session, agent, secret: str, run_id: str, control: dict) -> None:
        prompt = str(control.get("prompt_id"))
        self._asking.add(prompt)
        try:
            async def gone() -> bool:  # answered in Hermes's own surfaces, or the run moved on
                try:
                    run = await self._call("GET", agent, secret, f"/v1/runs/{run_id}")
                except Exception:
                    return False
                return not any(str(c.get("prompt_id")) == prompt for c in run.get("pending_controls") or [])

            verdict = await self.hold(session, str(control.get("command") or ""),
                                      str(control.get("description") or "a dangerous command"), gone)
            if verdict not in ("allow", "deny"):
                return  # nobody answered: Hermes's own timeout denies it
            await self._call("POST", agent, secret, f"/v1/runs/{run_id}/approval",
                             {"request_id": prompt, "execution_generation": control.get("execution_generation"),
                              "choice": "once" if verdict == "allow" else "deny"})
        except Exception as e:
            from loguru import logger

            logger.warning(f"agent {session.name}: approval {prompt[:8]} not answered ({type(e).__name__})")
        finally:
            self._asking.discard(prompt)

    async def stop(self, session, agent, secret: str, handle: dict) -> bool:
        try:
            await self._call("POST", agent, secret, f"/v1/runs/{handle['run']}/stop", {})
            return True
        except (LookupError, aiohttp.ClientResponseError):
            return False
