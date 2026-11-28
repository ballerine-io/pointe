"""Codex's shared daemon and OpenCode's local service, one of each per machine, with several sessions each, for the
fleet dialogues (bench/fleet/dialogue.py). The voice and its nodes reach them through their own adapters
(pointe/harnesses/codex.py, opencode.py), unchanged: a Unix socket named by CODEX_CONTROL_SOCKET, and an `opencode`
on the PATH that prints the service's URL. They run on one event loop in a thread of the run's own process.

What they keep is what the scorer reads: every request a session was sent (turn/start, turn/steer, prompt), and every
answer to an approval. They never answer anything on their own: a turn ends, or an approval is asked, only when the
dialogue says so. tests/test_codex.py and tests/test_opencode.py hold the one-session fakes these grew from.
"""

import asyncio
import itertools
import json
import secrets
import threading
import time
from pathlib import Path

from aiohttp import web


class Loop:
    """An event loop in a thread: the fakes run on it, and the dialogue calls into it with run()."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

    def run(self, coroutine, timeout: float = 30):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout)

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


def _turn(tid: str, user: str, answer: str, status: str = "completed") -> dict:
    at = int(time.time() * 1000)
    items = [{"type": "userMessage", "id": f"{tid}-u", "content": [{"type": "text", "text": user}]}] if user else []
    if answer:
        items.append({"type": "agentMessage", "id": f"{tid}-a", "text": answer, "phase": "final_answer"})
    return {"id": tid, "items": items, "status": status, "startedAt": at, "completedAt": at + 1}


class CodexMachine:
    """One machine's Codex app-server (JSON-RPC over a WebSocket on a Unix socket), with several loaded threads."""

    def __init__(self, path: Path):
        self.path = path
        self.threads: dict[str, dict] = {}  # id -> {cwd, title, turns}
        self.sent: list[dict] = []  # {session, at, text}: a turn/start or turn/steer
        self.answers: dict[int, dict] = {}  # approval request id -> the voice's result
        self.clients: list = []
        self.server = None
        self._ids = itertools.count(1)

    def add(self, tid: str, cwd: str, title: str, goal: str, last: str) -> None:
        self.threads[tid] = {"cwd": cwd, "title": title, "turns": [_turn(f"{tid[:8]}-t0", goal, last)]}

    async def start(self) -> None:
        from websockets.asyncio.server import unix_serve

        self.server = await unix_serve(self._handle, str(self.path), max_size=None)

    async def stop(self) -> None:
        for ws in list(self.clients):
            await ws.close()
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()

    async def _push(self, message: dict) -> None:
        for ws in list(self.clients):
            try:
                await ws.send(json.dumps({"jsonrpc": "2.0", **message}))
            except Exception:
                pass

    async def _handle(self, ws) -> None:
        self.clients.append(ws)
        try:
            async for raw in ws:
                m = json.loads(raw)
                if "method" not in m:
                    self.answers[m.get("id")] = m.get("result") or {"error": m.get("error")}
                    continue
                if "id" not in m:
                    continue
                result, error = self._answer(m["method"], m.get("params") or {})
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": m["id"],
                                          **({"error": {"message": error}} if error else {"result": result})}))
        except Exception:
            pass
        finally:
            self.clients.remove(ws)

    def _thread(self, tid: str) -> dict:
        t = self.threads[tid]
        return {"id": tid, "name": t["title"], "preview": t["title"], "cwd": t["cwd"], "recencyAt": 5,
                "status": {"type": "idle"}}

    def _answer(self, method: str, params: dict) -> tuple[dict, str | None]:
        tid = params.get("threadId")
        if tid is not None and tid not in self.threads:
            return {}, f"no thread {tid}"
        if method == "initialize":
            return {"userAgent": "fleet-bench"}, None
        if method in ("thread/resume", "thread/read"):
            return {"thread": self._thread(tid)}, None
        if method == "thread/turns/list":
            return {"data": self.threads[tid]["turns"], "nextCursor": None}, None
        if method == "thread/loaded/list":
            return {"data": sorted(self.threads)}, None
        if method == "thread/list":
            return {"data": [self._thread(t) for t in self.threads]}, None
        if method in ("turn/start", "turn/steer"):
            text = " ".join(str(c.get("text") or "") for c in params.get("input") or [] if isinstance(c, dict))
            self.sent.append({"session": tid, "at": time.time(), "text": text})
            return {"turn": {"id": f"{tid[:8]}-r{len(self.sent)}"}}, None
        if method == "thread/fork":
            return {}, "forks are not simulated"
        return {}, None

    async def finish(self, tid: str, text: str) -> None:
        """The thread's agent ends a turn with this message."""
        turn = _turn(f"{tid[:8]}-f{secrets.token_hex(3)}", "", text)
        await self._push({"method": "turn/started", "params": {"threadId": tid, "turn": {"id": turn["id"]}}})
        self.threads[tid]["turns"].append(turn)
        await self._push({"method": "turn/completed", "params": {"threadId": tid, "turn": {"id": turn["id"]}}})

    async def ask(self, tid: str, command: str, reason: str) -> int:
        """The thread asks to run a command; the voice's answer lands in `answers` under the id returned."""
        rid = next(self._ids)
        await self._push({"id": rid, "method": "item/commandExecution/requestApproval",
                          "params": {"threadId": tid, "turnId": f"{tid[:8]}-ask", "itemId": f"{tid[:8]}-cmd{rid}",
                                     "command": f"/bin/zsh -lc '{command}'", "reason": reason, "cwd": self.threads[tid]["cwd"],
                                     "availableDecisions": ["accept", "decline", "cancel"]}})
        return rid


def _assistant(mid: str, text: str) -> dict:
    created = int(time.time() * 1000)
    return {"id": mid, "type": "assistant", "content": [{"type": "text", "text": text}],
            "time": {"created": created, "completed": created + 1}, "finish": "stop"}


class OpenCodeMachine:
    """One machine's OpenCode service (HTTP and an event stream), with several sessions."""

    def __init__(self):
        self.sessions: dict[str, dict] = {}  # id -> {title, messages, permissions}
        self.sent: list[dict] = []  # {session, at, text}: a prompt
        self.answers: dict[str, dict] = {}  # permission id -> the voice's reply
        self.streams: list[asyncio.Queue] = []
        self.url = ""
        self._runner: web.AppRunner | None = None

    def add(self, sid: str, title: str, goal: str, last: str) -> None:
        created = int(time.time() * 1000) - 10_000
        self.sessions[sid] = {"title": title, "permissions": [], "messages": [
            {"id": f"msg_{sid[4:12]}u", "type": "user", "text": goal, "time": {"created": created}},
            {**_assistant(f"msg_{sid[4:12]}a", last), "time": {"created": created + 1, "completed": created + 2}}]}

    async def start(self) -> None:
        app = web.Application()
        r = app.router
        r.add_get("/api/session/{sid}/message", self._messages)
        r.add_get("/api/session/{sid}/permission", self._permissions)
        r.add_post("/api/session/{sid}/permission/{rid}/reply", self._reply)
        r.add_post("/api/session/{sid}/prompt", self._prompt)
        r.add_post("/api/session/{sid}/interrupt", self._interrupt)
        r.add_get("/api/session/{sid}", self._session)
        r.add_get("/api/event", self._events)
        self._runner = web.AppRunner(app, shutdown_timeout=0.2)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"

    async def stop(self) -> None:
        for queue in list(self.streams):
            queue.put_nowait(None)  # each open event stream ends its response
        await asyncio.sleep(0.1)
        if self._runner is not None:
            await self._runner.cleanup()

    def _known(self, request) -> dict | None:
        return self.sessions.get(request.match_info["sid"])

    async def _session(self, request):
        s = self._known(request)
        if s is None:
            return web.json_response({"error": "not found"}, status=404)
        return web.json_response({"data": {"id": request.match_info["sid"], "title": s["title"]}})

    async def _messages(self, request):
        s = self._known(request)
        if s is None:
            return web.json_response({"error": "not found"}, status=404)
        return web.json_response({"data": list(reversed(s["messages"])), "cursor": {}})  # newest first, like the service

    async def _permissions(self, request):
        s = self._known(request)
        return web.json_response({"data": list(s["permissions"]) if s else []})

    async def _reply(self, request):
        sid, rid = request.match_info["sid"], request.match_info["rid"]
        self.answers[rid] = await request.json()
        if sid in self.sessions:
            self.sessions[sid]["permissions"] = [p for p in self.sessions[sid]["permissions"] if p["id"] != rid]
        await self._push({"type": "permission.replied", "data": {"sessionID": sid, "requestID": rid}})
        return web.json_response({})

    async def _prompt(self, request):
        body = await request.json()
        self.sent.append({"session": request.match_info["sid"], "at": time.time(), "text": str(body.get("text") or "")})
        return web.json_response({"data": {}})

    async def _interrupt(self, request):
        return web.json_response({"data": {"interrupted": False}})

    async def _events(self, request):
        queue: asyncio.Queue = asyncio.Queue()
        self.streams.append(queue)
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        try:
            await response.write(b'data: {"type": "server.connected", "data": {}}\n\n')
            while (event := await queue.get()) is not None:
                await response.write(f"data: {json.dumps(event)}\n\n".encode())
        except ConnectionError:  # the adapter went away (its daemon stopped): the stream is over
            pass
        finally:
            self.streams.remove(queue)
        return response

    async def _push(self, event: dict) -> None:
        for queue in list(self.streams):
            queue.put_nowait(event)

    async def finish(self, sid: str, text: str) -> None:
        self.sessions[sid]["messages"].append(_assistant(f"msg_{secrets.token_hex(6)}", text))
        await self._push({"type": "session.idle", "data": {"sessionID": sid}})

    async def ask(self, sid: str, command: str, reason: str) -> str:
        rid = f"per_{secrets.token_hex(6)}"
        request = {"id": rid, "sessionID": sid, "action": "bash", "metadata": {"command": command},
                   "resources": [command], "message": reason}
        self.sessions[sid]["permissions"].append(request)
        await self._push({"type": "permission.asked", "data": request})
        return rid


def opencode_cli(folder: Path, url: str) -> None:
    """An `opencode` for the PATH that answers `opencode service status` with the service's URL, as OpenCode does."""
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "opencode"
    script.write_text(f'#!/bin/sh\nif [ "$1" = service ] && [ "$2" = status ]; then echo "{url} running"; exit 0; fi\nexit 1\n')
    script.chmod(0o755)
