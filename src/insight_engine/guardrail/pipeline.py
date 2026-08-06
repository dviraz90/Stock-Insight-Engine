"""Compliance Guardrail — spec §5.5.

A deterministic pipeline. Not an LLM asking an LLM to behave. Any failure ->
reject the whole output, do not patch it (§11.3). Every rejection is logged to
`guardrail_rejections` — the compliance evidence and the primary debug signal.

M0 (spec §9) activates **stage 1 (provenance)** as the gate and stage 4 (framing)
to attach the disclaimer required on every user-facing output (§2.7). Stages 2
(numeric re-extraction) and 3 (directive filter) are scaffolded here and turned
on at M1 — see `numeric_stage` / `directive_stage`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..domain.models import AnalysisReport, Status

DISCLAIMER = (
    "This is educational, informational content only and is not investment "
    "advice, an offer, or a solicitation. Figures are as of the data-as-of "
    "timestamp and may be delayed or revised. Consult a licensed professional "
    "before making any financial decision."
)


@dataclass
class Rejection:
    stage: str
    reason: str
    offending_text: str


@dataclass
class GuardrailResult:
    approved: bool
    report: AnalysisReport
    rejections: list[Rejection] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Stage 1 — Provenance (active at M0). Every claim must carry a source_id that
# resolves to a real row in `sources`.
# --------------------------------------------------------------------------- #
def provenance_stage(
    conn: sqlite3.Connection, report: AnalysisReport
) -> list[Rejection]:
    rejections: list[Rejection] = []
    for claim in report.claims:
        if not claim.source_id:
            rejections.append(
                Rejection("provenance", "claim has no source_id", claim.text)
            )
            continue
        row = conn.execute(
            "SELECT 1 FROM sources WHERE source_id = ?", (claim.source_id,)
        ).fetchone()
        if row is None:
            rejections.append(
                Rejection(
                    "provenance",
                    f"source_id {claim.source_id!r} does not resolve",
                    claim.text,
                )
            )
    # Every metric figure must also be sourced (§2.5 applies to numbers too).
    for key, mv in report.metrics.items():
        if not mv.source_id:
            rejections.append(
                Rejection("provenance", f"metric {key!r} has no source_id", key)
            )
    return rejections


# --------------------------------------------------------------------------- #
# Stage 2 — Numeric (M1). Re-extract every figure from narrative text and diff
# against stored values. Placeholder returns no rejections until M1.
# --------------------------------------------------------------------------- #
def numeric_stage(
    conn: sqlite3.Connection, report: AnalysisReport
) -> list[Rejection]:  # pragma: no cover - M1
    return []


# --------------------------------------------------------------------------- #
# Stage 3 — Directive filter (M1). Regex/rules blocking imperatives, predictions,
# price targets. Placeholder returns no rejections until M1.
# --------------------------------------------------------------------------- #
def directive_stage(
    report: AnalysisReport,
) -> list[Rejection]:  # pragma: no cover - M1
    return []


# --------------------------------------------------------------------------- #
# Stage 4 — Framing. Attach disclaimer + data_as_of + generation timestamp.
# --------------------------------------------------------------------------- #
def framing_stage(report: AnalysisReport) -> AnalysisReport:
    report.disclaimer = DISCLAIMER
    return report


def _log_rejections(
    conn: sqlite3.Connection, report: AnalysisReport, rejections: list[Rejection]
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for r in rejections:
        conn.execute(
            """INSERT INTO guardrail_rejections
                 (subject_type, subject_id, stage, reason, offending_text, created_at)
               VALUES (?,?,?,?,?,?)""",
            ("analysis_report", report.id, r.stage, r.reason, r.offending_text, now),
        )
    conn.commit()


def run(conn: sqlite3.Connection, report: AnalysisReport) -> GuardrailResult:
    """Run the active stages in order. First failing stage rejects the whole
    output; we log and stop (reject, don't patch)."""
    # Stage 1 (active at M0).
    rejections = provenance_stage(conn, report)
    # Stages 2 & 3 activate at M1; wired but currently no-ops.
    rejections += numeric_stage(conn, report)
    rejections += directive_stage(report)

    if rejections:
        report.status = Status.REJECTED
        _log_rejections(conn, report, rejections)
        return GuardrailResult(approved=False, report=report, rejections=rejections)

    framing_stage(report)
    report.status = Status.APPROVED
    return GuardrailResult(approved=True, report=report)
