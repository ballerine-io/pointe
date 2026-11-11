"""Codex CLI: its shared app-server daemon, which a TUI started with `codex --remote unix:// -C "$PWD"` also uses, so the
voice drives the thread the user is typing in. A plain `codex` runs its app-server inside its own process and holds the
thread's writer lock: it cannot be joined, and joining says how to start it instead.

Protocol (Codex 0.160+, JSON-RPC 2 over a WebSocket on the Unix socket ~/.codex/app-server-control/
app-server-control.sock): initialize + initialized; thread/loaded/list and thread/list {cwd} to find the thread;
thread/resume {threadId, excludeTurns} to subscribe to its events. Watch: turn/started, item/completed, turn/completed
filtered by threadId; history and final answers from thread/turns/list (full items), mirrored into a transcript in
Claude Code's JSONL shape so reports, notes and the record work unchanged. Send: turn/start when idle, turn/steer
{expectedTurnId} during a turn. Approvals: the server's item/commandExecution/requestApproval and
item/fileChange/requestApproval go through the daemon's permission flow, answered with a decision Codex offered;
serverRequest/resolved means the TUI answered first. Side questions: an ephemeral, read-only fork answers.
The daemon updates itself and restarts when idle: the connection comes back and the thread is resumed again.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import re
import time
from pathlib import Path

from loguru import logger

from .base import HOST, Harness

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
GONE_AFTER_SECS = 60.0  # the daemon unreachable this long, or the thread closed: it is off the voice
START_HINT = 'start Codex with `codex --remote unix:// -C "$PWD"` (alias codex to it), then join again'
_SHELL = re.compile(r"^/bin/(?:z|ba)?sh -l?c '(.*)'$", re.S)


def control_socket() -> Path:
    return Path(os.environ.get("CODEX_CONTROL_SOCKET", CODEX_HOME / "app-server-control" / "app-server-control.sock"))


class RpcError(Exception):
    pass


class Connection:
    """One JSON-RPC link to the Codex daemon, shared by every Codex session on the voice. Reconnects when the daemon
    restarts, and tells its listeners so they resume their threads."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self._socket = None
        self._ids = itertools.count(1000)
        self._waiting: dict[int, asyncio.Future] = {}
        self._reader: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self.listeners: list = []  # async callables (method, params, request_id | None)
        self.reconnected: list = []  # async callables run after each new connection
        self.down_since: float | None = None
        self._closing = False

    @property
    def up(self) -> bool:
        return self._socket is not None

    async def ensure(self) -> None:
        async with self._lock:
            if self._socket is not None:
                return
            from websockets.asyncio.client import unix_connect

            path = str(self.path or control_socket())
            self._socket = await unix_connect(path, uri="ws://localhost/", max_size=None, open_timeout=5)
            self._reader = asyncio.create_task(self._read(self._socket))
            await self.request("initialize", {"clientInfo": {"name": "pointe", "version": "1"},
                                              "capabilities": {"experimentalApi": True}})
            await self._send({"jsonrpc": "2.0", "method": "initialized"})
            self.down_since = None
        for again in list(self.reconnected):
            asyncio.create_task(again())

    async def _send(self, message: dict) -> None:
        if self._socket is None:
            raise ConnectionError("the Codex daemon is not connected")
        await self._socket.send(json.dumps(message))

    async def request(self, method: str, params: dict, timeout: float = 30) -> dict:
        request_id = next(self._ids)
        answer = asyncio.get_running_loop().create_future()
        self._waiting[request_id] = answer
        try:
            await self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            return await asyncio.wait_for(answer, timeout)
        finally:
            self._waiting.pop(request_id, None)

    async def reply(self, request_id, result: dict) -> None:
        await self._send({"jsonrpc": "2.0", "id": request_id, "result": result})

    async def _read(self, socket) -> None:
        try:
            async for raw in socket:
                try:
                    message = json.loads(raw)
                except ValueError:
                    continue
                if "method" in message:  # a notification, or a request from the server (it has an id)
                    for listener in list(self.listeners):
                        asyncio.create_task(listener(message["method"], message.get("params") or {}, message.get("id")))
                elif message.get("id") in self._waiting:
                    future = self._waiting[message["id"]]
                    if not future.done():
                        if "error" in message:
                            future.set_exception(RpcError(str((message["error"] or {}).get("message") or message["error"])))
                        else:
                            future.set_result(message.get("result") or {})
        except Exception as e:
            if not self._closing:
                logger.info(f"Codex daemon link dropped ({type(e).__name__})")
        finally:
            if self._socket is socket:
                self._socket = None
                self.down_since = time.time()
                for future in self._waiting.values():
                    if not future.done():
                        future.set_exception(ConnectionError("the Codex daemon went away"))

    async def close(self) -> None:
        self._closing = True
        if self._socket is not None:
            await self._socket.close()


def command_text(command: str) -> str:
    """What runs, without the shell wrapper Codex adds: `/bin/zsh -lc 'touch x'` is `touch x`."""
    found = _SHELL.match(command.strip())
    return found.group(1).replace("'\\''", "'") if found else command


def tool_request(method: str, params: dict) -> tuple[str, dict] | None:
    """A Codex approval request as the daemon's (tool name, tool input), so the read-out allowlist applies. None for
    kinds the voice does not answer (permission grants): the TUI asks for those."""
    if method == "item/commandExecution/requestApproval":
        return "Bash", {"command": command_text(str(params.get("command") or "")), "description": str(params.get("reason") or "")}
    if method == "item/fileChange/requestApproval":
        return "Edit", {"file_path": str(params.get("grantRoot") or ""), "description": str(params.get("reason") or "Change files")}
    return None


def decision(verdict: str, offered: list) -> str | None:
    """A decision Codex offered: accept for a yes; decline (the turn goes on) or cancel for a no."""
    plain = [d for d in offered or ["accept", "decline", "cancel"] if isinstance(d, str)]
    wanted = ["accept"] if verdict == "allow" else ["decline", "cancel"]
    return next((d for d in wanted if d in plain), None)


def mirror_lines(turn: dict) -> list[dict]:
    """A finished Codex turn as Claude Code transcript entries, for the existing follower."""
    out, finals = [], []
    stamp = turn.get("completedAt") or turn.get("startedAt")
    for item in turn.get("items") or []:
        base = {"cxItemID": item.get("id"), "timestamp": stamp}
        kind = item.get("type")
        if kind == "userMessage":
            text = " ".join(str(c.get("text") or "") for c in item.get("content") or [] if c.get("type") == "text").strip()
            if text:
                out.append({**base, "type": "user", "message": {"role": "user", "content": text}})
        elif kind == "commandExecution":
            out.append({**base, "type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": command_text(str(item.get("command") or ""))}}]}})
        elif kind == "fileChange":
            out.append({**base, "type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Edit", "input": {"changes": len(item.get("changes") or [])}}]}})
        elif kind == "agentMessage" and str(item.get("text") or "").strip():
            finals.append((base, str(item["text"]).strip()))
    for i, (base, text) in enumerate(finals):
        last = i == len(finals) - 1 and turn.get("status") == "completed"
        out.append({**base, "type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}],
                                                             **({"stop_reason": "end_turn"} if last else {})}})
    return out


class Codex(Harness):
    name = "codex"
    label = "codex"
    agent = "Codex"
    approvals = True
    side_questions = True
    attach = True
    permission_deadline = 600.0

    def __init__(self, connection: Connection | None = None):
        self.link = connection or Connection()
        self.link.listeners.append(self._on_message)
        self.link.reconnected.append(self._resume_all)
        self._sessions: dict[str, object] = {}  # thread id -> session, while watched
        self._seen: dict[str, set[str]] = {}
        self._active_turn: dict[str, str | None] = {}
        self._resolved: set = set()
        self._closed: set[str] = set()
        self._changed: dict[str, asyncio.Event] = {}

    @staticmethod
    def mirror_path(thread_id: str) -> Path:
        state = HOST.state_dir or Path(os.environ.get("CLAUDE_VOICE_STATE", Path.home() / ".claude-voice"))
        return Path(state) / "harness" / "codex" / f"{thread_id}.jsonl"

    def alive(self, session) -> bool:
        if session.id in self._closed:
            return False
        down = self.link.down_since
        return down is None or time.time() - down < GONE_AFTER_SECS

    def title(self, session) -> str | None:
        return (session.harness_data or {}).get("title") or None

    async def probe(self, session) -> None:
        try:
            await self.link.ensure()
            got = await self.link.request("thread/read", {"threadId": session.id}, timeout=5)
        except RpcError:
            self._closed.add(session.id)
            return
        except (ConnectionError, OSError, asyncio.TimeoutError):
            return
        thread = got.get("thread") or {}
        if (thread.get("status") or {}).get("type") == "notLoaded":
            self._closed.add(session.id)  # the TUI closed it
        if thread.get("name") and isinstance(session.harness_data, dict):
            session.harness_data["title"] = thread["name"]

    def join(self, argv: list[str]) -> dict:
        import argparse

        parser = argparse.ArgumentParser(prog="pointe join codex")
        parser.add_argument("--thread")
        parser.add_argument("--name")
        args = parser.parse_args(argv)
        found = asyncio.run(pick_thread(os.getcwd(), args.thread, self.link.path))
        cwd = thread_cwd(found) or os.getcwd()
        return {"id": found["id"], "name": args.name or Path(cwd).name, "name_given": bool(args.name), "cwd": cwd,
                "transcript": str(self.mirror_path(found["id"])),
                "harness_data": {"title": found.get("name") or found.get("preview") or ""}}

    def watch(self, session, feed):
        from sessions import follow_transcript

        async def run():
            self._sessions[session.id] = session
            self._changed.setdefault(session.id, asyncio.Event())
            follower = None
            try:
                while session.id not in self._closed:
                    try:
                        await self.link.ensure()
                        await self._resume(session)
                        break
                    except RpcError as e:
                        if "active writer" in str(e):
                            await feed(session, f"[{self.label}: not reachable] This Codex thread runs inside a plain "
                                                f"`codex`, which locks it. Tell the user to {START_HINT}.", False)
                            self._closed.add(session.id)
                            return
                        await asyncio.sleep(3)  # "no rollout found": nothing to resume before the first turn
                    except (ConnectionError, OSError, asyncio.TimeoutError):
                        await asyncio.sleep(3)
                await self.sync(session, history=True)  # what came before goes into the record, not the feed
                follower = asyncio.create_task(follow_transcript(session, feed, lambda: None))
                while session.id not in self._closed:
                    try:
                        await asyncio.wait_for(self._changed[session.id].wait(), 10)
                    except asyncio.TimeoutError:
                        pass
                    self._changed[session.id].clear()
                    if not self.link.up:
                        try:
                            await self.link.ensure()  # the daemon restarted (it updates itself): come back
                        except (ConnectionError, OSError, asyncio.TimeoutError):
                            continue
                    await self.sync(session)
            finally:
                if follower:
                    follower.cancel()
                self._sessions.pop(session.id, None)

        return [run()]

    async def _resume(self, session) -> None:
        got = await self.link.request("thread/resume", {"threadId": session.id, "excludeTurns": True})
        status = ((got.get("thread") or {}).get("status") or {}).get("type")
        if status != "active":
            self._active_turn[session.id] = None

    async def _resume_all(self) -> None:
        for session in list(self._sessions.values()):
            try:
                await self._resume(session)
                self._changed[session.id].set()  # read what happened while the link was down
            except Exception as e:
                logger.info(f"Codex thread {session.id[:12]} not resumed after a reconnect: {type(e).__name__}")

    async def sync(self, session, history: bool = False) -> None:
        """Write finished turns that are new to the mirror. With history, the first read only fills the record."""
        path = self.mirror_path(session.id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        seen = self._seen.get(session.id)
        if seen is None:
            seen = set()
            if path.exists():
                for line in path.read_text().splitlines():
                    try:
                        seen.add(json.loads(line).get("cxTurnID"))
                    except ValueError:
                        continue
            self._seen[session.id] = seen
        try:
            got = await self.link.request("thread/turns/list", {"threadId": session.id, "limit": 50, "itemsView": "full"})
        except RpcError as e:
            logger.info(f"Codex turns of {session.name} unreadable: {e}")
            return
        except (ConnectionError, OSError, asyncio.TimeoutError):
            return
        turns = sorted(got.get("data") or [], key=lambda t: (t.get("startedAt") or 0, t.get("id")))
        lines = []
        for turn in turns:
            if turn.get("id") in seen or turn.get("status") == "inProgress":
                continue  # a turn still running is read again when it completes
            seen.add(turn.get("id"))
            lines += [{**line, "cxTurnID": turn.get("id")} for line in mirror_lines(turn)]
        if lines:
            with path.open("a") as f:
                f.write("".join(json.dumps(line) + "\n" for line in lines))
            path.chmod(0o600)

    async def _on_message(self, method: str, params: dict, request_id) -> None:
        thread = params.get("threadId") or (params.get("thread") or {}).get("id")
        session = self._sessions.get(thread)
        if method == "serverRequest/resolved":
            self._resolved.add(params.get("requestId"))
            return
        if session is None:
            return
        if method == "turn/started":
            self._active_turn[thread] = (params.get("turn") or {}).get("id")
        elif method == "turn/completed":
            self._active_turn[thread] = None
            self._changed[thread].set()
        elif method == "thread/closed" or (method == "thread/status/changed" and
                                           (params.get("status") or {}).get("type") == "notLoaded"):
            self._closed.add(thread)
            self._changed[thread].set()
        elif method == "thread/name/updated" and isinstance(session.harness_data, dict):
            session.harness_data["title"] = params.get("threadName") or session.harness_data.get("title")
        elif request_id is not None and method.endswith("requestApproval"):
            await self._permission(session, method, params, request_id)

    async def _permission(self, session, method: str, params: dict, request_id) -> None:
        asked = tool_request(method, params)
        if asked is None or not HOST.hold_permission:
            return  # the TUI asks for it
        tool_name, tool_input = asked

        async def gone() -> bool:
            return request_id in self._resolved

        try:
            verdict = await HOST.hold_permission(session, tool_name, tool_input, gone)
            if verdict is None or request_id in self._resolved:
                return  # answered in the TUI, or the voice let go
            chosen = decision(verdict, params.get("availableDecisions") or [])
            if chosen:
                await self.link.reply(request_id, {"decision": chosen})
        except Exception as e:
            logger.warning(f"Codex approval for {session.name}: {type(e).__name__}")

    async def send(self, session, text: str) -> bool:
        from sessions import voice_message

        message = [{"type": "text", "text": voice_message(text)}]
        try:
            await self.link.ensure()
            turn = self._active_turn.get(session.id)
            if turn:
                try:
                    await self.link.request("turn/steer", {"threadId": session.id, "expectedTurnId": turn, "input": message})
                    return True
                except RpcError:
                    self._active_turn[session.id] = None  # it ended meanwhile: start a new turn instead
            await self.link.request("turn/start", {"threadId": session.id, "input": message})
            return True
        except Exception as e:
            logger.error(f"Codex message to {session.name} failed: {type(e).__name__}: {e}")
            return False

    async def side_question(self, session, question: str) -> str | None:
        """An ephemeral, read-only fork answers: the user's thread is not touched, and nothing is kept on disk."""
        await self.link.ensure()
        fork = await self.link.request("thread/fork", {"threadId": session.id, "ephemeral": True, "excludeTurns": True,
                                                        "sandbox": "read-only", "approvalPolicy": "never"})
        fork_id = (fork.get("thread") or {}).get("id")
        if not fork_id:
            return None
        done = asyncio.get_running_loop().create_future()

        async def finished(method, params, _request_id):
            if method == "turn/completed" and params.get("threadId") == fork_id and not done.done():
                done.set_result(params.get("turn") or {})

        self.link.listeners.append(finished)
        try:
            await self.link.request("turn/start", {"threadId": fork_id, "input": [{"type": "text", "text":
                                    f"{question}\n\n(Answer from what you already know in this thread. Do not run anything.)"}]})
            turn = await asyncio.wait_for(done, 110)
            texts = [str(i.get("text") or "") for i in turn.get("items") or [] if i.get("type") == "agentMessage"]
            return texts[-1].strip() if texts and texts[-1].strip() else None
        finally:
            self.link.listeners.remove(finished)


def thread_cwd(thread: dict) -> str | None:
    envs = thread.get("environments") or []
    return thread.get("cwd") or (envs[0].get("cwd") if envs else None)


def _same_folder(a: str | None, b: str | None) -> bool:
    return bool(a and b) and os.path.realpath(a) == os.path.realpath(b)


def _aliases_of(cwd: str) -> list[str]:
    """macOS spells /tmp and /var as /private/tmp and /private/var once resolved; Codex keeps what it was given."""
    real = os.path.realpath(cwd)
    return [real.removeprefix("/private")] if real.startswith(("/private/tmp", "/private/var")) else []


async def pick_thread(cwd: str, wanted: str | None, path: Path | None = None) -> dict:
    """The thread to join: the one named, else the newest one in this folder that the shared daemon has loaded."""
    link = Connection(path)
    try:
        await link.ensure()
    except (ConnectionError, OSError) as e:
        raise SystemExit(f"Codex's shared daemon is not running ({type(e).__name__}). {START_HINT[0].upper()}{START_HINT[1:]}.")
    try:
        if wanted:
            return (await link.request("thread/read", {"threadId": wanted})).get("thread") or {"id": wanted}
        loaded = set((await link.request("thread/loaded/list", {})).get("data") or [])
        # The same folder can be spelled two ways (/tmp is /private/tmp on macOS, or any symlink): ask for each, and
        # compare real paths.
        spellings = sorted({cwd, os.path.realpath(cwd), *_aliases_of(cwd)})
        here = (await link.request("thread/list", {"cwd": spellings, "limit": 20})).get("data") or []
        here = [t for t in here if _same_folder(thread_cwd(t), cwd)]
        joinable = [t for t in here if t.get("id") in loaded]
        if not joinable:
            if here:
                raise SystemExit(f"The Codex thread in {cwd} runs inside a plain `codex`, which cannot be joined: {START_HINT}.")
            for thread_id in loaded:  # loaded but not listed yet: a new thread before its first message
                try:
                    thread = (await link.request("thread/read", {"threadId": thread_id})).get("thread") or {}
                except RpcError:
                    continue
                if _same_folder(thread_cwd(thread), cwd):
                    raise SystemExit("The Codex session here has no message yet: send it one, then join again.")
            raise SystemExit(f"No Codex thread in {cwd}. Start one there: {START_HINT}.")
        return max(joinable, key=lambda t: t.get("recencyAt") or t.get("updatedAt") or 0)
    finally:
        await link.close()
