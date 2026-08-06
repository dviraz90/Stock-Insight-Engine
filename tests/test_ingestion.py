"""§10 Ingestion: feed the same payload twice, assert exactly one row."""

import pytest

from insight_engine import fixtures
from insight_engine.adapters.edgar import EdgarAdapter
from insight_engine.adapters.price import PriceAdapter
from insight_engine.ingestion.pipeline import ingest
from insight_engine.persistence import db


@pytest.fixture()
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    inst = fixtures.INSTRUMENT
    db.upsert_instrument(
        c, ticker=inst["ticker"], name=inst["name"], exchange=inst["exchange"],
        sector=inst["sector"], currency=inst["currency"],
    )
    yield c
    c.close()


def _adapters():
    return [
        EdgarAdapter(fixtures.edgar_transport),
        PriceAdapter(fixtures.price_transport),
    ]


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def test_first_ingest_inserts_rows(conn):
    new_rows, events = ingest(conn, "AAPL", _adapters())
    assert new_rows > 0
    assert _count(conn, "fundamentals") > 0
    assert _count(conn, "prices") == 4  # four fixture bars
    # events emitted for the write side
    assert any(type(e).__name__ == "PriceUpdated" for e in events)
    assert any(type(e).__name__ == "FundamentalsRevised" for e in events)


def test_reingest_is_idempotent(conn):
    ingest(conn, "AAPL", _adapters())
    f1, p1 = _count(conn, "fundamentals"), _count(conn, "prices")
    s1 = _count(conn, "sources")

    new_rows, _ = ingest(conn, "AAPL", _adapters())  # exact same payloads again
    assert new_rows == 0  # nothing new inserted
    assert _count(conn, "fundamentals") == f1
    assert _count(conn, "prices") == p1
    assert _count(conn, "sources") == s1
