"""Conflict alarm in the iPhone app against a real test daemon and the real reading model. The app pairs over pinned
TLS and holds the call (ConflictLiveUITests); this side writes two sessions' turns that disagree, then checks the
daemon: the card reached the app, Ask lantern came back as the user's typed words and reached no other session, and
Dismiss closed it. Every session, name and file here is made up.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-cfl CLAUDE_VOICE_DAEMON_PORT=7966 CLAUDE_VOICE_TLS_PORT=7566 \
     uv run python -u -I apps/ios/e2e/conflict_ui.py <simulator id> [screenshot folder]
POINTE_DERIVED_DATA (default /tmp/pointe-dd) and DEVELOPMENT_TEAM go to xcodebuild.
"""

import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT_DIR / "tests" / "e2e"))
sys.path.insert(0, str(ROOT_DIR))
from rig import DAEMON, ROOT, STATE, fresh_state, log_lines, stop_daemon  # noqa: E402

assert os.environ.get("CLAUDE_VOICE_STATE") and os.environ.get("CLAUDE_VOICE_TLS_PORT"), "isolated state and TLS port"
SIMULATOR = sys.argv[1]
SHOTS = Path(sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="pointe-conflict-ios-"))
results: list[tuple[str, bool]] = []

LANTERN_FINAL = ("The migration that adds the refund_reason column to the refunds table ran on staging and passed. "
                 "All migration checks are green.")
BILLING_FINAL = ("The refunds API test that reads the new refund_reason column failed on staging: "
                 "column refund_reason does not exist. The migration did not reach the staging database.")


def check(name: str, ok: bool, **detail) -> None:
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {json.dumps(detail)[:400]}", flush=True)


def call(path: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(f"{DAEMON}{path}", data=json.dumps(body).encode() if body is not None else None,
                                     method="POST" if body is not None else "GET", headers={
                                         "Authorization": f"Bearer {(STATE / 'token').read_text().strip()}",
                                         "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=30).read())


def turn(path: Path, asked: str, final: str) -> None:
    with path.open("a") as f:
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": asked}}) + "\n")
        f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": final}],
                                                             "stop_reason": "end_turn"}}) + "\n")


INBOX: dict[str, list[str]] = {}


def inbox(name: str) -> str:
    """A stand-in for the session's inbox socket: records each message the daemon sends to it."""
    path = f"/tmp/cfl-ios-inbox-{name}-{os.getpid()}.sock"
    Path(path).unlink(missing_ok=True)
    INBOX[name] = []

    class Take(socketserver.StreamRequestHandler):
        def handle(self):
            for line in self.rfile.read().decode().splitlines():
                if line.strip() and json.loads(line).get("type") == "user":
                    INBOX[name].append(json.loads(line)["message"]["content"])

    server = socketserver.UnixStreamServer(path, Take)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return path


def wait(test, timeout: float, every: float = 1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = test()
        if value:
            return value
        time.sleep(every)
    return test()


def main() -> None:
    fresh_state()
    import pair

    pair.STATE = STATE
    pair.setup(os.environ.get("IOS_E2E_HOST", "pointe.localtest.me"), "127.0.0.1")
    config = json.loads((STATE / "remote.json").read_text())
    (STATE / "remote.json").write_text(json.dumps({**config, "listen": ["127.0.0.1", "::1"]}))
    up = subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, text=True, env=dict(os.environ))
    assert up.returncode == 0, up.stderr[-400:]
    link = pair.pairing_link()
    work = Path(tempfile.mkdtemp(prefix="ios-conflict-e2e-"))
    repo = work / "shop"
    (repo / "db").mkdir(parents=True)
    (repo / "api").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    transcripts = {}
    for name, folder in (("lantern", repo / "db"), ("billing", repo / "api")):
        transcripts[name] = work / f"{name}.jsonl"
        transcripts[name].touch()
        call("/voice/register", {"id": f"ios-cfl-{name}-{os.getpid()}", "name": name, "name_given": True, "cwd": str(folder),
                                 "pid": os.getpid(), "transcript": str(transcripts[name]), "inbox_socket": inbox(name)})
    SHOTS.mkdir(parents=True, exist_ok=True)
    subprocess.run(["xcrun", "simctl", "boot", SIMULATOR], capture_output=True)
    subprocess.run(["xcrun", "simctl", "privacy", SIMULATOR, "grant", "microphone", "io.ballerine.pointe"], capture_output=True)
    xcode = subprocess.Popen(
        ["xcodebuild", "-project", str(ROOT / "apps" / "ios" / "Pointe.xcodeproj"), "-scheme", "Pointe", "-destination", f"id={SIMULATOR}",
         "-derivedDataPath", os.environ.get("POINTE_DERIVED_DATA", "/tmp/pointe-dd"),
         "-only-testing:PointeUITests/ConflictLiveUITests",
         *([f"DEVELOPMENT_TEAM={os.environ['DEVELOPMENT_TEAM']}"] if os.environ.get("DEVELOPMENT_TEAM") else []), "test"],
        env={**os.environ, "TEST_RUNNER_POINTE_CONFLICT_PAIR": link, "TEST_RUNNER_CONFLICT_SHOTS": str(SHOTS)},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        connected = wait(lambda: log_lines("phone connected"), 400)
        check("the app pairs over pinned TLS and the call connects", bool(connected))
        if connected:
            time.sleep(8)  # the greeting
            for name, path in transcripts.items():
                turn(path, "/pointe:voice", "Joined the voice.")  # the joining turn is never a report
            wait(lambda: len(log_lines("the join itself")) >= 2, 20)
            turn(transcripts["lantern"], "Run the refund_reason migration on staging.", LANTERN_FINAL)
            wait(lambda: log_lines("lantern finished|report for lantern"), 40)
            time.sleep(4)
            turn(transcripts["billing"], "Run the refunds API tests on staging.", BILLING_FINAL)
            raised = wait(lambda: call("/voice/status")["conflicts"], 90)
            check("the daemon raises one conflict for the pair", bool(raised) and len(raised) == 1, conflicts=raised)
            typed = wait(lambda: next((t for t in call("/voice/status")["talk"] if t["who"] == "user"
                                       and t["text"].startswith("Send lantern this question:")), None), 150)
            check("Ask lantern in the app is the user's typed words", bool(typed) and typed.get("typed") is True, typed=typed)
            wait(lambda: INBOX["lantern"], 30)
            routed = call("/voice/status")["recent"]
            check("the question reaches lantern's inbox once, and nothing reaches billing",
                  len(INBOX["lantern"]) == 1 and INBOX["billing"] == [] and not any("billing" in r["to"] for r in routed),
                  lantern=INBOX["lantern"], billing=INBOX["billing"], routed=routed[-3:])
            closed = wait(lambda: call("/voice/status")["conflicts"] == [] and log_lines("dismissed for this call"), 60)
            check("Dismiss in the app closes it on the Mac", bool(closed))
        out, _ = xcode.communicate(timeout=400)
        tail = [line for line in out.splitlines() if "error" in line.lower() or "TEST " in line or "XCTAssert" in line]
        check("the UI test passes (connect, the card, Ask, Dismiss, hang up)", "** TEST SUCCEEDED **" in out, tail=tail[-6:])
    finally:
        if xcode.poll() is None:
            xcode.kill()
        stop_daemon()
        print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed (iOS conflict alarm); screenshots in {SHOTS}")


main()
