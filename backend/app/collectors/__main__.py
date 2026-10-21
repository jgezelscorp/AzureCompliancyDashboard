"""Worker entry point: ``python -m app.collectors``."""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.azure.client import ArmClient, AzureIdentityTokenProvider, HttpxTransport
from app.collectors.runner import CollectionRunner
from app.collectors.scheduler import CollectionScheduler
from app.config import get_settings
from app.database import get_engine
from app.sink.service import build_sink


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    factory: sessionmaker[Session] = sessionmaker(get_engine(settings.database_url))
    client = ArmClient(
        HttpxTransport(),
        AzureIdentityTokenProvider(),
        allowed_subscriptions=frozenset(settings.subscription_ids),
        max_retries=settings.arm_max_retries,
    )
    runner = CollectionRunner(settings, factory, client, sink=build_sink(settings, factory))
    scheduler = CollectionScheduler(runner, timedelta(hours=settings.collection_interval_hours))
    asyncio.run(scheduler.run_forever())


if __name__ == "__main__":
    main()
