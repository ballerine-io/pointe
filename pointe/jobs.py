"""Bounded background work for the reading model: at most a couple at a time, each with a timeout, each logged by name
and duration only (never its content). The meeting secretary and lookups run here; later briefings and conflict checks."""

import asyncio
import time
from collections.abc import Awaitable, Callable

from loguru import logger


class JobRunner:
    def __init__(self, concurrency: int = 2) -> None:
        self._slots = asyncio.Semaphore(concurrency)
        self.running = 0
        self.done = 0
        self.failed = 0

    async def run(self, name: str, work: Callable[[], Awaitable], timeout: float):
        """The job's result, or None when it failed or ran out of time."""
        async with self._slots:
            self.running += 1
            started = time.time()
            try:
                result = await asyncio.wait_for(work(), timeout)
                self.done += 1
                logger.info(f"job {name} {time.time() - started:.1f}s")
                return result
            except Exception as e:
                self.failed += 1
                logger.warning(f"job {name} failed after {time.time() - started:.1f}s ({type(e).__name__})")
                return None
            finally:
                self.running -= 1

    def stats(self) -> dict:
        return {"running": self.running, "done": self.done, "failed": self.failed}
