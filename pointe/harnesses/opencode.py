"""OpenCode (v2): its local background service, which its TUI also uses, so the voice drives the session the user is
typing in. Discovery: `opencode service status` (a random localhost port) and HTTP Basic auth with the password in
~/.config/opencode/service.json, read when needed and never logged.

Watch: one SSE connection to /api/event; an event naming the session means "something changed", and the session's
messages are read again from /api/session/{id}/message, which is the source of truth (the stream has no replay). What
is new is written to a mirror transcript in Claude Code's JSONL shape, so the transcript follower, reports, notes and
"by the way" answers from the record all work unchanged.

Send: POST /api/session/{id}/prompt {text, delivery: "steer"}. Approvals: a permission.asked event goes through the
daemon's permission flow (read-out, consent rules, Face ID taps); the answer is POST .../permission/{id}/reply
{decision: "once" | "reject"}. If the user answers in OpenCode first (permission.replied), the voice lets go.
Side questions: a fork of the session answers, and the fork is deleted.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

import aiohttp
from loguru import logger

import childenv

from .base import HOST, Harness, StartError, refuse_bypass

SERVICE_FILE = Path(os.environ.get("OPENCODE_SERVICE_FILE", Path.home() / ".config" / "opencode" / "service.json"))
RESYNC_SECS = 5.0  # a slow poll under the event stream: the stream drops a slow reader and does not replay
GONE_AFTER_SECS = 60.0  # the service unreachable this long, or the session deleted: it is off the voice
TOOL_NAMES = {"bash": "Bash", "shell": "Bash", "edit": "Edit", "write": "Write", "read": "Read", "webfetch": "WebFetch", "glob": "Glob",
              "grep": "Grep", "list": "LS", "patch": "Edit", "multiedit": "MultiEdit", "task": "Task"}


class Service:
    """Where the local OpenCode service is, and how to talk to it. The URL is looked up again after a failure."""

    def __init__(self, url: str | None = None, password: str | None = None):
        self._url, self._password = url, password
        self._http: aiohttp.ClientSession | None = None

    def url(self) -> str:
        if not self._url:
            got = subprocess.run(["opencode", "service", "status"], capture_output=True, text=True, timeout=10,
                                 env=childenv.child_env())
            words = got.stdout.split()
            if got.returncode or not words or not words[0].startswith("http"):
                raise ConnectionError("the OpenCode service is not running (start OpenCode, or `opencode service start`)")
            self._url = words[0]
        return self._url

    def forget_url(self) -> None:
        self._url = None

    def _auth(self) -> str:
        password = self._password or json.loads(SERVICE_FILE.read_text())["password"]
        return "Basic " + base64.b64encode(f"opencode:{password}".encode()).decode()

    def http(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=5))
        return self._http

    async def close(self) -> None:
        if self._http is not None and not self._http.closed:
            await self._http.close()

    async def call(self, method: str, path: str, body: dict | None = None, timeout: float = 15) -> dict | None:
        url = await asyncio.to_thread(self.url)
        async with self.http().request(method, url + path, json=body, headers={"Authorization": self._auth()},
                                       timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            if r.status == 404:
                raise LookupError(path)
            r.raise_for_status()
            text = await r.text()
            return json.loads(text) if text.strip() else None

    async def events(self):
        """The service's event stream, one decoded event at a time."""
        url = await asyncio.to_thread(self.url)
        async with self.http().get(url + "/api/event", headers={"Authorization": self._auth()},
                                   timeout=aiohttp.ClientTimeout(total=None, sock_read=60)) as r:
            r.raise_for_status()
            async for raw in r.content:
                line = raw.decode(errors="replace").strip()
                if line.startswith("data:"):
                    try:
                        yield json.loads(line[5:])
                    except ValueError:
                        continue


def tool_request(request: dict) -> tuple[str, dict]:
    """An OpenCode permission request as the daemon's (tool name, tool input), so the read-out allowlist applies."""
    action = str(request.get("action") or "tool")
    meta = request.get("metadata") or {}
    resources = [str(r) for r in request.get("resources") or []]
    name = TOOL_NAMES.get(action.lower(), action)
    if name in ("Bash", "Edit", "Write", "Read", "MultiEdit") and len(resources) > 1 and not (
            meta.get("command") or meta.get("filePath") or meta.get("file_path") or meta.get("path")):
        return name, {"description": str(request.get("message") or action), "resources": resources}  # all shown, none read out
    if name == "Bash":
        return name, {"command": str(meta.get("command") or (resources[0] if resources else "")),
                      "description": str(request.get("message") or meta.get("description") or "")}
    if name in ("Edit", "Write", "Read", "MultiEdit"):
        path = str(meta.get("filePath") or meta.get("file_path") or meta.get("path") or (resources[0] if resources else ""))
        return name, {"file_path": path, "description": str(request.get("message") or "")}
    return name, {"description": str(request.get("message") or action), "resources": resources, **meta}


def mirror_lines(message: dict) -> list[dict]:
    """One OpenCode message as Claude Code transcript entries (user / assistant), for the existing follower."""
    kind, stamp = message.get("type"), message.get("time", {}).get("created")
    base = {"ocMessageID": message.get("id"), "timestamp": stamp}
    if kind == "user":
        return [{**base, "type": "user", "message": {"role": "user", "content": str(message.get("text") or "")}}]
    if kind != "assistant":
        return []
    out = []
    texts = []
    for item in message.get("content") or []:
        if item.get("type") == "tool":
            state = item.get("state") or {}
            out.append({**base, "type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": str(item.get("id")), "name": str(item.get("name")), "input": state.get("input") or {}}]}})
            if state.get("status") in ("completed", "error"):  # what it did: an edit applied, a test's output
                out.append({**base, "type": "user", "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": str(item.get("id")),
                     "content": str(state.get("output") or state.get("error") or ""), "is_error": state.get("status") == "error"}]}})
        elif item.get("type") == "text" and str(item.get("text") or "").strip():
            texts.append(str(item["text"]).strip())
    if texts:
        final = message.get("finish") == "stop"
        out.append({**base, "type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "\n\n".join(texts)}], **({"stop_reason": "end_turn"} if final else {})}})
    return out


def finished(message: dict) -> bool:
    """A message that will not change any more: users at once, assistants once completed."""
    if message.get("type") != "assistant":
        return True
    return bool((message.get("time") or {}).get("completed") or message.get("finish"))


class OpenCode(Harness):
    name = "opencode"
    label = "opencode"
    agent = "OpenCode"
    approvals = True
    interrupts = "now"  # POST /api/session/{id}/interrupt
    side_questions = True
    attach = True
    starts = True
    permission_deadline = 600.0  # OpenCode's own prompt waits as long as it takes: the voice still lets go eventually

    def __init__(self, service: Service | None = None):
        self.service = service or Service()
        self._seen: dict[str, set[str]] = {}  # session id -> message ids already in the mirror
        self._last_ok: dict[str, float] = {}
        self._gone: set[str] = set()
        self._replied: set[str] = set()  # permission requests answered in OpenCode itself
        self._asking: set[str] = set()  # permission requests being put to the user now

    @staticmethod
    def mirror_path(session_id: str) -> Path:
        state = HOST.state_dir or Path(os.environ.get("CLAUDE_VOICE_STATE", Path.home() / ".claude-voice"))
        return Path(state) / "harness" / "opencode" / f"{session_id}.jsonl"

    def alive(self, session) -> bool:
        if session.id in self._gone:
            return False
        last = self._last_ok.get(session.id)
        return last is None or time.time() - last < GONE_AFTER_SECS

    def title(self, session) -> str | None:
        return (session.harness_data or {}).get("title") or None

    async def probe(self, session) -> None:
        """Checked from the daemon's liveness loop, also with no call up: a deleted session drops off, a renamed one
        is renamed, without the event stream (which runs only during a call)."""
        try:
            got = await self.service.call("GET", f"/api/session/{session.id}", timeout=5)
        except LookupError:
            self._gone.add(session.id)
            return
        except (aiohttp.ClientError, ConnectionError, OSError, asyncio.TimeoutError):
            self.service.forget_url()
            return
        self._last_ok[session.id] = time.time()
        title = ((got or {}).get("data") or {}).get("title")
        if title and isinstance(session.harness_data, dict):
            session.harness_data["title"] = title

    def join(self, argv: list[str]) -> dict:
        import argparse

        parser = argparse.ArgumentParser(prog="pointe join opencode")
        parser.add_argument("--session")
        parser.add_argument("--name")
        parser.add_argument("--install-command", action="store_true")
        args = parser.parse_args(argv)
        if args.install_command:
            install_command()
            return {}
        found = pick_session(os.getcwd(), args.session)
        cwd = (found.get("location") or {}).get("directory") or os.getcwd()
        return {"id": found["id"], "name": args.name or Path(cwd).name, "name_given": bool(args.name), "cwd": cwd,
                "transcript": str(self.mirror_path(found["id"])), "harness_data": {"title": found.get("title") or ""}}

    def can_start(self) -> str | None:
        return None if shutil.which("opencode") else "OpenCode is not installed on this Mac."

    async def start(self, cwd: str, name: str, start_id: str, skip: bool = False) -> dict | None:
        """A new session at `cwd` on the local service, with the title the voice calls it. No agent, model or
        permission rules are sent: it starts as OpenCode's own configuration says."""
        if skip:  # `skips` is False here: the daemon never asks, and a caller that does is refused
            raise StartError("Not started: Pointe never starts a session that skips its permission prompts.")
        body = {"location": {"directory": cwd}, "title": name}
        refuse_bypass(*body)  # its keys: a `permissions` ruleset is never sent
        if set(body) - {"location", "title"}:
            raise StartError("Not started: Pointe never starts a session that skips its permission prompts.")
        try:
            got = await self.service.call("POST", "/api/session", body)
        except FileNotFoundError:
            raise StartError(self.can_start() or "OpenCode is not installed on this Mac.")
        except (aiohttp.ClientError, ConnectionError, LookupError, OSError, asyncio.TimeoutError, subprocess.SubprocessError) as e:
            self.service.forget_url()
            logger.info(f"OpenCode session not started: {type(e).__name__}")
            raise StartError("OpenCode's service is not running. Open OpenCode, or run `opencode service start`, and try again.")
        made = (got or {}).get("data") or {}
        if not made.get("id"):
            raise StartError("OpenCode did not create the session.")
        self._last_ok[made["id"]] = time.time()
        return {"id": made["id"], "name": name, "name_given": True, "cwd": cwd,
                "transcript": str(self.mirror_path(made["id"])), "harness_data": {"title": made.get("title") or name}}

    def open_hint(self, session) -> str:
        return f"opencode --session {session.id}"

    async def discover(self, since: float, cap: int) -> list:
        """Every session on the service (`/api/session`, newest first) and the ones running a turn (`/api/session/active`).
        All of them are driven through the service, so none needs reopening: active ones, and ones updated in the last
        OPEN_SECS, are listed as open, older ones as recent. Child sessions are left out."""
        from discovery import Found, keywords

        try:
            listed = (await self.service.call("GET", f"/api/session?limit={max(1, cap * 2)}", timeout=10) or {}).get("data") or []
            active = set(((await self.service.call("GET", "/api/session/active", timeout=10) or {}).get("data") or {}).keys())
        except (aiohttp.ClientError, ConnectionError, LookupError, OSError, asyncio.TimeoutError, FileNotFoundError,
                subprocess.SubprocessError, ValueError) as e:
            logger.info(f"OpenCode sessions not listed: {type(e).__name__}")
            return []
        now, out, recent = time.time(), [], 0
        for s in listed:
            if not isinstance(s, dict) or not s.get("id") or s.get("parentID"):
                continue
            cwd = str((s.get("location") or {}).get("directory") or s.get("directory") or "")
            updated = (s.get("time") or {}).get("updated") or (s.get("time") or {}).get("created") or 0
            when = float(updated) / (1000 if float(updated) > 1e11 else 1)  # milliseconds in OpenCode's records
            state = "open" if s["id"] in active or now - when < OPEN_SECS else "recent"
            if state == "recent" and (when < since or recent >= cap):
                continue
            recent += state == "recent"
            title = str(s.get("title") or "")
            found = Found(harness=self.name, id=str(s["id"]), name=title or Path(cwd).name or "opencode", cwd=cwd,
                          state=state, when=when, title=title, keywords=keywords(title), name_given=bool(title),
                          transcript=str(self.mirror_path(str(s["id"]))), status="busy" if s["id"] in active else "")
            if cwd and not os.path.isdir(cwd):
                found.joinable, found.why = False, "Its folder is no longer there."
            out.append(found)
        return out

    def attach_body(self, found) -> dict:
        """What `pointe join opencode --session <id>` registers."""
        cwd = found.cwd or os.getcwd()
        self._last_ok[found.id] = time.time()
        self._gone.discard(found.id)
        return {"id": found.id, "name": Path(cwd).name, "name_given": False, "cwd": cwd,
                "transcript": str(self.mirror_path(found.id)), "harness_data": {"title": found.title}}

    def watch(self, session, feed):
        from sessions import follow_transcript

        async def run():
            await self.sync(session, history=True)  # what came before goes into the record, not the feed
            follower = asyncio.create_task(follow_transcript(session, feed, lambda: None))
            try:
                await asyncio.gather(self._events(session), self._poll(session))
            finally:
                follower.cancel()

        return [run()]

    async def sync(self, session, history: bool = False) -> None:
        """Write what is new and finished to the mirror. With history, the first read only fills the record."""
        path = self.mirror_path(session.id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        seen = self._seen.get(session.id)
        if seen is None:
            seen = set()
            if path.exists():
                for line in path.read_text().splitlines():
                    try:
                        seen.add(json.loads(line).get("ocMessageID"))
                    except ValueError:
                        continue
            self._seen[session.id] = seen
        try:
            got = await self.service.call("GET", f"/api/session/{session.id}/message?limit=100")
        except LookupError:
            logger.info(f"OpenCode session {session.name} is gone")
            self._gone.add(session.id)
            return
        except (aiohttp.ClientError, ConnectionError, OSError, asyncio.TimeoutError) as e:
            self.service.forget_url()
            logger.info(f"OpenCode not reachable for {session.name}: {type(e).__name__}")
            return
        self._last_ok[session.id] = time.time()
        messages = sorted((got or {}).get("data") or [], key=lambda m: ((m.get("time") or {}).get("created") or 0, m.get("id")))
        lines = []
        for message in messages:
            if message.get("id") in seen or not finished(message):
                continue  # an assistant message still streaming is read again next time
            seen.add(message.get("id"))
            lines += mirror_lines(message)
        if lines:
            with path.open("a") as f:
                f.write("".join(json.dumps(line) + "\n" for line in lines))
            path.chmod(0o600)

    async def _poll(self, session) -> None:
        while session.id not in self._gone:
            await asyncio.sleep(RESYNC_SECS)
            await self.sync(session)
            await self._pending_permissions(session)

    async def _events(self, session) -> None:
        backoff = 1.0
        while session.id not in self._gone:
            try:
                async for event in self.service.events():
                    backoff = 1.0
                    data = event.get("data") if isinstance(event.get("data"), dict) else {}
                    if data.get("sessionID") != session.id:
                        continue
                    kind = event.get("type")
                    if kind == "permission.asked":
                        asyncio.create_task(self._permission(session, data))
                    elif kind == "permission.replied":
                        self._replied.add(str(data.get("requestID")))
                    elif kind in ("session.idle", "session.execution.succeeded", "session.step.ended",
                                  "session.tool.called", "session.execution.failed"):
                        await self.sync(session)
            except (aiohttp.ClientError, ConnectionError, OSError, asyncio.TimeoutError) as e:
                logger.info(f"OpenCode event stream for {session.name} dropped ({type(e).__name__}); reconnecting")
                self.service.forget_url()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
            await self.sync(session)  # the stream does not replay: read again what may have been missed

    async def _pending_permissions(self, session) -> None:
        """A request asked while the stream was down is still listed: put it to the user too."""
        try:
            got = await self.service.call("GET", f"/api/session/{session.id}/permission")
        except Exception:
            return
        for request in (got or {}).get("data") or []:
            if str(request.get("id")) not in self._asking:
                asyncio.create_task(self._permission(session, request))

    async def _permission(self, session, request: dict) -> None:
        request_id = str(request.get("id"))
        if request_id in self._asking or request_id in self._replied:
            return
        self._asking.add(request_id)
        try:
            tool_name, tool_input = tool_request(request)

            async def gone() -> bool:
                return request_id in self._replied

            verdict = await HOST.hold_permission(session, tool_name, tool_input, gone) if HOST.hold_permission else None
            if verdict is None or request_id in self._replied:
                return  # OpenCode's own prompt answers it
            await self.service.call("POST", f"/api/session/{session.id}/permission/{request_id}/reply",
                                    {"decision": "once" if verdict == "allow" else "reject",
                                     **({"message": "The user denied this by voice."} if verdict == "deny" else {})})
        except Exception as e:
            logger.warning(f"OpenCode permission {request_id} for {session.name}: {type(e).__name__}")
        finally:
            self._asking.discard(request_id)

    async def send(self, session, text: str) -> bool:
        from sessions import voice_message

        try:
            await self.service.call("POST", f"/api/session/{session.id}/prompt",
                                    {"text": voice_message(text), "delivery": "steer"})
            return True
        except Exception as e:
            logger.error(f"OpenCode prompt to {session.name} failed: {type(e).__name__}")
            return False

    async def interrupt(self, session) -> bool:
        """POST /api/session/{id}/interrupt: the service cuts the running execution and says whether one ran."""
        try:
            got = await self.service.call("POST", f"/api/session/{session.id}/interrupt", {})
        except Exception as e:
            logger.error(f"OpenCode interrupt of {session.name} failed: {type(e).__name__}")
            return False
        got = got or {}
        return bool((got.get("data") if isinstance(got.get("data"), dict) else got).get("interrupted"))

    async def side_question(self, session, question: str) -> str | None:
        """A fork answers, so the live session is never touched; the fork is deleted after."""
        fork = (await self.service.call("POST", f"/api/session/{session.id}/fork", {}) or {}).get("data") or {}
        fork_id = fork.get("id")
        if not fork_id:
            return None
        try:
            await self.service.call("POST", f"/api/session/{fork_id}/prompt", {
                "text": f"{question}\n\n(Answer from what you already know in this session. Do not use any tool.)"})
            deadline = time.time() + 110
            while time.time() < deadline:
                await asyncio.sleep(2)
                got = await self.service.call("GET", f"/api/session/{fork_id}/message?limit=10")
                answers = [m for m in (got or {}).get("data") or [] if m.get("type") == "assistant" and m.get("finish") == "stop"]
                if answers:
                    latest = max(answers, key=lambda m: (m.get("time") or {}).get("created") or 0)
                    text = " ".join(str(c.get("text") or "") for c in latest.get("content") or [] if c.get("type") == "text")
                    return text.strip() or None
            return None
        finally:
            try:
                await self.service.call("DELETE", f"/api/session/{fork_id}")
            except Exception as e:
                logger.info(f"OpenCode fork {fork_id[:12]} not deleted: {type(e).__name__}")


# ---------- joining from the command line (pointe join opencode) ----------

OPEN_SECS = 2 * 3600  # an OpenCode session touched this recently is listed as open: the service keeps them all
PLUGIN = Path.home() / ".config" / "opencode" / "plugins" / "pointe-voice.ts"
ROOT = Path(__file__).resolve().parents[2]


def _service_get(path: str) -> dict:
    url = subprocess.run(["opencode", "service", "status"], capture_output=True, text=True, timeout=10,
                         env=childenv.child_env()).stdout.split()
    if not url or not url[0].startswith("http"):
        raise SystemExit("OpenCode's service is not running. Open OpenCode (or run `opencode service start`) and try again.")
    password = json.loads(SERVICE_FILE.read_text())["password"]
    request = urllib.request.Request(url[0] + path, headers={
        "Authorization": "Basic " + base64.b64encode(f"opencode:{password}".encode()).decode()})
    return json.loads(urllib.request.urlopen(request, timeout=10).read())


def pick_session(cwd: str, wanted: str | None) -> dict:
    if wanted:
        return _service_get(f"/api/session/{wanted}")["data"]
    found = _service_get("/api/session?" + urllib.parse.urlencode({"directory": cwd, "limit": 20}))["data"]
    found = [s for s in found if (s.get("location") or {}).get("directory") == cwd and not s.get("parentID")]
    if not found:
        raise SystemExit(f"No OpenCode session in {cwd}. Start one there first, or pass --session.")
    running = set((_service_get("/api/session/active").get("data") or {}).keys())
    return max(found, key=lambda s: (s["id"] in running, (s.get("time") or {}).get("updated") or 0))


def pointe_command() -> Path:
    """The `pointe` a command written into another program runs: ~/.local/bin/pointe when Pointe wrote it, which follows
    updates and the newer of the plugin and the standalone install (bin/link-pointe); else this copy's, whose folder an
    update deletes."""
    link = Path.home() / ".local" / "bin" / "pointe"
    try:
        if "# Written by Pointe (bin/link-pointe)" in link.read_text(errors="replace"):  # uninstall.LINK_MARK
            return link
    except OSError:
        pass
    return ROOT / "bin" / "pointe"


def install_command() -> None:
    """An OpenCode v2 plugin with a /voice command: it joins the session it is typed in."""
    pointe = pointe_command()
    PLUGIN.parent.mkdir(parents=True, exist_ok=True)
    PLUGIN.write_text(f'''// Pointe: /voice joins this OpenCode session to the shared voice. Written by `pointe join opencode --install-command`.
import {{ execFile }} from "node:child_process"
import {{ promisify }} from "node:util"
import {{ Plugin }} from "@opencode/plugin"

const run = promisify(execFile)

export default Plugin.define({{
  id: "pointe.voice",
  async setup(ctx) {{
    await ctx.command.transform((editor) => {{
      editor.add({{
        name: "voice",
        description: "Join this session to the Pointe voice",
        async execute(input) {{
          await run({json.dumps(str(pointe))}, ["join", "opencode", "--session", String(input.sessionID)])
        }},
      }})
    }})
  }},
}})
''')
    print(f"Added /voice to OpenCode ({PLUGIN}). Restart OpenCode to load it.")


