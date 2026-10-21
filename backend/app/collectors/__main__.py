"""Worker entry point: ``python -m app.collectors``."""

import asyncio
import logging
from collections.abc import Awaitable
from datetime import timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.api.exports import purge_expired
from app.azure.client import ArmClient, AzureIdentityTokenProvider, HttpxTransport
from app.collectors.persist import recategorize_checks
from app.collectors.runner import CollectionRunner
from app.collectors.scheduler import CollectionScheduler
from app.config import get_settings
from app.database import get_engine
from app.logging_config import configure_logging
from app.onboarding import seed_configured_scopes
from app.sink.service import build_sink

log = logging.getLogger(__name__)


def purge_once(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        return purge_expired(session)


async def purge_forever(factory: sessionmaker[Session], interval: timedelta) -> None:
    while True:
        try:
            purged = await asyncio.to_thread(purge_once, factory)
            if purged:
                log.info("purged expired export artifacts", extra={"count": purged})
        except Exception:  # keep the purge loop alive across transient DB errors
            log.exception("export purge failed")
        await asyncio.sleep(interval.total_seconds())


async def run(scheduler: CollectionScheduler, purge: Awaitable[None]) -> None:
    await asyncio.gather(scheduler.run_forever(), purge)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    factory: sessionmaker[Session] = sessionmaker(get_engine(settings.database_url))
    with factory() as session:
        seed_configured_scopes(session, settings.subscription_ids)
    with factory() as session, session.begin():
        updated = recategorize_checks(session)
    if updated:
        log.info("recategorized stored checks", extra={"count": updated})
    client = ArmClient(
        HttpxTransport(),
        AzureIdentityTokenProvider(),
        allowed_subscriptions=frozenset(settings.subscription_ids),
        max_retries=settings.arm_max_retries,
    )
    runner = CollectionRunner(settings, factory, client, sink=build_sink(settings, factory))
    scheduler = CollectionScheduler(runner, timedelta(hours=settings.collection_interval_hours))
    purge = purge_forever(factory, timedelta(minutes=settings.export_purge_interval_minutes))
    asyncio.run(run(scheduler, purge))


if __name__ == "__main__":
    main()
