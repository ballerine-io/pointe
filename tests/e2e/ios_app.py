"""The iPhone app in the simulator against a test daemon: pair by link, pinned TLS, call up, a held request shown word
for word, denied by a tap, and the denial reaching Claude Code's hook.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-ios CLAUDE_VOICE_DAEMON_PORT=7869 CLAUDE_VOICE_TLS_PORT=7469 \
     uv run python -u -I tests/e2e/ios_app.py <simulator id>
"""

import json
import os
import runpy
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools" / "ui_guard.py"))["require"]("tests/e2e/ios_app.py")

sys.path.insert(0, str(Path(__file__).parent))
sys.path[0:0] = [str(Path(__file__).resolve().parents[2] / "pointe"), str(Path(__file__).resolve().parents[2])]
from rig import DAEMON, ROOT, STATE, fresh_state, log_lines, stop_daemon  # noqa: E402

assert os.environ.get("CLAUDE_VOICE_STATE") and os.environ.get("CLAUDE_VOICE_TLS_PORT"), "isolated state and TLS port"
SIMULATOR = sys.argv[1]
results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, **detail) -> None:
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {json.dumps(detail)[:300]}", flush=True)


def post(path: str, body: dict, timeout: float = 10) -> dict:
    request = urllib.request.Request(f"{DAEMON}{path}", data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {(STATE / 'token').read_text().strip()}", "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=timeout).read())


def main() -> None:
    fresh_state()
    import pair

    pair.STATE = STATE
    # A real name, not localhost: iOS exempts localhost from App Transport Security, which hid a -9802 refusal that every
    # real phone hit. *.localtest.me is public DNS for this machine.
    pair.setup(os.environ.get("IOS_E2E_HOST", "pointe.localtest.me"), "127.0.0.1")
    config = json.loads((STATE / "remote.json").read_text())
    (STATE / "remote.json").write_text(json.dumps({**config, "listen": ["127.0.0.1", "::1"]}))  # it resolves to either
    up = subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, text=True, env=dict(os.environ))
    assert up.returncode == 0, up.stderr[-400:]
    link = pair.pairing_link()

    subprocess.run(["xcrun", "simctl", "boot", SIMULATOR], capture_output=True)
    subprocess.run(["xcrun", "simctl", "privacy", SIMULATOR, "grant", "microphone", "io.ballerine.pointe"], capture_output=True)
    xcode = subprocess.Popen(
        ["xcodebuild", "-project", str(ROOT / "apps" / "ios" / "Pointe.xcodeproj"), "-scheme", "Pointe", "-destination", f"id={SIMULATOR}",
         "-derivedDataPath", os.environ.get("POINTE_DERIVED_DATA", "/tmp/pointe-dd"), "-only-testing:PointeUITests/PointeUITests",
         *([f"DEVELOPMENT_TEAM={os.environ['DEVELOPMENT_TEAM']}"] if os.environ.get("DEVELOPMENT_TEAM") else []), "test"],
        env={**os.environ, "TEST_RUNNER_POINTE_PAIR": link}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    verdict: dict = {}
    try:
        deadline = time.time() + 400
        while time.time() < deadline and not log_lines("phone connected"):
            time.sleep(1)
        check("the app pairs over pinned TLS and the call connects", bool(log_lines("phone connected")))
        if log_lines("phone connected"):
            time.sleep(6)  # a few heartbeats
            req = urllib.request.Request(f"{DAEMON}/voice/status", headers={
                "Authorization": f"Bearer {(STATE / 'token').read_text().strip()}"})
            health = json.loads(urllib.request.urlopen(req, timeout=10).read()).get("call", {})
            check("the app answers the Mac's heartbeat", health.get("rtt_ms") is not None, call=health)
            base = {"cwd": "/tmp", "pid": os.getpid(), "transcript": "/tmp/none.jsonl"}
            post("/voice/register", {"id": "ios-e2e", "name": "phone-check", **base})
            hook = {"session_id": "ios-e2e", "tool_name": "Bash",
                    "tool_input": {"command": "touch phone-check.txt", "description": "Create a file"}}
            held = threading.Thread(target=lambda: verdict.update(post("/voice/permission-hook", hook, timeout=200)))
            held.start()
            held.join(180)
            behavior = verdict.get("hookSpecificOutput", {}).get("decision", {}).get("behavior")
            check("a tap on Deny in the app reaches Claude Code's hook as a denial", behavior == "deny", verdict=verdict)
        out, _ = xcode.communicate(timeout=300)
        tail = [line for line in out.splitlines() if "error" in line.lower() or "TEST " in line or "XCTAssert" in line]
        check("the UI test passes (connect, the exact command on screen, Deny, hang up)", "** TEST SUCCEEDED **" in out,
              tail=tail[-6:])
    finally:
        if xcode.poll() is None:
            xcode.kill()
        stop_daemon()
        print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed (iOS app)")


main()
