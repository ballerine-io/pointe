"""Reaching Pointe from a phone through a private network (Twingate), without opening it to the LAN.

A second, HTTPS-only listener on 127.0.0.1 serves the same app; a network connector on this machine
forwards to it. A Host header is easy to forge, so a remote browser also needs a pairing cookie,
set once from a link that carries this machine's pairing secret. Localhost access is unchanged.
"""

import asyncio
import os
import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import PlainTextResponse, RedirectResponse

from guards import is_local_request

TLS_PORT = int(os.environ.get("CLAUDE_VOICE_TLS_PORT", "7443"))  # a second daemon (tests) needs its own
COOKIE = "pointe_pair"


class Remote:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        config = state_dir / "remote.json"
        settings = json.loads(config.read_text()) if config.exists() else {}
        self.host = settings["host"].lower() if settings.get("host") else None
        # 127.0.0.1 for a connector on this machine (Twingate, cloudflared); a Tailscale or Wi-Fi address from `pointe pair`
        self.listen = settings.get("listen") or ["127.0.0.1"]
        token = state_dir / "remote_token"
        self.token = token.read_text().strip() if token.exists() else None
        self.cert, self.key = state_dir / "tls" / "cert.pem", state_dir / "tls" / "key.pem"

    @property
    def enabled(self) -> bool:
        return bool(self.host and self.token and self.cert.exists() and self.key.exists())

    def _remote_request(self, request: Request) -> bool:
        """Over HTTPS, addressed to the configured name, and from a page of that name if from a page."""
        if not self.enabled:
            return False
        if (urlparse(f"//{request.headers.get('host', '')}").hostname or "").lower() != self.host:
            return False
        origin = request.headers.get("origin")
        return origin is None or (urlparse(origin).hostname or "").lower() == self.host

    @property
    def app_key(self) -> str:
        """For the Home Screen app's saved address: derived, so the pairing secret itself never sits in a URL."""
        return hmac.new(self.token.encode(), b"pointe home screen app", hashlib.sha256).hexdigest()[:32]

    def _set_cookie(self, response) -> None:
        response.set_cookie(COOKIE, self.token, max_age=365 * 86400, secure=True, httponly=True, samesite="strict")

    def _paired(self, request: Request) -> bool:
        return hmac.compare_digest(request.cookies.get(COOKIE, "").encode(), self.token.encode())

    @staticmethod
    def on_tls_listener(scope) -> bool:
        """By the port that accepted the connection. A Host or X-Forwarded-Proto header is the caller's to forge."""
        return (scope.get("server") or (None, 0))[1] == TLS_PORT

    def websocket_allowed(self, connection) -> bool:
        origin = connection.headers.get("origin")
        return (self.enabled and hmac.compare_digest(connection.cookies.get(COOKIE, "").encode(), self.token.encode())
                and (origin is None or (urlparse(origin).hostname or "").lower() == self.host))

    async def guard(self, request: Request, call_next):
        state = request.scope.get("state", {})
        if state.get("pointe_phone") or state.get("pointe_node"):  # LocalAuth passed the phone key, or a node route
            return await call_next(request)
        if not self.on_tls_listener(request.scope):
            return await call_next(request) if is_local_request(request) else PlainTextResponse("forbidden", status_code=403)
        if not self._remote_request(request):
            return PlainTextResponse("forbidden", status_code=403)
        offered = request.query_params.get("pair")
        if offered is not None and request.url.path == "/voice":
            if not hmac.compare_digest(offered.encode(), self.token.encode()):
                return PlainTextResponse("forbidden", status_code=403)
            # Land on an address that carries the app key: "Add to Home Screen" saves the current address, and a
            # Home Screen app may not share Safari's cookies.
            response = RedirectResponse(f"/voice?k={self.app_key}", status_code=303)
            self._set_cookie(response)
            return response
        app_key = request.query_params.get("k")
        if app_key is not None and request.url.path == "/voice":
            if not hmac.compare_digest(app_key.encode(), self.app_key.encode()):
                return PlainTextResponse("forbidden", status_code=403)
            response = await call_next(request)
            self._set_cookie(response)
            return response
        if not self._paired(request):
            return PlainTextResponse("not paired: open the pairing link from `pointe pair link` once",
                                     status_code=403)
        return await call_next(request)

    async def serve(self, app) -> None:
        """The HTTPS listener: loopback for a connector on this machine, or the private address `pointe pair` chose."""
        if not self.enabled:
            return
        import contextlib

        import uvicorn

        class Quiet(uvicorn.Server):
            def capture_signals(self):  # the main server owns Ctrl-C and SIGTERM
                return contextlib.nullcontext()

        # lifespan off: the main server already ran the app's startup, and running it again would recurse here
        servers = [Quiet(uvicorn.Config(app, host=address, port=TLS_PORT, log_level="warning", lifespan="off",
                                        proxy_headers=False, ssl_certfile=str(self.cert), ssl_keyfile=str(self.key)))
                   for address in self.listen]
        await asyncio.gather(*(server.serve() for server in servers))


def install(remote: Remote, app) -> None:
    """Guard every request, and run the HTTPS listener for the life of the main server."""
    from contextlib import asynccontextmanager

    app.middleware("http")(remote.guard)

    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(remote.serve(app)) if remote.enabled else None
        try:
            async with previous(_app):
                yield
        finally:
            if task:
                task.cancel()

    app.router.lifespan_context = lifespan  # the runner later combines its own lifespan with this one
