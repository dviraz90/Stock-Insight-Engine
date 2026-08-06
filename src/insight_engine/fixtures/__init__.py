"""Offline fixtures for one hardcoded ticker (spec M0: "one hardcoded ticker").

These let the vertical slice run end to end without network egress to sec.gov or
a price provider. The transports match the *shape* the live transports return,
so swapping to live is just changing which transport the adapter is built with.

Numbers are chosen round so the end-to-end path is easy to eyeball. The pure
metric unit tests (§10) use their own hand inputs and do not depend on these.
"""

from __future__ import annotations

from typing import Any

HARDCODED_TICKER = "AAPL"

INSTRUMENT = {
    "ticker": "AAPL",
    "name": "Apple Inc.",
    "exchange": "NASDAQ",
    "sector": "Technology",
    "currency": "USD",
}

# EDGAR company-facts shape: facts -> us-gaap -> Concept -> units -> unit -> [pts]
_EDGAR_COMPANY_FACTS: dict[str, Any] = {
    "cik": 320193,
    "entityName": "Apple Inc.",
    "facts": {
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        {"end": "2023-09-30", "val": 80000, "fy": 2023, "fp": "FY",
                         "form": "10-K"},
                        {"end": "2024-09-30", "val": 100000, "fy": 2024, "fp": "FY",
                         "form": "10-K"},
                    ]
                }
            },
            "GrossProfit": {
                "units": {
                    "USD": [
                        {"end": "2024-09-30", "val": 45000, "fy": 2024, "fp": "FY",
                         "form": "10-K"},
                    ]
                }
            },
            "NetIncomeLoss": {
                "units": {
                    "USD": [
                        {"end": "2024-09-30", "val": 25000, "fy": 2024, "fp": "FY",
                         "form": "10-K"},
                    ]
                }
            },
            "EarningsPerShareBasic": {
                "units": {
                    "USD/shares": [
                        {"end": "2024-09-30", "val": 5.0, "fy": 2024, "fp": "FY",
                         "form": "10-K"},
                    ]
                }
            },
        }
    },
}

# Daily OHLCV bars (ascending). Latest close = 100.0 -> P/E = 100/5 = 20.
_PRICE_BARS: list[dict[str, Any]] = [
    {"date": "2024-11-01", "open": 96, "high": 99, "low": 95, "close": 98, "volume": 1_000_000},
    {"date": "2024-11-04", "open": 98, "high": 103, "low": 97, "close": 102, "volume": 1_100_000},
    {"date": "2024-11-05", "open": 102, "high": 104, "low": 99, "close": 101, "volume": 900_000},
    {"date": "2024-11-06", "open": 101, "high": 102, "low": 98, "close": 100, "volume": 1_050_000},
]


def edgar_transport(ticker: str) -> dict[str, Any]:
    if ticker.upper() != HARDCODED_TICKER:
        raise LookupError(f"no fixture for {ticker!r}; M0 ships {HARDCODED_TICKER} only")
    return _EDGAR_COMPANY_FACTS


def price_transport(ticker: str) -> list[dict[str, Any]]:
    if ticker.upper() != HARDCODED_TICKER:
        raise LookupError(f"no fixture for {ticker!r}; M0 ships {HARDCODED_TICKER} only")
    return list(_PRICE_BARS)
