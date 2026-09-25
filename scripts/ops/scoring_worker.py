"""Separate durable scoring worker. No migrations or account bootstrap."""

import argparse
import asyncio
import logging
import signal

from src.aml_workshop_simulator.db.session import AsyncSessionLocal, async_engine
from src.aml_workshop_simulator.services.scoring_jobs import run_one, worker_loop


async def run(once=False, poll_seconds=0.5):
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows console still supports interruption.
            pass
    try:
        if once:
            return await run_one(AsyncSessionLocal)
        await worker_loop(AsyncSessionLocal, stop, poll_seconds)
    finally:
        await async_engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    args = parser.parse_args()
    if not 0.05 <= args.poll_seconds <= 10:
        parser.error("poll-seconds must be between 0.05 and 10")
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run(**vars(args)))
    except KeyboardInterrupt:
        pass
