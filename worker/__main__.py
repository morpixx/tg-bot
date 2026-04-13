from __future__ import annotations

import asyncio
import logging
import signal

import structlog

from bot.core.config import settings
from worker.scheduler import WorkerScheduler


def setup_logging() -> None:
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))


async def main() -> None:
    setup_logging()
    log = structlog.get_logger()
    log.info("Starting worker")

    scheduler = WorkerScheduler()
    scheduler.start()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        log.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await stop_event.wait()
    log.info("Shutting down worker")
    await scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
