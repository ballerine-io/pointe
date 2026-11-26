"""An old part of Pointe against a new one fails in one sentence (pointe/skew.py, docs/multi-machine.md "Versions"):
the scripts, the hooks and the CLI against the voice or host on this machine, and a host against a voice over the
link, in both directions. Never a traceback, a bare status or a hang."""

import asyncio
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
import guards  # noqa: E402
import hub_nodes  # noqa: E402
import node  # noqa: E402
import nodelink  # noqa: E402
import skew  # noqa: E402
from test_hub_nodes import FakeNode, paired, run, world  # noqa: E402,F401  (world is a fixture)
from test_node import FakeHub, _pair  # noqa: E402

BIN = ROOT / "bin"
TOKEN = "synthetic-daemon-token-0123456789"


# ---------- the rule ----------

def test_a_caller_in_range_or_with_no_header_is_served():
    assert skew.refusal(None, "0.10.0") is None  # every script before the header existed
    assert skew.refusal("not a header", "0.10.0") is None
    assert skew.refusal(skew.header("plugin", "0.10.0"), "0.10.0") is None
    assert skew.refusal("plugin/0.9.0 api=1", "0.10.0") is None


def test_a_newer_caller_is_told_to_start_the_newer_pointe():
    got = skew.refusal(f"hook/0.12.0 api={skew.API + 1}", "0.10.0")
    assert got["need"] == {"api": [skew.MIN_API, skew.API]}
    assert got["have"] == {"part": "hook", "version": "0.12.0", "api": skew.API + 1}
    assert got["how"] == "pointe restart" and "0.10.0" in got["error"] and "0.12.0" in got["error"]
    assert got["error"].endswith(got["how"])


@pytest.mark.parametrize("part, how", [("plugin", skew.PLUGIN_UPDATE), ("hook", skew.PLUGIN_UPDATE), ("cli", "pointe update")])
def test_an_older_caller_is_told_the_command_that_updates_it(part, how):
    got = skew.refusal(f"{part}/0.9.0 api=2", "0.14.0", api=5, min_api=3)
    assert got["how"] == how and got["error"].endswith(how) and "too old" in got["error"]


@pytest.mark.parametrize("status, body, says", [
    (426, json.dumps({"error": "The Pointe plugin that made this call is 0.9.0, too old. Update it: x"}), "too old"),
    (426, "", "different versions"),
    (403, "forbidden", "refused this call (403)"),
    (403, json.dumps(guards.NO_KEY), "does not carry the key"),
    (404, json.dumps({"detail": "Not Found"}), "older than this command"),
    (404, json.dumps({"detail": "not on the voice"}), "not on the voice"),
    (409, json.dumps({"detail": "No call is up."}), "No call is up."),
    (500, "Internal Server Error", "answered 500"),
    (200, "<html>hello</html>", "not what this version reads"),
    (0, "", "nothing answered on port 7860"),
])
def test_any_answer_that_is_not_a_200_with_json_is_one_sentence(status, body, says):
    line = skew.sentence(status, body, 7860)
    assert line.startswith("Pointe: ") and says in line and "\n" not in line and "Traceback" not in line


# ---------- the voice on this machine: the daemon's and the host's local routes ----------

@pytest.fixture
def served(monkeypatch):
    """The daemon's app and the token its guard checks. LocalAuth took the token when daemon.py was first imported (by
    whichever test came first), so the routes' own check is pointed at the same one for this test."""
    import daemon
    from fastapi.testclient import TestClient

    token = next(m.kwargs["token"] for m in daemon.app.user_middleware if m.cls is guards.LocalAuth)
    monkeypatch.setattr(daemon, "TOKEN", token)
    return daemon, TestClient(daemon.app, base_url="http://127.0.0.1:7860")


def test_the_daemon_refuses_a_caller_of_another_api_with_426_and_the_command(served):
    daemon, client = served
    got = client.get("/voice/status", headers={skew.HEADER: f"plugin/9.9.9 api={skew.API + 1}"})  # no token at all
    assert got.status_code == 426
    assert got.json()["how"] == "pointe restart" and daemon.VERSION in got.json()["error"]
    assert set(got.json()) == {"error", "need", "have", "how"}


def test_a_caller_of_this_api_is_served_as_before(served):
    daemon, client = served
    auth = {"authorization": f"Bearer {daemon.TOKEN}"}
    assert client.get("/voice/status", headers={**auth, skew.HEADER: skew.header("plugin", daemon.VERSION)}).status_code == 200
    assert client.get("/voice/status", headers=auth).status_code == 200  # no header: api 1


def test_a_local_caller_without_the_key_gets_a_sentence_it_can_print(served):
    _, client = served
    got = client.get("/voice/status")
    assert got.status_code == 403 and got.json() == guards.NO_KEY
    assert skew.sentence(403, got.content).startswith("Pointe: This call does not carry the key")


def test_a_web_page_learns_no_version_and_gets_no_sentence(served):
    _, client = served
    got = client.get("/voice/status", headers={"origin": "https://evil.example", skew.HEADER: "plugin/1.0.0 api=99"})
    assert got.status_code == 403 and got.text == "forbidden"
    got = client.get("/voice/status", headers={"host": "evil.example", skew.HEADER: "plugin/1.0.0 api=99"})
    assert got.status_code == 403 and got.text == "forbidden"


def test_a_host_answers_its_scripts_the_same_way(tmp_path):
    """node.py serves the same local routes in the daemon's place: the same gate, in front of its token check."""
    from fastapi.testclient import TestClient

    (tmp_path / "token").write_text("t0k3n")
    client = TestClient(node.Node(tmp_path, port=0).app(), base_url="http://127.0.0.1:7860")
    with client:
        got = client.get("/voice/status", headers={skew.HEADER: f"hook/9.9.9 api={skew.API + 1}"})
        assert got.status_code == 426 and got.json()["how"] == "pointe restart"
        assert client.get("/voice/status").json() == guards.NO_KEY
        ok = client.get("/voice/status", headers={"authorization": "Bearer t0k3n", skew.HEADER: skew.header("cli", "0.10.0")})
        assert ok.status_code == 200 and ok.json()["node"] is True


# ---------- the scripts: who they say they are, and what they print when refused ----------

class Answering:
    """A listener on 127.0.0.1 in this process, owning the port as bin/voice-ours checks, that answers every request
    with one status and body and records what it was sent."""

    def __init__(self, state: Path, status: int, body: str):
        self.requests, self.status, self.body = [], status, body
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _serve(self):
                size = int(self.headers.get("content-length") or 0)
                outer.requests.append({"path": self.path, "client": self.headers.get(skew.HEADER),
                                       "auth": self.headers.get("authorization"), "body": self.rfile.read(size).decode()})
                body = b'{"ok": true}' if self.path == "/voice/health" else outer.body.encode()
                self.send_response(200 if self.path == "/voice/health" else outer.status)
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = _serve

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        state.mkdir(exist_ok=True)
        (state / "token").write_text(TOKEN)
        (state / "daemon.pid").write_text(str(os.getpid()))
        self.env = {"PATH": os.environ["PATH"], "HOME": str(state.parent), "CLAUDE_VOICE_STATE": str(state),
                    "CLAUDE_VOICE_DAEMON_PORT": str(self.port), "CLAUDE_VOICE_NO_BROWSER": "1", "LANG": "C.UTF-8"}

    def run(self, argv: list[str], stdin: str = "", **extra) -> subprocess.CompletedProcess:
        return subprocess.run([str(BIN / argv[0]), *argv[1:]], env={**self.env, **extra}, input=stdin,
                              capture_output=True, text=True, timeout=30, cwd=self.env["HOME"])

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def answering(tmp_path):
    made = []

    def make(status: int, body: str) -> Answering:
        made.append(Answering(tmp_path / "state", status, body))
        return made[-1]

    yield make
    for a in made:
        a.close()


HOOK_EVENT = json.dumps({"session_id": "sess-1", "transcript_path": "/tmp/none.jsonl", "tool_name": "Bash",
                         "tool_input": {"command": "ls"}})
CALLERS = {  # name: (argv, stdin, extra environment, the part it says it is)
    "register-session": (["register-session"], HOOK_EVENT, {"CLAUDE_PID": "4242"}, "plugin"),
    "voice-permission-hook": (["voice-permission-hook"], HOOK_EVENT, {}, "hook"),
    "voice-talk": (["voice-talk", "on"], "", {}, "cli"),
    "voice-context": (["voice-context", "--json"], "", {}, "cli"),
    "claude-voice-attach status": (["claude-voice-attach", "status"], "", {}, "plugin"),
    "claude-voice-attach off": (["claude-voice-attach", "off"], "", {"CLAUDE_CODE_SESSION_ID": "sess-1"}, "plugin"),
}
REFUSALS = {
    "another api": (426, json.dumps(skew.refusal(f"plugin/0.1.6 api={skew.API + 5}", "0.10.0"))),
    "no key": (403, json.dumps(guards.NO_KEY)),
    "a bare 403 from an older Pointe": (403, "forbidden"),
    "a crash": (500, "Internal Server Error"),
    "not json": (200, "<html>Forbidden</html>"),
    "an unknown route on an older Pointe": (404, json.dumps({"detail": "Not Found"})),
}


@pytest.mark.parametrize("name", sorted(CALLERS))
def test_each_script_says_who_it_is_and_which_api_it_speaks(answering, name):
    argv, stdin, extra, part = CALLERS[name]
    daemon = answering(200, json.dumps({"open": True, "name": "api", "connected": True}))
    daemon.run(argv, stdin, **extra)
    version = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    sent = [r for r in daemon.requests if r["auth"]]
    assert sent and all(r["client"] == f"{part}/{version} api={skew.API}" for r in sent), daemon.requests
    assert all(skew.parse(r["client"]) == (part, version, skew.API) for r in sent)


@pytest.mark.parametrize("why", sorted(REFUSALS))
@pytest.mark.parametrize("name", sorted(CALLERS))
def test_a_refused_script_prints_one_sentence_and_never_a_traceback(answering, name, why):
    argv, stdin, extra, _ = CALLERS[name]
    status, body = REFUSALS[why]
    got = answering(status, body).run(argv, stdin, **extra)
    said = got.stdout + got.stderr
    for crash in ("Traceback", "JSONDecodeError", "curl:", "parse error", "syntax error"):
        assert crash not in said, said
    lines = [line for line in said.splitlines() if line.startswith("Pointe: ") or "Pointe" in line]
    if name == "voice-permission-hook":
        # Claude Code reads the hook's stdout as the decision: nothing there and exit 0 leaves the prompt in the terminal.
        assert got.returncode == 0 and got.stdout == "" and got.stderr.count("\n") == 1 and got.stderr.startswith("Pointe: ")
    elif name == "claude-voice-attach off" and why == "an unknown route on an older Pointe":
        assert "older than this command" in said
    else:
        assert lines, f"{name} said nothing a person can read: {said!r}"
    if why == "another api":
        assert "pointe restart" in said, said


def test_the_permission_hook_hands_the_decision_through_when_served(answering):
    decision = {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
    got = answering(200, json.dumps(decision)).run(["voice-permission-hook"], HOOK_EVENT)
    assert got.returncode == 0 and json.loads(got.stdout) == decision and got.stderr == ""
    got = answering(200, "{}").run(["voice-permission-hook"], HOOK_EVENT)
    assert got.returncode == 0 and got.stdout == ""


def test_voice_curl_reads_the_api_number_skew_py_holds():
    assert f"\nAPI = {skew.API} " in (ROOT / "pointe" / "skew.py").read_text()
    got = subprocess.run([sys.executable, "-I", str(ROOT / "pointe" / "skew.py"), "api"], capture_output=True, text=True)
    assert got.stdout.strip() == str(skew.API)


def test_the_sentence_runs_on_the_machines_own_python():
    """bin/voice-ask runs skew.py with `python3 -I`, which on a Mac is Python 3.9: annotations there are never
    evaluated (a `str | None` in a signature raised at import), and nothing outside the standard library is imported."""
    import ast

    tree = ast.parse((ROOT / "pointe" / "skew.py").read_text())
    imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert any(isinstance(n, ast.ImportFrom) and n.module == "__future__" and n.names[0].name == "annotations" for n in imports)
    names = {a.name.split(".")[0] for n in imports if isinstance(n, ast.Import) for a in n.names} | {
        n.module.split(".")[0] for n in imports if isinstance(n, ast.ImportFrom)}
    assert names <= {"__future__", "json", "re", "sys", "pathlib"}, names
    system = Path("/usr/bin/python3")
    if system.exists():
        got = subprocess.run([str(system), "-I", str(ROOT / "pointe" / "skew.py"), "sentence", "403", "7860"],
                             input="", capture_output=True, text=True, timeout=20)
        assert got.returncode == 0 and got.stdout.startswith("Pointe: ") and got.stderr == ""


def test_no_script_builds_the_request_on_its_own():
    """One place holds the header and the sentence (bin/voice-ask): a script that calls curl with the token itself
    would say nothing of its version and print whatever curl does."""
    for script in sorted(BIN.iterdir()):
        text = script.read_text(errors="replace")
        if script.name != "voice-ask":
            assert "Authorization: Bearer" not in text, f"bin/{script.name} sends the token without bin/voice-ask"


# ---------- the skew matrix: what each release's scripts send, replayed against this daemon ----------

MATRIX = json.loads((ROOT / "tests" / "fixtures" / "skew_requests.json").read_text())


@pytest.mark.parametrize("release, request_", [(r["release"], q) for r in MATRIX["releases"] for q in r["requests"]],
                         ids=lambda v: v if isinstance(v, str) else f"{v['method']} {v['path']}")
def test_every_released_request_gets_a_200_or_a_refusal_with_a_sentence(served, release, request_):
    daemon, client = served
    headers = {}
    if request_.get("client"):
        headers[skew.HEADER] = f"{request_['client']}/{release} api={request_['api']}"
    if request_.get("token"):
        headers["authorization"] = f"Bearer {daemon.TOKEN}"
    body = request_.get("body")
    if isinstance(body, dict) and "pid" in body:
        body = {**body, "pid": os.getpid()}
    got = client.request(request_["method"], request_["path"], headers=headers, json=body)
    assert got.status_code in request_["answers"], f"{release}: {got.status_code} {got.text[:200]}"
    if got.status_code != 200:
        told = got.json()  # never a bare status: a body a script can turn into one sentence
        assert isinstance(told.get("error") or told.get("detail"), str), told
        assert skew.sentence(got.status_code, got.content).startswith("Pointe: ")
    assert got.status_code < 500


def test_the_matrix_covers_this_release():
    """The version bump of a release adds that release's requests (docs/releasing.md), so the next one replays them."""
    version = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    assert version in [r["release"] for r in MATRIX["releases"]], (
        f"tests/fixtures/skew_requests.json has no entry for {version}: add what this release's scripts send")


# ---------- the link: a host against a voice, both directions ----------

def test_the_newest_protocol_both_sides_speak_is_chosen():
    assert nodelink.common(1, None, mine_min=1, mine_max=1) == 1
    assert nodelink.common(3, 2, mine_min=1, mine_max=2) == 2
    assert nodelink.common(2, 1, mine_min=1, mine_max=5) == 2
    assert nodelink.common(1, None, mine_min=2, mine_max=3) is None  # the other side is too old
    assert nodelink.common(4, 3, mine_min=1, mine_max=2) is None  # this side is too old
    assert nodelink.shared(["held", "from-the-future"]) == ["held"] and nodelink.shared(None) == []


def test_a_too_old_reason_fits_a_close_frame_and_reads_back():
    reason = nodelink.too_old("voice", 3, 1)
    assert len(reason.encode()) <= 123
    assert nodelink.skew_sentence(reason, "studio", "0.9.0") == (
        "studio runs an older Pointe (0.9.0) than this machine: update it there with pointe update, then this machine reconnects")
    assert "needs a newer Pointe on this machine" in nodelink.skew_sentence(nodelink.too_old("host", 2, 1), "studio")
    plain = "this hub needs protocol 2: update Pointe on this machine"  # what 0.9.0 and older close with
    assert "needs a newer Pointe on this machine" in nodelink.skew_sentence(plain, "studio")


def test_a_host_from_before_ranges_links_and_gets_no_features(world):
    """A 0.9.0 node: `protocol` alone, no range, no features. The link comes up as before."""
    hub, *_ = world
    entry = paired(hub)

    async def go():
        fake = FakeNode(hub, entry)
        welcome = await fake.connect(protocol=1)
        assert welcome["protocol"] == 1 and welcome["features"] == []
        await fake.drop()

    run(go())


def test_the_challenge_says_the_voices_range_and_version(world):
    hub, *_ = world

    async def go():
        fake = FakeNode(hub, paired(hub))
        fake.task = asyncio.create_task(hub.serve(fake.pipe))
        challenge = await fake.recv("challenge")
        assert challenge["protocol"] == nodelink.PROTOCOL and challenge["protocol_min"] == nodelink.MIN_PROTOCOL
        assert challenge["version"] == skew.version()
        await fake.drop()

    run(go())


@pytest.mark.parametrize("hello, update, says", [
    ({"protocol": 1}, "host", "runs an older Pointe (1.0.1). Update it there"),
    ({"protocol": 9, "protocol_min": 8}, "voice", "runs a newer Pointe (1.0.1) than this machine. Update this one"),
])
def test_no_common_protocol_is_said_on_both_sides_and_the_machine_stays_listed(world, monkeypatch, hello, update, says):
    hub, *_ = world
    monkeypatch.setattr(nodelink, "MIN_PROTOCOL", 2)
    monkeypatch.setattr(nodelink, "PROTOCOL", 3)
    entry = paired(hub)

    async def go():
        fake = FakeNode(hub, entry)
        fake.task = asyncio.create_task(hub.serve(fake.pipe))
        challenge = await fake.recv("challenge")
        await fake.send("hello", **hello, auth=nodelink.answer(entry["key"], challenge["nonce"], challenge["hub"]["id"]),
                        now=hub_nodes.time.time(), node={"id": entry["id"], "name": entry["name"], "os": "linux",
                                                         "arch": "x86_64", "version": "1.0.1", "harnesses": []})
        assert await fake.recv() is None
        code, reason = fake.pipe.closed
        assert code == nodelink.CLOSE_TOO_OLD and json.loads(reason)["update"] == update
        machine = hub_nodes.sessions.MACHINES[entry["name"]]
        assert not machine.online and says in machine.notice and "pointe update" in machine.notice

    run(go())


def test_a_stranger_cannot_mark_a_machine_as_out_of_date(world, monkeypatch):
    """The hello comes before any proof: only one whose key answers the nonce changes what the owner reads."""
    hub, *_ = world
    monkeypatch.setattr(nodelink, "MIN_PROTOCOL", 2)
    entry = paired(hub)

    async def go():
        fake = FakeNode(hub, entry)
        assert await fake.connect(key="00" * 32, protocol=1) is None
        assert fake.pipe.closed[0] == nodelink.CLOSE_TOO_OLD
        machine = hub_nodes.sessions.MACHINES.get(entry["name"])
        assert machine is None or not machine.notice

    run(go())


def test_the_notice_goes_when_the_updated_machine_links(world, monkeypatch):
    hub, *_ = world
    entry = paired(hub)

    async def go():
        monkeypatch.setattr(nodelink, "MIN_PROTOCOL", 2)
        monkeypatch.setattr(nodelink, "PROTOCOL", 2)
        assert await FakeNode(hub, entry).connect(protocol=1) is None
        assert "older Pointe" in hub_nodes.sessions.MACHINES[entry["name"]].notice
        fake = FakeNode(hub, entry)
        assert (await fake.connect(protocol=2))["protocol"] == 2
        assert hub_nodes.sessions.MACHINES[entry["name"]].notice == ""
        await fake.drop()

    run(go())


class _SkewedHub(FakeHub):
    """A voice the host cannot speak with: it closes 4426 with `reason`, or (a release from before ranges) welcomes
    with its own protocol whatever the host offered."""

    reason: str | None = None
    welcomes_with: int | None = None
    version: str | None = None

    async def _ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.connections += 1
        extra = {"version": self.version} if self.version else {}
        await ws.send_str(nodelink.encode("challenge", nonce=nodelink.new_nonce(), hub=self.HUB, **extra))
        self.hellos.append(json.loads(await ws.receive_str()))
        if self.welcomes_with is not None:
            await ws.send_str(json.dumps({"t": "welcome", "protocol": self.welcomes_with, "call_up": False,
                                          "approvals_terminal": False, "vendors": [], "resume": {}}))
            await ws.receive()
        else:
            await ws.close(code=nodelink.CLOSE_TOO_OLD, message=(self.reason or "").encode())
        return ws


def _link_error(tmp_path, monkeypatch, **hub_options) -> tuple[str, dict]:
    monkeypatch.setattr(nodelink, "backoff", lambda attempt: 30)

    async def go():
        hub = _SkewedHub(tmp_path)
        for name, value in hub_options.items():
            setattr(hub, name, value)
        await hub.start()
        state = tmp_path / "state"
        _pair(state, hub)
        (state / "token").write_text("t0k3n")
        n = node.Node(state, port=0)
        await n.start()
        try:
            for _ in range(100):
                if n.link_error:
                    break
                await asyncio.sleep(0.05)
            assert not n.linked.is_set()
            assert (state / "node_keys" / hub.HUB["id"]).exists(), "a version mismatch never deletes the key"
            return n.link_error, hub.hellos[0]
        finally:
            await n.stop()
            await hub.stop()

    return asyncio.run(go())


def test_a_host_says_its_range_and_features_in_its_hello(tmp_path, monkeypatch):
    _, hello = _link_error(tmp_path, monkeypatch, reason=nodelink.too_old("host", 5, 1))
    assert hello["protocol"] == nodelink.PROTOCOL and hello["protocol_min"] == nodelink.MIN_PROTOCOL
    assert hello["features"] == list(nodelink.FEATURES)


def test_a_host_too_old_for_its_voice_says_so_with_the_command(tmp_path, monkeypatch):
    error, _ = _link_error(tmp_path, monkeypatch, reason=nodelink.too_old("host", 5, 1))
    assert error == "studio needs a newer Pointe on this machine: update it with pointe update, then it reconnects"


def test_a_voice_too_old_for_its_host_is_named_on_the_host(tmp_path, monkeypatch):
    error, _ = _link_error(tmp_path, monkeypatch, reason=nodelink.too_old("voice", 4, 1), version="0.9.0")
    assert error == ("studio runs an older Pointe (0.9.0) than this machine: update it there with pointe update, "
                     "then this machine reconnects")


def test_a_voice_from_before_ranges_that_welcomes_with_an_older_protocol_is_named_too(tmp_path, monkeypatch):
    """0.9.0 and older never look at the host's range: they welcome with protocol 1. A host that needs 2 says the
    voice is the old side, since the voice cannot."""
    monkeypatch.setattr(nodelink, "MIN_PROTOCOL", 2)
    monkeypatch.setattr(nodelink, "PROTOCOL", 2)
    error, _ = _link_error(tmp_path, monkeypatch, welcomes_with=1)
    assert error.startswith("studio runs an older Pointe than this machine: update it there with pointe update")
