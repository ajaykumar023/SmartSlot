"""Single-process demo sweeper. Use a distributed task queue for production."""
import asyncio
import logging
from .auto_allocator import process_all
from .config import settings
from .database import SessionLocal

log = logging.getLogger(__name__)


def sweep_once():
    with SessionLocal() as db:
        process_all(db)


async def sweep_forever():
    while True:
        try:
            await asyncio.to_thread(sweep_once)
        except Exception:
            log.exception("Automatic allocator failed; will retry")
        await asyncio.sleep(max(30, settings.auto_allocator_interval_seconds))
