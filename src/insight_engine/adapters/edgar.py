"""EdgarAdapter — spec §5.1.

SEC EDGAR company-facts + filings. Free, stable, well documented. The live
transport hits data.sec.gov; a fixture transport (see fixtures/) lets the whole
vertical slice run offline and deterministically, which is also what the
ingestion/metric tests need.

SEC ToS requires a descriptive User-Agent. No scraping of exchange feeds — EDGAR
is a permitted, licensed public source (§2 "Also constrained").
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from .base import RawRecord

SOURCE_NAME = "SEC EDGAR"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# Transport: ticker -> raw provider JSON. Injected so the adapter has no opinion
# about HTTP vs fixture (dependency inversion at the edge).
Transport = Callable[[str], dict[str, Any]]


def _http_transport(user_agent: str) -> Transport:
    """Real transport against data.sec.gov. Requires network egress to sec.gov
    (not available in every sandbox — use the fixture transport for offline)."""

    def fetch_json(ticker: str) -> dict[str, Any]:
        import json
        import urllib.request

        cik = _resolve_cik(ticker, user_agent)
        url = COMPANY_FACTS_URL.format(cik=cik)
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))

    return fetch_json


def _resolve_cik(ticker: str, user_agent: str) -> int:
    import json
    import urllib.request

    url = "https://www.sec.gov/files/company_tickers.json"
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        table = json.loads(resp.read().decode("utf-8"))
    for row in table.values():
        if row["ticker"].upper() == ticker.upper():
            return int(row["cik_str"])
    raise LookupError(f"ticker not found on EDGAR: {ticker}")


class EdgarAdapter:
    """Adapter for SEC EDGAR. Conforms to the DataAdapter port."""

    def __init__(
        self,
        transport: Transport,
        *,
        source_url: str = "https://data.sec.gov",
    ) -> None:
        self._transport = transport
        self._source_url = source_url

    def fetch(self, ticker: str, since: datetime) -> list[RawRecord]:
        raw = self._transport(ticker)
        records: list[RawRecord] = []

        # One record per (fact, period). EDGAR nests facts under
        # facts -> us-gaap -> <Concept> -> units -> <unit> -> [ {end, val, ...} ].
        gaap = raw.get("facts", {}).get("us-gaap", {})
        for concept, body in gaap.items():
            for unit, points in body.get("units", {}).items():
                for point in points:
                    end = point.get("end")
                    if not end:
                        continue
                    if _parse_date(end) < since:
                        continue
                    payload = {
                        "kind": "fundamental",
                        "ticker": ticker.upper(),
                        "concept": concept,
                        "period": point.get("fp") and f"{point.get('fy')}{point['fp']}"
                        or end,
                        "value": point["val"],
                        "unit": unit,
                        "end": end,
                        "form": point.get("form"),
                    }
                    records.append(
                        RawRecord.build(
                            payload,
                            source_name=SOURCE_NAME,
                            source_url=f"{self._source_url}/api/xbrl/companyfacts",
                        )
                    )
        return records


def _parse_date(s: str) -> datetime:
    return datetime.fromisoformat(s)
