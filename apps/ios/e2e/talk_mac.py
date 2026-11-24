"""A stand-in for the Mac, for "Talk to Pointe" from outside the app: it serves a status in Session mode with two
sessions that need you, the microphone set to push to talk, and a call socket that pings; and it prints what the phone
did, one line each, for the driver (talk_outside_ui.py) to check: `mode <body>`, `ptt open|closed`, `hung-up`,
`approve <body>`, `phone connected`, `phone closed`. Serves the paired certificate on the TLS port, so the app's pinning
accepts it. Made-up content only.

    python talk_mac.py <state dir> <port> <seconds>
"""

import asyncio
import builtins
import json
import ssl
import sys
import time
from pathlib import Path

from aiohttp import WSMsgType, web

STATE, PORT, SECS = Path(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])
MODE = ["session"]


def print(line: str, **kw) -> None:  # every line carries when, for the driver's timings
    builtins.print(f"{line} @{time.time():.3f}", **kw)

PRESS = {"open": False}
PHONE = {"up": False}


def status() -> dict:
    sessions = [{"name": "billing", "working": True, "waiting": False, "needs": None},
                {"name": "docs", "working": False, "waiting": True, "needs": None, "request_id": "r1",
                 "request": "Bash: rm -rf build"},
                {"name": "shop", "working": False, "waiting": False, "needs": "a decision on the rollout"}]
    return {"connected": PHONE["up"], "mode": MODE[0], "active": "billing", "polish": False, "hearing": "", "talk": [],
            "sessions": sessions, "voice_lock": {"level": "off"},
            "machines": [{"id": "hub", "name": "studio", "here": True, "os": "macos", "online": True, "sessions": 3, "need": 2}],
            "ptt": {"mode": "ptt", "open": PRESS["open"], "closed_why": "released"}}


def authorized(request: web.Request) -> bool:
    return request.headers.get("Authorization") == f"Bearer {(STATE / 'phone_key').read_text().strip()}"


async def phone(request: web.Request) -> web.WebSocketResponse:
    if not authorized(request):
        raise web.HTTPForbidden()
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    PHONE["up"] = True
    print("phone connected", flush=True)

    async def pings() -> None:
        n = 0
        while not ws.closed:
            n += 1
            await ws.send_str(json.dumps({"type": "ping", "id": n, "rtt_ms": 20}))
            await asyncio.sleep(2)

    task = asyncio.create_task(pings())
    async for message in ws:
        if message.type == WSMsgType.TEXT:
            body = json.loads(message.data)
            if body.get("type") == "ptt":
                PRESS["open"] = bool(body.get("open"))
                print(f"ptt {'open' if PRESS['open'] else 'closed'}", flush=True)
    task.cancel()
    PRESS["open"] = False  # the daemon drops a press whose call ended before its release
    PHONE["up"] = False
    print("phone closed", flush=True)
    return ws


async def handle(request: web.Request) -> web.Response:
    if not authorized(request):
        raise web.HTTPForbidden()
    if request.path == "/voice/status":
        print("status", flush=True)
        return web.json_response(status())
    if request.path == "/voice/prefs":
        return web.json_response({"microphone": "ptt"})
    body = await request.text()
    if request.path == "/voice/mode":
        MODE[0] = json.loads(body).get("mode", MODE[0])
        print(f"mode {body}", flush=True)
    elif request.path == "/voice/hung-up":
        print("hung-up", flush=True)
    elif request.path == "/voice/approve":
        print(f"approve {body}", flush=True)
    return web.json_response({"ok": True})


async def main() -> None:
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(STATE / "tls" / "cert.pem", STATE / "tls" / "key.pem")
    app = web.Application()
    app.router.add_get("/voice/phone", phone)
    app.router.add_route("*", "/{tail:.*}", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    for host in ("127.0.0.1", "::1"):
        await web.TCPSite(runner, host, PORT, ssl_context=context).start()
    print("talk mac up", flush=True)
    started = time.monotonic()
    while time.monotonic() - started < SECS:
        await asyncio.sleep(0.5)


asyncio.run(main())
