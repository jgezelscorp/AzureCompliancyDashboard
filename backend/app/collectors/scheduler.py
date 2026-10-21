"""Six-hour (configurable) collection scheduler. Overlap is also prevented in the database."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Protocol

log = logging.getLogger(__name__)


class Runnable(Protocol):
    def run_once(self) -> object: ...


class CollectionScheduler:
    def __init__(
        self,
        runner: Runnable,
        interval: timedelta,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._runner = runner
        self._interval = interval
        self._sleep = sleep

    async def run_forever(self, max_runs: int | None = None) -> int:
        """Runs immediately, then once per interval. Runs are sequential, never concurrent."""
        runs = 0
        loop = asyncio.get_running_loop()
        while max_runs is None or runs < max_runs:
            began = loop.time()
            try:
                await asyncio.to_thread(self._runner.run_once)
            except Exception:  # a failed run must not stop the schedule
                log.exception("scheduled collection raised")
            runs += 1
            if max_runs is not None and runs >= max_runs:
                break
            elapsed = loop.time() - began
            await self._sleep(max(0.0, self._interval.total_seconds() - elapsed))
        return runs
