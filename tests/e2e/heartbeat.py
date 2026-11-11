"""A call that dies silently: the client answers the Mac's pings, then goes quiet as a phone does when its VPN drops. The
daemon must close that call within its dead-after time, and a reconnect must get through instead of "already up".

Run: CLAUDE_VOICE_STATE=/tmp/cv-state-beat CLAUDE_VOICE_DAEMON_PORT=7899 CLAUDE_VOICE_TLS_PORT=7499 \
     uv run python -u -I tests/e2e/heartbeat.py
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import phone  # noqa: E402
from rig import DAEMON, ROOT, STATE, fresh_state, log_lines, stop_daemon  # noqa: E402
from scenarios import check, results  # noqa: E402


async def dial():
    from websockets.asyncio.client import connect

    return await connect(DAEMON.replace("http", "ws", 1) + "/voice/call", max_size=None, additional_headers={
        "Authorization": f"Bearer {(STATE / 'token').read_text().strip()}"})


async def main() -> None:
    assert os.environ.get("CLAUDE_VOICE_STATE"), "use an isolated CLAUDE_VOICE_STATE"
    fresh_state()
    assert subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], capture_output=True, env=dict(os.environ)).returncode == 0
    socket = await dial()
    pings, answered = [], 0
    try:
        deadline = time.time() + 8
        while time.time() < deadline:  # a healthy client: answer every ping
            message = await asyncio.wait_for(socket.recv(), 5)
            if isinstance(message, str) and json.loads(message).get("type") == "ping":
                ping = json.loads(message)
                pings.append(ping)
                await socket.send(json.dumps({"type": "pong", "id": ping["id"]}))
                answered += 1
        check("the Mac pings every few seconds and measures the round trip",
              answered >= 3 and any(p.get("rtt_ms") is not None for p in pings), pings=pings[-2:])

        went_quiet = time.time()  # now the client goes silent: it reads nothing and answers nothing
        closed_at = None
        while time.time() - went_quiet < phone.DEAD_AFTER_SECS + 8:
            await asyncio.sleep(0.5)
            if log_lines("stopped answering"):
                closed_at = time.time()
                break
        check("a call that stops answering is closed by the Mac",
              closed_at is not None and closed_at - went_quiet <= phone.DEAD_AFTER_SECS + 4,
              after_s=round(closed_at - went_quiet, 1) if closed_at else None)

        await asyncio.sleep(1)
        again = await dial()
        first = await asyncio.wait_for(again.recv(), 8)
        check("the reconnect gets through, not 'already up'",
              isinstance(first, (bytes, str)) and again.close_code is None, first=str(first)[:80])
        await again.close()
    finally:
        try:
            await socket.close()
        except Exception:
            pass
        stop_daemon()
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed (heartbeat)")


asyncio.run(main())
