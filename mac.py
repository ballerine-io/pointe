"""This Mac's own state that the phone depends on: whether the user is at it.

The idle time is IOKit's HIDIdleTime (`ioreg`): nanoseconds since the last keyboard, mouse or trackpad input, for
anyone logged in at this Mac's screen. Read in a subprocess, never on the event loop's thread, at most every
IDLE_READ_SECS and only while something asks (a status poll).
"""

import asyncio
import re
import time

from loguru import logger

SYSTEM = True  # tests turn it off: they never read this machine's idle time or power, nor keep it awake

# Used within this long: the user is at the Mac, and a phone or another device stays quiet (attention items `quiet`).
# A minute covers reading a diff or the page between keystrokes, and is short enough that walking away from the desk
# lets the next alert through: a missed approval costs more than one extra buzz. Longer than the 15 s a prompt waits
# before it alerts (sessions.TERMINAL_NEWS_AFTER_SECS), so typing at the Mac never sets the wrist off.
AT_MAC_SECS = 60.0
IDLE_READ_SECS = 5.0
IDLE_STALE_SECS = 15.0  # an older reading says nothing about now: unknown, never "at the Mac"
IDLE_TIMEOUT_SECS = 2.0
IOREG = ("ioreg", "-c", "IOHIDSystem", "-d", "4", "-r", "-k", "HIDIdleTime")
_IDLE = re.compile(r'"HIDIdleTime"\s*=\s*(\d+)')


def parse_idle(out: str) -> float | None:
    """Seconds since the last input, from ioreg's output; None when it has no reading."""
    found = _IDLE.search(out)
    return int(found.group(1)) / 1e9 if found else None


async def read_idle() -> float | None:
    if not SYSTEM:
        return None
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(*IOREG, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), IDLE_TIMEOUT_SECS)
    except (OSError, asyncio.TimeoutError):  # not a Mac, or ioreg stuck: no reading
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
        return None
    return parse_idle(out.decode(errors="replace"))


class IdleClock:
    """The last reading of the idle time, kept fresh while it is asked for."""

    def __init__(self, read=read_idle, clock=time.time):
        self._read, self._clock = read, clock
        self.idle: float | None = None
        self.at = 0.0  # when it was read
        self._reading: asyncio.Task | None = None

    def secs(self) -> float | None:
        """Seconds since the user last touched this Mac, as of a reading under IDLE_STALE_SECS old; None when there is
        none. A stale one starts a new reading in the background: the caller never waits for ioreg."""
        now = self._clock()
        if now - self.at >= IDLE_READ_SECS and (self._reading is None or self._reading.done()):
            try:
                self._reading = asyncio.get_running_loop().create_task(self._refresh())
            except RuntimeError:  # no loop: nothing can read it
                pass
        return self.idle if now - self.at < IDLE_STALE_SECS else None

    def in_use(self) -> bool:
        idle = self.secs()
        return idle is not None and idle < AT_MAC_SECS

    async def _refresh(self) -> None:
        idle = await self._read()
        if idle is None and self.idle is not None:
            logger.info("the Mac's idle time could not be read")
        self.idle, self.at = idle, self._clock()
