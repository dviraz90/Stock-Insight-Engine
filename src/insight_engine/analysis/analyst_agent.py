"""Analyst agent — spec §5.3.

The LLM orchestrates; code computes. The agent runs the deterministic tools,
caps tool-call depth so one report cannot spiral, hands the sourced results to
the LLM client to compose an explanation, and returns a structured
`AnalysisReport` in DRAFT. Approval is the guardrail's job, never the agent's.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from ..domain.models import AnalysisReport, Status
from .llm import LLMClient, StubLLMClient
from .tools import AnalystTools

MAX_TOOL_CALLS = 12  # §5.3 "Cap tool-call depth (suggest: 12 calls / report)"


class ToolBudgetExceeded(RuntimeError):
    pass


class _CountingTools:
    """Wraps AnalystTools to enforce the per-report tool-call cap."""

    def __init__(self, tools: AnalystTools, budget: int) -> None:
        self._tools = tools
        self._remaining = budget

    def __getattr__(self, name: str):
        attr = getattr(self._tools, name)
        if not callable(attr):
            return attr

        def guarded(*args, **kwargs):
            if self._remaining <= 0:
                raise ToolBudgetExceeded(
                    f"exceeded {MAX_TOOL_CALLS} tool calls for one report"
                )
            self._remaining -= 1
            return attr(*args, **kwargs)

        return guarded


def generate_report(
    conn: sqlite3.Connection,
    ticker: str,
    *,
    llm: LLMClient | None = None,
    max_tool_calls: int = MAX_TOOL_CALLS,
) -> AnalysisReport:
    llm = llm or StubLLMClient()
    tools = _CountingTools(AnalystTools(conn), max_tool_calls)

    # Deterministic orchestration for M0 (fixed tool plan). Each call is metered.
    metrics = tools.compute_metrics(ticker).values
    _ = tools.get_fundamentals(ticker)      # gathered for provenance/audit
    price_series = tools.get_price_series(ticker)

    data_as_of = _latest_price_ts(price_series) or datetime.now(timezone.utc)

    composition = llm.compose(ticker, metrics)

    return AnalysisReport(
        id=str(uuid.uuid4()),
        ticker=ticker.upper(),
        generated_at=datetime.now(timezone.utc),
        data_as_of=data_as_of,
        metrics=metrics,
        narrative=composition.narrative,
        claims=composition.claims,
        status=Status.DRAFT,
    )


def _latest_price_ts(price_series) -> datetime | None:
    if not price_series.points:
        return None
    return datetime.fromisoformat(price_series.points[-1].ts)
