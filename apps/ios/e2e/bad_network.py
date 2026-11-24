"""The iPhone app in the simulator, through a bad network, against a test daemon with a stand-in voice.

The daemon is Pointe's own (its phone listener, pinned TLS, socket_call, the status the app polls) with the call's
ears, brain and mouth replaced by tests/net_bench.py's Bot: each typed line gets a few seconds of synthetic speech.
tests/netshaper.py sits between the app and the phone listener; the outage or network switch is timed from the moment
the call is up. The app runs with POINTE_SYNTHETIC_MIC: a tone in place of the microphone, and a silent speaker. No
vendor, no key (vendor lookups are answered with made-up values, never from the Keychain), no microphone.

    CLAUDE_VOICE_STATE=/tmp/cv-state-net CLAUDE_VOICE_DAEMON_PORT=9781 CLAUDE_VOICE_TLS_PORT=9782 \\
        uv run --locked python -u -I apps/ios/e2e/bad_network.py <simulator id> <profile> [at:what ...]

`what` as in netshaper.py (`outage=5`, `switch`), `at` seconds after the call is up. Build first, into the derived data
path (POINTE_DERIVED_DATA, default /tmp/pointe-dd-net): xcodebuild build-for-testing -project apps/ios/Pointe.xcodeproj
-scheme Pointe -destination id=<simulator> -derivedDataPath /tmp/pointe-dd-net
POINTE_LINES (seconds after the call is up, comma-separated) are when the UI test types a line; POINTE_HOLD_SECS how
long it holds the call. Prints one JSON line at the end: what the app, the daemon and the shaper saw.
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STATE = Path(os.environ["CLAUDE_VOICE_STATE"])
assert STATE != Path.home() / ".claude-voice" and os.environ.get("CLAUDE_VOICE_TLS_PORT"), "isolated state and TLS port"
DAEMON_PORT = int(os.environ.get("CLAUDE_VOICE_DAEMON_PORT", "9781"))
TLS_PORT = int(os.environ["CLAUDE_VOICE_TLS_PORT"])
SHAPER_PORT = TLS_PORT + 1
REPLY_SECS = float(os.environ.get("POINTE_REPLY_SECS", "8"))


def serve_daemon() -> None:
    """The test daemon: Pointe's app, with the stand-in voice."""
    sys.path.insert(0, str(ROOT / "tests"))
    sys.path.insert(0, str(ROOT))
    os.environ.update(POINTE_LINK_DIR=str(STATE / "link"), CLAUDE_VOICE_SKIP_KEY_CHECK="1")
    import vendors

    vendors._stored = lambda vendor, keep=True: f"made-up-{vendor}-key"  # never the Keychain: these keys reach nothing
    import harnesses.claude_code

    harnesses.claude_code.ROSTER = False
    import mac

    mac.SYSTEM = False
    import daemon
    from net_bench import Bot

    daemon.COPY_SESSIONS = False
    bot = Bot(daemon, REPLY_SECS)
    daemon.run_call = bot.run_call

    async def nothing(*_a, **_k):
        return None

    daemon.KEEP_AWAKE.update = nothing  # no caffeinate for a test call
    sys.argv = ["daemon", "--port", str(DAEMON_PORT)]
    daemon.main()


def fresh_state() -> str:
    shutil.rmtree(STATE, ignore_errors=True)
    STATE.mkdir(parents=True)
    (STATE / "token").write_text("net-rig")
    (STATE / "first-hello").write_text("")
    sys.path.insert(0, str(ROOT))
    import pair

    pair.STATE = STATE
    pair.setup("pointe.localtest.me", "127.0.0.1")
    return pair.pairing_link().replace(f"port={TLS_PORT}", f"port={SHAPER_PORT}")  # the app dials the shaper


async def run(simulator: str, profile: str, events: list[str]) -> dict:
    sys.path.insert(0, str(ROOT / "tests"))
    from netshaper import Shaper

    link = fresh_state()
    log = open(STATE / "rig-daemon.log", "w")
    daemon = subprocess.Popen([sys.executable, "-u", "-I", __file__, "--daemon"], stdout=log, stderr=subprocess.STDOUT,
                              env={**os.environ, "POINTE_NET_LOG": "INFO"})
    shaper = await Shaper(SHAPER_PORT, TLS_PORT, profile).start()
    hold = float(os.environ.get("POINTE_HOLD_SECS", "60"))
    lines = os.environ.get("POINTE_LINES", "3,20,40")
    subprocess.run(["xcrun", "simctl", "boot", simulator], capture_output=True)
    derived = Path(os.environ.get("POINTE_DERIVED_DATA", "/tmp/pointe-dd-net"))
    xctestrun = next((derived / "Build" / "Products").glob("*.xctestrun"))
    test = await asyncio.create_subprocess_exec(
        "xcodebuild", "test-without-building", "-xctestrun", str(xctestrun), "-destination", f"id={simulator}",
        "-only-testing:PointeUITests/BadNetworkUITests",
        env={**os.environ, "TEST_RUNNER_POINTE_PAIR": link, "TEST_RUNNER_POINTE_HOLD_SECS": str(hold),
             "TEST_RUNNER_POINTE_LINES": lines},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    output: list[str] = []
    call_up = asyncio.Event()

    async def read():
        async for raw in test.stdout:
            line = raw.decode(errors="replace").rstrip()
            output.append(line)
            if line.startswith("NETCALL up"):
                call_up.set()

    reader = asyncio.create_task(read())
    timeline = []

    async def events_after_call():
        await call_up.wait()
        t0 = time.monotonic()
        for step in sorted(events, key=lambda s: float(s.split(":", 1)[0])):
            at, what = step.split(":", 1)
            await asyncio.sleep(max(0.0, t0 + float(at) - time.monotonic()))
            if what.startswith("outage="):
                shaper.outage(float(what.split("=", 1)[1]))
            elif what == "switch":
                shaper.switch()
            elif what.startswith("profile="):
                shaper.set_profile(what.split("=", 1)[1])
            timeline.append((round(time.monotonic() - t0, 1), what))

    scheduler = asyncio.create_task(events_after_call())
    await test.wait()
    await reader
    scheduler.cancel()
    await shaper.stop()
    daemon.terminate()
    daemon.wait(timeout=20)
    log.close()
    return judge(output, (STATE / "rig-daemon.log").read_text(), shaper, profile, timeline)


def judge(output: list[str], daemon_log: str, shaper, profile: str, timeline: list) -> dict:
    text = "\n".join(output)
    trace_line = (re.findall(r"NETTRACE (.*)", text) or [""])[-1]
    trace = dict(re.findall(r"(\w+)=([-\d./]+)", trace_line))
    sent = [float(t) for t in trace.get("sent", "").split("/") if t]
    shown = [int(v) if v != "-" else None for v in trace.get("shown", "").split("/") if v]
    heard = {}
    for stamp, n in re.findall(r"^(\S+ \S+) \| INFO .*user said: 'status of the rollout part (\d+)'", daemon_log, re.M):
        heard.setdefault(int(n) - 1, datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S.%f").timestamp())
    said_twice = sum(len(re.findall(rf"user said: 'status of the rollout part {n + 1}'", daemon_log)) > 1 for n in range(len(sent)))
    end = (re.findall(r"NETEND (.*)", text) or [""])[-1]
    return {
        "profile": profile, "events": timeline,
        "ui_test": "passed" if "** TEST EXECUTE SUCCEEDED **" in text else "FAILED",
        "call_up_at_end": "up=true" in end, "ended_busy": "busy=true" in end,
        "calls_started": daemon_log.count("phone connected"),
        "resumed": daemon_log.count("came back to the call"),
        "typed_shown_ms": shown,
        "typed_taken_ms": [round((heard[n] - at) * 1000) if n in heard else None for n, at in enumerate(sent)],
        "typed_taken_twice": said_twice,
        "app_trace": {k: v for k, v in trace.items() if k not in ("sent", "shown")} or None,
        "shaper_connections": shaper.connections, "segments_lost": shaper.lost,
    }


if __name__ == "__main__":
    if sys.argv[1:] == ["--daemon"]:
        serve_daemon()
    else:
        result = asyncio.run(run(sys.argv[1], sys.argv[2], sys.argv[3:]))
        print(json.dumps(result), flush=True)
