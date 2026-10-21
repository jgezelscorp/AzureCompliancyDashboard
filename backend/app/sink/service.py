"""Optional sink facade used by the collector. Every failure here is contained."""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.azure.client import HttpxTransport, TokenProvider, Transport
from app.config import Settings
from app.db import CollectionRunRow
from app.sink import outbox, rows, schema
from app.sink.client import LogsIngestionClient

log = logging.getLogger(__name__)


class LogsSink:
    def __init__(
        self,
        settings: Settings,
        factory: sessionmaker[Session],
        client: LogsIngestionClient,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._factory = factory
        self._clock = clock
        self._delivery = outbox.OutboxDelivery(
            factory,
            client,
            max_bytes=settings.logs_batch_max_bytes,
            max_records=settings.logs_batch_max_records,
            max_attempts=settings.logs_max_attempts,
            retry_max=timedelta(minutes=settings.logs_retry_max_minutes),
            max_records_per_drain=settings.logs_max_records_per_drain,
            clock=clock,
            sleep=sleep,
        )

    def publish(self, run_id: int) -> outbox.DrainResult | None:
        """Queue the run's rows, then deliver everything that is due (including old backlog).

        Never raises: the PostgreSQL collection is already committed and stays valid whatever
        happens here. Problems are visible through ``outbox.delivery_summary``.
        """
        try:
            now = self._clock()
            with self._factory() as session, session.begin():
                run = session.get(CollectionRunRow, run_id)
                if run is not None:
                    outbox.enqueue(session, rows.rows_for_run(session, run), run_id, now)
        except Exception:
            log.exception("could not queue Logs rows for run %s", run_id)
        return self.drain()

    def drain(self) -> outbox.DrainResult | None:
        try:
            result = self._delivery.drain()
            now = self._clock()
            cutoff = now - timedelta(days=30 * self._settings.retention_months)
            with self._factory() as session, session.begin():
                outbox.purge_outbox(
                    session, now, timedelta(days=self._settings.logs_delivered_keep_days), cutoff
                )
            if result.stopped:
                log.warning("Logs delivery paused: %s", result.stopped)
            return result
        except Exception:
            log.exception("Logs delivery failed unexpectedly")
            return None


def build_sink(
    settings: Settings,
    factory: sessionmaker[Session],
    transport: Transport | None = None,
    tokens: TokenProvider | None = None,
) -> LogsSink | None:
    """Return None unless the sink is explicitly enabled; the app never requires Logs."""
    if not settings.logs_sink_enabled:
        return None
    if tokens is None:
        from app.azure.client import AzureIdentityTokenProvider

        tokens = AzureIdentityTokenProvider()
    client = LogsIngestionClient(
        transport or HttpxTransport(),
        tokens,
        settings.logs_ingestion_endpoint,
        settings.logs_dcr_immutable_id,
        schema.api_version(),
    )
    return LogsSink(settings, factory, client)
