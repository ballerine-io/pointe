"""A stand-in for the Mac, for the app states a real daemon cannot be put in on cue: an older Pointe without meeting
routes, a Mac with no Soniox key, a Mac that stops answering in the middle of a meeting, and (voice) what the owner's
voice does on the Mac, step by step, with nothing tapped on the phone. It serves the paired certificate on the TLS port,
so the app's pinning accepts it. Made-up content only.

    python fake_mac.py <state dir> <port> old|nosoniox|meeting|voice [step file]
"""

import asyncio
import json
import ssl
import sys
import time
from pathlib import Path

from aiohttp import web

STATE, PORT, CASE = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
STEP = Path(sys.argv[4]) if len(sys.argv) > 4 else STATE / "fake-step"  # voice: the driver writes the step number here
SINCE = time.time() - 300
NOTES = [{"id": 1, "kind": "question", "at": SINCE + 60, "text": "Who owns the rollout checklist?", "state": "open",
          "meta": {"asked_by": "Speaker 2"}}]
VENDORS = {"room_audio": "soniox", "notes": "anthropic", "speech": "elevenlabs", "commands": "anthropic"}
CAUGHT_UP = STATE / "fake-caught-up"  # touched by the driver: a note added while the app could not reach the Mac


def current_notes() -> list:
    return NOTES + ([{"id": 2, "kind": "action", "at": time.time(), "text": "Send the rollout checklist", "state": "open",
                      "meta": {"owner": "Dana"}}] if CAUGHT_UP.exists() else [])


def _session(name: str, harness: str = "claude-code") -> dict:
    return {"name": name, "harness": harness, "working": False, "waiting": False, "needs": None}


# What the voice did on the Mac, one step at a time (tests/e2e/demo_voice_control.py and demo_meeting.py say it live):
# the app must show each step from the status alone.
RESULT = {"summary": "The billing webhooks failed during a retry storm; the limit stays at five for now.",
          "action_items": [{"what": "Raise the retry limit to eight attempts", "owner": "Sam", "due": "Friday"},
                           {"what": "Update the on-call runbook", "owner": "Dana", "due": ""}]}
READ_BACK = "Send 2 action items to billing: Raise the retry limit to eight attempts; Update the on-call runbook. Send them?"


def voice_status(base: dict) -> dict:
    step = int(STEP.read_text() or 0) if STEP.exists() else 0
    names = ["billing", "docs", "shop"] + (["shop-2"] if step == 2 else ["shop-tests"] if step in (3, 4, 5) else [])
    if step >= 5:
        names.remove("docs")
    out = {**base, "sessions": [_session(n, "codex" if n.startswith("shop-") else "claude-code") for n in names],
           "active": "billing" if step >= 4 else "shop", "mode": "session" if 4 <= step <= 6 else "orchestrator",
           "starting": [{"id": "s1", "name": "shop-2", "harness": "codex", "label": "Codex", "folder": "shop",
                         "state": "starting"}] if step == 1 else []}
    if step in (8, 9):
        out["meeting"] = {"on": True, "id": "m1", "mode": "participating" if step == 9 else "listening", "since": SINCE,
                          "owner_known": True, "speaking": False, "paused": False, "recording": True, "turns": 4,
                          "vendors": VENDORS, "sessions": [], "speakers": [{"label": "1", "is_owner": True, "turns": 2}]}
        out["notes"] = {"version": len(NOTES), "last_id": len(NOTES)}
    elif step >= 10:
        out["meeting"] = {"on": False, "ended": True, "result": RESULT,
                          "send_pending": {"session": "billing", "line": READ_BACK, "expires_in": 50} if step == 10 else None,
                          "sent_to": "billing" if step >= 11 else None}
    return out


def status() -> dict:
    base = {"connected": True, "mode": "orchestrator", "polish": False, "hearing": "", "talk": [],
            "sessions": [{"name": "pricing", "working": False, "waiting": False, "needs": None}]}
    if CASE == "voice":
        return voice_status(base)
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
