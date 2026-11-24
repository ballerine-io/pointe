"""Talk to Pointe from outside the app, in the simulator: a press (the Debug build's `-talkPress`, the same PhoneTalk
path the Control and the Action button take) starts a call to a stand-in Mac in Session mode; the Live Activity's Send
on the Lock Screen sends the press, and its Hang up ends the call. Passes when the Mac saw, in order: the call, the
press open, the press closed, the call hung up, with Orchestrator mode before the send; and never an approval, though
two sessions wait.

Run (after `xcodebuild build-for-testing -project apps/ios/Pointe.xcodeproj -scheme Pointe -derivedDataPath <dir>`; add
POINTE_SHARE_GROUP=YES for the widget's status, which the press does not need):
    CLAUDE_VOICE_STATE=/tmp/cv-state-talk-outside CLAUDE_VOICE_TLS_PORT=7481 POINTE_DERIVED_DATA=<dir> \
        uv run --locked python -u -I apps/ios/e2e/talk_outside_ui.py <simulator id> [screenshot dir] [control|widget]
`control`: the real path instead. The Talk to Pointe control in Control Center (add it once: TalkWidgetUITests), tapped
with the app not running: Pointe opens talking, a tap on the mic sends, the Lock Screen's Hang up ends the call. It
prints the time from the tap to the press open on the Mac. `widget`: the same from the Home Screen widget, added first.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
STATE = Path(os.environ["CLAUDE_VOICE_STATE"])
assert STATE != Path.home() / ".claude-voice" and os.environ.get("CLAUDE_VOICE_TLS_PORT"), "isolated state and TLS port"
SIMULATOR = sys.argv[1]
PATHS = {"control": "testTheControlInControlCenterOpensPointeTalking", "widget": "testTheHomeScreenWidgetOpensPointeTalking"}
REAL = next((a for a in sys.argv[2:] if a in PATHS), None)  # the real path: the control or the widget, the app not running
SHOTS = next((Path(a) for a in sys.argv[2:] if a not in PATHS), None)
EXPECTED = ["phone connected", "ptt open", "ptt closed", "hung-up"]
ORCHESTRATOR = 'mode {"mode":"orchestrator"}'  # set while you talk: any time before the send


def main() -> None:
    import pair

    pair.STATE = STATE
    pair.setup("pointe.localtest.me", "127.0.0.1")
    link = pair.pairing_link()
    port = os.environ["CLAUDE_VOICE_TLS_PORT"]
    mac = subprocess.Popen([sys.executable, "-u", "-I", str(Path(__file__).with_name("talk_mac.py")), str(STATE), port, "240"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    subprocess.run(["xcrun", "simctl", "boot", SIMULATOR], capture_output=True)
    subprocess.run(["xcrun", "simctl", "privacy", SIMULATOR, "grant", "microphone", "io.ballerine.pointe"], capture_output=True)
    if SHOTS:
        SHOTS.mkdir(parents=True, exist_ok=True)
    derived = Path(os.environ.get("POINTE_DERIVED_DATA", "/tmp/pointe-dd-talk"))
    run = next((derived / "Build" / "Products").glob("*.xctestrun"))
    test = subprocess.run(
        ["xcodebuild", "test-without-building", "-xctestrun", str(run), "-destination", f"id={SIMULATOR}",
         "-only-testing:PointeUITests/TalkOutsideUITests/" + PATHS.get(REAL, "testAPressStartsACallToTheOrchestratorAndTheLockScreenSendsIt")],
        env={**os.environ, "TEST_RUNNER_POINTE_PAIR": link, "TEST_RUNNER_POINTE_SHOTS": str(SHOTS or "")},
        capture_output=True, text=True)
    mac.terminate()
    out, _ = mac.communicate(timeout=30)
    print(out)
    lines = [line.rsplit(" @", 1) for line in out.splitlines() if " @" in line]
    seen = [text for text, _ in lines if text.split(" ")[0] in ("mode", "phone", "ptt", "hung-up", "approve")]
    tap = SHOTS and (SHOTS / "tap.time").exists() and float((SHOTS / "tap.time").read_text())
    opened = next((float(at) for text, at in lines if text == "ptt open"), None)
    if tap and opened:
        first = next((float(at) for text, at in lines if text == "status" and float(at) > tap), opened)
        print(f"from the tap to the press open on the Mac: {opened - tap:.2f} s "
              f"(iOS opening the app: {first - tap:.2f} s, then the app: {opened - first:.2f} s)")
    ui_ok = "** TEST EXECUTE SUCCEEDED **" in test.stdout
    order_ok = [line for line in seen if line in EXPECTED] == EXPECTED and ORCHESTRATOR in seen[:seen.index("ptt closed")]
    approved = [line for line in seen if line.startswith("approve")]
    print(f"ui test {'passed' if ui_ok else 'FAILED'}; the Mac saw {seen}")
    if not ui_ok:
        print(test.stdout[-4000:])
    ok = ui_ok and order_ok and not approved
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
