"""PriceAdapter — spec §5.1.

One price/fundamentals provider. The interface is deliberately narrow so the
concrete provider can be swapped once the free-tier decision in §12 is made.
Transport is injected (HTTP for live, fixture for offline/tests).

Provider is intentionally abstract here: normalize whatever the provider returns
into a list of daily OHLCV points. No exchange-feed scraping (§2).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from .base import RawRecord

SOURCE_NAME = "PriceProvider"

# Transport: ticker -> list of daily bars as plain dicts with keys
# {date, open, high, low, close, volume}. Provider-specific parsing lives in the
# transport, not the adapter.
Transport = Callable[[str], list[dict[str, Any]]]


class PriceAdapter:
    def __init__(
        self,
        transport: Transport,
        *,
        source_name: str = SOURCE_NAME,
        source_url: str = "https://example-price-provider.invalid",
    ) -> None:
        self._transport = transport
        self._source_name = source_name
        self._source_url = source_url

    def fetch(self, ticker: str, since: datetime) -> list[RawRecord]:
        bars = self._transport(ticker)
        records: list[RawRecord] = []
        for bar in bars:
            ts = _parse_date(bar["date"])
            if ts < since:
                continue
            payload = {
                "kind": "price",
                "ticker": ticker.upper(),
                "ts": bar["date"],
                "open": float(bar["open"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
                "close": float(bar["close"]),
                "volume": int(bar["volume"]),
            }
            records.append(
                RawRecord.build(
                    payload,
                    source_name=self._source_name,
                    source_url=self._source_url,
                )
            )
        return records


def _parse_date(s: str) -> datetime:
    return datetime.fromisoformat(s)
