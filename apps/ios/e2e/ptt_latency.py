"""Push to talk, press to first frame, on the simulator: the real app and its real microphone, against a stand-in Mac that
runs the daemon's own gate (ptt.Ptt) on what arrives. PushToTalkLatencyUITests connects and holds the ring a few times;
the app's debug trace says, per press, how long the touch took to open the gate, when the first chunk left, and from when
its audio was captured; this side says when the press message and the first audio reached the Mac, and how much of the
press's audio the gate passed. No vendor, no key, no daemon: made-up content only.

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-ptt CLAUDE_VOICE_TLS_PORT=7571 \
     uv run --locked python -u -I apps/ios/e2e/ptt_latency.py <simulator id>
POINTE_DERIVED_DATA (default /tmp/pointe-dd) and DEVELOPMENT_TEAM go to xcodebuild.
"""

import asyncio
import json
import os
import re
import ssl
import subprocess
import sys
import time
from pathlib import Path

from aiohttp import WSMsgType, web

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
assert os.environ.get("CLAUDE_VOICE_STATE") and os.environ.get("CLAUDE_VOICE_TLS_PORT"), "isolated state and TLS port"
import pair  # noqa: E402
from ptt import Ptt  # noqa: E402

SIMULATOR = sys.argv[1]
STATE = Path(os.environ["CLAUDE_VOICE_STATE"])
PORT = int(os.environ["CLAUDE_VOICE_TLS_PORT"])
BYTES_PER_SEC = 16000 * 2
presses: list[dict] = []


def status() -> dict:
    return {"connected": True, "mode": "orchestrator", "polish": False, "hearing": "", "talk": [],
            "sessions": [{"name": "pricing", "working": False, "waiting": False, "needs": None}],
            "ptt": {"mode": "ptt", "open": False, "closed_why": ""}}


async def handle(request: web.Request) -> web.StreamResponse:
    if request.path == "/voice/phone":
        return await call(request)
    if request.path == "/voice/status":
        return web.json_response(status())
    if request.path == "/voice/prefs":
        return web.json_response({"microphone": "ptt", "turns.patience": "normal"})
    return web.json_response({"ok": True})


async def call(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    gate, press, n = Ptt(), None, 0

    async def ping() -> None:
        nonlocal n
        while not ws.closed:  # the app redials a link that says nothing for 6 s
            n += 1
            await ws.send_str(json.dumps({"type": "ping", "id": n, "rtt_ms": 1}))
            await asyncio.sleep(1)

    pinger = asyncio.create_task(ping())
    try:
        async for msg in ws:
            now = time.time()
            if msg.type == WSMsgType.TEXT:
                body = json.loads(msg.data)
                if body.get("type") == "ptt" and body.get("open") is True and gate.press(now):
                    press = {"open_at": now, "first_audio_at": None, "passed": 0, "dropped_before": gate.dropped_bytes}
                    presses.append(press)
                elif body.get("type") == "ptt" and body.get("open") is False:
                    gate.release(now)
            elif msg.type == WSMsgType.BINARY:
                ok = gate.audio(len(msg.data), "ptt", now)
                if press is not None and ok:
                    press["passed"] += len(msg.data)
                    press["first_audio_at"] = press["first_audio_at"] or now
    finally:
        pinger.cancel()
    return ws


async def serve() -> web.AppRunner:
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(STATE / "tls" / "cert.pem", STATE / "tls" / "key.pem")
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    for host in ("127.0.0.1", "::1"):
        await web.TCPSite(runner, host, PORT, ssl_context=context).start()
    return runner


async def main() -> None:
    pair.STATE = STATE
    pair.setup(os.environ.get("IOS_E2E_HOST", "pointe.localtest.me"), "127.0.0.1")  # a real name: see tests/e2e/ios_app.py
    link = pair.pairing_link()
    runner = await serve()
    subprocess.run(["xcrun", "simctl", "boot", SIMULATOR], capture_output=True)
    subprocess.run(["xcrun", "simctl", "privacy", SIMULATOR, "grant", "microphone", "io.ballerine.pointe"], capture_output=True)
    xcode = await asyncio.create_subprocess_exec(
        "xcodebuild", "-project", str(ROOT / "apps" / "ios" / "Pointe.xcodeproj"), "-scheme", "Pointe", "-destination", f"id={SIMULATOR}",
        "-derivedDataPath", os.environ.get("POINTE_DERIVED_DATA", "/tmp/pointe-dd"),
        "-only-testing:PointeUITests/PushToTalkLatencyUITests",
        *([f"DEVELOPMENT_TEAM={os.environ['DEVELOPMENT_TEAM']}"] if os.environ.get("DEVELOPMENT_TEAM") else []), "test",
        env={**os.environ, "TEST_RUNNER_POINTE_PAIR": link}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = (await xcode.communicate())[0].decode(errors="replace")
    await runner.cleanup()
    traces = re.findall(r"PTTTRACE (\d+) held_ms=(\d+) (.*)", out)
    print(f"xcodebuild exit {xcode.returncode}; {len(traces)} presses traced by the app, {len(presses)} seen by the Mac")
    for (i, held, trace), press in zip(traces, presses):
        first = press["first_audio_at"]
        gap = f"{(first - press['open_at']) * 1000:.0f} ms" if first else "never"
        print(f"press {i}: held {held} ms | app: {trace} | Mac: first audio {gap} after the press message, "
              f"{press['passed'] / BYTES_PER_SEC * 1000:.0f} ms of audio passed the gate")
    if xcode.returncode != 0:
        print(out[-3000:])
    sys.exit(0 if xcode.returncode == 0 and traces and len(presses) >= len(traces) else 1)


asyncio.run(main())
