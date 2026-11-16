"""Two machines on one Mac: a hub daemon and a node, each with its own state dir and port, paired for real with
`pointe hub invite` and `pointe node join`, through a TCP proxy the test can cut (a VPN going down). Real Claude Code
sessions on both, OpenCode and Codex on the node, and a real voice call (synthetic speech, as scenarios.py).

Run (the transcriber's key per process; nothing is printed):
  GOOGLE_API_KEY="$(security find-generic-password -s gemini-api-key-paid -w)" \
  CLAUDE_VOICE_STATE=/tmp/cv-state-mmw-hub CLAUDE_VOICE_DAEMON_PORT=7981 CLAUDE_VOICE_TLS_PORT=7581 \
    uv run python -u -I tests/e2e/two_machines.py [phase,...]
Phases: pair, brain, approve, offline, restart, link, pairing, skew, rotate (default: all, in that order).
"""

import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import rig  # noqa: E402
from rig import ROOT, STATE, Browser, fresh_state, log_lines, stop_daemon, transcribe  # noqa: E402
from hook_session import JoinedSession  # noqa: E402
from scenarios import TEST_MODEL, _daemon, check, log_time, results  # noqa: E402
from harness_matrix import CodexTui, codex_ready, opencode_delete  # noqa: E402

import nodelink  # noqa: E402

assert str(STATE).startswith("/tmp/cv-state-mmw"), "use CLAUDE_VOICE_STATE=/tmp/cv-state-mmw-hub"
HUB_PORT, TLS_PORT = int(os.environ["CLAUDE_VOICE_DAEMON_PORT"]), int(os.environ["CLAUDE_VOICE_TLS_PORT"])
PROXY_PORT = TLS_PORT + 2  # what the node dials: the test can cut it
NODE_STATE, NODE_PORT = Path("/tmp/cv-state-mmw-node"), HUB_PORT + 1
SPARE_STATE, SPARE_PORT = Path("/tmp/cv-state-mmw-spare"), HUB_PORT + 3
WORK = Path("/tmp/mmw")
NODE = "devbox"
HUB_ENV = {**os.environ, "CLAUDE_VOICE_FRONT": "brain"}
NODE_ENV = {k: v for k, v in HUB_ENV.items() if k not in ("CLAUDE_VOICE_TLS_PORT",)}
NODE_ENV.update(CLAUDE_VOICE_STATE=str(NODE_STATE), CLAUDE_VOICE_DAEMON_PORT=str(NODE_PORT))
REPOS = {"hub-shop": (WORK / "hub" / "shop", "The release codename is Juniper."),
         "node-shop": (WORK / "node" / "shop", "The deploy region is Frankfurt."),
         "lighthouse": (WORK / "node" / "lighthouse", "The on-call engineer is Marisol."),
         "orchard": (WORK / "node" / "orchard", "The database port is 6543."),
         "harbor": (WORK / "node" / "harbor", "The cache size is 512 megabytes.")}
PHASES = (sys.argv[1] if len(sys.argv) > 1 else "pair,brain,approve,offline,restart,link,pairing,skew,rotate").split(",")
made: dict = {"oc": None, "cx": [], "procs": []}
verdicts: dict[str, str] = {}


def scenario(name: str, ok: bool, why: str = "") -> None:
    verdicts[name] = ("PASS" if ok else "FAIL") + (f": {why[:160]}" if why else "")
    check(name, ok, evidence=why[:400])


# ---------- the link the test can cut ----------

class Proxy:
    """127.0.0.1:PROXY_PORT -> the hub's TLS listener. `blackhole` stops every byte both ways but keeps the sockets, as
    a VPN that went down does: only the heartbeats notice."""

    def __init__(self):
        self.blackhole = False
        self.conns: list[asyncio.StreamWriter] = []

    async def start(self):
        """On its own thread and loop: the test's loop blocks while a Claude Code session starts, and a starved proxy
        would look like a dead link."""
        import threading

        self.loop = asyncio.new_event_loop()
        ready = threading.Event()

        def serve():
            asyncio.set_event_loop(self.loop)
            self.server = self.loop.run_until_complete(asyncio.start_server(self._serve, "127.0.0.1", PROXY_PORT))
            ready.set()
            self.loop.run_forever()

        threading.Thread(target=serve, daemon=True).start()
        ready.wait(10)

    async def _serve(self, reader, writer):
        try:
            up_r, up_w = await asyncio.open_connection("127.0.0.1", TLS_PORT)
        except OSError:
            writer.close()
            return
        self.conns += [writer, up_w]

        async def pipe(src, dst):
            try:
                while data := await src.read(65536):
                    while self.blackhole:
                        await asyncio.sleep(0.2)
                    dst.write(data)
                    await dst.drain()
            except (OSError, ConnectionError):
                pass
            finally:
                dst.close()

        await asyncio.gather(pipe(reader, up_w), pipe(up_r, writer))

    def cut(self):
        def close():
            for w in self.conns:
                w.close()
            self.conns = []
        self.loop.call_soon_threadsafe(close)


# ---------- helpers ----------

def run(cmd: list[str], env: dict, timeout: float = 180, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout, cwd=cwd)


def status() -> dict:
    return _daemon("/voice/status") or {"sessions": []}


def node_status() -> dict:
    import urllib.request
    try:
        token = (NODE_STATE / "token").read_text().strip()
        req = urllib.request.Request(f"http://127.0.0.1:{NODE_PORT}/voice/status", headers={"Authorization": f"Bearer {token}"})
        return json.loads(urllib.request.urlopen(req, timeout=5).read())
    except Exception:
        return {}


def session(prefix: str, machine: str | None = None) -> dict | None:
    for s in status().get("sessions", []):
        if s["name"].lower().startswith(prefix) and (machine is None or s.get("machine") == machine):
            return s
    return None


def said_since(t: float) -> list[str]:
    return [line.split("speak: ", 1)[1] for line in log_lines(r"speak: ") if log_time(line) >= t]


def node_log() -> str:
    path = NODE_STATE / "daemon.log"
    return path.read_text(errors="ignore") if path.exists() else ""


async def until(test, timeout: float, step: float = 1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        got = test()
        if got:
            return got
        await asyncio.sleep(step)
    return test()


async def spoken_with(t: float, needle: str, timeout: float = 120) -> str:
    pattern = re.compile(needle, re.I)
    return await until(lambda: next((s for s in said_since(t) if pattern.search(s)), ""), timeout, 2) or ""


async def quiet(b: Browser, settle: float = 2.0, timeout: float = 40) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        spans = b.speaker.speech_spans(since=time.time() - 30)
        if not spans or time.time() - spans[-1][1] > settle:
            return
        await asyncio.sleep(0.5)


async def say(b: Browser, text: str) -> float:
    await quiet(b)
    _, end = await b.say(text)
    await asyncio.sleep(max(0, end - time.time()))
    return end


async def heard(b: Browser, t: float, timeout: float = 40) -> str:
    """What the bot audibly said after t, transcribed (the call's audio, not the daemon's log)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        spans = b.speaker.speech_spans(since=t)
        if spans and time.time() - spans[-1][1] > 2.5:
            return await transcribe(b.speaker.audio(spans[0][0], spans[-1][1]))
        await asyncio.sleep(0.5)
    spans = b.speaker.speech_spans(since=t)
    return await transcribe(b.speaker.audio(spans[0][0], spans[-1][1])) if spans else ""


TAPPER = {"on": True}  # off while a phase tests approvals itself


async def tapper() -> None:
    """A person tapping Approve on prompts no check is about (a model may read a file with a shell command)."""
    while True:
        await asyncio.sleep(2)
        if TAPPER["on"]:
            for s in status().get("sessions", []):
                if s.get("request_id"):
                    tap(s, "allow")


def point_at(s: dict) -> None:
    """Make it the active session, so its prompts are read out, as a click does; then back to orchestrator mode, which a
    click leaves (it pins session mode), so the next phase's sends to other sessions are not refused."""
    _daemon("/voice/switch", {"name": s["name"]})
    _daemon("/voice/mode", {"mode": "orchestrator"})


def tap(s: dict, decision: str) -> dict:
    return _daemon("/voice/approve", {"session": s["name"], "request_id": s["request_id"], "decision": decision})


async def pending(prefix: str, machine: str | None = None, timeout: float = 150, other_than: str | None = None):
    return await until(lambda: (lambda s: s if s and s.get("request_id") and s["request_id"] != other_than else None)(
        session(prefix, machine)), timeout, 1)


async def clear(prefix: str, machine: str | None = None, timeout: float = 120) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = session(prefix, machine)
        if not s:
            return
        if s.get("request_id"):
            tap(s, "allow")  # not deny: Claude Code then refuses the same command again, even when asked anew
        elif not s.get("working"):
            await asyncio.sleep(3)
            if not (session(prefix, machine) or {}).get("working"):
                return
        await asyncio.sleep(2)


def mirror_dupes() -> dict[str, int]:
    """Entries the hub wrote twice into any node mirror (by uuid): a resume that re-sent what was already there."""
    out = {}
    for path in (STATE / "harness" / "remote").rglob("*.jsonl"):
        seen, dupes = set(), 0
        for line in path.read_text(errors="ignore").splitlines():
            try:
                uid = json.loads(line).get("uuid")
            except ValueError:
                continue
            if uid:
                dupes += uid in seen
                seen.add(uid)
        out[path.name] = dupes
    return out


def has_file(repo: Path, stem: str) -> bool:
    """A file whose name holds stem, any case: speech-to-text turns "touch oc.txt" into "TouchOC.txt"."""
    return any(stem in p.name.lower() for p in repo.iterdir())


def make_repo(path: Path, fact: str) -> None:
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    (path / "FACT.md").write_text(f"# Facts\n{fact}\n")
    (path / "README.md").write_text(f"# {path.name}\nA scratch project for a two-machine voice test.\n")
    subprocess.run("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm init",
                   shell=True, cwd=path, check=True)


class NodeSession(JoinedSession):
    """A Claude Code session on the node: the plugin's hooks and /pointe:voice see the node's state and port."""

    def start(self, timeout: float = 90) -> None:
        saved = dict(os.environ)
        os.environ.clear()
        os.environ.update(NODE_ENV)
        try:
            super().start(timeout)
        finally:
            os.environ.clear()
            os.environ.update(saved)


class NodeCodex(CodexTui):
    def start(self) -> None:
        saved = dict(os.environ)
        os.environ.clear()
        os.environ.update(NODE_ENV)
        try:
            super().start()
        finally:
            os.environ.clear()
            os.environ.update(saved)


def hub_ensure() -> bool:
    return run([str(ROOT / "bin" / "voice-daemon"), "ensure"], HUB_ENV, 120).returncode == 0


def hub_stop() -> None:
    log = STATE / "daemon.log"
    if log.exists():  # voice-daemon ensure starts a new log: keep what came before, for the report
        with open(STATE / "daemon.before-restarts.log", "a") as kept:
            kept.write(log.read_text(errors="ignore"))
    run([str(ROOT / "bin" / "voice-daemon"), "stop"], HUB_ENV, 60)


def node_cmd(*args: str, env: dict | None = None, timeout: float = 180) -> subprocess.CompletedProcess:
    return run([str(ROOT / "bin" / "pointe"), "node", *args], env or NODE_ENV, timeout)


def invite(name: str) -> tuple[subprocess.Popen, str]:
    """`pointe hub invite --name`: the line it prints, pointed at the proxy (the pin is the certificate's, so the
    address does not matter)."""
    p = subprocess.Popen([str(ROOT / "bin" / "pointe"), "hub", "invite", "--name", name], env=HUB_ENV,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    made["procs"].append(p)
    line = p.stdout.readline().strip()
    assert line.startswith("pointe://hub?"), line
    return p, line.replace(f"port={TLS_PORT}", f"port={PROXY_PORT}")


async def join_node(name: str = NODE) -> tuple[bool, str]:
    p, line = invite(name)
    joined = await asyncio.to_thread(node_cmd, "join", line)
    printed = ""
    for _ in range(3):  # "Valid once...", then "<name> paired from <address> (...), key <fp>"
        printed = await asyncio.to_thread(p.stdout.readline)
        if "paired from" in printed or not printed:
            break
    return joined.returncode == 0, (joined.stdout + joined.stderr).strip() + " || hub: " + printed.strip()


async def connect_call() -> Browser:
    b = Browser()
    await b.connect()
    return b


# ---------- phases ----------

async def phase_pair() -> None:
    ok, out = await join_node()
    shown = re.search(r"devbox paired from 127\.0\.0\.1 \(a connector on this Mac\), key ([0-9a-f]{16})", out)
    fp_match = bool(shown) and shown.group(1) in out.split("||")[0]
    scenario("pair: invite + node join, owner sees address and key fingerprint", ok and fp_match, out)
    up = await until(lambda: node_status().get("link") == "up", 30)
    st = node_status()
    scenario("pair: node links up, knows its name and the hub's vendors by company name",
             bool(up) and st.get("hub") == "studio" and "Gemini" in (st.get("vendors") or [])
             and not any(":" in v for v in st.get("vendors") or []), json.dumps(st)[:300])
    again = node_cmd("join", "pointe://hub?v=1&host=127.0.0.1&port=1&fp=" + "a" * 64 + "&code=AAAA-AAAA")
    scenario("pair: a second join while paired is refused", again.returncode != 0 and "leave" in again.stderr,
             again.stderr.strip()[-160:])


async def start_sessions() -> dict:
    """Claude Code on the hub (shop) and on the node (shop: the collision, and lighthouse); OpenCode (orchard) and Codex
    (harbor) on the node. Each blocking start runs in a thread: a loop blocked for half a minute stops answering the
    call's WebSocket pings, and the hub drops the call."""
    out: dict = {}
    cc_hub = JoinedSession(REPOS["hub-shop"][0], "--model", TEST_MODEL, "--permission-mode", "default", front="brain")
    await asyncio.to_thread(cc_hub.start)
    out["cc_hub"] = cc_hub
    await asyncio.sleep(4)
    for key in ("node-shop", "lighthouse"):
        s = NodeSession(REPOS[key][0], "--model", TEST_MODEL, "--permission-mode", "default", front="brain")
        await asyncio.to_thread(s.start)
        out[key] = s
        await asyncio.sleep(4)
    from harnesses.opencode import Service
    service = Service()
    try:
        made_oc = await service.call("POST", "/api/session", {
            "title": "pointe two machines", "location": {"directory": str(REPOS["orchard"][0])},
            "permissions": [{"action": a, "resource": "*", "effect": "ask"} for a in ("shell", "bash", "edit")]})
        made["oc"] = (made_oc.get("data") or made_oc)["id"]
    finally:
        await service.close()
    oc = await asyncio.to_thread(run, [str(ROOT / "bin" / "pointe"), "join", "opencode", "--name", "orchard", "--session",
                                       made["oc"]], NODE_ENV, 60, cwd=REPOS["orchard"][0])
    print("opencode join", oc.returncode, (oc.stdout + oc.stderr)[-200:], flush=True)
    await asyncio.to_thread(run, ["codex", "app-server", "daemon", "start"], NODE_ENV, 60)
    tui = NodeCodex(REPOS["harbor"][0])
    tui.start()
    out["codex"] = tui
    await codex_ready(tui)
    tui.type("Reply with the single word ok.")
    await until(lambda: "ok" in tui.screen.split("Reply with the single word ok.")[-1].lower(), 90, 2)
    await asyncio.sleep(5)
    cx = await asyncio.to_thread(run, [str(ROOT / "bin" / "pointe"), "join", "codex", "--name", "harbor"], NODE_ENV, 60,
                                 cwd=REPOS["harbor"][0])
    print("codex join", cx.returncode, (cx.stdout + cx.stderr)[-200:], flush=True)
    for s in node_status().get("sessions", []):
        if s["harness"] == "codex":
            made["cx"].append(s["id"])
    await until(lambda: len([s for s in status()["sessions"] if s.get("machine") == NODE]) >= 4, 60)
    return out


async def phase_brain(b: Browser) -> None:
    st = status()
    names = {s["name"]: s.get("machine") for s in st["sessions"]}
    print("sessions:", names, flush=True)
    remote = [n for n, m in names.items() if m == NODE]
    scenario("sessions: hub CC, node CC x2, OpenCode, Codex all on the voice with their machine",
             len(remote) >= 4 and any(m == "studio" for m in names.values())
             and {"claude-code", "opencode", "codex"} <= {s["harness"] for s in st["sessions"] if s.get("machine") == NODE},
             json.dumps(names))
    twin = next((n for n, m in names.items() if m == NODE and n.startswith("shop")), "")
    scenario("name collision across machines: the later one is suffixed with its machine",
             any(n.startswith("shop") and m == "studio" and NODE not in n for n, m in names.items()) and NODE in twin, twin)

    t = await say(b, "What's going on everywhere?")
    answer = await heard(b, t, 60)
    scenario("'what's going on everywhere' names both machines", "devbox" in answer.lower().replace(" ", "") and
             ("studio" in answer.lower() or "this mac" in answer.lower() or "here" in answer.lower()), answer)

    _daemon("/voice/mode", {"mode": "orchestrator"})
    t = await say(b, "Go to devbox.")
    answer = await heard(b, t, 30)
    active = status().get("active") or ""
    on_node = (session(active.split("/")[0].lower()) or {}).get("machine") == NODE if active else False
    scenario("'go to devbox' switches to a session there or asks which one", on_node or
             sum(w in answer.lower() for w in ("lighthouse", "orchard", "harbor", "shop")) >= 2, f"active={active}; {answer}")
    await say(b, "Go back to shop on studio.")
    await asyncio.sleep(6)

    for key, needle, ask in (("orchard", "6543", "Ask orchard what the database port is in its FACT file."),
                             ("harbor", "512", "Ask harbor what the cache size is in its FACT file."),
                             ("lighthouse", "marisol", "Ask lighthouse who the on-call engineer is, from its FACT file.")):
        t = await say(b, ask)
        got = await spoken_with(t, needle, 180)
        sent = [line for line in log_lines(rf" - -> {key}") if log_time(line) >= t - 2]
        scenario(f"send to a remote session by name ({key}) and hear its report", bool(got) and bool(sent),
                 (sent or ["no send"])[-1][-100:] + " | " + got[:120])

    t = await say(b, f"Ask shop {NODE} what the deploy region is in its FACT file.")
    got = await spoken_with(t, "frankfurt", 180)
    sent = [line for line in log_lines(r" - -> shop") if log_time(line) >= t - 2]
    scenario("the colliding remote session is reached by its suffixed name", bool(got) and any(NODE in s for s in sent),
             (sent or ["no send"])[-1][-100:] + " | " + got[:120])
    t = await say(b, "Ask shop on studio what the release codename is in its FACT file.")
    got = await spoken_with(t, "juniper", 180)
    scenario("the hub's own shop is still reached as itself", bool(got), got[:120])


async def phase_approve(b: Browser) -> None:
    repo = REPOS["lighthouse"][0]
    await clear("lighthouse")
    point_at(session("lighthouse"))
    await asyncio.sleep(3)
    t = await say(b, "Ask lighthouse to run exactly one command, touch created.txt, with nothing chained to it.")
    first = await pending("lighthouse")
    read = await spoken_with(t, r"should it\?", 60) if first else ""
    if first and first.get("voice_can_approve"):
        for _ in range(3):
            await say(b, "Yes.")
            if await until(lambda: has_file(repo, "created"), 25):
                break
    scenario("voice yes approves a remote readable prompt (node re-checked the spoken line)",
             has_file(repo, "created"), f"read-out {read[:80]!r}; pending={bool(first)}")
    await asyncio.sleep(10)
    await say(b, "Ask lighthouse to run exactly one command: uname dash a, redirected into where.txt.")
    second = await pending("lighthouse", other_than=(first or {}).get("request_id"), timeout=90)
    unreadable = bool(second) and not second.get("voice_can_approve")
    if second:
        await say(b, "Yes.")
        await asyncio.sleep(8)
    still = session("lighthouse") or {}
    waited = unreadable and still.get("request_id") == second["request_id"] and not has_file(repo, "where")
    scenario("a prompt that cannot be read out waits for a tap: a spoken yes does nothing", waited,
             (second or {}).get("request", "")[:100])
    if second:
        tap(second, "allow")
    ok = await until(lambda: has_file(repo, "where"), 60)
    scenario("a tap through /voice/approve approves it on the node", bool(ok), str(ok))
    twin = session("shop", NODE)  # a session that has never been told no: Claude Code avoids a command once denied
    await clear("shop", NODE)
    point_at(twin)
    await asyncio.sleep(3)
    t = await say(b, f"Ask shop {NODE} to run exactly one command, touch cherry.txt, with nothing chained to it.")
    asked = await pending("shop", NODE)
    if asked:  # the read-out itself: "On it, I asked shop to run touch cherry.txt" is no question, and a no before it counts not
        await spoken_with(t, r"should it\?", 60)
        await say(b, "No.")
    gone = await until(lambda: not (session("shop", NODE) or {}).get("request_id"), 60)
    await asyncio.sleep(8)
    scenario("voice no denies a remote prompt", bool(asked) and bool(gone) and not has_file(REPOS["node-shop"][0], "cherry"),
             f"asked={bool(asked)}")

    # OpenCode and Codex on the node: one prompt each, tapped
    for key, harness_file in (("orchard", "apple"), ("harbor", "banana")):
        await clear(key)
        t = await say(b, f"Ask {key} to create a file called {harness_file}.txt with the touch command.")
        p = await pending(key, timeout=150)
        if p:
            tap(p, "allow")
        done = await until(lambda: has_file(REPOS[key][0], harness_file), 90)
        scenario(f"a remote {key} ({'OpenCode' if key == 'orchard' else 'Codex'}) prompt reaches the hub and a tap answers it",
                 bool(p) and bool(done), f"pending={bool(p)}")


async def phase_offline(b: Browser, proxy: Proxy, sessions: dict) -> None:
    await clear("lighthouse")
    point_at(session("lighthouse"))
    await asyncio.sleep(3)
    await say(b, "Ask lighthouse to create a file called offline.txt with the touch command.")
    p = await pending("lighthouse")
    if not p:
        return scenario("offline mid-approval", False, "no prompt came")
    await asyncio.sleep(4)
    t0 = time.time()
    proxy.blackhole = True
    off = await until(lambda: (session("lighthouse") or {}).get("online") is False, 30, 0.5)
    t_off = time.time() - t0
    line = await spoken_with(t0, r"dropped|offline|terminal", 30)
    scenario("offline mid-approval: hub marks the session offline within 15 s and says the approval went back",
             bool(off) and t_off < 15 and bool(line), f"{t_off:.1f} s; {line[:120]}")
    refused = tap(p, "allow")
    scenario("offline: a tap is refused, nothing approves", not has_file(REPOS["lighthouse"][0], "offline"),
             json.dumps(refused)[:160])
    back = await until(lambda: "handed back to the terminal (dropped)" in node_log(), 45)
    screen = sessions["lighthouse"].flat()[-3000:]
    scenario("offline: the node hands the prompt to its terminal after its 20 s grace", bool(back) and
             ("doyouwant" in screen or "proceed" in screen), f"node log={bool(back)}; screen ...{screen[-160:]}")
    proxy.blackhole = False
    proxy.cut()
    up = await until(lambda: (session("lighthouse") or {}).get("online") is True, 60)
    scenario("offline: the link comes back by itself", bool(up), "")
    os.write(sessions["lighthouse"].fd, b"\r")  # answer the terminal's own prompt: yes (a no makes it stop asking)
    await asyncio.sleep(5)


async def hub_restart_with_prompt(b: Browser) -> Browser:
    TAPPER["on"] = False
    await clear("lighthouse")
    point_at(session("lighthouse"))
    await asyncio.sleep(3)
    finished_before = len(log_lines(r"lighthouse[^\]]*finished its turn"))
    await say(b, "Ask lighthouse to create a file called restart.txt with the touch command.")
    p = await pending("lighthouse")
    if not p:
        scenario("hub restart: re-asked prompt", False, "no prompt came")
        return b
    await asyncio.sleep(3)
    t0 = time.time()
    hub_stop()  # the call drops with the daemon, as in a crash or an upgrade: not hung up first
    await b.close()
    started = await asyncio.to_thread(hub_ensure)
    b = await connect_call()  # the page reconnects as soon as the daemon is back
    t_call = time.time() - t0
    again = await until(lambda: (lambda s: s if s and s.get("request_id") == p["request_id"] else None)(session("lighthouse")),
                        30, 0.5)
    t_again = time.time() - t0
    read = await spoken_with(t0, r"should it\?", 30)
    scenario("hub restart: the held remote prompt is put again within 20 s", started and bool(again) and t_again < 20,
             f"call back at {t_call:.1f} s, prompt back at {t_again:.1f} s; read {read[:80]!r}")
    if again and again.get("voice_can_approve"):
        await say(b, "Yes.")
    else:
        if again:
            tap(again, "allow")
    ok = await until(lambda: has_file(REPOS["lighthouse"][0], "restart"), 45)
    scenario("hub restart: the re-asked prompt is approved", bool(ok), "")
    await asyncio.sleep(20)
    dupes = mirror_dupes()
    scenario("hub restart: mirrors resumed from the stored offsets, nothing appended twice", not any(dupes.values()),
             json.dumps(dupes))
    finished_after = log_lines(r"lighthouse[^\]]*finished its turn")
    scenario("hub restart: no duplicate 'finished' lines (only the new turn's)", len(finished_after) <= 1,
             f"before restart {finished_before}, since restart {len(finished_after)}")
    return b


async def phase_restart(b: Browser) -> Browser:
    # node restart
    before = {s["name"] for s in status()["sessions"] if s.get("machine") == NODE}
    t0 = time.time()
    await asyncio.to_thread(run, [str(ROOT / "bin" / "voice-node"), "stop"], NODE_ENV)
    ensured = await asyncio.to_thread(run, [str(ROOT / "bin" / "voice-node"), "ensure"], NODE_ENV)
    up = await until(lambda: node_status().get("link") == "up", 40)
    await asyncio.sleep(6)
    after = {s["name"] for s in status()["sessions"] if s.get("machine") == NODE and s.get("online")}
    scenario("node restart: it reconnects and every session is still on the voice", ensured.returncode == 0 and bool(up)
             and before <= after, f"{time.time() - t0:.1f} s; before={sorted(before)} after={sorted(after)}")
    t = await say(b, "Ask orchard to read its README and say its first line.")
    got = await spoken_with(t, r"first line (is|reads)|heading", 150)  # its first line is "# orchard"; not the "on it"
    scenario("node restart: a send and its report still work", bool(got), got[:120])
    dupes = mirror_dupes()
    scenario("node restart: nothing appended twice to any mirror", not any(dupes.values()), json.dumps(dupes))
    return await hub_restart_with_prompt(b)


async def phase_link() -> None:
    """A second connection with the node's key while the node is connected: 4409, and the first stays."""
    import aiohttp

    config = json.loads((NODE_STATE / "node.json").read_text())
    key = (NODE_STATE / "node_keys" / config["hub"]["id"]).read_text().strip()
    code = None
    async with aiohttp.ClientSession() as http:
        async with http.ws_connect(f"wss://127.0.0.1:{TLS_PORT}{nodelink.PATH}",
                                   ssl=aiohttp.Fingerprint(bytes.fromhex(config["hub"]["fp"]))) as ws:
            challenge = json.loads((await ws.receive()).data)
            await ws.send_str(nodelink.encode("hello", protocol=nodelink.PROTOCOL,
                                              auth=nodelink.answer(key, challenge["nonce"], challenge["hub"]["id"]),
                                              now=time.time(), node={"id": config["id"], "name": NODE, "os": "macos",
                                                                     "arch": "arm64", "version": "1", "harnesses": []}))
            await ws.receive()
            code = ws.close_code
    await asyncio.sleep(2)
    scenario("a second connection with the same key is closed 4409 and the real node stays linked",
             code == nodelink.CLOSE_ALREADY_CONNECTED and node_status().get("link") == "up", f"close {code}")


async def phase_pairing() -> None:
    env = {**NODE_ENV, "CLAUDE_VOICE_STATE": str(SPARE_STATE), "CLAUDE_VOICE_DAEMON_PORT": str(SPARE_PORT)}
    shutil.rmtree(SPARE_STATE, ignore_errors=True)
    p, line = invite("sparebox")
    wrong = re.sub(r"code=[^&]+", "code=AAAA-AAAA", line)
    w = node_cmd("join", wrong, "--no-start", env=env)
    scenario("wrong invite code is refused with the hub's reason", w.returncode != 0 and "wrong code" in w.stderr,
             w.stderr.strip()[-120:])
    ok = node_cmd("join", line, "--no-start", env=env)
    shutil.rmtree(SPARE_STATE, ignore_errors=True)
    reused = node_cmd("join", line, "--no-start", env=env)
    scenario("a used invite cannot pair again", ok.returncode == 0 and reused.returncode != 0
             and re.search(r"no invite outstanding|expired|wrong code", reused.stderr) is not None,
             reused.stderr.strip()[-120:])
    shutil.rmtree(SPARE_STATE, ignore_errors=True)
    await asyncio.sleep(61)  # the limit counts every attempt from this address in a minute, the ones above too
    p, line = invite("ratebox")
    wrong = re.sub(r"code=[^&]+", "code=AAAA-AAAA", line)
    codes = [node_cmd("join", wrong, "--no-start", env=env).stderr.strip()[-60:] for _ in range(6)]
    scenario("pairing is rate limited: the sixth attempt in a minute is 429", "too many attempts" in codes[-1]
             and all("wrong code" in c for c in codes[:5]), json.dumps(codes))
    _daemon("/voice/hub/invite", {"cancel": True})
    run([str(ROOT / "bin" / "pointe"), "hub", "revoke", "sparebox"], HUB_ENV, 30)


async def phase_skew(b: Browser) -> None:
    """A node whose clock is an hour behind: a protocol-level node (real hub, real TLS, real pairing route)."""
    import aiohttp

    await asyncio.sleep(61)  # out of the pairing rate window the last phase filled
    p, line = invite("skewbox")
    inv = nodelink.parse_invite(line.replace(f"port={PROXY_PORT}", f"port={TLS_PORT}"))
    skew = -3600.0
    async with aiohttp.ClientSession() as http:
        pin = aiohttp.Fingerprint(bytes.fromhex(inv["fp"]))
        async with http.post(f"https://127.0.0.1:{TLS_PORT}{nodelink.PAIR_PATH}", ssl=pin,
                             json={"code": inv["code"], "name": "skewbox", "os": "linux"}) as r:
            got = await r.json()
        async with http.ws_connect(f"wss://127.0.0.1:{TLS_PORT}{nodelink.PATH}", ssl=pin) as ws:
            challenge = json.loads((await ws.receive()).data)
            await ws.send_str(nodelink.encode("hello", protocol=nodelink.PROTOCOL,
                                              auth=nodelink.answer(got["node_key"], challenge["nonce"], got["hub"]["id"]),
                                              now=time.time() + skew,
                                              node={"id": got["node_id"], "name": "skewbox", "os": "linux", "arch": "x86_64",
                                                    "version": "1", "harnesses": ["claude-code"]}))
            await ws.receive()  # welcome
            entry = {"id": "sk1", "name": "kestrel", "name_given": True, "cwd": "/srv/kestrel", "pid": 1,
                     "harness": "claude-code", "home": "", "title": None, "capabilities": {"approvals": True}, "files": []}
            await ws.send_str(nodelink.encode("sessions", sessions=[entry]))
            await asyncio.sleep(3)

            def stamp(dt):
                return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + skew + dt))
            lines = [json.dumps({"type": "user", "uuid": "u1", "timestamp": stamp(0), "message": {"role": "user",
                     "content": "What is the kestrel build number?"}}) + "\n",
                     json.dumps({"type": "assistant", "uuid": "a1", "timestamp": stamp(1), "message": {"role": "assistant",
                     "content": [{"type": "text", "text": "The kestrel build number is 4471."}]}}) + "\n"]
            body = "".join(lines).encode()
            await ws.send_str(nodelink.encode("transcript", id="sk1", gen=0, offset=0, next_offset=len(body), entries=lines))

            async def pong():
                async for msg in ws:
                    frame = json.loads(msg.data)
                    if frame.get("t") == "ping":
                        await ws.send_str(nodelink.encode("pong", id=frame["id"]))
            ponger = asyncio.create_task(pong())
            measured = await until(lambda: log_lines(r"node skewbox connected \(skew \+3600"), 10)
            await asyncio.sleep(4)
            t = await say(b, "What did kestrel say in the last few minutes?")
            answer = await heard(b, t, 60)
            ponger.cancel()
            await ws.send_str(nodelink.encode("bye"))
    scenario("clock skew: the hub measures the node's clock offset at hello", bool(measured), (measured or [""])[0][-80:])
    scenario("clock skew: a remote line stamped an hour behind still counts as recent", "4471" in answer, answer[:160])


async def phase_rotate_revoke_leave() -> None:
    rotated = run([str(ROOT / "bin" / "pointe"), "pair", "rotate"], HUB_ENV, 60)
    hub_stop()
    hub_ensure()
    hint = await until(lambda: "rotated" in (node_status().get("link_error") or ""), 60)
    st = node_cmd("status")
    scenario("cert rotation: the node refuses the new certificate and says to pair again",
             rotated.returncode == 0 and bool(hint) and "pair again" in st.stdout, st.stdout.strip()[-200:])
    left = node_cmd("leave")
    scenario("cert rotation: leave with the link down says the hub still lists it and how to revoke",
             f"pointe hub revoke {NODE}" in left.stdout, left.stdout.strip()[-200:])
    run([str(ROOT / "bin" / "pointe"), "hub", "revoke", NODE], HUB_ENV, 30)
    ok, out = await join_node()
    scenario("cert rotation: after a new invite the node pairs and links again",
             ok and bool(await until(lambda: node_status().get("link") == "up", 30)), out[-160:])
    # revoke from the hub
    r = run([str(ROOT / "bin" / "pointe"), "hub", "revoke", NODE], HUB_ENV, 30)
    gone = await until(lambda: not [s for s in status()["sessions"] if s.get("machine") == NODE], 30)
    unpaired = await until(lambda: not (NODE_STATE / "node.json").exists(), 30)
    scenario("revoke: the node is told, deletes its key, and its sessions leave the voice",
             r.returncode == 0 and bool(gone) and bool(unpaired), f"left={left.returncode} {r.stdout.strip()[-80:]}")
    # pair again, then unpair from the node's side
    run([str(ROOT / "bin" / "voice-node"), "stop"], NODE_ENV)
    ok, out = await join_node()
    await until(lambda: node_status().get("link") == "up", 30)
    leave = node_cmd("leave")
    nodes = await until(lambda: not _daemon("/voice/hub/nodes").get("nodes"), 20)
    scenario("unpair from the node side: pointe node leave makes the hub forget it", ok and leave.returncode == 0
             and bool(nodes), leave.stdout.strip()[-120:])


async def main() -> None:
    fresh_state()
    hub_stop()
    run([str(ROOT / "bin" / "voice-node"), "stop"], NODE_ENV)
    for state in (STATE, NODE_STATE):  # no machine, key or mirror from an earlier run
        for p in state.glob("*") if state.exists() else []:
            if p.name != "node-env":
                shutil.rmtree(p) if p.is_dir() else p.unlink()
    (STATE / "config.json").write_text(json.dumps({"machine": "studio"}))
    for path, fact in REPOS.values():
        make_repo(path, fact)
    run(["uv", "run", "--project", str(ROOT), "python", "-c", "import pair; pair.setup('127.0.0.1', '127.0.0.1')"],
        HUB_ENV, 60, cwd=ROOT)  # what `pointe pair host 127.0.0.1` writes, without opening the QR picture
    assert hub_ensure(), "the hub did not start"
    proxy = Proxy()
    await proxy.start()
    sessions: dict = {}
    b = None
    tapping = asyncio.create_task(tapper())
    try:
        await phase_pair()
        b = await connect_call()
        await asyncio.sleep(6)
        sessions = await start_sessions()
        await asyncio.sleep(6)
        for phase in PHASES:
            print(f"\n=== {phase}", flush=True)
            TAPPER["on"] = phase in ("brain", "restart", "skew")
            try:
                if phase == "brain":
                    await phase_brain(b)
                elif phase == "approve":
                    await phase_approve(b)
                elif phase == "offline":
                    await phase_offline(b, proxy, sessions)
                elif phase == "restart":
                    b = await phase_restart(b)
                elif phase == "link":
                    await phase_link()
                elif phase == "pairing":
                    await phase_pairing()
                elif phase == "skew":
                    await phase_skew(b)
                elif phase == "rotate":
                    await phase_rotate_revoke_leave()
            except Exception as e:
                import traceback
                traceback.print_exc()
                scenario(f"{phase}: ran to the end", False, f"{type(e).__name__}: {e}")
    finally:
        tapping.cancel()
        if b:
            await b.close()
        for s in sessions.values():
            try:
                s.stop()
            except Exception:
                pass
        for p in made["procs"]:
            p.kill()
        run([str(ROOT / "bin" / "voice-node"), "stop"], NODE_ENV)
        stop_daemon()
        if made["oc"]:
            try:
                await opencode_delete(made["oc"])
            except Exception as e:
                print("opencode cleanup:", type(e).__name__)
        for thread in made["cx"]:
            subprocess.run(["codex", "delete", "--force", thread], capture_output=True, timeout=60)
        print("\nTWO MACHINES")
        for name, verdict in verdicts.items():
            print(f"  {verdict[:4]}  {name}{verdict[4:]}")
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (two machines)")


asyncio.run(main())
