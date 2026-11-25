"""The QA tour (apps/ios/PointeUITests/QATour.swift) against a real test daemon and the real voice: typing, a fix, clean-up,
an empty brain dump, focusing one session and back, swiping a session off the voice, the New pill while scrolled up,
and a held request denied by a tap. The test and this driver hand each other cue files in the screenshot folder.
Every session, name and word here is made up.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-qat CLAUDE_VOICE_DAEMON_PORT=7972 CLAUDE_VOICE_TLS_PORT=7572 \
     uv run python -u -I apps/ios/e2e/qa_tour.py <simulator id> [screenshot folder]
POINTE_DERIVED_DATA (default /tmp/pointe-dd) and DEVELOPMENT_TEAM as for the other iOS e2e drivers.
"""

import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[3] / "tools" / "ui_guard.py"))["require"]("apps/ios/e2e/qa_tour.py")

ROOT_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT_DIR / "tests" / "e2e"))
sys.path.insert(0, str(ROOT_DIR))
from rig import DAEMON, ROOT, STATE, fresh_state, log_lines, stop_daemon  # noqa: E402

assert os.environ.get("CLAUDE_VOICE_STATE") and os.environ.get("CLAUDE_VOICE_TLS_PORT"), "isolated state and TLS port"
SIMULATOR = sys.argv[1]
SHOTS = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/pointe-qa-tour")
results: list[tuple[str, bool]] = []
MORE_TALK = ["What is the capital of Canada? One word.", "And of Australia? One word.", "And of Brazil? One word.",
             "And of Kenya? One word."]
EVEN_MORE = ["What is the capital of Norway? One word.", "And of Chile? One word."]


def check(name: str, ok: bool, **detail) -> None:
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {json.dumps(detail)[:300]}", flush=True)


def call(path: str, body: dict | None = None, timeout: float = 20) -> dict:
    request = urllib.request.Request(f"{DAEMON}{path}", data=json.dumps(body).encode() if body is not None else None,
                                     method="POST" if body is not None else "GET", headers={
                                         "Authorization": f"Bearer {(STATE / 'token').read_text().strip()}",
                                         "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=timeout).read())


def cued(name: str, xcode: subprocess.Popen, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline and xcode.poll() is None:
        if (SHOTS / f"cue-{name}").exists():
            return True
        time.sleep(0.5)
    return False


def say_all(lines: list[str]) -> None:
    for line in lines:
        call("/voice/say", {"text": line})
        time.sleep(7)  # one answer at a time


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
    work = Path(tempfile.mkdtemp(prefix="ios-qa-tour-"))
    for name in ("alpha", "beta", "gamma"):
        (work / name).mkdir()
        (work / f"{name}.jsonl").touch()
        call("/voice/register", {"id": f"ios-qa-{name}-{os.getpid()}", "name": name, "name_given": True, "cwd": str(work / name),
                                 "pid": os.getpid(), "transcript": str(work / f"{name}.jsonl")})

    shutil.rmtree(SHOTS, ignore_errors=True)
    SHOTS.mkdir(parents=True)
    subprocess.run(["xcrun", "simctl", "boot", SIMULATOR], capture_output=True)
    subprocess.run(["xcrun", "simctl", "privacy", SIMULATOR, "grant", "microphone", "io.ballerine.pointe"], capture_output=True)
    xcode = subprocess.Popen(
        ["xcodebuild", "-project", str(ROOT / "apps" / "ios" / "Pointe.xcodeproj"), "-scheme", "Pointe", "-destination", f"id={SIMULATOR}",
         "-derivedDataPath", os.environ.get("POINTE_DERIVED_DATA", "/tmp/pointe-dd"), "-only-testing:PointeUITests/QATour",
         *([f"DEVELOPMENT_TEAM={os.environ['DEVELOPMENT_TEAM']}"] if os.environ.get("DEVELOPMENT_TEAM") else []), "test"],
        env={**os.environ, "TEST_RUNNER_POINTE_PAIR": link, "TEST_RUNNER_QA_SHOTS": str(SHOTS)},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    verdict: dict = {}
    try:
        deadline = time.time() + 400
        while time.time() < deadline and not log_lines("phone connected") and xcode.poll() is None:
            time.sleep(1)
        check("the app pairs over pinned TLS and the call connects", bool(log_lines("phone connected")))
        if cued("more-talk", xcode, 400):
            say_all(MORE_TALK)
        if cued("even-more-talk", xcode, 120):
            say_all(EVEN_MORE)
        if cued("request", xcode, 120):
            hook = {"session_id": f"ios-qa-alpha-{os.getpid()}", "tool_name": "Bash",
                    "tool_input": {"command": "touch tour-check.txt", "description": "Create a file"}}
            held = threading.Thread(target=lambda: verdict.update(call("/voice/permission-hook", hook, timeout=200)))
            held.start()
            held.join(180)
            behavior = verdict.get("hookSpecificOutput", {}).get("decision", {}).get("behavior")
            check("Deny in the app reaches Claude Code's hook as a denial", behavior == "deny", verdict=verdict)
        gone = not any(s["name"] == "gamma" for s in call("/voice/status")["sessions"])
        check("gamma, swiped off in the Sessions sheet, is off the voice on the Mac", gone)
        out, _ = xcode.communicate(timeout=400)
        tail = [line for line in out.splitlines() if "error" in line.lower() or "TEST " in line or "XCTAssert" in line]
        check("the UI test passes (the whole tour)", "** TEST SUCCEEDED **" in out and "QATour testTour]' passed" in out, tail=tail[-8:])
    finally:
        if xcode.poll() is None:
            xcode.kill()
        stop_daemon()
        print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed (QA tour); screenshots in {SHOTS}")
        sys.exit(0 if results and all(ok for _, ok in results) else 1)


main()
