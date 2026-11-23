"""Settings → Phone on the page: connect the iPhone app without a terminal (docs/phone.md).

The page asks which routes reach this Mac (pair.routes), picks one, and gets a QR made here: the listener's name, its
certificate's fingerprint and a one-time code (pair.invite_pairing_link). The app trades the code for the phone key
with POST /voice/phone/pair over the listener it pins, so the QR holds no lasting secret. The code is single use, ends
after PHONE_INVITE_SECS, is kept only as a hash, and wrong guesses are bounded as for machines (hub_nodes.Invites).

Each pairing mints the phone its own key; phones.json keeps only its SHA-256. Unpair signs out that phone alone, at its
next request, and ends its call; Unpair all signs out every phone. The shared `phone_key` from before (and from
`pointe pair show`, which still prints the old link with that key, minting it again if it was unpaired) counts as one
more phone, so upgrading signs no one out.

The owner routes (/voice/phone/routes, /voice/phone/invite, /voice/phone/unpair) answer only the page on this Mac, by
its cookie: not the phone key, not the daemon token, not a page opened over the TLS listener.
"""

import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

import hub_nodes
import pair

PHONE_INVITE_SECS = 300
ONLINE_SECS = 10.0  # the app asks for the status every second or less while it is open
SEEN_WRITE_SECS = 60.0  # last seen reaches the disk at most this often; in memory it is exact
MAX_DEVICE_CHARS = 60
LEGACY = "legacy"  # the shared phone_key from before per-phone keys, and from `pointe pair show`
_UNPRINTABLE = re.compile(r"[\x00-\x1f\x7f]|\x1b\[[0-9;]*[A-Za-z]")


def _clean(text, most: int) -> str:
    return " ".join(_UNPRINTABLE.sub(" ", str(text or "")).split())[:most]


class Phones:
    """phones.json (0600): each paired phone's name, the SHA-256 of its own key, and when it paired and was last seen.
    Never a key. The `phone_key` file from before per-phone keys (and from `pointe pair show`) is one more phone,
    LEGACY, named "Paired phone" until the app reports its name, so the upgrade signs no one out."""

    def __init__(self, state_dir: Path, clock: Callable[[], float] = time.time):
        self.state_dir, self.path, self._clock = state_dir, state_dir / "phones.json", clock
        self._load()

    def _on_disk(self) -> tuple | None:
        try:
            st = self.path.stat()
        except OSError:
            return None
        return st.st_ino, st.st_mtime_ns, st.st_size

    def _load(self) -> None:
        self._read = self._on_disk()
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        self.paired: list[dict] = [p for p in data.get("paired") or []
                                   if isinstance(p, dict) and isinstance(p.get("hash"), str) and p.get("id")]
        self.legacy_name: str | None = data.get("legacy_name")
        self.seen: dict[str, float] = {k: v for k, v in (data.get("seen") or {}).items() if isinstance(v, (int, float))}
        self._written = max(self.seen.values(), default=0.0)

    def refresh(self) -> None:
        """phones.json changed under the daemon (`pointe pair rotate` or `off` deleted it): what it says now. Before every
        check and every change, so a signed-out phone is refused at once and a later save cannot bring it back."""
        if self._on_disk() != self._read:
            self._load()

    def _save(self) -> None:
        old = os.umask(0o077)
        try:
            self.path.write_text(json.dumps({"paired": self.paired, "legacy_name": self.legacy_name, "seen": self.seen}) + "\n")
        finally:
            os.umask(old)
        self.path.chmod(0o600)
        self._written = max(self.seen.values(), default=0.0)
        self._read = self._on_disk()

    def _legacy_key(self) -> str | None:
        try:
            return (self.state_dir / "phone_key").read_text().strip() or None
        except OSError:
            return None

    def allowed(self, authorization: str | None) -> str | None:
        """LocalAuth's phone check: which phone holds this key, or None. Every key is compared, each in constant time,
        with no early exit. Marks that phone seen."""
        self.refresh()
        if not authorization or not authorization.startswith("Bearer ") or not authorization[7:].strip():
            return None
        offered = authorization[7:]
        digest = hashlib.sha256(offered.encode()).digest()
        found = None
        for p in self.paired:
            if hmac.compare_digest(digest, bytes.fromhex(p["hash"])) and found is None:
                found = p["id"]
        legacy = self._legacy_key()
        if legacy is not None and hmac.compare_digest(offered.encode(), legacy.encode()) and found is None:
            found = LEGACY
        if found:
            now = self.seen[found] = self._clock()
            if now - self._written >= SEEN_WRITE_SECS:
                self._save()
        return found

    def mint(self, name: str, device_id: str, address: str) -> str:
        """A new phone's key, returned once. Pairing the same phone again (its id) replaces its entry and old key."""
        self.refresh()
        for p in [p for p in self.paired if device_id and p.get("device") == device_id]:
            self.seen.pop(p["id"], None)
        self.paired = [p for p in self.paired if not (device_id and p.get("device") == device_id)]
        key = secrets.token_urlsafe(32)
        self.paired.append({"id": secrets.token_hex(6), "name": name, "device": device_id, "paired_at": self._clock(),
                            "address": address, "hash": hashlib.sha256(key.encode()).hexdigest()})
        self._save()
        return key

    def report(self, phone_id: str | None, name: str | None) -> None:
        """The app said its name: names the legacy phone, once. A phone paired here keeps the name it paired with."""
        self.refresh()
        name = _clean(name, MAX_DEVICE_CHARS)
        if phone_id == LEGACY and name and not self.legacy_name:
            self.legacy_name = name
            self._save()

    def unpair(self, phone_id: str) -> bool:
        self.refresh()
        if phone_id == LEGACY:
            if self._legacy_key() is None:
                return False
            (self.state_dir / "phone_key").unlink(missing_ok=True)  # `pointe pair show` makes a new one when asked
            self.legacy_name = None
        elif not any(p["id"] == phone_id for p in self.paired):
            return False
        self.paired = [p for p in self.paired if p["id"] != phone_id]
        self.seen.pop(phone_id, None)
        self._save()
        return True

    def unpair_all(self) -> None:
        self.refresh()
        (self.state_dir / "phone_key").unlink(missing_ok=True)
        self.paired, self.legacy_name, self.seen = [], None, {}
        self._save()

    def holds(self, phone_id: str | None) -> bool:
        """Is this phone (an id `allowed` gave) still paired?"""
        self.refresh()
        if phone_id == LEGACY:
            return self._legacy_key() is not None
        return any(p["id"] == phone_id for p in self.paired)

    def status(self) -> dict:
        """For /voice/status: ids, names and times only."""
        self.refresh()
        now = self._clock()

        def entry(phone_id: str, name: str, paired_at, legacy: bool) -> dict:
            seen = self.seen.get(phone_id)
            return {"id": phone_id, "name": name, "paired_at": paired_at, "last_seen": seen, "legacy": legacy,
                    "online": bool(seen and now - seen < ONLINE_SECS)}

        out = [entry(p["id"], p.get("name") or "iPhone", p.get("paired_at"), False) for p in self.paired]
        if self._legacy_key() is not None:
            out.append(entry(LEGACY, self.legacy_name or "Paired phone", None, True))
        return {"paired": out}


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
        refused = invites.check(body.get("code", ""), address)  # the rate limit, then the code (hub_nodes.Invites)
        if refused:
            logger.warning(f"phone pairing from {address}: {refused[1]}")
            return refused
        invites.cancel()
        name = _clean(body.get("device"), MAX_DEVICE_CHARS) or "iPhone"
        key = self.phones.mint(name, _clean(body.get("id"), 80), address)
        invites.paired = {"name": name, "address": address, "at": time.time()}
        logger.info(f"phone paired: {name} from {address}")
        return 200, {"key": key, "mac": hub_nodes._here(self.state_dir)}


def _svg(link: str) -> str:
    import segno

    # omitsize: a viewBox and no fixed size, so the page's tile scales the whole code; with width/height attributes
    # the browser kept the 285 px drawing and clipped it to the 220 px box (two finder squares fell off the edge).
    return segno.make(link, error="m").svg_inline(scale=5, border=4, dark="#000", light="#fff", omitsize=True)


def install(app, link: PhoneLink, page_key: str, listener,
            on_unpair: Callable[[set[str] | None], Awaitable[None]] | None = None) -> None:
    """The routes. `listener` is remote.Remote (its restart serves a newly chosen route now); `on_unpair(ids)` ends the
    call of a phone just unpaired (None: every phone)."""
    from fastapi import Request
    from fastapi.responses import JSONResponse, PlainTextResponse

    from guards import LOCAL_COOKIE
    from remote import Remote

    refused = PlainTextResponse("forbidden", status_code=403)

    def the_page(request: Request) -> bool:
        """The page on this Mac and nothing else: LocalAuth has checked its headers; its cookie is checked here."""
        if Remote.on_tls_listener(request.scope) or request.scope.get("state", {}).get("pointe_phone"):
            return False
        if request.scope.get("state", {}).get("pointe_page"):  # the Mac app's proof, checked by LocalAuth (local_proof.py)
            return True
        return bool(page_key) and hmac.compare_digest(request.cookies.get(LOCAL_COOKIE, "").encode(), page_key.encode())

    async def body_of(request: Request) -> dict:
        try:
            body = await request.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    @app.post("/voice/phone/pair")
    async def phone_pair(request: Request):
        if not link.invites.outstanding:  # answered before a byte of the body is read
            return PlainTextResponse(link.redeem({}, "")[1], status_code=403)
        body = await hub_nodes.pairing_body(request)
        if body is None:
            return PlainTextResponse("too large", status_code=413)
        status, answer = link.redeem(body, request.client.host if request.client else "")
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
        """{"id": ...} signs out that phone only; {"all": true} every phone, the legacy key included."""
        if not the_page(request):
            return refused
        body = await body_of(request)
        if body.get("all"):
            link.invites.cancel()
            link.phones.unpair_all()
            ids = None
            logger.info("every phone unpaired from the page")
        else:
            phone_id = str(body.get("id") or "")
            if not link.phones.unpair(phone_id):
                return PlainTextResponse("no such phone is paired", status_code=404)
            ids = {phone_id}
            logger.info(f"phone {phone_id} unpaired from the page")
        if on_unpair:
            await on_unpair(ids)
        return {"ok": True}
