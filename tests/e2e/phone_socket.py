"""A real call over the phone app's WebSocket (phone.py), driven by a stand-in phone: speech in, the bot's speech out.

Run with an isolated state: CLAUDE_VOICE_STATE=/tmp/cv-state-phone CLAUDE_VOICE_DAEMON_PORT=7867 uv run python -u -I tests/e2e/phone_socket.py
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).parent))
from rig import DAEMON, RATE, ROOT, STATE, fresh_state, stop_daemon, synth, transcribe  # noqa: E402

URL = DAEMON.replace("http", "ws", 1) + "/voice/phone"
IN_RATE, OUT_RATE, CHUNK = 16000, 24000, 320  # 20 ms at 16 kHz
results: list[dict] = []


def check(name: str, ok: bool, **detail) -> None:
    results.append({"name": name, "ok": ok})
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {json.dumps(detail, ensure_ascii=False)[:300]}", flush=True)


def resample(pcm: np.ndarray, src: int, dst: int) -> np.ndarray:
    n = int(len(pcm) * dst / src)
    return np.interp(np.linspace(0, len(pcm), n, endpoint=False), np.arange(len(pcm)), pcm).astype(np.int16)


class Phone:
    """Plays what the daemon sends and remembers when; drops its buffer on "interrupt", as the app must."""

    def __init__(self, socket):
        self.socket, self.audio, self.interrupts = socket, [], 0

    async def listen(self) -> None:
        async for message in self.socket:
            if isinstance(message, bytes):
                self.audio.append((time.time(), np.frombuffer(message, dtype=np.int16)))
            elif json.loads(message).get("type") == "interrupt":
                self.interrupts += 1

    async def send(self, pcm16k: np.ndarray) -> None:
        start = time.time()
        for i in range(0, len(pcm16k), CHUNK):
            await self.socket.send(pcm16k[i:i + CHUNK].tobytes())
            wait = start + (i + CHUNK) / IN_RATE - time.time()
            if wait > 0:
                await asyncio.sleep(wait)

    async def silence(self, seconds: float) -> None:
        await self.send(np.zeros(int(seconds * IN_RATE), dtype=np.int16))

    def heard_since(self, t: float) -> tuple[float | None, np.ndarray]:
        chunks = [(at, a) for at, a in self.audio if at >= t]
        if not chunks:
            return None, np.zeros(0, dtype=np.int16)
        return chunks[0][0], np.concatenate([a for _, a in chunks])


async def refused(headers: dict) -> bool:
    try:
        async with connect(URL, additional_headers=headers, open_timeout=5) as socket:
            await asyncio.wait_for(socket.recv(), 3)
    except Exception:
        return True
    return False


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    fresh_state()
    up = subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, text=True, env=dict(os.environ))
    assert up.returncode == 0, up.stderr[-500:]
    key = (STATE / "phone_key").read_text().strip()
    try:
        check("a wrong key is refused", await refused({"Authorization": "Bearer wrong"}))
        check("the daemon's own token is refused", await refused({"Authorization": f"Bearer {(STATE / 'token').read_text().strip()}"}))
        async with connect(URL, additional_headers={"Authorization": f"Bearer {key}"}, max_size=None) as socket:
            phone = Phone(socket)
            listening = asyncio.create_task(phone.listen())
            await phone.silence(8)
            first, greeting = phone.heard_since(0)
            check("the bot greets the phone", len(greeting) > OUT_RATE // 2, seconds=round(len(greeting) / OUT_RATE, 1))
            check("a second phone is turned away while one is on a call",
                  await refused({"Authorization": f"Bearer {key}"}))

            question = resample(await synth("What time zone is Tel Aviv in?"), RATE, IN_RATE)
            await phone.send(question)
            ended = time.time()
            await phone.silence(10)
            started, reply = phone.heard_since(ended)
            said = await transcribe(resample(reply, OUT_RATE, RATE)) if len(reply) else ""
            check("a spoken question gets a spoken answer over the phone socket",
                  any(w in said.lower() for w in ("utc", "israel", "gmt", "two", "2")),
                  latency_s=round(started - ended, 2) if started else None, said=said)

            await phone.send(resample(await synth("Explain in detail how TCP congestion control works, slow start, everything."), RATE, IN_RATE))
            await phone.silence(4)
            before = phone.interrupts
            await phone.send(resample(await synth("Stop. What is two plus two?"), RATE, IN_RATE))
            await phone.silence(8)
            check("talking over the bot tells the phone to drop its buffer", phone.interrupts > before,
                  interrupts=phone.interrupts - before)
            listening.cancel()
    finally:
        stop_daemon()
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (phone socket)")


if __name__ == "__main__":  # page_drive.py borrows Phone
    asyncio.run(main())
