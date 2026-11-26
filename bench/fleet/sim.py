"""The fleet simulator: H machines with S scripted sessions each, on real links, on one host.

One voice daemon (the system under test: bench/fleet/voice.py, daemon.py as it runs), and every other machine a real
node process (pointe/node.py serve), paired with the voice by its own invite (`/voice/hub/invite`, then node_cli.py
join) and linked over the voice's TLS listener on 127.0.0.1. Every session is a stand-in (tests/fleet.py StandIn): an
inbox socket that keeps what the daemon or its node delivers, and a Claude Code-shaped record this process appends to.
The stand-ins are threads of the run's own process; they never answer a request.

A node, not a daemon, per machine: a node imports no model, no vendor SDK and no Pipecat (tests/test_node.py), and a
second daemon is another voice, which the system under test is not. What each costs is measured by `run.py up`.

Everything is under a throwaway folder in /tmp, on ports chosen free at run time, and every process is stopped by
its own handle. The live Pointe (7860, 7443, ~/.claude-voice) is never touched: tests/fleet.py refuses those ports.
"""

import asyncio
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[0:0] = [str(ROOT / "tests"), str(Path(__file__).resolve().parent)]
from fleet import LIVE_PORTS, Daemon, StandIn, free_port, socket_folder, until  # noqa: E402

VOICE_SCRIPT = Path(__file__).resolve().parent / "voice.py"
POLL_SECS = 0.02  # how often the inboxes are read while a turn is watched: a delivery's time is exact to this


class Voice(Daemon):
    """The voice daemon: tests/fleet.py's Daemon, started through bench/fleet/voice.py so its model calls are written
    down, with the stubbed models or the real ones."""

    def __init__(self, root: Path, name: str, owner: str, models: str, calls: Path, env: dict | None = None,
                 checkout: Path = ROOT):
        super().__init__(root, name, owner, env)
        self.models, self.calls, self.checkout = models, calls, checkout

    def listen(self) -> None:
        """Daemon.listen, with the checkout under test's own pair.py."""
        made = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import pair; "
                               "pair.setup('127.0.0.1', '127.0.0.1')", str(self.checkout / "pointe")],
                              env=self.env(), capture_output=True, text=True, timeout=60)
        assert made.returncode == 0, made.stderr[-2000:]

    def env(self) -> dict:
        env = super().env()
        # The daemon's own brain front. The call has no ears (voice.py) and its mouth is never reached: it is opened
        # in reading mode, where a reply is shown and not synthesised (daemon.MuteOut).
        env.update(CLAUDE_VOICE_FRONT="brain", POINTE_BENCH_MODELS=self.models,
                   POINTE_BENCH_CALLS=str(self.calls), CLAUDE_VOICE_NO_BROWSER="1",
                   POINTE_BENCH_CHECKOUT=str(self.checkout))
        if self.models == "real":
            env.pop("GOOGLE_API_KEY")  # the made-up key of an offline fleet: the real ones come from the Keychain
            env["POINTE_BENCH_KEY_HOME"] = str(Path.home())  # where the Keychain is; the daemon's own HOME is throwaway
        env.update(self.extra)
        return env

    def launch(self) -> None:
        assert self.proc is None or self.proc.poll() is not None, f"{self.name} is already running"
        assert not {self.port, self.tls_port} & LIVE_PORTS
        self.starts += 1
        log = (self.state.parent / f"{self.name}.log").open("a")
        self.proc = subprocess.Popen([sys.executable, "-I", str(VOICE_SCRIPT), str(self.port)], env=self.env(),
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)


class Node:
    """One other machine: pointe/node.py serve on its own state folder and port, paired with the voice."""

    def __init__(self, root: Path, name: str, voice: Voice):
        self.name, self.voice = name, voice
        self.state = root / name
        self.state.mkdir(mode=0o700, parents=True)
        self.port = free_port()
        self.token = secrets.token_hex(24)
        (self.state / "token").write_text(self.token)
        self.proc: subprocess.Popen | None = None
        self.log_path = root / f"{name}.log"

    def env(self) -> dict:
        env = {k: v for k, v in self.voice.env().items() if not k.startswith(("POINTE_BENCH_", "CLAUDE_VOICE_TLS"))
               and k not in ("GOOGLE_API_KEY", "CLAUDE_VOICE_FRONT")}
        env.update(CLAUDE_VOICE_STATE=str(self.state), CLAUDE_VOICE_DAEMON_PORT=str(self.port),
                   POINTE_LINK_DIR=str(self.state / "link"))
        return env

    def join(self) -> None:
        """The voice's invite, then `pointe node join` with it, as a person pairs a machine."""
        invite = self.voice.post("/voice/hub/invite", {"name": self.name})["link"]
        paired = subprocess.run([sys.executable, str(self.voice.checkout / "pointe" / "node_cli.py"), "join", invite, "--name", self.name,
                                 "--no-start"], env=self.env(), capture_output=True, text=True, timeout=60)
        assert paired.returncode == 0, paired.stdout + paired.stderr

    def launch(self) -> None:
        assert self.port not in LIVE_PORTS
        self.proc = subprocess.Popen([sys.executable, str(self.voice.checkout / "pointe" / "node.py"), "serve", "--port", str(self.port)],
                                     env=self.env(), stdin=subprocess.DEVNULL, stdout=self.log_path.open("a"),
                                     stderr=subprocess.STDOUT)
        (self.state / "daemon.pid").write_text(str(self.proc.pid))  # the hook answers only for the port's owner

    def call(self, path: str, body: dict | None = None, timeout: float = 30) -> tuple[int, dict | str]:
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method="POST" if body is not None else "GET",
                                         data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Authorization": f"Bearer {self.token}", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as reply:
                status, text = reply.status, reply.read().decode()
        except urllib.error.HTTPError as e:
            status, text = e.code, e.read().decode(errors="replace")
        try:
            return status, json.loads(text or "{}")
        except ValueError:
            return status, text

    def register(self, session: StandIn) -> str:
        status, body = self.call("/voice/register", session.body())
        assert status == 200, (self.name, status, body)
        return body["name"]

    def up(self, timeout: float = 60.0) -> None:
        until(f"node {self.name} answers", lambda: self.proc.poll() is None and self.call("/voice/health")[0] == 200, timeout)

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)

    def log(self, chars: int = 3000) -> str:
        return self.log_path.read_text(errors="replace")[-chars:] if self.log_path.exists() else ""


class Scripted(StandIn):
    """A stand-in with an identity from the fleet's description and a state script: what its record says when it
    joins, and the lines it writes after."""

    def __init__(self, folder: Path, sockets: Path, described: dict):
        super().__init__(folder, sockets, described["id"], described["name"])
        self.described = described
        self.seen = 0  # inbox lines already timed (FleetSim.watch)

    def _line(self, kind: str, content, stop: str | None = None) -> None:
        message = {"role": kind, "content": content}
        if kind == "assistant":
            message["stop_reason"] = stop
        with self.transcript.open("a") as f:
            f.write(json.dumps({"type": kind, "uuid": secrets.token_hex(8), "sessionId": self.id,
                                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()), "message": message}) + "\n")

    def tool(self, name: str, **tool_input) -> None:
        """The agent uses a tool: its turn goes on."""
        self._line("assistant", [{"type": "tool_use", "id": f"toolu_{secrets.token_hex(6)}", "name": name,
                                  "input": tool_input}], "tool_use")

    def final(self, text: str) -> None:
        """The agent ends its turn with this message."""
        self._line("assistant", [{"type": "text", "text": text}], "end_turn")

    def seed(self) -> None:
        """Its folder (a git index with its files, as the daemon and a node list them) and its record so far."""
        d = self.described
        for name in d["files"]:
            (self.cwd / name).write_text(f"# {d['topic']}\n")
        env = {"HOME": str(self.cwd), "PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1"}
        for cmd in (["git", "init", "-q"], ["git", "add", "-A"]):
            subprocess.run(cmd, cwd=self.cwd, env=env, check=True, capture_output=True, timeout=30)
        first = d["files"][0]
        self._line("user", f"{d['goal']} Start with {first}.")
        self.tool("Read", file_path=str(self.cwd / first))
        self._line("user", [{"type": "tool_result", "tool_use_id": "seed", "content": f"# {d['topic']}"}])
        if d["state"] == "idle":
            self.final(f"The work on the {d['topic']} is done: the change is in {first} and all 14 tests pass. "
                       "Nothing is waiting on you.")
        elif d["state"] == "asks":
            self.final(f"I read {first} for the {d['topic']}. {d['question']}")
        else:  # working, or about to stand at a permission prompt: in the middle of a turn
            self._line("assistant", [{"type": "text", "text": f"I read {first}. Next I change the {d['topic']} and run its tests."}])

    def finish(self) -> str:
        text = f"The {self.described['topic']} work is finished: {self.described['files'][0]} is changed and its tests pass."
        self.final(text)
        return text


class Call:
    """The page's side of a call (the socket rig.Browser opens), with no audio: it holds the line so the daemon
    follows the sessions and answers typed words. Opened in reading mode (?reading=1): replies are shown, not spoken,
    so no voice is synthesised."""

    def __init__(self, voice: Voice):
        self.voice = voice
        self.connected = threading.Event()
        self.failed: str | None = None
        self._stop: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = threading.Thread(target=lambda: asyncio.run(self._hold()), daemon=True)

    async def _hold(self) -> None:
        from websockets.asyncio.client import connect

        self._loop, self._stop = asyncio.get_running_loop(), asyncio.Event()
        try:
            async with connect(f"ws://127.0.0.1:{self.voice.port}/voice/call?reading=1", max_size=None,
                               additional_headers={"Authorization": f"Bearer {self.voice.token}"}) as ws:
                self.connected.set()
                reader = asyncio.ensure_future(self._drain(ws))
                await self._stop.wait()
                reader.cancel()
        except Exception as e:
            self.failed = f"{type(e).__name__}: {e}"
            self.connected.set()

    @staticmethod
    async def _drain(ws) -> None:
        async for _ in ws:
            pass

    def open(self) -> "Call":
        self._thread.start()
        assert self.connected.wait(30) and not self.failed, self.failed or "the call did not open"
        until("the voice has the call", lambda: self.voice.status().get("connected"), 30)
        return self

    def close(self) -> None:
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(10)


def usage_of(pid: int) -> dict:
    """A process's memory and the CPU time it has used so far (ps)."""
    out = subprocess.run(["ps", "-o", "rss=,time=", "-p", str(pid)], capture_output=True, text=True).stdout.split()
    if len(out) < 2:
        return {"rss_mb": None, "cpu_secs": None}
    parts = out[1].replace("-", ":").split(":")
    secs = sum(float(p) * m for p, m in zip(reversed(parts), (1, 60, 3600, 86400)))
    return {"rss_mb": round(int(out[0]) / 1024, 1), "cpu_secs": round(secs, 2)}


class FleetSim:
    """A fleet from its description (gen.fleet): up(), then the stand-ins by id, the call, typed words, and what
    landed where."""

    def __init__(self, described: dict, root: Path, models: str = "stub", env: dict | None = None,
                 notes: Path | None = None, checkout: Path = ROOT):
        assert str(root).startswith(("/tmp/", "/private/tmp/")), "a fleet's folder is under /tmp"
        self.described, self.root, self.models, self.notes = described, root, models, notes
        root.mkdir(parents=True, exist_ok=True)
        self.sockets = socket_folder()
        self.calls = root / "calls.jsonl"
        self.voice = Voice(root, described["voice_machine"], "Sam", models, self.calls, env, checkout)
        self.nodes: dict[str, Node] = {}
        self.sessions: dict[str, Scripted] = {}
        self.call: Call | None = None
        self.timing: dict[str, float] = {}
        self._hooks: list[threading.Thread] = []
        self.closing = threading.Event()

    # ---- up ----

    def up(self) -> "FleetSim":
        d, at = self.described, time.monotonic()
        self.voice.listen()
        self.voice.start()
        self.timing["voice_up_secs"] = round(time.monotonic() - at, 1)
        at = time.monotonic()
        for name in d["machines"][1:]:
            node = self.nodes[name] = Node(self.root, name, self.voice)
            node.join()  # one invite at a time: a new one replaces the last
            node.launch()
        for node in self.nodes.values():
            node.up()
        if self.nodes:
            until("every node is linked", lambda: sum(bool(n.get("online")) for n in self.voice.get("/voice/hub/nodes")["nodes"])
                  == len(self.nodes), 90, every=0.25)
        self.timing["nodes_up_secs"] = round(time.monotonic() - at, 1)
        at = time.monotonic()
        short = {s["id"][:8] for s in d["sessions"]}
        assert len(short) == len(d["sessions"]), "two session ids share a socket name"
        for s in d["sessions"]:
            session = self.sessions[s["id"]] = Scripted(self.root / "work" / s["machine"], self.sockets, s)
            session.seed()
        self.timing["seed_secs"] = round(time.monotonic() - at, 1)
        self._restore_notes()
        at = time.monotonic()
        for s in d["sessions"]:  # machine by machine, the voice's own first
            where = self.nodes.get(s["machine"]) or self.voice
            where.register(self.sessions[s["id"]])
        until("every session is on the voice", lambda: len(self.registry()) == len(d["sessions"]), 180, every=0.5)
        self.timing["sessions_joined_secs"] = round(time.monotonic() - at, 1)
        return self

    # ---- the voice's view ----

    def registry(self) -> dict[str, dict]:
        """The voice's own record of each session (its sessions.json), by the id the fleet's description gives it: a
        session on another machine is `<node>-<id>` there. /voice/status lists the same sessions without their ids."""
        saved = json.loads((self.voice.state / "sessions.json").read_text())["sessions"]
        return {s["id"][-36:]: s for s in saved}

    def names(self) -> dict[str, str]:
        """session id -> the name the voice knows it by."""
        return {sid: s["name"] for sid, s in self.registry().items()}

    def machines_seen(self) -> dict[str, str]:
        """session id -> its machine as the voice records it; the voice's own machine for its own sessions."""
        return {sid: s.get("machine") or self.described["voice_machine"] for sid, s in self.registry().items()}

    # ---- notes: what the reader wrote about each session, kept between runs of one fleet ----

    def _restore_notes(self) -> None:
        """The reader's notes from an earlier run of this same fleet, put where the daemon keeps them before the
        sessions join, so a paid run does not pay for every session to be read again. A session on another machine is
        read from its mirror on the voice's machine: its notes go in once the mirror is whole (settle_notes)."""
        if self.notes is None or not self.notes.exists():
            return
        for s in self.described["sessions"]:
            if s["machine"] == self.described["voice_machine"]:
                self._put_notes(s["id"], s["id"], self.sessions[s["id"]].transcript)

    def _put_notes(self, described_id: str, voice_id: str, record: Path) -> bool:
        kept = self.notes / f"{described_id}.json"
        if not kept.exists():
            return False
        briefs = self.voice.state / "briefs"
        briefs.mkdir(mode=0o700, exist_ok=True)
        (briefs / f"{voice_id}.json").write_text(json.dumps({"brief": json.loads(kept.read_text()), "size": record.stat().st_size}))
        return True

    def settle_notes(self, timeout: float = 120.0) -> dict:
        """Before the call: every mirror whole (as long as the session's own record), then the kept notes of the
        sessions on other machines. How many sessions have notes on disk, of how many."""
        remote = {sid: s for sid, s in self.registry().items() if s.get("machine")}

        def whole() -> bool:
            return all(Path(s["transcript"]).exists()
                       and Path(s["transcript"]).stat().st_size >= self.sessions[sid].transcript.stat().st_size
                       for sid, s in remote.items())

        until("every mirror is whole", whole, timeout, every=0.25)
        if self.notes is not None and self.notes.exists():
            for sid, s in remote.items():
                self._put_notes(sid, s["id"], Path(s["transcript"]))
        return {"with_notes": len(self.noted()), "sessions": len(self.sessions)}

    def noted(self) -> dict[str, dict]:
        """The notes the voice holds on disk now, by the description's session id."""
        out = {}
        for path in (self.voice.state / "briefs").glob("*.json"):
            try:
                out[path.stem[-36:]] = json.loads(path.read_text())["brief"]
            except (OSError, ValueError, KeyError):
                pass
        return out

    def save_notes(self) -> int:
        assert self.notes is not None
        self.notes.mkdir(parents=True, exist_ok=True)
        notes = self.noted()
        for sid, brief in notes.items():
            (self.notes / f"{sid}.json").write_text(json.dumps(brief, ensure_ascii=False, indent=1) + "\n")
        return len(notes)

    # ---- the call and the scripts ----

    def open_call(self) -> Call:
        self.call = Call(self.voice).open()
        return self.call

    def start_states(self) -> None:
        """What each session does once the call is up: a working one uses a tool (the daemon then knows it works), one
        at a permission prompt asks its machine's hook and waits there until the fleet closes."""
        for s in self.described["sessions"]:
            session = self.sessions[s["id"]]
            if s["state"] == "working":
                session.tool("Edit", file_path=str(session.cwd / s["files"][0]), old_string="#", new_string="##")
            elif s["state"] == "permission":
                thread = threading.Thread(target=self._prompt, args=(s,), daemon=True)
                thread.start()
                self._hooks.append(thread)

    def _prompt(self, s: dict) -> None:
        """Claude Code's PermissionRequest hook, as bin/voice-permission-hook posts it: held until answered."""
        where = self.nodes.get(s["machine"]) or self.voice
        body = {"session_id": s["id"], "hook_event_name": "PermissionRequest", "tool_name": "Bash",
                "tool_input": {"command": "git status --short", "description": "List changed files"}}
        while not self.closing.is_set():
            try:
                status, answer = where.call("/voice/permission-hook", body, timeout=3600)
            except OSError:
                return
            if status != 200 or answer:  # answered (or refused): the prompt is over
                return
            time.sleep(2)  # {}: nobody held it (no call up yet); the prompt stays in its terminal, ask again

    def type(self, text: str) -> float:
        """The user types a line into the call (/voice/say). When it was sent."""
        at = time.time()
        self.voice.post("/voice/say", {"text": text})
        return at

    def deliveries(self) -> list[dict]:
        """Every request that reached a stand-in since the last look: where it landed is the inbox it is in."""
        now, out = time.time(), []
        for sid, session in self.sessions.items():
            got = session.received
            while session.seen < len(got):
                line = got[session.seen]
                session.seen += 1
                if line.get("type") == "user":
                    out.append({"session": sid, "at": now, "text": str(line["message"]["content"])[:2000]})
        return out

    # ---- what it costs ----

    def footprint(self) -> dict:
        nodes = [usage_of(n.proc.pid) for n in self.nodes.values() if n.proc and n.proc.poll() is None]
        return {"voice": usage_of(self.voice.proc.pid), "nodes": len(nodes),
                "nodes_rss_mb": round(sum(n["rss_mb"] or 0 for n in nodes), 1),
                "nodes_cpu_secs": round(sum(n["cpu_secs"] or 0 for n in nodes), 2),
                "runner": usage_of(os.getpid()), "threads": threading.active_count()}

    def close(self) -> None:
        self.closing.set()
        if self.call is not None:
            self.call.close()
        self.voice.stop()
        for node in self.nodes.values():
            node.stop()
        for session in self.sessions.values():
            session.close()
        shutil.rmtree(self.sockets, ignore_errors=True)

    def logs(self) -> str:
        return f"---- voice\n{self.voice.log()}\n" + "\n".join(f"---- {n.name}\n{n.log(1500)}" for n in self.nodes.values())
