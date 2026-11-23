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
        self._app, self._task, self._servers = None, None, []
        self._restarting: asyncio.Lock | None = None
        self.load()

    def load(self) -> None:
        """Read remote.json, remote_token and the certificate: at start, and when Settings → Phone picks a route."""
        state_dir = self.state_dir
        self._seen = self._on_disk()  # before reading: a change while it reads shows as a change next time
        config = state_dir / "remote.json"
        settings = json.loads(config.read_text()) if config.exists() else {}
        self.host = settings["host"].lower() if settings.get("host") else None
        # 127.0.0.1 for a connector on this machine (Twingate, cloudflared); a Tailscale or Wi-Fi address from `pointe pair`
        self.listen = settings.get("listen") or ["127.0.0.1"]
        token = state_dir / "remote_token"
        self.token = token.read_text().strip() if token.exists() else None
        self.cert, self.key = state_dir / "tls" / "cert.pem", state_dir / "tls" / "key.pem"

    def _on_disk(self) -> list:
        found = []
        for path in (self.state_dir / "remote.json", self.state_dir / "remote_token",
                     self.state_dir / "tls" / "cert.pem", self.state_dir / "tls" / "key.pem"):
            try:
                st = path.stat()
                found.append((st.st_ino, st.st_mtime_ns, st.st_size))
            except OSError:
                found.append(None)
        return found

    def changed(self) -> bool:
        """The route, the pairing secret or the certificate changed since load(): `pointe pair` ran in a terminal."""
        return self._on_disk() != self._seen

    @property
    def enabled(self) -> bool:
        return bool(self.host and self.token and self.cert.exists() and self.key.exists())

    def _remote_request(self, request: Request) -> bool:
        """Over HTTPS, addressed to the configured name, and from a page of that name if from a page."""
        if not self.enabled:
            return False
        if (urlparse(f"//{request.headers.get('host', '')}").hostname or "").lower() != self.host:
            return False
        return self._own_origin(request.headers.get("origin"))

    def _own_origin(self, origin: str | None) -> bool:
        """No Origin (the app, a script), or exactly this listener's: scheme, name and port. Cookies and SameSite ignore
        ports, so a page on another port of this name (a dev server, `tailscale serve`) is same-site and gets the
        pairing cookie; WebSockets have no same-origin rule, so this compare is all that keeps such a page out."""
        if origin is None:
            return True
        own = {f"https://{self.host}:{TLS_PORT}"} | ({f"https://{self.host}"} if TLS_PORT == 443 else set())
        return origin.lower() in own

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
                and self._own_origin(origin))

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

    async def serve(self, app, fatal: bool = True) -> None:
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
        self._servers = servers

        async def one(server) -> None:
            try:
                await server.serve()
            except SystemExit:  # uvicorn exits when it cannot bind: at start that ends the daemon, as it always did
                if fatal:
                    raise

        await asyncio.gather(*(one(server) for server in servers))

    def start(self, app, fatal: bool = True) -> None:
        """`fatal`: a listener that cannot start ends the daemon (at start), or only itself (a restart says why)."""
        self._app = app
        self._task = asyncio.create_task(self.serve(app) if fatal else self.serve(app, False)) if self.enabled else None

    async def stop(self) -> None:
        """Close the sockets, not just the task: a cancelled uvicorn server keeps its port bound."""
        for server in self._servers:
            server.should_exit = True
        if self._task:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), 5)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                self._task.cancel()
        self._task, self._servers = None, []

    async def restart(self, only_if_changed: bool = False) -> str | None:
        """Serve what remote.json says now, without a daemon restart. None once every address listens, else why not.
        One at a time: the page choosing a route and the daemon following `pointe pair` must not both bind the port."""
        self._restarting = self._restarting or asyncio.Lock()
        async with self._restarting:
            if only_if_changed and not self.changed():
                return None
            return await self._restart()

    async def _restart(self) -> str | None:
        await self.stop()
        self.load()
        if self._app is None or not self.enabled:
            return None if self._app is None else "the listener is not set up"
        self.start(self._app, fatal=False)
        for _ in range(50):
            if self._task.done():
                break
            if self._servers and all(server.started for server in self._servers):
                return None
            await asyncio.sleep(0.1)
        await self.stop()
        return f"could not listen on {', '.join(self.listen)} port {TLS_PORT} (is another program using it?)"


def install(remote: Remote, app) -> None:
    """Guard every request, and run the HTTPS listener for the life of the main server."""
    from contextlib import asynccontextmanager

    app.middleware("http")(remote.guard)

    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(_app):
        remote.start(app)
        try:
            async with previous(_app):
                yield
        finally:
            if remote._task:
                remote._task.cancel()

    app.router.lifespan_context = lifespan  # the runner later combines its own lifespan with this one
