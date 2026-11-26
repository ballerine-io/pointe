"""Fake agent servers for the agent-framework harnesses (docs/design/agents.md): the routes and frames Pointe uses of
OpenClaw's gateway, Hermes's API server, an A2A server and an OpenAI-compatible endpoint, each with state a test can
change. No real framework, no model. Shapes copied from OpenClaw 2026.11.10 and Hermes Agent v0.23.4 as seen live."""

import asyncio
import itertools
import json
import uuid

from aiohttp import WSMsgType, web

TOKEN = "made-up-agent-token"


async def serve(app: web.Application):
    runner = web.AppRunner(app, shutdown_timeout=0.2)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"


def _authed(request) -> bool:
    return request.headers.get("Authorization") == f"Bearer {TOKEN}"


class FakeHermes:
    """/v1/runs: a run is `running` for `polls` reads, then completes; or asks an approval first."""

    def __init__(self):
        self.runs: dict[str, dict] = {}
        self.inputs: list[dict] = []
        self.approvals: list[dict] = []
        self.stops: list[str] = []
        self.polls = 2
        self.approve_command = ""  # a run asks this approval before finishing
        self.answer = "Hermes here: the calendar is clear on Friday."

    def app(self):
        app = web.Application()
        app.router.add_get("/health", self.health)
        app.router.add_get("/v1/capabilities", self.capabilities)
        app.router.add_post("/v1/runs", self.start)
        app.router.add_get("/v1/runs/{rid}", self.get)
        app.router.add_post("/v1/runs/{rid}/approval", self.approval)
        app.router.add_post("/v1/runs/{rid}/stop", self.stop)
        app.router.add_get("/api/sessions/{sid}/messages", self.messages)
        return app

    async def health(self, request):
        return web.json_response({"status": "ok", "version": "0.23.4"})

    async def capabilities(self, request):
        if not _authed(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response({"object": "hermes.api_server.capabilities", "features": {"run_submission": True}})

    async def start(self, request):
        if not _authed(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        body = await request.json()
        self.inputs.append({**body, "idempotency": request.headers.get("Idempotency-Key")})
        rid = f"run_{uuid.uuid4().hex[:8]}"
        self.runs[rid] = {"run_id": rid, "status": "running", "session_id": body.get("session_id"), "reads": 0,
                          "pending_controls": [], "output": ""}
        if self.approve_command:
            self.runs[rid]["pending_controls"] = [{"kind": "approval", "prompt_id": f"p{rid}", "execution_generation": 1,
                                                   "command": self.approve_command, "description": "recursive delete",
                                                   "choices": ["once", "deny", "session", "always"]}]
            self.runs[rid]["status"] = "waiting_for_approval"
        return web.json_response({"run_id": rid, "status": "started"})

    async def get(self, request):
        run = self.runs.get(request.match_info["rid"])
        if run is None:
            return web.json_response({"error": "not found"}, status=404)
        run["reads"] += 1
        if run["status"] == "running" and run["reads"] > self.polls:
            run["status"], run["output"] = "completed", self.answer
        return web.json_response({k: v for k, v in run.items() if k != "reads"})

    async def approval(self, request):
        run = self.runs[request.match_info["rid"]]
        body = await request.json()
        self.approvals.append(body)
        run["pending_controls"] = []
        run["status"] = "completed"
        run["output"] = "Done, the folder is gone." if body["choice"] == "once" else "You denied it, so nothing ran."
        return web.json_response({"status": "resolved"})

    async def stop(self, request):
        self.stops.append(request.match_info["rid"])
        self.runs[request.match_info["rid"]]["status"] = "cancelled"
        return web.json_response({"status": "stopping"})

    async def messages(self, request):
        return web.json_response({"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "From the history."}]})


class FakeOpenClaw:
    """The gateway WebSocket: challenge, connect, chat.send (a final `chat` event after a moment), chat.abort,
    chat.history, and an exec approval before the reply when `approve_command` is set."""

    def __init__(self):
        self.sent: list[dict] = []
        self.connects: list[dict] = []
        self.resolved: list[dict] = []
        self.aborted: list[dict] = []
        self.approve_command = ""
        self.answer = "OpenClaw here: I booked the table for seven."
        self.history: list[dict] = []
        self.sockets: list[web.WebSocketResponse] = []
        self._ids = itertools.count(1)

    def app(self):
        app = web.Application()
        app.router.add_get("/", self.ws)
        return app

    async def broadcast(self, event: str, payload: dict) -> None:
        for ws in list(self.sockets):
            if not ws.closed:
                await ws.send_json({"type": "event", "event": event, "payload": payload, "seq": next(self._ids)})

    async def ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json({"type": "event", "event": "connect.challenge", "payload": {"nonce": "n", "ts": 1}})
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            frame = json.loads(msg.data)
            method, params, rid = frame.get("method"), frame.get("params") or {}, frame.get("id")
            if method == "connect":
                self.connects.append(params)
                if (params.get("auth") or {}).get("token") != TOKEN:
                    await ws.send_json({"type": "res", "id": rid, "ok": False,
                                        "error": {"code": "UNAUTHORIZED", "details": {"code": "AUTH_TOKEN_MISMATCH"}}})
                    await ws.close()
                    break
                self.sockets.append(ws)
                await ws.send_json({"type": "res", "id": rid, "ok": True, "payload": {"type": "hello-ok", "protocol": 4}})
            elif method == "chat.send":
                self.sent.append(params)
                run = f"run-{len(self.sent)}"
                await ws.send_json({"type": "res", "id": rid, "ok": True, "payload": {"runId": run, "status": "started"}})
                asyncio.get_running_loop().create_task(self._turn(params, run))
            elif method == "exec.approval.resolve":
                self.resolved.append(params)
                await ws.send_json({"type": "res", "id": rid, "ok": True, "payload": {"ok": True}})
                await self.broadcast("exec.approval.resolved", {"id": params["id"], "decision": params["decision"]})
            elif method == "chat.abort":
                self.aborted.append(params)
                await ws.send_json({"type": "res", "id": rid, "ok": True, "payload": {"aborted": True}})
                await self.broadcast("chat", {"runId": params["runId"], "sessionKey": params["sessionKey"], "state": "aborted"})
            elif method == "chat.history":
                await ws.send_json({"type": "res", "id": rid, "ok": True, "payload": {"messages": self.history}})
            else:
                await ws.send_json({"type": "res", "id": rid, "ok": False, "error": {"code": "UNKNOWN_METHOD"}})
        return ws

    async def _turn(self, params: dict, run: str) -> None:
        await asyncio.sleep(0.05)
        key = params["sessionKey"]
        if self.approve_command:
            approval = f"appr-{run}"
            await self.broadcast("exec.approval.requested", {"id": approval, "request": {
                "command": self.approve_command, "cwd": "/home/node/.openclaw/workspace", "sessionKey": key, "runId": run}})
            while not any(r["id"] == approval for r in self.resolved):
                await asyncio.sleep(0.02)
            decision = next(r["decision"] for r in self.resolved if r["id"] == approval)
            text = "Ran it." if decision == "allow-once" else "The operator declined, so I did not run it."
        else:
            text = self.answer
        await self.broadcast("chat", {"runId": run, "sessionKey": key, "state": "delta", "deltaText": text[:5]})
        await self.broadcast("chat", {"runId": run, "sessionKey": key, "state": "final", "message": {
            "role": "assistant", "content": [{"type": "text", "text": text}], "timestamp": 1795734223229}})


class FakeA2A:
    """An A2A 1.0 server (`SendMessage` returns a working task, `GetTask` completes it), or a pre-1.0 one (`old`)."""

    def __init__(self, old: bool = False):
        self.old = old
        self.calls: list[dict] = []
        self.tasks: dict[str, int] = {}
        self.answer = "The A2A agent says: three open invoices."

    def app(self):
        app = web.Application()
        app.router.add_get("/.well-known/agent-card.json", self.card)
        app.router.add_post("/rpc", self.rpc)
        return app

    async def card(self, request):
        base = f"http://{request.host}"
        if self.old:
            return web.json_response({"name": "old", "url": base + "/rpc", "protocolVersion": "0.3.0"})
        return web.json_response({"name": "fake", "supportedInterfaces": [{"url": base + "/rpc", "protocolBinding": "JSONRPC",
                                                                           "protocolVersion": "1.0"}]})

    async def rpc(self, request):
        if not _authed(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        body = await request.json()
        self.calls.append(body)
        method, params = body["method"], body.get("params") or {}
        new = {"SendMessage", "GetTask", "CancelTask"}
        if self.old and method in new:
            return web.json_response({"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32601, "message": "Method not found"}})
        if method in ("SendMessage", "message/send"):
            tid = f"task-{len(self.tasks) + 1}"
            self.tasks[tid] = 0
            state = "working" if self.old else "TASK_STATE_WORKING"
            return web.json_response({"jsonrpc": "2.0", "id": body["id"], "result": {"task": {
                "id": tid, "contextId": params["message"].get("contextId"), "status": {"state": state}}}})
        if method in ("GetTask", "tasks/get"):
            self.tasks[params["id"]] += 1
            done = self.tasks[params["id"]] >= 2
            state = ("completed" if done else "working") if self.old else ("TASK_STATE_COMPLETED" if done else "TASK_STATE_WORKING")
            return web.json_response({"jsonrpc": "2.0", "id": body["id"], "result": {"task": {
                "id": params["id"], "status": {"state": state},
                **({"artifacts": [{"artifactId": "a1", "parts": [{"text": self.answer}]}]} if done else {})}}})
        return web.json_response({"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32601, "message": "Method not found"}})


class FakeOpenAI:
    """/v1/models and /v1/chat/completions: the reply says how many messages it was sent."""

    def __init__(self):
        self.bodies: list[dict] = []

    def app(self):
        app = web.Application()
        app.router.add_get("/v1/models", self.models)
        app.router.add_post("/v1/chat/completions", self.chat)
        return app

    async def models(self, request):
        if not _authed(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response({"object": "list", "data": [{"id": "agent-model"}]})

    async def chat(self, request):
        if not _authed(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        body = await request.json()
        self.bodies.append(body)
        return web.json_response({"choices": [{"index": 0, "finish_reason": "stop", "message": {
            "role": "assistant", "content": f"I have {len(body['messages'])} messages from you."}}]})
