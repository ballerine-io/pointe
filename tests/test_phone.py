import asyncio
import json
import os
import stat
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipecat.frames.frames import InputAudioRawFrame, InterruptionFrame, OutputAudioRawFrame, TextFrame  # noqa: E402

from phone import IN_RATE, OUT_RATE, PhoneSerializer, phone_allowed, phone_key  # noqa: E402


def run(c):
    return asyncio.run(c)


def test_phone_audio_comes_in_as_16k_frames():
    frame = run(PhoneSerializer().deserialize(b"\x01\x00" * 320))
    assert isinstance(frame, InputAudioRawFrame) and frame.sample_rate == IN_RATE and frame.num_channels == 1


def test_odd_or_text_input_is_dropped():
    s = PhoneSerializer()
    assert run(s.deserialize(b"\x01\x00\x02")) is None
    assert run(s.deserialize('{"type": "mute"}')) is None


def test_bot_audio_goes_out_at_24k():
    s = PhoneSerializer()
    same = run(s.serialize(OutputAudioRawFrame(audio=b"\x00\x01" * 480, sample_rate=OUT_RATE, num_channels=1)))
    assert same == b"\x00\x01" * 480
    tone = (np.sin(np.arange(1600) / 5) * 8000).astype(np.int16).tobytes()  # 100 ms at 16 kHz
    out = b"".join(run(s.serialize(OutputAudioRawFrame(audio=tone, sample_rate=16000, num_channels=1))) for _ in range(5))
    assert abs(len(out) / 2 / OUT_RATE - 0.5) < 0.05  # 500 ms in, about 500 ms out


def test_an_interruption_tells_the_phone_to_drop_its_buffer():
    assert json.loads(run(PhoneSerializer().serialize(InterruptionFrame()))) == {"type": "interrupt"}


def test_other_frames_are_not_sent():
    assert run(PhoneSerializer().serialize(TextFrame("hi"))) is None


def test_phone_key_is_private_and_stable(tmp_path):
    key = phone_key(tmp_path)
    assert len(key) >= 40 and phone_key(tmp_path) == key
    assert stat.S_IMODE(os.stat(tmp_path / "phone_key").st_mode) == 0o600


def test_an_empty_key_file_is_replaced(tmp_path):
    (tmp_path / "phone_key").write_text("")
    assert phone_key(tmp_path)


def test_only_the_phone_key_is_allowed(tmp_path):
    key = phone_key(tmp_path)
    assert phone_allowed(tmp_path, f"Bearer {key}")
    for bad in (None, "", "Bearer ", f"Bearer {key}x", key, "Bearer " + "a" * len(key)):
        assert not phone_allowed(tmp_path, bad)


def test_the_heartbeat_measures_the_round_trip_and_spots_a_silent_client(monkeypatch):
    import json as _json

    import phone

    beat = phone.Heartbeat()
    assert not beat.dead()  # a client that never answered (an old one) is never closed for silence
    ping = _json.loads(beat.ping())
    assert ping["type"] == "ping" and ping["rtt_ms"] is None
    beat.pong(ping["id"])
    assert beat.rtt_ms is not None and not beat.dead()
    beat.last_pong -= phone.DEAD_AFTER_SECS + 1  # it stopped answering
    assert beat.dead()


def test_a_pong_from_the_client_reaches_the_heartbeat():
    import asyncio as _asyncio
    import json as _json

    import phone

    serializer = phone.PhoneSerializer()
    ping = _json.loads(serializer.heartbeat.ping())
    assert _asyncio.run(serializer.deserialize(_json.dumps({"type": "pong", "id": ping["id"]}))) is None
    assert serializer.heartbeat.last_pong > 0


def test_a_phone_whose_pings_wait_behind_the_bots_voice_is_behind_not_gone(monkeypatch):
    """A path slower than the bot's voice (ios/e2e/talking_mac_ui.py with POINTE_DOWN_KBPS): the pings queue behind
    seconds of audio and no pong comes back, but the app's own keep-alive (protocol 4, the exact text Call.alive sends,
    ios/PointeTests) still arrives. The call stays up, no round trip is made up from a keep-alive, and the lag shows."""
    import asyncio as _asyncio
    import json as _json

    import phone

    clock = [1000.0]
    monkeypatch.setattr(phone.time, "monotonic", lambda: clock[0])
    serializer = phone.PhoneSerializer()
    beat = serializer.heartbeat
    first = _json.loads(beat.ping())
    clock[0] += 0.05
    _asyncio.run(serializer.deserialize(_json.dumps({"type": "pong", "id": first["id"]})))
    assert beat.rtt_ms == 50 and beat.behind() == 0
    for _ in range(15):  # 30 s of pings that never come back, and a keep-alive every 2 s
        clock[0] += 2
        beat.ping()
        _asyncio.run(serializer.deserialize('{"alive":true,"id":1,"type":"pong"}'))
        assert not beat.dead()
    assert beat.rtt_ms == 50
    assert beat.behind() >= 18  # the oldest of the ten pings kept
    clock[0] += phone.DEAD_AFTER_SECS + 0.1  # and then nothing at all: gone
    assert beat.dead()


def test_a_client_that_never_answered_is_never_behind():
    import phone

    beat = phone.Heartbeat()
    for _ in range(12):
        beat.ping()
    assert beat.behind() == 0 and not beat.dead()


def test_audio_from_a_client_that_answered_before_keeps_the_call(monkeypatch):
    """Over a slow uplink the pongs wait behind the microphone's audio: arriving audio proves the client is there."""
    import asyncio as _asyncio

    import phone

    clock = [1000.0]
    monkeypatch.setattr(phone.time, "monotonic", lambda: clock[0])
    serializer = phone.PhoneSerializer()
    _asyncio.run(serializer.deserialize(b"\x00\x00" * 320))
    assert serializer.heartbeat.last_pong == 0  # an old client that never answered stays exempt
    serializer.heartbeat.pong(serializer.heartbeat.next_id)
    for _ in range(20):
        clock[0] += 1
        _asyncio.run(serializer.deserialize(b"\x00\x00" * 320))
    assert not serializer.heartbeat.dead()


def test_the_page_sends_the_same_keep_alive_as_the_app():
    page = (Path(__file__).resolve().parents[1] / "ui.html").read_text()
    assert "JSON.stringify({type: 'pong', id: call.answered || 0, alive: true})" in page and "clearInterval(call.alive)" in page
