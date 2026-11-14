"""Settings → Phone on the page: connect the iPhone app without a terminal (docs/phone.md).

The page asks which routes reach this Mac (pair.routes), picks one, and gets a QR made here: the listener's name, its
certificate's fingerprint and a one-time code (pair.invite_pairing_link). The app trades the code for the phone key
with POST /voice/phone/pair over the listener it pins, so the QR holds no lasting secret. The code is single use, ends
after PHONE_INVITE_SECS, is kept only as a hash, and wrong guesses are bounded as for machines (hub_nodes.Invites).

The key is pair.py's: one phone key for every phone (phone.phone_key). Connecting another phone keeps those already
paired; Unpair deletes the key, so every paired phone must connect again.

The owner routes (/voice/phone/routes, /voice/phone/invite, /voice/phone/unpair) answer only the page on this Mac, by
its cookie: not the phone key, not the daemon token, not a page opened over the TLS listener.
"""

import asyncio
import hmac
import json
import os
import re
import time
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

import hub_nodes
import pair
import phone

PHONE_INVITE_SECS = 300
ONLINE_SECS = 10.0  # the app asks for the status every second or less while it is open
SEEN_WRITE_SECS = 60.0  # last seen reaches the disk at most this often; in memory it is exact
MAX_DEVICE_CHARS = 60
_UNPRINTABLE = re.compile(r"[\x00-\x1f\x7f]|\x1b\[[0-9;]*[A-Za-z]")


def _clean(text, most: int) -> str:
    return " ".join(_UNPRINTABLE.sub(" ", str(text or "")).split())[:most]


class Phones:
    """phones.json (0600): who paired and when, and when the phone key was last used. Never the key."""

    def __init__(self, state_dir: Path, clock: Callable[[], float] = time.time):
        self.state_dir, self.path, self._clock = state_dir, state_dir / "phones.json", clock
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        self.paired: list[dict] = [p for p in data.get("paired") or [] if isinstance(p, dict)]
        self.last_seen: float | None = data.get("last_seen")
        self._written = self.last_seen or 0.0

    def _save(self) -> None:
        old = os.umask(0o077)
        try:
            self.path.write_text(json.dumps({"paired": self.paired, "last_seen": self.last_seen}) + "\n")
        finally:
            os.umask(old)
        self.path.chmod(0o600)
        self._written = self.last_seen or 0.0

    def allowed(self, authorization: str | None) -> bool:
        """LocalAuth's phone check, which also marks the phone seen."""
        if not phone.phone_allowed(self.state_dir, authorization):
            return False
        self.last_seen = self._clock()
        if self.last_seen - self._written >= SEEN_WRITE_SECS:
            self._save()
        return True

    def add(self, name: str, device_id: str, address: str) -> None:
        """Pairing the same phone again (its id) replaces its entry."""
        self.paired = [p for p in self.paired if not (device_id and p.get("id") == device_id)]
        self.paired.append({"name": name, "id": device_id, "paired_at": self._clock(), "address": address})
        self._save()

    def unpair(self) -> None:
        (self.state_dir / "phone_key").unlink(missing_ok=True)  # phone.phone_key makes a new one when next asked
        self.paired, self.last_seen = [], None
        self._save()

    def status(self) -> dict:
        """For /voice/status: names and times only."""
        seen = self.last_seen
        return {"paired": [{"name": p.get("name") or "iPhone", "paired_at": p.get("paired_at")} for p in self.paired],
                "last_seen": seen, "online": bool(seen and self._clock() - seen < ONLINE_SECS)}


class PhoneLink:
    """The one-time code and its redemption."""

    def __init__(self, state_dir: Path, phones: Phones, monotonic: Callable[[], float] = time.monotonic):
        self.state_dir, self.phones = state_dir, phones
        self.invites = hub_nodes.Invites(monotonic, secs=PHONE_INVITE_SECS)

    def redeem(self, body, address: str) -> tuple[int, dict | str]:
        """POST /voice/phone/pair: (status, the phone key and this Mac's name, or why not)."""
        invites = self.invites
        if invites.code is None:
            return 403, "no invite outstanding"
        if not invites.outstanding:
            return 403, "invite expired"
        body = body if isinstance(body, dict) else {}
        if not invites.matches(body.get("code", "")):  # the right code pairs whatever the rate limit says (hub_nodes)
            logger.warning(f"phone pairing from {address}: wrong code")
            ended = invites.refuse(address)
            if ended:
                logger.warning(ended)
                return 403, ended
            return (403, "wrong code") if invites.admit(address) else (429, "too many attempts: wait a minute")
        invites.cancel()
        name = _clean(body.get("device"), MAX_DEVICE_CHARS) or "iPhone"
        self.phones.add(name, _clean(body.get("id"), 80), address)
        invites.paired = {"name": name, "address": address, "at": time.time()}
        logger.info(f"phone paired: {name} from {address}")
        return 200, {"key": phone.phone_key(self.state_dir), "mac": hub_nodes._here(self.state_dir)}


def _svg(link: str) -> str:
    import segno

    return segno.make(link, error="m").svg_inline(scale=5, border=4, dark="#000", light="#fff")


def install(app, link: PhoneLink, page_key: str, listener, on_unpair: Callable[[], Awaitable[None]] | None = None) -> None:
    """The routes. `listener` is remote.Remote (its restart serves a newly chosen route now); `on_unpair` ends a phone
    call that is up."""
    from fastapi import Request
    from fastapi.responses import JSONResponse, PlainTextResponse

    from guards import LOCAL_COOKIE
    from remote import Remote

    refused = PlainTextResponse("forbidden", status_code=403)

    def the_page(request: Request) -> bool:
        """The page on this Mac and nothing else: LocalAuth has checked its headers; its cookie is checked here."""
        if Remote.on_tls_listener(request.scope) or request.scope.get("state", {}).get("pointe_phone"):
            return False
        return bool(page_key) and hmac.compare_digest(request.cookies.get(LOCAL_COOKIE, "").encode(), page_key.encode())

    async def body_of(request: Request) -> dict:
        try:
            body = await request.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    @app.post("/voice/phone/pair")
    async def phone_pair(request: Request):
        status, answer = link.redeem(await body_of(request), request.client.host if request.client else "")
        return JSONResponse(answer) if status == 200 else PlainTextResponse(answer, status_code=status)

    @app.get("/voice/phone/routes")
    async def phone_routes(request: Request, host: str | None = None):
        if not the_page(request):
            return refused
        return await asyncio.to_thread(pair.routes, host)

    @app.post("/voice/phone/invite")
    async def phone_invite(request: Request):
        """{"kind": "tailscale"|"wifi"|"host", "host": name for host} sets that route up if it is not the one now, and
        makes a code (replacing any other); {"cancel": true} ends it."""
        if not the_page(request):
            return refused
        body = await body_of(request)
        if body.get("cancel"):
            link.invites.cancel()
            return {"ok": True}
        kind, typed = str(body.get("kind") or ""), str(body.get("host") or "").strip().lower() or None
        found = await asyncio.to_thread(pair.routes, typed if kind == "host" else None)
        route = next((r for r in found["routes"] if r["kind"] == kind and (kind != "host" or r["host"] == typed)), None)
        if route is None:
            return PlainTextResponse("no such route", status_code=409)
        if not route["usable"]:
            return PlainTextResponse(route["problem"] or "that route does not reach this Mac", status_code=409)
        if not route["current"]:
            await asyncio.to_thread(pair.setup, route["host"], route["listen"])
            problem = await listener.restart()
            if problem:
                return PlainTextResponse(problem, status_code=409)
            logger.info(f"phone route set from the page: {route['kind']} {route['host']}")
        code = link.invites.make()
        line = pair.invite_pairing_link(code)
        return {"code": code, "link": line, "svg": _svg(line), "expires_in": PHONE_INVITE_SECS,
                "host": route["host"], "kind": route["kind"]}

    @app.get("/voice/phone/invite")
    async def phone_invite_status(request: Request):
        """While the QR shows: how long it has, and who paired. Never the code: the page has it from the make."""
        if not the_page(request):
            return refused
        st = link.invites.status()
        return {"expires_in": st["expires_in"] if st else 0, "wrong_codes": st["wrong_codes"] if st else 0,
                "paired": link.invites.paired, "ended": link.invites.ended}

    @app.post("/voice/phone/unpair")
    async def phone_unpair(request: Request):
        if not the_page(request):
            return refused
        link.invites.cancel()
        link.phones.unpair()
        logger.info("phones unpaired from the page: the phone key is deleted")
        if on_unpair:
            await on_unpair()
        return {"ok": True}
