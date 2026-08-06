"""Metric computation — spec §5.3.

`compute_metrics` calculates P/E, margins, growth rates, volatility **in Python**.
The LLM never does arithmetic (§2 "Also constrained", §11.2). The pure functions
below are the unit-tested core (§10 "Metrics: pure unit tests, no LLM").
"""

from __future__ import annotations

import sqlite3
from statistics import stdev

from ..domain.models import MetricValue

# --------------------------------------------------------------------------- #
# Pure math — no I/O, fully unit-tested. Return None when undefined rather than
# raising or inventing a number.
# --------------------------------------------------------------------------- #
def pe_ratio(price: float, eps: float) -> float | None:
    if eps == 0:
        return None
    return price / eps


def net_margin(net_income: float, revenue: float) -> float | None:
    if revenue == 0:
        return None
    return net_income / revenue


def gross_margin(gross_profit: float, revenue: float) -> float | None:
    if revenue == 0:
        return None
    return gross_profit / revenue


def growth_rate(previous: float, current: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / previous


def simple_returns(closes: list[float]) -> list[float]:
    return [
        (closes[i] / closes[i - 1]) - 1.0
        for i in range(1, len(closes))
        if closes[i - 1] != 0
    ]


def daily_volatility(closes: list[float]) -> float | None:
    """Sample standard deviation of daily simple returns. Needs >= 3 closes
    (>= 2 returns) for a sample stdev."""
    rets = simple_returns(closes)
    if len(rets) < 2:
        return None
    return stdev(rets)


# --------------------------------------------------------------------------- #
# DB-backed assembly — reads verified rows, attaches provenance to each figure.
# Every MetricValue carries the source_id of its primary input (§2.5, §11.5).
# --------------------------------------------------------------------------- #
def _latest_fundamental(
    conn: sqlite3.Connection, ticker: str, metric: str
) -> sqlite3.Row | None:
    cur = conn.execute(
        """SELECT value, unit, period, source_id FROM fundamentals
           WHERE ticker = ? AND metric = ?
           ORDER BY period DESC LIMIT 1""",
        (ticker.upper(), metric),
    )
    return cur.fetchone()


def _fundamental_series(
    conn: sqlite3.Connection, ticker: str, metric: str
) -> list[sqlite3.Row]:
    cur = conn.execute(
        """SELECT value, unit, period, source_id FROM fundamentals
           WHERE ticker = ? AND metric = ? ORDER BY period ASC""",
        (ticker.upper(), metric),
    )
    return cur.fetchall()


def _price_closes(conn: sqlite3.Connection, ticker: str) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT ts, close, source_id FROM prices WHERE ticker = ? ORDER BY ts ASC",
        (ticker.upper(),),
    )
    return cur.fetchall()


def compute_metrics(conn: sqlite3.Connection, ticker: str) -> dict[str, MetricValue]:
    """Assemble the metric set for a ticker from verified rows.

    Each metric that can be computed from available data is emitted as a
    MetricValue with a source_id. Missing inputs simply omit that metric —
    the system never fabricates a figure.
    """
    metrics: dict[str, MetricValue] = {}

    revenue = _latest_fundamental(conn, ticker, "Revenues")
    net_income = _latest_fundamental(conn, ticker, "NetIncomeLoss")
    gross_profit = _latest_fundamental(conn, ticker, "GrossProfit")
    eps = _latest_fundamental(conn, ticker, "EarningsPerShareBasic")
    closes = _price_closes(conn, ticker)

    if eps and closes:
        pe = pe_ratio(closes[-1]["close"], eps["value"])
        if pe is not None:
            # Ratio combines price + EPS; cite the price close as primary input.
            metrics["pe_ratio"] = MetricValue(
                value=round(pe, 4), unit="ratio", source_id=closes[-1]["source_id"]
            )

    if net_income and revenue:
        nm = net_margin(net_income["value"], revenue["value"])
        if nm is not None:
            metrics["net_margin"] = MetricValue(
                value=round(nm, 4), unit="fraction", source_id=net_income["source_id"]
            )

    if gross_profit and revenue:
        gm = gross_margin(gross_profit["value"], revenue["value"])
        if gm is not None:
            metrics["gross_margin"] = MetricValue(
                value=round(gm, 4), unit="fraction", source_id=gross_profit["source_id"]
            )

    rev_series = _fundamental_series(conn, ticker, "Revenues")
    if len(rev_series) >= 2:
        g = growth_rate(rev_series[-2]["value"], rev_series[-1]["value"])
        if g is not None:
            metrics["revenue_growth"] = MetricValue(
                value=round(g, 4), unit="fraction", source_id=rev_series[-1]["source_id"]
            )

    if len(closes) >= 3:
        vol = daily_volatility([c["close"] for c in closes])
        if vol is not None:
            metrics["daily_volatility"] = MetricValue(
                value=round(vol, 6), unit="stdev_of_daily_return",
                source_id=closes[-1]["source_id"],
            )

    return metrics
