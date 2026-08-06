"""SQLite access — spec §6. Thin helpers, no ORM (§11.1 don't over-engineer).

Idempotency (§5.2) is enforced at the storage layer via UNIQUE constraints plus
INSERT OR IGNORE: feeds redeliver constantly, so writes must be safe to repeat.
"""

from __future__ import annotations

import json
import sqlite3
from importlib import resources
from pathlib import Path

from ..adapters.base import RawRecord
from ..domain.models import AnalysisReport, Status


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    schema = resources.files("insight_engine.persistence").joinpath("schema.sql").read_text()
    conn.executescript(schema)
    conn.commit()


def upsert_instrument(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    name: str,
    exchange: str,
    sector: str,
    currency: str,
) -> None:
    conn.execute(
        """INSERT INTO instruments(ticker, name, exchange, sector, currency)
           VALUES (?,?,?,?,?)
           ON CONFLICT(ticker) DO UPDATE SET
             name=excluded.name, exchange=excluded.exchange,
             sector=excluded.sector, currency=excluded.currency""",
        (ticker.upper(), name, exchange, sector, currency),
    )
    conn.commit()


def _insert_source(conn: sqlite3.Connection, rec: RawRecord) -> str:
    """Persist the source row idempotently; return its source_id (the hash)."""
    source_id = rec.source_hash
    conn.execute(
        """INSERT OR IGNORE INTO sources
             (source_id, source_name, source_url, retrieved_at, source_hash)
           VALUES (?,?,?,?,?)""",
        (
            source_id,
            rec.source_name,
            rec.source_url,
            rec.retrieved_at.isoformat(),
            rec.source_hash,
        ),
    )
    return source_id


def store_records(conn: sqlite3.Connection, records: list[RawRecord]) -> int:
    """Write normalized rows + their sources idempotently.

    Returns the number of *new* fundamental/price rows actually inserted
    (redeliveries insert 0). This is the observable idempotency signal the
    ingestion test asserts on.
    """
    inserted = 0
    for rec in records:
        source_id = _insert_source(conn, rec)
        p = rec.payload
        if p["kind"] == "fundamental":
            cur = conn.execute(
                """INSERT OR IGNORE INTO fundamentals
                     (ticker, period, metric, value, unit, source_id)
                   VALUES (?,?,?,?,?,?)""",
                (p["ticker"], p["period"], p["concept"], float(p["value"]),
                 p["unit"], source_id),
            )
            inserted += cur.rowcount
        elif p["kind"] == "price":
            cur = conn.execute(
                """INSERT OR IGNORE INTO prices
                     (ticker, ts, open, high, low, close, volume, source_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (p["ticker"], p["ts"], p["open"], p["high"], p["low"],
                 p["close"], p["volume"], source_id),
            )
            inserted += cur.rowcount
        else:  # pragma: no cover - defensive
            raise ValueError(f"unknown record kind: {p.get('kind')!r}")
    conn.commit()
    return inserted


# --------------------------------------------------------------------------- #
# Report persistence (used by the analyst agent + guardrail + read model)
# --------------------------------------------------------------------------- #
def save_report(conn: sqlite3.Connection, report: AnalysisReport) -> None:
    conn.execute(
        """INSERT INTO analysis_reports
             (id, ticker, generated_at, data_as_of, metrics_json, narrative, status)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             status=excluded.status, narrative=excluded.narrative,
             metrics_json=excluded.metrics_json""",
        (
            report.id,
            report.ticker,
            report.generated_at.isoformat(),
            report.data_as_of.isoformat(),
            json.dumps({k: v.model_dump() for k, v in report.metrics.items()}),
            report.narrative,
            report.status.value,
        ),
    )
    conn.execute("DELETE FROM claims WHERE report_id = ?", (report.id,))
    for claim in report.claims:
        conn.execute(
            "INSERT INTO claims(report_id, text, source_id) VALUES (?,?,?)",
            (report.id, claim.text, claim.source_id),
        )
    conn.commit()


def latest_approved_report(
    conn: sqlite3.Connection, ticker: str
) -> sqlite3.Row | None:
    """Read model support (§5.6): serve only APPROVED reports."""
    cur = conn.execute(
        """SELECT * FROM analysis_reports
           WHERE ticker = ? AND status = ?
           ORDER BY generated_at DESC LIMIT 1""",
        (ticker.upper(), Status.APPROVED.value),
    )
    return cur.fetchone()
