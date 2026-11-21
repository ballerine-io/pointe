"""The app answers the Mac's pings while the Mac talks: a stand-in Mac (talking_mac.py) streams bot audio at the
daemon's real rate for a while, pings every 2 s, and times each pong. The daemon closes a call whose pongs stop for
12 s; on a phone in Twingate this closed a call every minute or two, each time the bot spoke. Passes when the app never
went 6 s without a pong of either kind (an answer, or its own keep-alive), and, on a link that keeps up, the slowest
answer came back within MAX_PONG_MS. On a slow link (POINTE_DOWN_KBPS) the answers are late by design: they wait behind
the audio.

Run (after `xcodebuild ... build-for-testing` into the derived data path):
    CLAUDE_VOICE_STATE=/tmp/cv-state-talk CLAUDE_VOICE_TLS_PORT=7471 \
        uv run --locked python -u -I ios/e2e/talking_mac_ui.py <simulator id> [seconds of speech] [busy|plain]
POINTE_DOWN_KBPS=200 puts a link slower than the bot's voice (384 kbit/s) between the app and the stand-in.
POINTE_BACKGROUND=1 sends the app to the background (Home) for the whole speech: the call must keep answering there.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
STATE = Path(os.environ["CLAUDE_VOICE_STATE"])
assert STATE != Path.home() / ".claude-voice" and os.environ.get("CLAUDE_VOICE_TLS_PORT"), "isolated state and TLS port"
SIMULATOR = sys.argv[1]
SPEECH_SECS = float(sys.argv[2]) if len(sys.argv) > 2 else 40
SCREEN = sys.argv[3] if len(sys.argv) > 3 else "busy"  # "busy": a full screen whose status changes on every poll
MAX_PONG_MS = 2500  # a ping every 2 s and nothing in the way: an answer behind more than one ping is something new
MAX_SILENCE_MS = 6000  # half the daemon's 12 s: a keep-alive every 2 s, so more is the bug coming back


def main() -> None:
    import pair

    pair.STATE = STATE
    pair.setup("pointe.localtest.me", "127.0.0.1")
    link = pair.pairing_link()
    port = os.environ["CLAUDE_VOICE_TLS_PORT"]
    mac = subprocess.Popen([sys.executable, "-u", "-I", str(Path(__file__).with_name("talking_mac.py")), str(STATE), port,
                            str(SPEECH_SECS), SCREEN, os.environ.get("POINTE_DOWN_KBPS", "0")], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    subprocess.run(["xcrun", "simctl", "boot", SIMULATOR], capture_output=True)
    subprocess.run(["xcrun", "simctl", "privacy", SIMULATOR, "grant", "microphone", "io.ballerine.pointe"], capture_output=True)
    derived = Path(os.environ.get("POINTE_DERIVED_DATA", "/tmp/pointe-dd-link"))
    run = next((derived / "Build" / "Products").glob("*.xctestrun"))
    test = subprocess.run(
        ["xcodebuild", "test-without-building", "-xctestrun", str(run), "-destination", f"id={SIMULATOR}",
         "-only-testing:PointeUITests/TalkingMacUITests"],
        env={**os.environ, "TEST_RUNNER_POINTE_PAIR": link, "TEST_RUNNER_POINTE_HOLD_SECS": str(SPEECH_SECS + 12),
             "TEST_RUNNER_POINTE_BACKGROUND": os.environ.get("POINTE_BACKGROUND", "0")},
        capture_output=True, text=True)
    mac.terminate()
    out, _ = mac.communicate(timeout=30)
    print(out)
    delays = [int(m) for m in re.findall(r"^pong \d+ (\d+)$", out, re.M)]
    silence = int((re.findall(r"silence_ms=(\d+)", out) or ["999999"])[-1])
    slow = float(os.environ.get("POINTE_DOWN_KBPS", "0")) > 0
    ui_ok = "** TEST EXECUTE SUCCEEDED **" in test.stdout
    print(f"ui test {'passed' if ui_ok else 'FAILED'}; answers={len(delays)} slowest={max(delays, default=-1)} ms "
          f"longest silence={silence} ms")
    if not ui_ok:
        print(test.stdout[-3000:])
    ok = ui_ok and silence < MAX_SILENCE_MS and (slow or (len(delays) > SPEECH_SECS / 4 and max(delays) <= MAX_PONG_MS))
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
