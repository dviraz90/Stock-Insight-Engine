"""Analyst tool contracts — spec §5.3.

Typed in, typed out. Every result carries a source_id. No tool returns free text
the model can silently reinterpret as fact. The LLM orchestrates these; code
computes. `compute_metrics` is the deterministic core in metrics.py.
"""

from __future__ import annotations

import sqlite3

from pydantic import BaseModel

from ..domain.models import MetricValue
from . import metrics as metrics_mod


# --------------------------------------------------------------------------- #
# Typed tool outputs
# --------------------------------------------------------------------------- #
class SourcedFigure(BaseModel):
    metric: str
    value: float
    unit: str
    period: str
    source_id: str


class Fundamentals(BaseModel):
    ticker: str
    figures: list[SourcedFigure]


class PricePoint(BaseModel):
    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    source_id: str


class PriceSeries(BaseModel):
    ticker: str
    points: list[PricePoint]


class Metrics(BaseModel):
    ticker: str
    values: dict[str, MetricValue]


class Filing(BaseModel):
    type: str
    filed_at: str
    url: str
    source_id: str


class Passage(BaseModel):
    text: str
    source_id: str


# --------------------------------------------------------------------------- #
# Tool implementations (code side of §5.3). Pure DB reads + the metric core.
# --------------------------------------------------------------------------- #
class AnalystTools:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_fundamentals(self, ticker: str, period: str | None = None) -> Fundamentals:
        sql = (
            "SELECT metric, value, unit, period, source_id FROM fundamentals "
            "WHERE ticker = ?"
        )
        args: list[object] = [ticker.upper()]
        if period:
            sql += " AND period = ?"
            args.append(period)
        sql += " ORDER BY period ASC, metric ASC"
        rows = self._conn.execute(sql, args).fetchall()
        return Fundamentals(
            ticker=ticker.upper(),
            figures=[
                SourcedFigure(
                    metric=r["metric"], value=r["value"], unit=r["unit"],
                    period=r["period"], source_id=r["source_id"],
                )
                for r in rows
            ],
        )

    def get_price_series(self, ticker: str, range_: str = "all") -> PriceSeries:
        rows = self._conn.execute(
            """SELECT ts, open, high, low, close, volume, source_id
               FROM prices WHERE ticker = ? ORDER BY ts ASC""",
            (ticker.upper(),),
        ).fetchall()
        return PriceSeries(
            ticker=ticker.upper(),
            points=[
                PricePoint(
                    ts=r["ts"], open=r["open"], high=r["high"], low=r["low"],
                    close=r["close"], volume=r["volume"], source_id=r["source_id"],
                )
                for r in rows
            ],
        )

    def compute_metrics(self, ticker: str) -> Metrics:
        return Metrics(
            ticker=ticker.upper(),
            values=metrics_mod.compute_metrics(self._conn, ticker),
        )

    def get_filings(
        self, ticker: str, type_: str | None = None, since: str | None = None
    ) -> list[Filing]:
        sql = "SELECT type, filed_at, url, source_id FROM filings WHERE ticker = ?"
        args: list[object] = [ticker.upper()]
        if type_:
            sql += " AND type = ?"
            args.append(type_)
        if since:
            sql += " AND filed_at >= ?"
            args.append(since)
        rows = self._conn.execute(sql, args).fetchall()
        return [
            Filing(type=r["type"], filed_at=r["filed_at"], url=r["url"],
                   source_id=r["source_id"])
            for r in rows
        ]

    def search_context(self, ticker: str, query: str) -> list[Passage]:
        """RAG over filings/news. M2 decides embeddings vs keyword (§12). M0
        ships a keyword scan so the tool contract is real and testable."""
        rows = self._conn.execute(
            "SELECT raw_text, source_id FROM filings WHERE ticker = ?",
            (ticker.upper(),),
        ).fetchall()
        needle = query.lower()
        passages: list[Passage] = []
        for r in rows:
            for line in r["raw_text"].splitlines():
                if needle in line.lower():
                    passages.append(Passage(text=line.strip(), source_id=r["source_id"]))
        return passages
