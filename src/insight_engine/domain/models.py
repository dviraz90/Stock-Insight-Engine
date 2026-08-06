"""Domain model — spec §4. Four aggregates. Keep them boring.

Plain Pydantic. No provider knowledge, no LLM knowledge, no SQL knowledge lives
here (engineering principle §11.4: the domain core stays plain Python).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Status(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# --------------------------------------------------------------------------- #
# Value objects
# --------------------------------------------------------------------------- #
class MetricValue(BaseModel):
    """A single computed figure. Every number is traceable to a source (§2.5)."""

    value: float
    unit: str
    source_id: str


class Claim(BaseModel):
    """A factual statement in a narrative. A claim without a source_id is
    rejected by the guardrail (§2.5, guardrail stage 1)."""

    text: str
    # Optional at the type level so a *malformed* (unsourced) claim can still be
    # constructed and then correctly REJECTED by the guardrail. The guardrail —
    # not the type system — is the enforcement point.
    source_id: str | None = None


# --------------------------------------------------------------------------- #
# Aggregates
# --------------------------------------------------------------------------- #
class Instrument(BaseModel):
    ticker: str
    name: str
    exchange: str
    sector: str
    currency: str


class AnalysisReport(BaseModel):
    id: str
    ticker: str
    generated_at: datetime
    data_as_of: datetime
    metrics: dict[str, MetricValue] = Field(default_factory=dict)
    narrative: str = ""
    claims: list[Claim] = Field(default_factory=list)
    status: Status = Status.DRAFT
    # Populated by the guardrail's framing stage (§5.5 stage 4). Empty until then.
    disclaimer: str | None = None


class Insight(BaseModel):
    id: str
    report_id: str
    user_id: str
    generated_at: datetime
    context: str = ""
    considerations: list[str] = Field(default_factory=list)
    status: Status = Status.DRAFT


class UserProfile(BaseModel):
    user_id: str
    watchlist: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
