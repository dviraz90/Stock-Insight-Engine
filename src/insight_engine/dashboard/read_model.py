"""Dashboard data layer — plan.md §1.

Pure, DB-reading assembly of one JSON-serializable snapshot per ticker. No HTML,
no CLI, no I/O beyond the given `sqlite3.Connection`. This is deliberately the
shape a future `GET /dashboard/{ticker}` (M3) would return verbatim via
`.model_dump(mode="json")`, so the render layer (and eventually a web server)
never needs its own joins.

Never fabricates: if no APPROVED report exists yet for the ticker, `report` is
None (spec §5.6 — never serve unapproved/partial content).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from pydantic import BaseModel

from ..domain.models import Claim, Instrument, MetricValue
from ..guardrail.pipeline import DISCLAIMER
from ..persistence import db


class SourceView(BaseModel):
    source_id: str
    source_name: str
    source_url: str
    retrieved_at: str


class FundamentalRow(BaseModel):
    period: str
    metric: str
    value: float
    unit: str
    source_id: str


class PriceRow(BaseModel):
    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    source_id: str


class RejectionView(BaseModel):
    stage: str
    reason: str
    offending_text: str
    created_at: str


class ReportView(BaseModel):
    id: str
    status: str
    generated_at: datetime
    data_as_of: datetime
    metrics: dict[str, MetricValue]  # reuse domain.MetricValue
    narrative: str
    claims: list[Claim]  # reuse domain.Claim
    disclaimer: str | None


class DashboardData(BaseModel):
    generated_at: datetime
    instrument: Instrument  # reuse domain.Instrument
    report: ReportView | None  # None only if no approved report exists yet
    rejections: list[RejectionView]
    fundamentals: list[FundamentalRow]
    prices: list[PriceRow]
    sources: dict[str, SourceView]  # keyed by source_id, for citation lookups


def _instrument_from_row(row: sqlite3.Row) -> Instrument:
    return Instrument(
        ticker=row["ticker"],
        name=row["name"],
        exchange=row["exchange"],
        sector=row["sector"],
        currency=row["currency"],
    )


def _report_view_from_row(
    conn: sqlite3.Connection, row: sqlite3.Row, source_ids: set[str]
) -> ReportView:
    metrics_raw = json.loads(row["metrics_json"])
    metrics = {key: MetricValue(**mv) for key, mv in metrics_raw.items()}
    for mv in metrics.values():
        if mv.source_id:
            source_ids.add(mv.source_id)

    claim_rows = conn.execute(
        "SELECT text, source_id FROM claims WHERE report_id = ?", (row["id"],)
    ).fetchall()
    claims = [Claim(text=r["text"], source_id=r["source_id"]) for r in claim_rows]
    for claim in claims:
        if claim.source_id:
            source_ids.add(claim.source_id)

    # `analysis_reports` has no `disclaimer` column (schema.sql is untouched by
    # this feature) — the framing stage attaches this exact constant to every
    # report that reaches APPROVED status, so reconstructing it here from the
    # constant is faithful reconstruction, not fabrication (spec §2.7).
    return ReportView(
        id=row["id"],
        status=row["status"],
        generated_at=row["generated_at"],
        data_as_of=row["data_as_of"],
        metrics=metrics,
        narrative=row["narrative"],
        claims=claims,
        disclaimer=DISCLAIMER,
    )


def _rejections_for_ticker(
    conn: sqlite3.Connection, ticker: str
) -> list[RejectionView]:
    # guardrail_rejections has no ticker column (schema.sql is untouched); the
    # guardrail always logs with subject_type="analysis_report" and
    # subject_id=report.id (see guardrail/pipeline.py:_log_rejections), so join
    # through analysis_reports to scope rejections to this ticker.
    rows = conn.execute(
        """SELECT gr.stage, gr.reason, gr.offending_text, gr.created_at
             FROM guardrail_rejections gr
             JOIN analysis_reports ar ON ar.id = gr.subject_id
            WHERE gr.subject_type = 'analysis_report' AND ar.ticker = ?
            ORDER BY gr.created_at""",
        (ticker,),
    ).fetchall()
    return [
        RejectionView(
            stage=r["stage"],
            reason=r["reason"],
            offending_text=r["offending_text"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


def _fundamentals_for_ticker(
    conn: sqlite3.Connection, ticker: str, source_ids: set[str]
) -> list[FundamentalRow]:
    rows = conn.execute(
        """SELECT period, metric, value, unit, source_id FROM fundamentals
            WHERE ticker = ? ORDER BY period, metric""",
        (ticker,),
    ).fetchall()
    out = [
        FundamentalRow(
            period=r["period"],
            metric=r["metric"],
            value=r["value"],
            unit=r["unit"],
            source_id=r["source_id"],
        )
        for r in rows
    ]
    source_ids.update(r.source_id for r in out if r.source_id)
    return out


def _prices_for_ticker(
    conn: sqlite3.Connection, ticker: str, source_ids: set[str]
) -> list[PriceRow]:
    rows = conn.execute(
        """SELECT ts, open, high, low, close, volume, source_id FROM prices
            WHERE ticker = ? ORDER BY ts""",
        (ticker,),
    ).fetchall()
    out = [
        PriceRow(
            ts=r["ts"],
            open=r["open"],
            high=r["high"],
            low=r["low"],
            close=r["close"],
            volume=r["volume"],
            source_id=r["source_id"],
        )
        for r in rows
    ]
    source_ids.update(r.source_id for r in out if r.source_id)
    return out


def _sources_by_id(
    conn: sqlite3.Connection, source_ids: set[str]
) -> dict[str, SourceView]:
    sources: dict[str, SourceView] = {}
    for source_id in source_ids:
        if not source_id:
            continue
        row = conn.execute(
            "SELECT source_id, source_name, source_url, retrieved_at FROM sources"
            " WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        if row is not None:
            sources[source_id] = SourceView(
                source_id=row["source_id"],
                source_name=row["source_name"],
                source_url=row["source_url"],
                retrieved_at=row["retrieved_at"],
            )
    return sources


def build_dashboard_data(conn: sqlite3.Connection, ticker: str) -> DashboardData:
    """Assemble one snapshot of everything the pipeline knows about `ticker`.

    Never fabricates: `report` is None if no APPROVED report has ever been
    saved for this ticker.
    """
    ticker = ticker.upper()

    inst_row = conn.execute(
        "SELECT ticker, name, exchange, sector, currency FROM instruments"
        " WHERE ticker = ?",
        (ticker,),
    ).fetchone()
    if inst_row is None:
        raise LookupError(f"no instrument found for ticker {ticker!r}")
    instrument = _instrument_from_row(inst_row)

    source_ids: set[str] = set()

    report: ReportView | None = None
    report_row = db.latest_approved_report(conn, ticker)
    if report_row is not None:
        report = _report_view_from_row(conn, report_row, source_ids)

    rejections = _rejections_for_ticker(conn, ticker)
    fundamentals = _fundamentals_for_ticker(conn, ticker, source_ids)
    prices = _prices_for_ticker(conn, ticker, source_ids)
    sources = _sources_by_id(conn, source_ids)

    return DashboardData(
        generated_at=datetime.now(timezone.utc),
        instrument=instrument,
        report=report,
        rejections=rejections,
        fundamentals=fundamentals,
        prices=prices,
        sources=sources,
    )
