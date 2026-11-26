"""OpenClaw through its Gateway WebSocket, protocol 4, as an operator client (docs/design/agents.md).

    connect {role: operator, client.mode: backend, auth.token, caps: [exec-approvals]}   the handshake
    chat.send {sessionKey, message, idempotencyKey} -> {runId}                          a turn
    event chat {runId, sessionKey, state: final | error | aborted, message}             its reply
    chat.abort {sessionKey, runId}                                                      stop it
    event exec.approval.requested {id, request: {command, sessionKey, ...}}            an approval
    exec.approval.resolve {id, decision: allow-once | deny}                             its answer
    chat.history {sessionKey, limit}                                                    catch up after a reconnect

The gateway delivers an approval only to a client that declares the `exec-approvals` capability and holds
`operator.approvals`; `operator.admin` lets it see approvals the gateway's own tool runtime raised. With none connected
the gateway denies at once ("Headless runs cannot wait for interactive exec approval"). Checked against OpenClaw
2026.11.10, live in the agents lab. One socket per agent, kept open while the daemon runs, so a reply the agent posts
later on its own (a scheduled job announcing into the conversation) arrives too.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from urllib.parse import urlparse

import aiohttp
from loguru import logger

from .agent import AgentError, AgentHarness, Reply

PROTOCOL = 4
SCOPES = ["operator.read", "operator.write", "operator.approvals", "operator.admin"]
CAPS = ["exec-approvals"]
CONNECT_SECS = 30.0  # the gateway's own connect deadline


def ws_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = {"http": "ws", "https": "wss"}.get(parsed.scheme, parsed.scheme)
    return parsed._replace(scheme=scheme).geturl().rstrip("/")


class Link:
    """One gateway socket: requests by id, events to the harness. Reconnects with backoff while it is wanted."""

    def __init__(self, harness: "OpenClaw", agent, secret_fn):
        self.harness, self.agent, self.secret_fn = harness, agent, secret_fn
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.http: aiohttp.ClientSession | None = None
        self.pending: dict[str, asyncio.Future] = {}
        self.ready = asyncio.Event()
        self.task: asyncio.Task | None = None
        self.why = ""  # the last connect failure, fixed words
        self.connects = 0

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.get_running_loop().create_task(self._run())

    async def close(self) -> None:
        if self.task:
            self.task.cancel()
        if self.ws is not None:
            await self.ws.close()
        if self.http is not None:
            await self.http.close()

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            try:
                await self._connect_and_read()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except AgentError as e:
                self.why = str(e)
            except Exception as e:
                from .agent import _offline_words

                self.why = _offline_words(self.agent.name, e)
            self.ready.clear()
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("the gateway connection dropped"))
            self.pending.clear()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    async def _connect_and_read(self) -> None:
        secret = await asyncio.to_thread(self.secret_fn, self.agent)
        if not secret:
            raise AgentError(f"Pointe could not read {self.agent.name}'s credential from the Keychain")
        if self.http is None or self.http.closed:
            self.http = aiohttp.ClientSession()
        async with self.http.ws_connect(ws_url(self.agent.url), max_msg_size=0, heartbeat=30,
                                        timeout=aiohttp.ClientWSTimeout(ws_close=5)) as ws:
            challenge = await asyncio.wait_for(ws.receive_json(), CONNECT_SECS)
            if challenge.get("event") != "connect.challenge":
                raise AgentError(f"{self.agent.name} is not an OpenClaw gateway")
            hello_id = uuid.uuid4().hex
            await ws.send_json({"type": "req", "id": hello_id, "method": "connect", "params": {
                "minProtocol": PROTOCOL, "maxProtocol": PROTOCOL,
                "client": {"id": "gateway-client", "version": "1", "platform": "pointe", "mode": "backend"},
                "role": "operator", "scopes": SCOPES, "caps": CAPS, "commands": [], "permissions": {},
                "auth": {"token": secret, "password": secret}, "locale": "en-US", "userAgent": "pointe"}})
            secret = None
            deadline = time.time() + CONNECT_SECS
            while True:
                frame = await asyncio.wait_for(ws.receive_json(), max(0.1, deadline - time.time()))
                if frame.get("id") == hello_id:
                    break
            if not frame.get("ok"):
                code = str(((frame.get("error") or {}).get("details") or {}).get("code") or (frame.get("error") or {}).get("code") or "")
                if "AUTH" in code or "TOKEN" in code or "UNAUTHORIZED" in code:
                    raise AgentError(f"{self.agent.name} refused Pointe's credential: connect it again with a current one")
                if "PROTOCOL" in code:
                    raise AgentError(f"{self.agent.name} speaks another protocol version: update Pointe or OpenClaw")
                raise AgentError(f"{self.agent.name} refused the connection ({code or 'no reason given'})")
            self.ws, self.why = ws, ""
            self.connects += 1
            self.ready.set()
            if self.connects > 1:
                asyncio.get_running_loop().create_task(self.harness.catch_up(self))
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    frame = json.loads(msg.data)
                except ValueError:
                    continue
                if frame.get("type") == "res" and frame.get("id") in self.pending:
                    future = self.pending.pop(frame["id"])
                    if not future.done():
                        future.set_result(frame)
                elif frame.get("type") == "event":
                    self.harness.event(self, str(frame.get("event") or ""), frame.get("payload") or {})
        self.ws = None

    async def request(self, method: str, params: dict, timeout: float = 20) -> dict:
        self.start()
        try:
            await asyncio.wait_for(self.ready.wait(), min(timeout, 15))
        except asyncio.TimeoutError:
            raise AgentError(self.why or f"{self.agent.name} is not reachable: is its gateway running?")
        rid = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[rid] = future
        await self.ws.send_json({"type": "req", "id": rid, "method": method, "params": params})
        frame = await asyncio.wait_for(future, timeout)
        if not frame.get("ok"):
            error = frame.get("error") or {}
            raise AgentError(f"{self.agent.name} refused it ({error.get('code') or 'no reason given'})")
        return frame.get("payload") or {}


class OpenClaw(AgentHarness):
    name = "openclaw"
    label = "openclaw"
    agent = "OpenClaw"
    approvals = True  # exec approvals, when the gateway's exec policy asks
    interrupts = "now"  # chat.abort

    def __init__(self) -> None:
        super().__init__()
        self.links: dict[str, Link] = {}  # session id -> its link
        self.sessions: dict[str, object] = {}  # session id -> Session, for events
        self.waiting: dict[str, asyncio.Future] = {}  # runId -> the reply
        self.answered: set[str] = set()  # approval ids answered (anywhere)
        self.asking: set[str] = set()

    @staticmethod
    def key(session, agent) -> str:
        return f"agent:{agent.agent or 'main'}:pointe-{session.id.removeprefix('agent-')}"

    def link(self, session, agent) -> Link:
        from .agent import SECRET

        link = self.links.get(session.id)
        if link is None or link.agent.url != agent.url or link.agent.agent != agent.agent:
            if link is not None:
                asyncio.get_running_loop().create_task(link.close())
            link = self.links[session.id] = Link(self, agent, SECRET)
        self.sessions[session.id] = session
        link.start()
        return link

    async def health(self, session, agent) -> str:
        link = self.link(session, agent)
        try:
            await asyncio.wait_for(link.ready.wait(), 3)
        except asyncio.TimeoutError:
            return link.why or f"{session.name} is not reachable: is its gateway running?"
        return ""

    async def check(self, agent, secret: str) -> None:
        """The credential works: a full handshake on a socket of its own, then closed."""
        async with aiohttp.ClientSession() as http:
            async with http.ws_connect(ws_url(agent.url), max_msg_size=0) as ws:
                challenge = await asyncio.wait_for(ws.receive_json(), CONNECT_SECS)
                if challenge.get("event") != "connect.challenge":
                    raise AgentError("That address is not an OpenClaw gateway.")
                await ws.send_json({"type": "req", "id": "check", "method": "connect", "params": {
                    "minProtocol": PROTOCOL, "maxProtocol": PROTOCOL,
                    "client": {"id": "gateway-client", "version": "1", "platform": "pointe", "mode": "backend"},
                    "role": "operator", "scopes": SCOPES, "caps": [], "commands": [], "permissions": {},
                    "auth": {"token": secret, "password": secret}, "locale": "en-US", "userAgent": "pointe"}})
                while True:
                    frame = await asyncio.wait_for(ws.receive_json(), CONNECT_SECS)
                    if frame.get("id") == "check":
                        break
                if not frame.get("ok"):
                    raise AgentError("The gateway refused that token or password.")

    async def submit(self, session, agent, secret: str, message: str, turn: str) -> dict:
        got = await self.link(session, agent).request("chat.send", {"sessionKey": self.key(session, agent), "message": message,
                                                                   "idempotencyKey": f"pointe-{turn}"})
        run = got.get("runId")
        if not run:
            raise AgentError(f"{session.name} did not start the turn.")
        self.waiting.setdefault(run, asyncio.get_running_loop().create_future())
        return {"run": run}

    async def wait(self, session, agent, secret: str, handle: dict) -> Reply:
        future = self.waiting.setdefault(handle["run"], asyncio.get_running_loop().create_future())
        link = self.link(session, agent)
        while not future.done():
            try:
                await asyncio.wait_for(asyncio.shield(future), 60)
            except asyncio.TimeoutError:
                if link.connects and not link.ready.is_set():
                    continue  # reconnecting: catch_up resolves it from the history
                try:  # still running? a run that ended while this socket was away is in the history
                    await self._resolve_from_history(link, session, agent)
                except Exception:
                    pass
        self.waiting.pop(handle["run"], None)
        return future.result()

    async def stop(self, session, agent, secret: str, handle: dict) -> bool:
        got = await self.link(session, agent).request("chat.abort", {"sessionKey": self.key(session, agent), "runId": handle["run"]})
        return bool(got.get("aborted", True))

    # ---------- events ----------

    def _session_of(self, key: str):
        for sid, session in self.sessions.items():
            agent = self.config(session)
            if agent is not None and self.key(session, agent) == key:
                return session, agent
        return None, None

    def event(self, link: Link, name: str, payload: dict) -> None:
        if name == "chat":
            self._chat(payload)
        elif name == "exec.approval.requested":
            request = payload.get("request") or {}
            session, agent = self._session_of(str(request.get("sessionKey") or ""))
            if session is not None and str(payload.get("id")) not in self.asking:
                asyncio.get_running_loop().create_task(self._approve(link, session, payload))
        elif name == "exec.approval.resolved":
            self.answered.add(str(payload.get("id")))

    def _chat(self, payload: dict) -> None:
        state = payload.get("state")
        if state not in ("final", "error", "aborted"):
            return
        session, agent = self._session_of(str(payload.get("sessionKey") or ""))
        if session is None:
            return
        run = str(payload.get("runId") or "")
        future = self.waiting.get(run)
        text = _text(payload.get("message"))
        if state == "final":
            reply = Reply(text)
        else:
            reply = AgentError("the turn was stopped." if state == "aborted" else
                               f"the turn failed. {str(payload.get('errorMessage') or '')[:300]}".strip())
        session.harness_data["seen"] = max(float(session.harness_data.get("seen") or 0), _stamp(payload.get("message")))
        if future is not None:
            if not future.done():
                (future.set_exception if isinstance(reply, Exception) else future.set_result)(reply)
        elif state == "final" and text:
            self.reply(session, text)  # a reply nobody here asked for: a scheduled job announcing into the conversation

    async def catch_up(self, link: Link) -> None:
        """After a reconnect: replies posted while the socket was away (`chat.history`, newer than the last seen)."""
        for sid in list(self.links):
            if self.links.get(sid) is not link or sid not in self.sessions:
                continue
            session = self.sessions[sid]
            agent = self.config(session)
            if agent is not None:
                try:
                    await self._resolve_from_history(link, session, agent)
                except Exception as e:
                    logger.info(f"agent {session.name}: history not read after a reconnect ({type(e).__name__})")

    async def _resolve_from_history(self, link: Link, session, agent) -> None:
        got = await link.request("chat.history", {"sessionKey": self.key(session, agent), "limit": 20})
        seen = float(session.harness_data.get("seen") or 0)
        mine = [run for run in self.waiting if not self.waiting[run].done()]
        for message in got.get("messages") or []:
            if not isinstance(message, dict) or message.get("role") != "assistant" or _stamp(message) <= seen:
                continue
            text = _text(message)
            if not text:
                continue
            session.harness_data["seen"] = _stamp(message)
            run = str(message.get("runId") or message.get("openclawRunId") or "")
            target = run if run in mine else (mine[0] if len(mine) == 1 else None)
            if target:
                self.waiting[target].set_result(Reply(text))
                mine.remove(target)
            else:
                self.reply(session, text)

    async def _approve(self, link: Link, session, payload: dict) -> None:
        approval = str(payload.get("id"))
        request = payload.get("request") or {}
        self.asking.add(approval)
        try:
            async def gone() -> bool:
                return approval in self.answered

            where = str(request.get("cwd") or "")
            verdict = await self.hold(session, str(request.get("command") or ""),
                                      f"{session.name} wants to run this" + (f" in {where}" if where else ""), gone)
            if verdict not in ("allow", "deny") or approval in self.answered:
                return  # nobody answered here: the gateway's own timeout and askFallback (deny) decide
            await link.request("exec.approval.resolve", {"id": approval, "decision": "allow-once" if verdict == "allow" else "deny"})
        except Exception as e:
            logger.warning(f"agent {session.name}: approval {approval[:8]} not answered ({type(e).__name__})")
        finally:
            self.asking.discard(approval)

    async def leave(self, session) -> None:
        await super().leave(session)
        link = self.links.pop(session.id, None)
        self.sessions.pop(session.id, None)
        if link is not None:
            await link.close()


def _text(message) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    return "\n\n".join(str(b.get("text") or "").strip() for b in content or []
                       if isinstance(b, dict) and b.get("type") == "text" and str(b.get("text") or "").strip())


def _stamp(message) -> float:
    try:
        return float((message or {}).get("timestamp") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0.0
