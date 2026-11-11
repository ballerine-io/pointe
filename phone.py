"""The phone app's audio link: one WebSocket, so it crosses Tailscale, Twingate and tunnels without WebRTC's UDP setup.

Protocol, version 1:
- phone to daemon, binary: 16-bit little-endian mono PCM at 16 kHz, in chunks of about 20 ms.
- daemon to phone, binary: 16-bit little-endian mono PCM at 24 kHz.
- daemon to phone, text: {"type": "interrupt"} when the user cut the bot off. Drop all queued playback at once, or the
  bot keeps talking over the user from the phone's buffer.
Text from the phone is ignored in version 1; it mutes by not sending audio.

Version 2 adds a heartbeat, because a call can die silently (a VPN drops, the phone sleeps) and both ends keep showing
it as up:
- daemon to client, text, every 2 s: {"type": "ping", "id": n, "rtt_ms": last round trip or null}.
- client to daemon, text: {"type": "pong", "id": n}.
Version 3 adds a client hello, text, once after connecting: {"type": "hello", "protocol": 3, "device": "...",
"capabilities": [...]}. Unknown text is ignored both ways, so version 2 clients keep working.
A client that heard nothing for 6 s treats the call as dead and reconnects. The daemon closes a call (code 4408) that
has answered pings before and then stops answering for 12 s, so the line is free for the reconnect.
"""

import hmac
import json
import secrets
import time
from pathlib import Path

from pipecat.audio.utils import create_stream_resampler
from pipecat.frames.frames import Frame, InputAudioRawFrame, InterruptionFrame, OutputAudioRawFrame
from pipecat.serializers.base_serializer import FrameSerializer

PROTOCOL = 3
IN_RATE = 16000
OUT_RATE = 24000


PING_SECS = 2.0
DEAD_AFTER_SECS = 12.0


class Heartbeat:
    def __init__(self) -> None:
        self.sent: dict[int, float] = {}
        self.next_id = 0
        self.rtt_ms: int | None = None
        self.last_pong = 0.0  # 0 until the client answers once: an old client is never closed for silence

    def ping(self) -> str:
        self.next_id += 1
        self.sent[self.next_id] = time.monotonic()
        for old in [i for i in self.sent if i < self.next_id - 10]:
            del self.sent[old]
        return json.dumps({"type": "ping", "id": self.next_id, "rtt_ms": self.rtt_ms})

    def pong(self, ping_id: int) -> None:
        sent = self.sent.pop(ping_id, None)
        if sent is not None:
            self.rtt_ms = round((time.monotonic() - sent) * 1000)
        self.last_pong = time.monotonic()

    def dead(self) -> bool:
        return bool(self.last_pong) and time.monotonic() - self.last_pong > DEAD_AFTER_SECS


class PhoneSerializer(FrameSerializer):
    def __init__(self, heartbeat: Heartbeat | None = None) -> None:
        super().__init__()
        self._resampler = create_stream_resampler()
        self.heartbeat = heartbeat or Heartbeat()
        self.client: dict = {}

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, InterruptionFrame):
            return json.dumps({"type": "interrupt"})
        if isinstance(frame, OutputAudioRawFrame):
            if frame.sample_rate == OUT_RATE:
                return frame.audio
            return await self._resampler.resample(frame.audio, frame.sample_rate, OUT_RATE)
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, bytes) and data and len(data) % 2 == 0:
            return InputAudioRawFrame(audio=data, sample_rate=IN_RATE, num_channels=1)
        if isinstance(data, str):
            try:
                message = json.loads(data)
            except ValueError:
                return None
            if isinstance(message, dict) and message.get("type") == "pong" and isinstance(message.get("id"), int):
                self.heartbeat.pong(message["id"])
            elif isinstance(message, dict) and message.get("type") == "hello":  # protocol 3: who the client is
                self.client = {k: message.get(k) for k in ("protocol", "device", "capabilities") if k in message}
        return None


def phone_key(state_dir: Path) -> str:
    """The phone's own secret, given only through the pairing QR code. Separate from the page key, so either can be
    revoked by deleting its file."""
    path = state_dir / "phone_key"
    if not path.exists() or not path.read_text().strip():
        path.touch(mode=0o600)
        path.write_text(secrets.token_urlsafe(32))
    return path.read_text().strip()


def phone_allowed(state_dir: Path, authorization: str | None) -> bool:
    if not authorization or not authorization.startswith("Bearer "):
        return False
    return hmac.compare_digest(authorization[7:].encode(), phone_key(state_dir).encode())
