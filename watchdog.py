"""Finds what freezes the daemon's event loop: a thread watches a heartbeat the loop beats, and when the loop misses it for
half a second, logs where the loop's thread is stuck. A frozen loop delays everything: the page's status, the
phone, the next reply.
"""

import asyncio
import sys
import threading
import time
import traceback

from loguru import logger

STALL_SECS = 0.5
_beat = time.monotonic()


async def heartbeat() -> None:
    global _beat
    while True:
        _beat = time.monotonic()
        await asyncio.sleep(0.1)


def start(loop_thread_id: int) -> None:
    """Call from the loop's thread, with its own threading.get_ident()."""

    def watch() -> None:
        reported = 0.0
        while True:
            time.sleep(0.1)
            stalled = time.monotonic() - _beat
            if stalled > STALL_SECS and time.monotonic() - reported > 5:
                frame = sys._current_frames().get(loop_thread_id)
                where = "".join(traceback.format_stack(frame)[-6:]) if frame else "(no frame)"
                logger.warning(f"event loop stalled {stalled:.1f}s, in:\n{where}")
                reported = time.monotonic()

    threading.Thread(target=watch, name="loop-watchdog", daemon=True).start()
