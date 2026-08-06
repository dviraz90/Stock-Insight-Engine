"""Domain events — spec §5.2 (emitted by ingestion) and §7 (event flow).

M0 keeps these as plain records; the in-process queue (§8) is added at M3.
They exist now so ingestion has a real thing to emit and analysis a real thing
to react to.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DomainEvent:
    ticker: str
    occurred_at: datetime


@dataclass(frozen=True)
class PriceUpdated(DomainEvent):
    pass


@dataclass(frozen=True)
class FilingPublished(DomainEvent):
    filing_type: str


@dataclass(frozen=True)
class FundamentalsRevised(DomainEvent):
    period: str
