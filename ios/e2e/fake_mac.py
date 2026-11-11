"""A stand-in for the Mac, for the app states a real daemon cannot be put in on cue: an older Pointe without meeting
routes, a Mac with no Soniox key, and a Mac that stops answering in the middle of a meeting. It serves the paired
certificate on the TLS port, so the app's pinning accepts it. Made-up content only.

    python fake_mac.py <state dir> <port> old|nosoniox|meeting
"""

import asyncio
import json
import ssl
import sys
import time
from pathlib import Path

from aiohttp import web

STATE, PORT, CASE = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
SINCE = time.time() - 300
NOTES = [{"id": 1, "kind": "question", "at": SINCE + 60, "text": "Who owns the rollout checklist?", "state": "open",
          "meta": {"asked_by": "Speaker 2"}}]
VENDORS = {"room_audio": "soniox", "notes": "anthropic", "speech": "elevenlabs", "commands": "anthropic"}
CAUGHT_UP = STATE / "fake-caught-up"  # touched by the driver: a note added while the app could not reach the Mac


def current_notes() -> list:
    return NOTES + ([{"id": 2, "kind": "action", "at": time.time(), "text": "Send the rollout checklist", "state": "open",
                      "meta": {"owner": "Dana"}}] if CAUGHT_UP.exists() else [])


def status() -> dict:
    base = {"connected": True, "mode": "orchestrator", "polish": False, "hearing": "", "talk": [],
            "sessions": [{"name": "pricing", "working": False, "waiting": False, "needs": None}]}
    if CASE != "meeting":
        return base
    notes = current_notes()
    return {**base, "notes": {"version": len(notes), "last_id": len(notes)},
            "meeting": {"on": True, "mode": "listening", "since": SINCE, "owner_known": True, "speaking": False,
                        "paused": False, "recording": True, "turns": 12, "vendors": VENDORS, "sessions": [],
                        "speakers": [{"label": "1", "is_owner": True, "turns": 5}, {"label": "2", "turns": 7}]}}


async def handle(request: web.Request) -> web.Response:
    path = request.path
    if path == "/voice/status":
        return web.json_response(status())
    if CASE == "old":  # an older daemon: no meeting routes at all
        return web.json_response({"detail": "Not Found"}, status=404)
    if path == "/voice/meeting":
        body = json.loads(await request.text() or "{}")
        if body.get("action") == "vendors":
            return web.json_response({"vendors": VENDORS, "soniox": CASE != "nosoniox"})
        if body.get("action") == "start" and CASE == "nosoniox":
            return web.json_response({"detail": "Meeting mode needs a Soniox key: it is the only speech vendor that "
                                                "tells speakers apart live."}, status=409)
        return web.json_response({"ok": True})
    if path == "/voice/notes":
        return web.json_response({"version": len(current_notes()), "notes": current_notes()})
    if path == "/voice/prefs":
        return web.json_response({"meeting.default_mode": "listening", "meeting.auto_lookups": False,
                                  "meeting.notes_language": "auto", "meeting.consented": True})
    return web.json_response({"ok": True})


async def main() -> None:
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(STATE / "tls" / "cert.pem", STATE / "tls" / "key.pem")
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    for host in ("127.0.0.1", "::1"):
        await web.TCPSite(runner, host, PORT, ssl_context=context).start()
    print("fake mac up", flush=True)
    await asyncio.Event().wait()


asyncio.run(main())
