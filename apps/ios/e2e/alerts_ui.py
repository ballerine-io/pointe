"""Wrist approvals, end to end on the simulator: a real test daemon, a real call from the app, and
AlertsUITests.testWristApprovalEndToEnd driving the app and the lock screen. They hand each other cue files.

The app goes to the background with a request pending: the notification shows the read-out form; Approve on it reaches
Claude Code's hook as "allow", logged as from a notification. An unreadable request is posted with Deny only and none of
its text. Answered on the Mac, it is withdrawn by the app, still alive in the background on its call.

A real Apple Watch cannot be driven here: the watch shows the same notification (iOS mirrors it), so this checks
everything up to the mirror. Made-up commands and names only.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-wst CLAUDE_VOICE_DAEMON_PORT=7970 CLAUDE_VOICE_TLS_PORT=7570 \
     uv run python -u -I apps/ios/e2e/alerts_ui.py <simulator id> [screenshot folder]
POINTE_DERIVED_DATA (default /tmp/pointe-dd) and DEVELOPMENT_TEAM as for the other iOS e2e drivers.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT_DIR / "tests" / "e2e"))
sys.path.insert(0, str(ROOT_DIR))
from rig import DAEMON, ROOT, STATE, fresh_state, log_lines, stop_daemon  # noqa: E402

assert os.environ.get("CLAUDE_VOICE_STATE") and os.environ.get("CLAUDE_VOICE_TLS_PORT"), "isolated state and TLS port"
SIMULATOR = sys.argv[1]
SHOTS = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/pointe-alerts-shots")
results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, **detail) -> None:
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {json.dumps(detail)[:300]}", flush=True)


def post(path: str, body: dict, timeout: float = 10) -> dict:
    request = urllib.request.Request(f"{DAEMON}{path}", data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {(STATE / 'token').read_text().strip()}", "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=timeout).read())


def status() -> dict:
    request = urllib.request.Request(f"{DAEMON}/voice/status", headers={"Authorization": f"Bearer {(STATE / 'token').read_text().strip()}"})
    return json.loads(urllib.request.urlopen(request, timeout=10).read())


def wait_for(test, timeout: float):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = test()
        if value:
            return value
        time.sleep(0.5)
    return test()


def cue(name: str) -> None:
    (SHOTS / f"cue-{name}").touch()


def seen(name: str) -> bool:
    return (SHOTS / f"cue-{name}").exists()


def hold(command: str, description: str, into: dict) -> threading.Thread:
    """Claude Code's permission hook: held until the request is answered."""
    hook = {"session_id": "alerts-e2e", "tool_name": "Bash", "tool_input": {"command": command, "description": description}}
    t = threading.Thread(target=lambda: into.update(post("/voice/permission-hook", hook, timeout=300)), daemon=True)
    t.start()
    return t


def behavior(reply: dict) -> str | None:
    return reply.get("hookSpecificOutput", {}).get("decision", {}).get("behavior")


def main() -> None:
    shutil.rmtree(SHOTS, ignore_errors=True)
    SHOTS.mkdir(parents=True)
    fresh_state()
    import pair

    pair.STATE = STATE
    pair.setup(os.environ.get("IOS_E2E_HOST", "pointe.localtest.me"), "127.0.0.1")
    config = json.loads((STATE / "remote.json").read_text())
    (STATE / "remote.json").write_text(json.dumps({**config, "listen": ["127.0.0.1", "::1"]}))
    up = subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, text=True, env=dict(os.environ))
    assert up.returncode == 0, up.stderr[-400:]
    link = pair.pairing_link()
    subprocess.run(["xcrun", "simctl", "boot", SIMULATOR], capture_output=True)
    subprocess.run(["xcrun", "simctl", "privacy", SIMULATOR, "grant", "microphone", "io.ballerine.pointe"], capture_output=True)
    team = [f"DEVELOPMENT_TEAM={os.environ['DEVELOPMENT_TEAM']}"] if os.environ.get("DEVELOPMENT_TEAM") else []
    log = open(SHOTS / "xcodebuild.log", "w")
    xcode = subprocess.Popen(
        ["xcodebuild", "-project", str(ROOT / "apps" / "ios" / "Pointe.xcodeproj"), "-scheme", "Pointe", "-destination", f"id={SIMULATOR}",
         "-derivedDataPath", os.environ.get("POINTE_DERIVED_DATA", "/tmp/pointe-dd"),
         "-only-testing:PointeUITests/AlertsUITests/testWristApprovalEndToEnd", *team, "test"],
        env={**os.environ, "TEST_RUNNER_POINTE_PAIR": link, "TEST_RUNNER_ALERTS_SHOTS": str(SHOTS)},
        stdout=log, stderr=subprocess.STDOUT, text=True)
    try:
        check("the app pairs and the call connects", bool(wait_for(lambda: log_lines("phone connected"), 600)))
        check("the app turned its alerts on", bool(wait_for(lambda: seen("ready"), 180)))
        post("/voice/prefs", {"alerts.watch_approve": True})  # the Face ID step for this is covered by testTheAlertsSheet
        post("/voice/register", {"id": "alerts-e2e", "name": "river-lantern", "name_given": True, "cwd": "/tmp",
                                 "pid": os.getpid(), "transcript": "/tmp/none.jsonl"})

        first: dict = {}
        held = hold("git push origin dev", "Push the release branch", first)
        held.join(240)
        check("Approve on the notification reaches Claude Code's hook as allow", behavior(first) == "allow", reply=first)
        check("the daemon logged it as an answer from a notification",
              bool(log_lines(r"-> allow \(from a notification\)")), lines=log_lines("from a notification")[-2:])

        second: dict = {}
        held = hold("python3 -c 'import os; print(os.environ)' | sh", "A harmless check", second)
        cue("unreadable")
        check("the unreadable request was seen with Deny only", bool(wait_for(lambda: seen("unreadable-seen"), 150)))
        request_id = next((s["request_id"] for s in status()["sessions"] if s["name"] == "river-lantern" and s["request_id"]), None)
        post("/voice/approve", {"session": "river-lantern", "request_id": request_id, "decision": "deny"})  # as the page would
        held.join(30)
        check("answered on the Mac, it reaches the hook as deny", behavior(second) == "deny", reply=second)
        cue("answered")
        check("the app withdrew the notification", bool(wait_for(lambda: seen("withdrawn"), 120)))

        try:
            xcode.wait(timeout=240)
        except subprocess.TimeoutExpired:
            xcode.kill()
        out = (SHOTS / "xcodebuild.log").read_text()
        tail = [line for line in out.splitlines() if "error:" in line or "TEST " in line][-6:]
        check("the UI test passes", "** TEST SUCCEEDED **" in out, tail=tail)
    finally:
        if xcode.poll() is None:
            xcode.kill()
        stop_daemon()
        print(f"screenshots: {SHOTS}")
        print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed (iOS wrist approvals)")
    sys.exit(0 if all(ok for _, ok in results) else 1)


main()
