"""The call's link to the page or the phone: one object for the whole call, over one client socket at a time.

Pipecat's WebSocket transport holds this in place of the socket (it uses receive, send_bytes, send_text, close and the
states). Under it a socket can drop and another take its place (phone.py, protocol 5):

- A link that drops without a hang-up holds the call GRACE_SECS for the client to come back with the call's token. The
  pipeline, the conversation and the press go on; a short outage is bridged and nothing is said again.
- Sending never waits on the network: the pipeline puts the bot's audio in a short queue and goes on, and one writer
  per socket drains it. A slow reader stalls only its writer. Audio that would play late is dropped, not queued: the
  queue keeps QUEUE_SECS, and while the client is behind (phone.Heartbeat.lagging) new audio is not sent at all.
- Text (pings, an interrupt, a press from the Mac) goes before queued audio, and an interrupt drops the queued audio:
  it reaches the client without waiting behind audio it would only throw away.
"""

import asyncio
import hmac
import json
import secrets
import time

from loguru import logger
from starlette.websockets import WebSocketState

import phone

GRACE_SECS = 30.0  # a Wi-Fi to cellular switch through a VPN can take this long; the call waits for the client
QUEUE_SECS = 0.5  # bot audio queued for the writer beyond this is dropped, oldest first
HELLO_SECS = 3.0  # a second socket while a call is up has this long to say whose call it is coming back to
HANG_UP = 1000

_DISCONNECT = {"type": "websocket.disconnect", "code": HANG_UP}


class CallLink:
    def __init__(self, socket, who: str, heartbeat: phone.Heartbeat, serializer: phone.PhoneSerializer,
                 phone_id: str | None = None, grace: float | None = None) -> None:
        self.who, self.phone_id = who, phone_id
        self.heartbeat, self.serializer = heartbeat, serializer
        self.grace = GRACE_SECS if grace is None else grace
        self.token = secrets.token_urlsafe(18)
        self.headers = getattr(socket, "headers", {})
        self.scope = getattr(socket, "scope", {})
        self.socket = None
        self.ended = False
        self.resumable = False  # the client's hello listed "resume": until then a drop ends the call, as before
        self.duckable = False  # the client's hello listed "duck": it lowers its own playback when told (daemon._duck_voice)
        self.stats = {"sockets": 0, "resumes": 0, "shed_bytes": 0, "dropped_bytes": 0, "outages": 0}
        self._inbox: asyncio.Queue = asyncio.Queue()
        self._text: list[str] = []
        self._audio: list[bytes] = []
        self._audio_bytes = 0
        self._wake = asyncio.Event()
        self._writer: asyncio.Task | None = None
        self._pump: asyncio.Task | None = None
        self._released: dict[int, asyncio.Event] = {}  # per socket: set once it no longer carries the call
        self._lost_at = 0.0
        self._attach(socket)

    # ---------- what pipecat sees ----------

    @property
    def client_state(self) -> WebSocketState:
        return WebSocketState.DISCONNECTED if self.ended else WebSocketState.CONNECTED

    application_state = client_state

    async def receive(self) -> dict:
        """The client's next message, from whichever socket carries the call; a disconnect only when the call ends."""
        while True:
            if self.ended:
                return _DISCONNECT
            wait = None
            if self.socket is None:
                wait = self._lost_at + self.grace - time.monotonic()
                if wait <= 0:
                    self._end(f"nobody came back within {self.grace:.0f} s")
                    return _DISCONNECT
            try:
                socket, message = await asyncio.wait_for(self._inbox.get(), wait)
            except asyncio.TimeoutError:
                continue
            if self.ended:
                return _DISCONNECT
            if message is None or socket is not self.socket:
                continue  # a wake-up, or the last words of a socket the call already left
            if message.get("type") == "websocket.disconnect":
                code = message.get("code") or 1006
                if code == HANG_UP or code == 4401 or not self.resumable:
                    self._end(f"the {self.who} closed the link ({code})")
                    return _DISCONNECT
                self.lost(socket, f"closed {code}")
                continue
            if message.get("type") == "websocket.receive":
                if message.get("text"):
                    self._hello(message["text"])
                return message

    async def send_bytes(self, data: bytes) -> None:
        if self.ended or self.socket is None:
            self.stats["dropped_bytes"] += len(data)
            return
        if self.heartbeat.lagging():
            self.stats["shed_bytes"] += len(data)
            return
        self._audio.append(data)
        self._audio_bytes += len(data)
        limit = QUEUE_SECS * self._bytes_per_sec()
        while self._audio_bytes > limit and len(self._audio) > 1:
            old = self._audio.pop(0)
            self._audio_bytes -= len(old)
            self.stats["dropped_bytes"] += len(old)
        self._wake.set()

    async def send_text(self, text: str) -> None:
        if self.ended or self.socket is None:
            return
        if text.startswith('{"type": "interrupt"'):
            self._clear_audio()  # the client drops its own buffer on this; what waits here is the same stale speech
        self._text.append(text)
        self._wake.set()

    async def close(self, code: int = HANG_UP, reason: str | None = None) -> None:
        """The call ends here (the pipeline stopped, the phone was unpaired): no grace, no resume."""
        socket = self.socket
        self._end(f"closed by the Mac ({code})")
        if socket is not None:
            await _close(socket, code, reason or "")

    # ---------- sockets ----------

    def takes(self, token: object, who: str, phone_id: str | None) -> bool:
        """A new socket may take this call over: the same kind of client, the same phone, and the call's own token."""
        return (not self.ended and isinstance(token, str) and who == self.who and phone_id == self.phone_id
                and hmac.compare_digest(token.encode(), self.token.encode()))

    async def resume(self, socket, hello: str) -> None:
        """A socket that came back for this call: it carries it from now on, until it drops or another takes over.
        Returns once it no longer does, since the ASGI handler that owns it must stay up while it is in use."""
        self.stats["resumes"] += 1
        away = time.monotonic() - self._lost_at if self.socket is None and self._lost_at else 0.0
        logger.info(f"{self.who} came back to the call" + (f" after {away:.1f} s" if away else ", replacing its link"))
        released = self._attach(socket)
        self._hello(hello, resumed=True)
        await released.wait()

    def lost(self, socket, why: str) -> None:
        """This socket stopped carrying the call: it is closed, and the call waits for the client to come back."""
        if socket is not self.socket:
            return
        self._detach()
        if not self.resumable:
            self._end(f"the {self.who}'s link dropped ({why})")
        else:
            self._lost_at = time.monotonic()
            self.stats["outages"] += 1
            logger.warning(f"{self.who}'s link dropped ({why}): holding the call {self.grace:.0f} s for it to come back")
            self._inbox.put_nowait((None, None))  # receive() starts counting the grace now
        asyncio.ensure_future(_close(socket, 4408 if "ping" in why else 1001, why[:100]))

    def _attach(self, socket) -> asyncio.Event:
        old = self.socket
        if old is not None:
            self._detach()
            asyncio.ensure_future(_close(old, 4410, "the call went on another link"))
        self.socket = socket
        self.stats["sockets"] += 1
        self.serializer.up = phone.PCM16  # a new socket starts in PCM until the client says otherwise
        self.heartbeat.attached()
        released = self._released.setdefault(id(socket), asyncio.Event())
        self._pump = asyncio.ensure_future(self._read(socket))
        self._writer = asyncio.ensure_future(self._write(socket))
        return released

    def _detach(self) -> None:
        socket, self.socket = self.socket, None
        self._clear_audio()
        self._text.clear()
        for task in (self._pump, self._writer):
            if task is not None and task is not asyncio.current_task():
                task.cancel()
        self._pump = self._writer = None
        if socket is not None and (event := self._released.pop(id(socket), None)):
            event.set()

    def _end(self, why: str) -> None:
        if self.ended:
            return
        logger.info(f"call link ends: {why}")
        self._detach()
        self.ended = True
        self._inbox.put_nowait((None, None))
        for event in self._released.values():
            event.set()
        self._released.clear()

    async def _read(self, socket) -> None:
        try:
            while True:
                message = await socket.receive()
                self._inbox.put_nowait((socket, message))
                if message.get("type") == "websocket.disconnect":
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            self._inbox.put_nowait((socket, {"type": "websocket.disconnect", "code": 1006}))

    async def _write(self, socket) -> None:
        """One per socket, so a send stuck on a link that died never holds up the socket that replaced it."""
        try:
            while self.socket is socket:
                await self._wake.wait()
                self._wake.clear()
                while self.socket is socket and (self._text or self._audio):
                    if self._text:
                        await socket.send_text(self._text.pop(0))
                    else:
                        chunk = self._audio.pop(0)
                        self._audio_bytes -= len(chunk)
                        await socket.send_bytes(chunk)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.lost(socket, f"a send failed: {type(e).__name__}")

    # ---------- the call message ----------

    def _hello(self, text: str, resumed: bool = False) -> None:
        """The client said who it is: answer with the call's token and codec (protocol 5). An older client lists
        neither and gets the answer too, which it ignores as unknown text."""
        try:
            hello = json.loads(text)
        except ValueError:
            return
        if not isinstance(hello, dict) or hello.get("type") != "hello":
            return
        capabilities = hello.get("capabilities") if isinstance(hello.get("capabilities"), list) else []
        self.resumable = "resume" in capabilities
        self.duckable = "duck" in capabilities
        codec = phone.ADPCM if "adpcm" in capabilities else phone.PCM16
        if codec != self.serializer.down:
            self._clear_audio()  # queued in the old codec: the client reads what follows the answer in the new one
            self.serializer.down = codec
        self._text.append(json.dumps({"type": "call", "resume": self.token, "resumed": resumed, "codec": codec,
                                      "grace": self.grace if self.resumable else 0}))
        self._wake.set()

    def _clear_audio(self) -> None:
        self._audio.clear()
        self._audio_bytes = 0

    def _bytes_per_sec(self) -> float:
        return phone.OUT_RATE * (0.5 if self.serializer.down == phone.ADPCM else 2)


async def first_hello(socket) -> str | None:
    """A second socket while a call is up: its first message, if it is a hello, within HELLO_SECS."""
    try:
        message = await asyncio.wait_for(socket.receive(), HELLO_SECS)
    except (asyncio.TimeoutError, Exception):
        return None
    text = message.get("text") if isinstance(message, dict) else None
    try:
        return text if text and json.loads(text).get("type") == "hello" else None
    except (ValueError, AttributeError):
        return None


def resume_token(hello: str | None) -> str | None:
    try:
        token = json.loads(hello or "").get("resume")
    except (ValueError, AttributeError):
        return None
    return token if isinstance(token, str) else None


async def _close(socket, code: int, reason: str) -> None:
    try:
        await asyncio.wait_for(socket.close(code=code, reason=reason), 2)
    except Exception:  # already closed, or a peer that is gone
        pass
