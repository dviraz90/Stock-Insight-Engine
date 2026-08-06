"""Ingestion pipeline — spec §5.2 (write side).

Idempotent by construction: storage-layer UNIQUE constraints + INSERT OR IGNORE
mean re-running ingestion never duplicates rows. Emits domain events (§7) that
the analysis worker reacts to. Debounce + cursor-based backfill are M3 concerns
(§9); M0 does a straight-through fetch for one ticker.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from ..adapters.base import DataAdapter
from ..domain.events import DomainEvent, FundamentalsRevised, PriceUpdated
from ..persistence import db

# Beginning of time for M0's single-shot fetch (no cursor yet).
_EPOCH = datetime(1970, 1, 1)


def ingest(
    conn: sqlite3.Connection,
    ticker: str,
    adapters: list[DataAdapter],
    *,
    since: datetime = _EPOCH,
) -> tuple[int, list[DomainEvent]]:
    """Fetch from every adapter, persist idempotently, return (new_rows, events).

    `new_rows` counts only rows actually inserted — redeliveries return 0, which
    is what the idempotency test asserts.
    """
    total_new = 0
    events: list[DomainEvent] = []
    now = datetime.now(timezone.utc)

    for adapter in adapters:
        records = adapter.fetch(ticker, since)
        if not records:
            continue
        new_rows = db.store_records(conn, records)
        total_new += new_rows

        kinds = {r.payload["kind"] for r in records}
        if "price" in kinds and new_rows:
            events.append(PriceUpdated(ticker=ticker.upper(), occurred_at=now))
        if "fundamental" in kinds and new_rows:
            periods = {
                r.payload["period"] for r in records if r.payload["kind"] == "fundamental"
            }
            for period in sorted(periods):
                events.append(
                    FundamentalsRevised(
                        ticker=ticker.upper(), occurred_at=now, period=period
                    )
                )

    return total_new, events
