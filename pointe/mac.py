"""This Mac's own state that the phone depends on: whether the user is at it, and staying awake for a call from it.

The idle time is IOKit's HIDIdleTime (`ioreg`): nanoseconds since the last keyboard, mouse or trackpad input, for
anyone logged in at this Mac's screen. Read in a subprocess, never on the event loop's thread, at most every
IDLE_READ_SECS and only while something asks (a status poll).
"""

import asyncio
import os
import re
import time

from loguru import logger

import childenv

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
                                                    stderr=asyncio.subprocess.DEVNULL, env=childenv.child_env())
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


POWER = ("pmset", "-g", "ps")
POWER_TIMEOUT_SECS = 2.0
_SOURCE = re.compile(r"Now drawing from '([^']+)'")


def on_ac(out: str) -> bool | None:
    """True on AC power, False on battery, from `pmset -g ps`; None when it says neither."""
    found = _SOURCE.search(out)
    return None if found is None else found.group(1) == "AC Power"


async def read_power() -> bool | None:
    if not SYSTEM:
        return None
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(*POWER, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.DEVNULL, env=childenv.child_env())
        out, _ = await asyncio.wait_for(proc.communicate(), POWER_TIMEOUT_SECS)
    except (OSError, asyncio.TimeoutError):
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
        return None
    return on_ac(out.decode(errors="replace"))


async def start_caffeinate():
    """`caffeinate -i -w <this daemon>`: holds off idle sleep (the display may still sleep, a closed lid still sleeps),
    and ends by itself when the daemon does, however it ends."""
    if not SYSTEM:
        return None
    try:
        return await asyncio.create_subprocess_exec("caffeinate", "-i", "-w", str(os.getpid()), stdin=asyncio.subprocess.DEVNULL,
                                                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                                                    env=childenv.child_env())
    except OSError as e:
        logger.warning(f"could not keep the Mac awake: {e}")
        return None


class KeepAwake:
    """While a call from another device is up and the Mac is on AC power, the Mac does not idle-sleep under it: the
    phone's call would drop with the Mac. Never on battery; a power source that cannot be read counts as battery."""

    def __init__(self, power=read_power, start=start_caffeinate):
        self._power, self._start = power, start
        self.proc = None
        self.why = "no call from another device"
        self._lock = asyncio.Lock()

    @property
    def on(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def update(self, call_from_elsewhere: bool) -> None:
        """Called when such a call starts or ends, and every few seconds (the power source can change under a call)."""
        async with self._lock:
            ac = await self._power() if call_from_elsewhere else None
            want = call_from_elsewhere and ac is True
            self.why = ("a call from another device is up and the Mac is on power" if want else
                        "the Mac is on battery" if call_from_elsewhere and ac is False else
                        "the power source is unknown" if call_from_elsewhere else "no call from another device")
            if want and not self.on:
                self.proc = await self._start()
                if self.on:
                    logger.info("keeping the Mac awake: a call from another device is up, on AC power")
            elif not want and self.proc is not None:
                self.stop()
                logger.info(f"no longer keeping the Mac awake: {self.why}")

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc is not None and proc.returncode is None:
            proc.terminate()
            asyncio.get_running_loop().create_task(proc.wait())  # reaped: no zombie

    def status(self) -> dict:
        return {"on": self.on, "why": self.why}
