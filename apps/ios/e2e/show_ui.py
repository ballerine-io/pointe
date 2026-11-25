"""Show while it says in the iPhone app, against a real test daemon over the pinned HTTPS link.

A fake browser holds the call; the paired app is a second screen (ShowUITests.testShowLive). A synthetic project gets
a Claude Code turn (an edit at line 41, a failing pytest), the real reader and brain report it, and:
- with "Show while it says" off on the phone, the app shows no card and the phone key reads nothing;
- once it is on, the card appears, the sheet shows the edited line and the failing assertion read from the Mac.
The test and this driver hand each other cue files in the screenshot folder.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-sws CLAUDE_VOICE_DAEMON_PORT=7951 CLAUDE_VOICE_TLS_PORT=7551 \
     uv run python -u -I apps/ios/e2e/show_ui.py <simulator id> [screenshot folder]
"""

import asyncio
import json
import os
import runpy
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[3] / "tools" / "ui_guard.py"))["require"]("apps/ios/e2e/show_ui.py")

ROOT_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT_DIR / "tests" / "e2e"))
sys.path.insert(0, str(ROOT_DIR))
from page_show import FAILING, line, project, turn  # noqa: E402
from rig import DAEMON, ROOT, STATE, Browser, fresh_state, stop_daemon  # noqa: E402

assert os.environ.get("CLAUDE_VOICE_STATE") and os.environ.get("CLAUDE_VOICE_TLS_PORT"), "isolated state and TLS port"
SIMULATOR = sys.argv[1]
SHOTS = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/pointe-show-ios-shots")
results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, **detail) -> None:
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {json.dumps(detail, ensure_ascii=False)[:300]}", flush=True)


def call(path: str, body: dict | None = None, key: str | None = None) -> tuple[int, dict]:
    secret = key or (STATE / "token").read_text().strip()
    request = urllib.request.Request(f"{DAEMON}{path}", data=json.dumps(body).encode() if body is not None else None,
                                     method="POST" if body is not None else "GET",
                                     headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}


def status() -> dict:
    return call("/voice/status")[1]


async def until(what, timeout: float, every: float = 0.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = what()
        if value:
            return value
        await asyncio.sleep(every)
    return what()


def cue(name: str):
    return lambda: (SHOTS / f"cue-{name}").exists()


def go(name: str) -> None:
    (SHOTS / f"go-{name}").touch()


async def main() -> None:
    import pair

    shutil.rmtree(SHOTS, ignore_errors=True)
    SHOTS.mkdir(parents=True)
    fresh_state()
    (STATE / "prefs.json").unlink(missing_ok=True)
    pair.STATE = STATE
    pair.setup(os.environ.get("IOS_E2E_HOST", "pointe.localtest.me"), "127.0.0.1")  # a real name: see tests/e2e/ios_app.py
    config = json.loads((STATE / "remote.json").read_text())
    (STATE / "remote.json").write_text(json.dumps({**config, "listen": ["127.0.0.1", "::1"]}))
    up = subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, text=True, env=dict(os.environ))
    assert up.returncode == 0, up.stderr[-400:]
    link = pair.pairing_link()
    phone_key = (STATE / "phone_key").read_text().strip()
    subprocess.run(["xcrun", "simctl", "boot", SIMULATOR], capture_output=True)

    root = project()
    transcript = root.parent / "transcript.jsonl"
    transcript.write_text(line("user", "<command-name>/pointe:voice</command-name>"))
    call("/voice/register", {"id": f"show-ios-{os.getpid()}", "cwd": str(root), "pid": os.getpid(), "name": "orchard",
                             "name_given": True, "transcript": str(transcript)})
    browser = Browser()
    log = SHOTS / "xcode.log"
    xcode = None
    try:
        await browser.connect()
        await asyncio.sleep(10)  # the greeting
        with transcript.open("a") as f:
            f.write(line("assistant", [{"type": "text", "text": "Joined the voice."}], "end_turn"))
        team = (ROOT / "apps" / "ios" / ".team").read_text().strip()
        xcode = subprocess.Popen(
            ["xcodebuild", "-project", str(ROOT / "apps" / "ios" / "Pointe.xcodeproj"), "-scheme", "Pointe", "-destination",
             f"id={SIMULATOR}", "-derivedDataPath", "/tmp/dd-sws", f"DEVELOPMENT_TEAM={team}",
             "-only-testing:PointeUITests/ShowUITests/testShowLive", "test"],
            env={**os.environ, "TEST_RUNNER_POINTE_PAIR": link, "TEST_RUNNER_SHOW_LIVE": str(SHOTS)},
            stdout=open(log, "w"), stderr=subprocess.STDOUT, text=True)
        ready = await until(cue("ready"), 600, 1)
        check("the app paired and is on the call screen", ready)

        turn(transcript, 1, [(root / "pricing.py", "    return price  # rule 14\n",
                              "    return price * 0.8  # rule 14: gold pays 80%\n")], FAILING,
             "I changed rule_14 in pricing.py so gold customers pay 80%. tests/test_pricing.py still fails.")
        shown = await until(lambda: status().get("showing"), 90)
        code, seen = call("/voice/status", key=phone_key)
        edit = next((a for a in (shown or {}).get("artifacts", []) if a["kind"] == "edit"), {})
        refused = call(f"/voice/artifact?id={edit.get('id')}", key=phone_key)[0]
        check("the report is on screen on the Mac; the phone key sees none of it while off",
              bool(shown) and code == 200 and seen.get("showing") is None and refused == 403, phone=refused)
        go("reported-off")
        check("the app shows no card while it is off", await until(cue("checked-off"), 60))

        code, prefs = call("/voice/prefs", {"show.on_phone": True})  # Face ID cannot be passed in the simulator
        check("turned on from the Mac", code == 200 and prefs.get("show.on_phone") is True)
        go("on")
        done = await until(lambda: cue("done")() or xcode.poll() is not None, 120, 1)
        check("the card appears and the sheet shows the edited line and the failing assertion, read from the Mac",
              bool(done) and cue("done")())
    finally:
        if xcode is not None:
            try:
                xcode.wait(timeout=180)
            except subprocess.TimeoutExpired:
                xcode.kill()
            out = log.read_text() if log.exists() else ""
            check("xcodebuild: the UI test passed", "** TEST SUCCEEDED **" in out,
                  tail=[x.strip()[-160:] for x in out.splitlines() if "error:" in x or "XCTAssert" in x][-5:])
        await browser.close()
        stop_daemon()
        print(f"\nscreenshots: {SHOTS}")
        print(f"{sum(ok for _, ok in results)}/{len(results)} passed (iOS show while it says)")


asyncio.run(main())
