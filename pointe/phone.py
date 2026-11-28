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
"capabilities": [...]}, and push to talk: {"type": "ptt", "open": true|false} when a press opens or closes the
microphone (ptt.py; the daemon's gate is the rule, whatever the client sends). The same message goes daemon to client,
with "by": "shortcut", when a system-wide shortcut on the Mac (POST /voice/talk) opened or closed the gate: the client
then sends its audio as if its own press held it. Unknown text is ignored both ways, so version 2 clients keep working.
Version 4 adds the client's own keep-alive, text, every 2 s whatever it receives: {"type": "pong", "id": n, "alive":
true}, n the newest ping it has answered (0 before the first). Pings travel in order behind the bot's audio (24 kHz PCM,
384 kbit/s), so on a path slower than that (a weak Twingate or cellular link) they wait behind seconds of it, and the
daemon took a phone that was only behind for one that was gone. The keep-alive goes the other way, which the audio does
not fill; shaped as a pong for a ping already answered, a version 2 or 3 daemon counts it and measures no round trip.
A client that heard nothing for 6 s treats the call as dead and reconnects. The daemon closes a call (code 4408) that
has answered pings before and then sends nothing (no pong of either kind, no audio) for 12 s, so the line is free for
the reconnect.
Mute (mute.py; once reading mode, whose names the wire keeps) needs no new version: the client adds `?reading=1` to the call's address when its own choice is
on, and the daemon sends {"type": "reading", "on": true|false} when the owner changed it by voice during the call, for
the client to keep. An older client ignores the message and calls without the parameter: Pointe speaks to it.

Version 5 keeps a call through a dropped link (calllink.py), and makes the audio a quarter of the size:
- The client's hello may list "resume" and "adpcm" in its capabilities, and carry "resume": the token of the call it
  is coming back to. The daemon answers the hello with {"type": "call", "resume": token, "resumed": bool, "codec":
  "adpcm"|"pcm16", "grace": secs}. A hello whose token is the current call's, from the same client, takes that call
  over: the pipeline, the conversation and the press go on, nothing is said again, and the old socket is closed (4410).
- A link that drops without a hang-up (any close but 1000, a dead heartbeat, a failed send) holds the call for
  `grace` seconds for the client to come back. Close with 1000 to hang up; 4000 when redialling.
- "codec": "adpcm" in that answer: the daemon's audio after it is IMA ADPCM. The client sends {"type": "codec", "up":
  "adpcm"} before its own first ADPCM chunk. Each ADPCM message decodes on its own: a 4-byte header (the predictor,
  int16 little-endian, then the step index, then 0) and 4-bit samples, the first in the high nibble. 24 kHz down is
  96 kbit/s, 16 kHz up 64 kbit/s, against 384 and 256 for PCM: a weak cellular or VPN path carries it.
- Each ping carries "heard_ms": the client's audio the daemon took on this socket. The client compares it with what
  it sent: more than a second and a half on the way (over the round trip) and it drops its newer chunks until the
  path catches up, since the kernel's buffers on both ends hold many seconds before a send ever waits.
- A pong may carry "ahead_ms": the bot audio the client holds, not yet played. While the link is SHED_SECS behind and
  the client has next to nothing left, the daemon drops new bot audio rather than let a path slower than the voice fall
  further behind (Heartbeat.lagging).
Ducking needs no new version either: a client that lists "duck" in its hello's capabilities gets {"type": "duck",
"gain": 0 to 1} when a voice comes over the bot's (a lower gain at once) and when its words were judged (1 again), and
sets its own playback level, which reaches the half second it already holds. For any other client the daemon scales
the audio it has not sent yet (PhoneSerializer.gain). Unknown text is ignored, so an older client keeps working.
"""

import asyncio
import hmac
import json
import secrets
import struct
import time
import warnings
from dataclasses import dataclass
from pathlib import Path

from pipecat.audio.utils import create_stream_resampler
from pipecat.frames.frames import Frame, InputAudioRawFrame, InterruptionFrame, OutputAudioRawFrame, SystemFrame
from pipecat.serializers.base_serializer import FrameSerializer

with warnings.catch_warnings():  # stdlib before 3.13, audioop-lts after; pipecat.audio.utils imports it already
    warnings.simplefilter("ignore", DeprecationWarning)
    import audioop

PROTOCOL = 5
OLDEST_APP_PROTOCOL = 1  # the oldest app this Mac still serves (every one so far); /voice/status says both
IN_RATE = 16000
OUT_RATE = 24000


@dataclass
class PttFrame(SystemFrame):
    """The client's push-to-talk press (open) or release. A system frame, like the audio it gates."""
    open: bool = False


PING_SECS = 2.0
DEAD_AFTER_SECS = 12.0
BEHIND_SECS = 4.0  # an unanswered ping this old: the link to the client is behind, and the log says so
SHED_SECS = 3.0  # the link this far behind its own best round trip, the client nearly out: new bot audio is dropped
CAUGHT_UP_SECS = 1.0
DRY_SECS = 0.5
ADPCM = "adpcm"
PCM16 = "pcm16"
# The bot's voice goes out this far ahead of the speed it plays at (send_ahead). Pipecat's websocket transport paces it
# at exactly that speed (its "/ 2" halves bytes, not time): a client then holds only what its own buffer waited for, and
# on a VPN path each late chunk (a lost segment waits a retransmission timeout, 200 ms and more) breaks the voice between
# words. Half a second covers one retransmission on a relayed path. The voice stops playing this much after the daemon
# stops sending it (echo.PLAYBACK_LAG_SECS), and a barge-in drops it on the client.
SEND_LEAD_SECS = 0.5


def next_send_at(clock: float, now: float, chunk_secs: float, lead: float = SEND_LEAD_SECS) -> float:
    """When the transport may send the chunk after the one it sent at `now`: a chunk's time on, on a clock that runs at
    the voice's speed and up to `lead` seconds ahead of `now`. After a pause or a barge-in (pipecat zeroes its clock)
    the next reply starts with the whole lead again."""
    return max(clock, now - lead) + chunk_secs


def send_ahead(output) -> None:
    """Pace this pipecat FastAPIWebsocketOutputTransport by next_send_at instead of its own clock. It sleeps in
    _write_audio_sleep after each chunk, until _next_send_time; tests/test_bad_network.py measures what a client gets."""
    async def write_audio_sleep() -> None:
        now = time.monotonic()
        chunk = output.audio_chunk_size / (2 * output._params.audio_out_channels * output.sample_rate)
        output._next_send_time = next_send_at(output._next_send_time, now, chunk, SEND_LEAD_SECS)
        await asyncio.sleep(max(0.0, output._next_send_time - now))

    output._write_audio_sleep = write_audio_sleep


def adpcm_encode(pcm: bytes, state: tuple[int, int] | None) -> tuple[bytes, tuple[int, int]]:
    """One message of IMA ADPCM: the header is the encoder's state before it, so a message decodes without the ones
    before it (one dropped as stale costs only itself)."""
    predictor, index = state or (0, 0)
    body, after = audioop.lin2adpcm(pcm, 2, (predictor, index))
    return struct.pack("<hBB", predictor, index, 0) + body, after


def adpcm_decode(message: bytes) -> bytes | None:
    """16-bit PCM from one ADPCM message, or None for one that is not."""
    if len(message) < 5:
        return None
    predictor, index, _ = struct.unpack_from("<hBB", message)
    if index > 88:
        return None
    pcm, _ = audioop.adpcm2lin(message[4:], 2, (predictor, index))
    return pcm


class Heartbeat:
    def __init__(self) -> None:
        self.sent: dict[int, float] = {}
        self.next_id = 0
        self.rtt_ms: int | None = None
        self.best_rtt = 0.0  # the link's shortest round trip this call: what is above it is queue, not distance
        self.last_pong = 0.0  # 0 until the client answers once: an old client is never closed for silence
        self.ahead: float | None = None  # bot audio the client said it holds, in seconds (protocol 5); None: not said
        self.shedding = False
        self.heard_secs = 0.0  # client audio taken on this socket, told in each ping: the client's own uplink check

    def attached(self) -> None:
        """A new socket for the same call (a resume): its pings start afresh, and it has said nothing yet."""
        self.sent.clear()
        if self.last_pong:
            self.last_pong = time.monotonic()
        self.ahead, self.shedding, self.heard_secs = None, False, 0.0

    def ping(self) -> str:
        self.next_id += 1
        self.sent[self.next_id] = time.monotonic()
        for old in [i for i in self.sent if i < self.next_id - 10]:
            del self.sent[old]
        return json.dumps({"type": "ping", "id": self.next_id, "rtt_ms": self.rtt_ms, "heard_ms": round(self.heard_secs * 1000)})

    def pong(self, ping_id: int, ahead_ms=None) -> None:
        if isinstance(ahead_ms, (int, float)) and not isinstance(ahead_ms, bool) and ahead_ms >= 0:
            self.ahead = ahead_ms / 1000
        sent = self.sent.pop(ping_id, None)
        if sent is not None:
            rtt = time.monotonic() - sent
            self.rtt_ms = round(rtt * 1000)
            self.best_rtt = min(self.best_rtt, rtt) if self.best_rtt else rtt
        self.last_pong = time.monotonic()

    def heard(self, secs: float = 0.0) -> None:
        """Audio from the client: over a slow uplink its pongs wait behind it, and its arriving proves the client is
        there (the hub's node links learned the same, tests/test_found_defects_node_link.py). Not for a client that never answered."""
        self.heard_secs += secs
        if self.last_pong:
            self.last_pong = time.monotonic()

    def dead(self) -> bool:
        return bool(self.last_pong) and time.monotonic() - self.last_pong > DEAD_AFTER_SECS

    def behind(self) -> float:
        """How long the oldest unanswered ping (of the last ten) has waited: how far the link to the client lags. 0 for
        a client that never answered one, which never will."""
        if not self.last_pong or not self.sent:
            return 0.0
        return time.monotonic() - min(self.sent.values())

    def lagging(self) -> bool:
        """New bot audio would only add to a queue the client cannot drain: drop it. That is a link behind by more than
        SHED_SECS over its best round trip while the client has almost nothing left to play. Neither alone: pings
        wait behind the reply's audio, so on a path barely faster than the voice they fall behind while the client
        still has its lead (SEND_LEAD_SECS) to play; and a lossy path stalls for a second or two and then catches up.
        A client that does not say what it holds (before protocol 5) counts as holding nothing."""
        queue = self.behind() - self.best_rtt
        if self.shedding:
            self.shedding = queue > CAUGHT_UP_SECS
        else:
            self.shedding = queue > SHED_SECS and (self.ahead or 0.0) < DRY_SECS
        return self.shedding


class PhoneSerializer(FrameSerializer):
    def __init__(self, heartbeat: Heartbeat | None = None) -> None:
        super().__init__()
        self._resampler = create_stream_resampler()
        self.heartbeat = heartbeat or Heartbeat()
        self.client: dict = {}
        self.down = PCM16  # the bot's audio as sent: ADPCM once the daemon said so in its `call` message (protocol 5)
        self.up = PCM16  # the client's audio: ADPCM after its {"type": "codec"}, PCM again on each new socket
        self._down_state: tuple[int, int] | None = None
        self.gain = 1.0  # under 1 while the voice is ducked, for a client that cannot duck its own playback

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, InterruptionFrame):
            return json.dumps({"type": "interrupt"})
        if isinstance(frame, OutputAudioRawFrame):
            pcm = frame.audio if frame.sample_rate == OUT_RATE else await self._resampler.resample(frame.audio, frame.sample_rate, OUT_RATE)
            if self.gain < 1.0 and pcm:
                pcm = audioop.mul(pcm, 2, self.gain)
            if self.down == ADPCM and pcm:
                message, self._down_state = adpcm_encode(pcm, self._down_state)
                return message
            return pcm
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, bytes) and self.up == ADPCM:
            pcm = adpcm_decode(data)
            if not pcm:
                return None
            self.heartbeat.heard(len(pcm) / 2 / IN_RATE)
            return InputAudioRawFrame(audio=pcm, sample_rate=IN_RATE, num_channels=1)
        if isinstance(data, bytes) and data and len(data) % 2 == 0:
            self.heartbeat.heard(len(data) / 2 / IN_RATE)
            return InputAudioRawFrame(audio=data, sample_rate=IN_RATE, num_channels=1)
        if isinstance(data, str):
            try:
                message = json.loads(data)
            except ValueError:
                return None
            if isinstance(message, dict) and message.get("type") == "pong" and isinstance(message.get("id"), int):
                self.heartbeat.pong(message["id"], message.get("ahead_ms"))
            elif isinstance(message, dict) and message.get("type") == "codec" and message.get("up") in (ADPCM, PCM16):
                self.up = message["up"]
            elif isinstance(message, dict) and message.get("type") == "ptt" and isinstance(message.get("open"), bool):
                return PttFrame(open=message["open"])
            elif isinstance(message, dict) and message.get("type") == "hello":  # protocol 3: who the client is
                # never the token; "machines": the machines the client holds, names and ids only (handoff.py)
                self.client = {k: message.get(k) for k in ("protocol", "device", "capabilities", "machines") if k in message}
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
