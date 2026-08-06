"""Data adapter port — spec §5.1.

One module per source, all behind the `DataAdapter` port. The domain must not
know which provider is in use (§11.4: ports and adapters at the edges only).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class RawRecord(BaseModel):
    """Every record a provider returns, wrapped with provenance (§5.1).

    `payload` is the normalized-but-still-source-shaped data; the raw payload is
    persisted alongside normalized data for audit + reprocessing (§5.2).
    """

    payload: dict[str, Any]
    source_name: str
    retrieved_at: datetime
    source_url: str
    source_hash: str

    @staticmethod
    def hash_payload(payload: dict[str, Any]) -> str:
        """Stable content hash used for the ingestion dedupe key (§5.2)."""
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def build(
        cls,
        payload: dict[str, Any],
        *,
        source_name: str,
        source_url: str,
        retrieved_at: datetime | None = None,
    ) -> "RawRecord":
        return cls(
            payload=payload,
            source_name=source_name,
            retrieved_at=retrieved_at or datetime.now(timezone.utc),
            source_url=source_url,
            source_hash=cls.hash_payload(payload),
        )


@runtime_checkable
class DataAdapter(Protocol):
    """The narrow port (§5.1). Keep it narrow so swapping providers is cheap."""

    def fetch(self, ticker: str, since: datetime) -> list[RawRecord]: ...
