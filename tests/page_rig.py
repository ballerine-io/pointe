"""The page (ui.html) in a headless Chrome, against a stub Mac.

The stub plays the daemon over real HTTP: it serves ui.html as daemon.py does and answers /voice/status from a fixture
the test mutates. A POST changes the fixture the way the real route would (switch, mode, prefs.microphone, polish,
listen, dump), so the page sees its own request come back on the next poll. `delay` stalls every answer, as a Mac whose event
loop froze does. The browser is the one the e2e rig uses, driven over the DevTools protocol.

Used by tests/test_ui_perf.py (regressions) and tests/e2e/page_perf.py (the numbers).
"""

import asyncio
import json
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def page_html() -> str:
    """ui.html with its includes, as daemon.py serves it."""
    return (
        (ROOT / "ui.html").read_text().replace("{{LOGO}}", (ROOT / "assets" / "logo.svg").read_text())
        .replace("{{DICTIONARY}}", (ROOT / "ui_dictionary.html").read_text())
        .replace("{{WHISPER}}", (ROOT / "ui_whisper.html").read_text())
    )


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------- the fixture: what /voice/status says ----------

MACHINES = [("studio", "macos", True), ("devbox", "linux", False), ("laptop", "macos", False)]
LOREM = ("the tests pass on the branch now; the flaky one needed a longer timeout on the socket read, "
         "and I left a note in the docstring about why it waits for the second heartbeat before asserting")


def fixture(sessions: int = 1, machines: int = 1, talk: int = 0, approval: bool = False, connected: bool = False) -> dict:
    """A status like the daemon's. `sessions` spread over `machines` (the first is this Mac), one waiting on an approval
    when asked, the rest cycling through working, idle and a question for the user."""
    names = [f"s{i}-{['shop', 'api', 'mobile', 'infra', 'docs'][i % 5]}" for i in range(sessions)]
    rows = []
    for i, name in enumerate(names):
        machine = MACHINES[i % machines][0] if machines > 1 and i % machines else ""
        waiting = approval and i == 1
        rows.append({"name": name, "harness": "opencode" if i == 3 else "claude-code", "capabilities": {"approvals": True},
                     "working": not waiting and i % 3 != 2, "waiting": waiting, "machine": machine, "online": True,
                     "request": "Bash(rm -rf build && make test)" if waiting else None, "request_id": f"perm-{i}" if waiting else None,
                     "voice_can_approve": waiting, "needs": "which branch should it target?" if (not waiting and i % 5 == 4) else None,
                     "mode": "channel"})
    now = time.time()
    machine_rows = [{"id": name, "name": name, "here": here, "os": os_, "online": True, "since": now - 3600,
                     "sessions": sum(1 for r in rows if (r["machine"] or MACHINES[0][0]) == name),
                     "need": 0, "rtt_ms": None if here else 23 + 10 * k, "key_fp": None if here else f"ab{k}1cd"}
                    for k, (name, os_, here) in enumerate(MACHINES[:machines])]
    turns = [{"id": i + 1, "who": "user" if i % 2 == 0 else "bot",
              "text": (f"Turn {i + 1}: what is the state of the build? " if i % 2 == 0 else f"Turn {i + 1}: {LOREM}"),
              "typed": False, "corrected": False} for i in range(talk)]
    attention = [{"id": "perm-1", "kind": "permission", "title": f"{names[1]} needs approval", "body": "Bash(rm -rf build && make test)",
                  "text": f"{names[1]} needs approval", "approvable": True}] if approval and sessions > 1 else []
    return {
        "active": names[0] if names else None, "connected": connected, "problem": None, "idle_hangup": False, "monologue": None,
        "brain_dump": None,
        "speaking": None, "mode": "orchestrator",
        "ptt": {"mode": "always", "open": False, "sent_bytes": 0, "room_heard": False},
        "whisper": {"on": False, "held": None, "suggest_ptt": False, "lock_note": None},
        "mode_state": {"mode": "normal", "speech": "full", "approvals": "voice"},
        "drive": {"on": False, "pending": []}, "local": {"line": "Cloud voice: Soniox + ElevenLabs"},
        "meeting": None, "notes": {"version": 0, "last_id": 0}, "attention": attention, "conflicts": [],
        "briefing": {"playing": False, "paused": False, "building": False, "part": 0, "parts": 0, "latest_id": None},
        "challenge": None,
        "voice_lock": {"level": "off", "enrolled": False, "devices": [], "enrolling": None, "lines": [], "model": "ready", "problem": None,
                       "ignored": {"count": 0, "last_at": None, "recent": []}, "speaker": None, "unsure_streak": 0},
        "jobs": {}, "showing": None, "shown_earlier": [], "show_on_phone": False, "dictionary": {"learned_this_call": []},
        "tokens": {"context": 48210, "at": "15:04"}, "router": "orchestrator: named session → auto (gate) → active session",
        "recent": [{"said": f"what is {names[i % max(1, len(names))] if names else 'shop'} doing", "at": f"15:0{i}:12",
                    "to": [names[i % len(names)]] if names else [], "how": "named"} for i in range(min(8, max(1, sessions)))],
        "call": {}, "talk": turns, "polish": False, "hearing": "", "machines": machine_rows, "invite": None, "can_invite": True,
        "invite_ended": None, "phones": {"paired": []}, "sessions": rows,
    }


# ---------- the stub Mac ----------

class StubMac:
    """Serves the page and the fixture; `delay` seconds before every answer when set."""

    def __init__(self, port: int):
        self.port = port
        self.status = fixture()
        self.delay = 0.0
        self.posts: list[tuple[str, dict, float]] = []  # path, body, when it was answered
        self.status_hits = 0
        self._runner = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/voice"

    async def start(self) -> "StubMac":
        app = web.Application()
        app.router.add_get("/voice", self._page)
        app.router.add_get("/voice/call", self._call)
        app.router.add_get("/voice/status", self._status)
        app.router.add_get("/voice/prefs", self._prefs)
        app.router.add_get("/voice/briefings", self._briefings)
        app.router.add_get("/voice/context", self._context)
        app.router.add_get("/voice/phone/invite", self._ok)
        app.router.add_get("/voice/artifact", self._gone)
        app.router.add_get("/voice/new-session", self._new_session)
        app.router.add_route("POST", "/{tail:.*}", self._post)
        app.router.add_route("DELETE", "/{tail:.*}", self._ok)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, "127.0.0.1", self.port).start()
        return self

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    async def _stall(self) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)

    async def _page(self, request):
        return web.Response(text=page_html(), content_type="text/html")

    async def _call(self, request):  # the call's socket: accepted, never spoken on
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for _ in ws:
            pass
        return ws

    async def _status(self, request):
        self.status_hits += 1
        await self._stall()
        return web.json_response(self.status)

    async def _prefs(self, request):
        await self._stall()
        return web.json_response({"microphone": self.status["ptt"]["mode"], "meeting.default_mode": "listening", "meeting.auto_lookups": False,
                                  "meeting.notes_language": "auto", "meeting.consented": False, "conflicts.on": True, "conflicts.spoken": True,
                                  "alerts.watch_approve": False, "show.on_phone": False, "whisper": False, "dictionary.learn": True})

    async def _briefings(self, request):
        await self._stall()
        return web.json_response({"schedule": {"time": "", "days": [0, 1, 2, 3, 4, 5, 6], "length": "normal", "speak_on_connect": True,
                                               "skip_empty": False}, "briefings": []})

    async def _context(self, request):
        await self._stall()
        return web.json_response({"tokens": None, "connected": False, "breakdown": [], "messages": []})

    async def _ok(self, request):
        await self._stall()
        return web.json_response({"ok": True})

    # What the New session sheet is offered (daemon.new_session_options); a test may replace it.
    new_session = {"harnesses": [{"name": "claude-code", "title": "Claude Code", "available": True, "why": None},
                                 {"name": "opencode", "title": "OpenCode", "available": True, "why": None},
                                 {"name": "codex", "title": "Codex", "available": False, "why": "Codex is not installed on this Mac."}],
                   "machines": [{"name": "studio", "here": True, "available": True, "why": None}],
                   "folders": [{"path": "/Users/sam/work/shop", "name": "shop", "source": "session"},
                               {"path": "/Users/sam/work/billing", "name": "billing", "source": "recent"}],
                   "max_prompt": 4000}

    async def _new_session(self, request):
        await self._stall()
        return web.json_response(self.new_session)

    async def _gone(self, request):
        return web.json_response({"detail": "gone"}, status=404)

    async def _post(self, request):
        body = await request.json() if request.can_read_body else {}
        await self._stall()
        path = request.path
        s = self.status
        if path == "/voice/switch":
            s["mode"], s["active"] = "session", body["name"]
        elif path == "/voice/mode":
            s["mode"] = body["mode"]
        elif path == "/voice/prefs" and "microphone" in body:
            s["ptt"]["mode"] = body["microphone"]
        elif path == "/voice/polish":
            s["polish"] = bool(body.get("on"))
        elif path == "/voice/new-session":  # as daemon.new_session: a start shows as a row; a tap answers the read-back
            pending = s.get("start_pending")
            if "confirm" in body or "cancel" in body:
                s["start_pending"] = None
            started = pending if "confirm" in body and pending else body if "harness" in body else None
            if started:
                name = started.get("name") or started["folder"].rsplit("/", 1)[-1]
                s.setdefault("starting", []).append({"id": f"st{len(self.posts)}", "name": name, "harness": started["harness"],
                                                     "label": started["harness"], "folder": started["folder"].rsplit("/", 1)[-1],
                                                     "state": "starting", "detail": "", "since": time.time()})
        elif path == "/voice/listen":
            s["monologue"] = {"since": time.time(), "said": ""} if body.get("on") else None
        elif path == "/voice/dump":  # as daemon.py's route would, with the model's part stubbed
            d, action = s.get("brain_dump"), body.get("action")
            if action == "start":
                pinned = s["active"] if s.get("mode") == "session" else None  # the routing now, as braindump.capture keeps it
                s["brain_dump"] = {"id": f"d{int(time.time() * 1000)}", "state": "dumping", "since": time.time(), "thoughts": [], "dropped": 0,
                                   "prompt": None, "target": None, "problem": None, "resumed": False, "fallback": False,
                                   "send_to": {"orchestrator": not pinned, "session": pinned, "gone": None}}
            elif action == "done" and d:
                thoughts = [t["text"] for t in d["thoughts"]]
                d["state"], d["prompt"] = "review", {"goal": thoughts[0] if thoughts else "", "context": thoughts[1:], "constraints": [],
                                                      "open_questions": [],
                                                      "text": "\n\n".join(([f"Goal\n{thoughts[0]}"] if thoughts else [])
                                                                          + (["Context\n" + "\n".join(f"- {t}" for t in thoughts[1:])] if thoughts[1:] else []))}
            elif action == "more" and d:
                d["state"] = "dumping"
            elif action == "edit" and d and d.get("prompt"):
                d["prompt"]["text"] = body.get("text", "")
            elif action in ("send", "discard"):
                s["brain_dump"] = None
        self.posts.append((path, body, time.time()))
        return web.json_response({"ok": True})


# ---------- the browser ----------

class Chrome:
    """Headless Chrome over the DevTools protocol: `cdp` for commands, `on` for events."""

    def __init__(self, ws):
        self.ws = ws
        self.n = 0
        self.waiting: dict[int, asyncio.Future] = {}
        self.listeners: list = []
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        async for raw in self.ws:
            msg = json.loads(raw)
            if "id" in msg:
                fut = self.waiting.pop(msg["id"], None)
                if fut and not fut.done():
                    fut.set_result(msg)
            else:
                for cb in list(self.listeners):
                    cb(msg)

    async def cdp(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        fut = asyncio.get_running_loop().create_future()
        self.waiting[self.n] = fut
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        reply = await fut
        if "error" in reply:
            raise RuntimeError(f"{method}: {reply['error']}")
        return reply.get("result", {})

    def on(self, cb) -> None:
        self.listeners.append(cb)

    async def eval(self, expression: str):
        r = await self.cdp("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True})
        if "exceptionDetails" in r:
            raise RuntimeError(json.dumps(r["exceptionDetails"])[:800])
        return r["result"].get("value")

    async def wait_for_page(self) -> None:
        # `status` is a `let` in the page: not window.status (the status-bar string). The list is drawn by the first poll.
        for _ in range(80):
            if await self.eval("typeof poll === 'function' && document.getElementById('list').children.length > 0"):
                return
            await asyncio.sleep(0.25)
        raise RuntimeError("the page did not get its first status")


class Browser:
    """Launches Chrome on about:blank; `open(url)` navigates and hands back the page's Chrome."""

    def __init__(self):
        self.port = free_port()
        self.profile = Path(tempfile.mkdtemp(prefix="pointe-page-perf-"))
        self.proc = None
        self.ws = None

    async def __aenter__(self) -> "Browser":
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", f"--remote-debugging-port={self.port}", f"--user-data-dir={self.profile / 'profile'}",
             "--no-first-run", "--window-size=1440,900", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
             "--autoplay-policy=no-user-gesture-required", "--disable-background-timer-throttling", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return self

    async def __aexit__(self, *exc):
        if self.ws:
            await self.ws.close()
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)

    async def open(self, url: str) -> Chrome:
        from websockets.asyncio.client import connect

        target = None
        for _ in range(80):
            try:
                tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json", timeout=1).read())
                target = next(t for t in tabs if t.get("type") == "page")
                break
            except Exception:
                await asyncio.sleep(0.25)
        assert target, "Chrome did not open a page"
        self.ws = await connect(target["webSocketDebuggerUrl"], max_size=None)
        chrome = Chrome(self.ws)
        await chrome.cdp("Page.enable")
        await chrome.cdp("Runtime.enable")
        await chrome.cdp("Page.navigate", {"url": url})
        await chrome.wait_for_page()
        return chrome


# ---------- probes the page is given ----------

# Counts what the page does on its own: long tasks, DOM mutations in the three lists, and the render time of each poll
# (from the status JSON being parsed to the end of poll()).
PROBES = """
(() => {
  window.__probe = {longtasks: [], muts: {list: 0, recent: 0, talk: 0}, ticks: [], jsonAt: null};
  const ob = new PerformanceObserver(l => { for (const e of l.getEntries()) __probe.longtasks.push({start: e.startTime, dur: e.duration}); });
  ob.observe({type: 'longtask'});
  for (const id of ['list', 'recent', 'talk'])
    new MutationObserver(ms => { __probe.muts[id] += ms.length; }).observe(document.getElementById(id),
      {childList: true, subtree: true, attributes: true, characterData: true});
  const realFetch = window.fetch;
  window.fetch = async (u, o) => {
    const r = await realFetch(u, o);
    if (String(u).startsWith('/voice/status') && !(o && o.method)) {
      const j = r.json.bind(r);
      r.json = async () => { const v = await j(); __probe.jsonAt = performance.now(); return v; };
    }
    return r;
  };
  const realPoll = window.poll;
  window.poll = async () => { __probe.jsonAt = null; await realPoll(); if (__probe.jsonAt != null) __probe.ticks.push(performance.now() - __probe.jsonAt); };
  window.__reset = () => { __probe.longtasks = []; __probe.muts = {list: 0, recent: 0, talk: 0}; __probe.ticks = []; };
  // Resolves when `cond` holds, with the time and the animation frames it took; null time when it never did.
  window.__until = (cond, timeout = 6000) => new Promise(res => {
    const t0 = performance.now(); let frames = 0;
    if (cond()) return res({ms: 0, frames: 0});
    const tick = () => { frames++; if (cond()) return res({ms: performance.now() - t0, frames});
                         if (performance.now() - t0 > timeout) return res({ms: null, frames}); requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  });
  return true;
})()
"""
