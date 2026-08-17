"""Tests for `insight_engine.dashboard` — plan.md (dashboard feature).

Shared between two halves of the dashboard work:
  - `build_dashboard_data` (data layer, read_model.py) — tests below.
  - `render` (presentation layer, render_html.py) — append your tests below
    the data-layer ones; don't remove/reorder the existing tests.

Mirrors the DB-setup pattern in `tests/test_guardrail.py`: ingest the bundled
AAPL fixtures into an in-memory DB, then run the analyst agent + guardrail to
get an APPROVED report.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from insight_engine import fixtures
from insight_engine.adapters.edgar import EdgarAdapter
from insight_engine.adapters.price import PriceAdapter
from insight_engine.analysis import analyst_agent
from insight_engine.dashboard.read_model import build_dashboard_data
from insight_engine.domain.models import Status
from insight_engine.guardrail import pipeline as guardrail
from insight_engine.ingestion.pipeline import ingest
from insight_engine.persistence import db


@pytest.fixture()
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    inst = fixtures.INSTRUMENT
    db.upsert_instrument(
        c, ticker=inst["ticker"], name=inst["name"], exchange=inst["exchange"],
        sector=inst["sector"], currency=inst["currency"],
    )
    ingest(c, "AAPL", [
        EdgarAdapter(fixtures.edgar_transport),
        PriceAdapter(fixtures.price_transport),
    ])
    yield c
    c.close()


def _approve_report(conn):
    """Mirror cli.cmd_report's generate -> guardrail -> save sequence."""
    report = analyst_agent.generate_report(conn, "AAPL")
    result = guardrail.run(conn, report)
    db.save_report(conn, result.report)
    assert result.approved  # sanity: fixtures always yield an approvable report
    return result.report


# --------------------------------------------------------------------------- #
# Data layer — build_dashboard_data
# --------------------------------------------------------------------------- #
def test_build_dashboard_data_happy_path(conn):
    saved = _approve_report(conn)

    data = build_dashboard_data(conn, "AAPL")

    inst = fixtures.INSTRUMENT
    assert data.instrument.ticker == inst["ticker"]
    assert data.instrument.name == inst["name"]
    assert data.instrument.exchange == inst["exchange"]
    assert data.instrument.sector == inst["sector"]
    assert data.instrument.currency == inst["currency"]

    assert data.report is not None
    assert data.report.id == saved.id
    assert data.report.status == Status.APPROVED.value
    assert data.report.disclaimer  # hard constraint #7: always attached

    m = data.report.metrics
    assert m["pe_ratio"].value == pytest.approx(20.0)
    assert m["net_margin"].value == pytest.approx(0.25)
    assert m["gross_margin"].value == pytest.approx(0.45)
    assert m["revenue_growth"].value == pytest.approx(0.25)

    # Every source_id referenced anywhere (metrics, claims, fundamentals,
    # prices) must resolve as a key in data.sources — no dangling citations.
    referenced_source_ids = set()
    for mv in data.report.metrics.values():
        referenced_source_ids.add(mv.source_id)
    for claim in data.report.claims:
        if claim.source_id:
            referenced_source_ids.add(claim.source_id)
    for row in data.fundamentals:
        referenced_source_ids.add(row.source_id)
    for row in data.prices:
        referenced_source_ids.add(row.source_id)

    assert referenced_source_ids, "expected at least one sourced figure"
    for sid in referenced_source_ids:
        assert sid in data.sources

    assert data.fundamentals, "expected raw fundamentals rows"
    assert data.prices, "expected raw price rows"
    assert data.rejections == []


def test_build_dashboard_data_no_approved_report_yet(conn):
    # No report generated/approved at all: report must be None, never fabricated.
    data = build_dashboard_data(conn, "AAPL")
    assert data.report is None
    assert data.rejections == []


def test_build_dashboard_data_includes_rejections_for_ticker(conn):
    saved = _approve_report(conn)

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO guardrail_rejections
             (subject_type, subject_id, stage, reason, offending_text, created_at)
           VALUES (?,?,?,?,?,?)""",
        ("analysis_report", saved.id, "provenance", "seeded test rejection",
         "AAPL had strong margins.", now),
    )
    conn.commit()

    data = build_dashboard_data(conn, "AAPL")

    assert len(data.rejections) == 1
    rejection = data.rejections[0]
    assert rejection.stage == "provenance"
    assert rejection.reason == "seeded test rejection"
    assert rejection.offending_text == "AAPL had strong margins."
    assert rejection.created_at == now


# --------------------------------------------------------------------------- #
# Render layer — render_html.render (append below; do not remove the above)
# --------------------------------------------------------------------------- #
from insight_engine.dashboard import render_html  # noqa: E402


def test_render_happy_path_contains_ticker_and_disclaimer(conn):
    _approve_report(conn)
    data = build_dashboard_data(conn, "AAPL")

    out = render_html.render(data)

    assert isinstance(out, str)
    assert "AAPL" in out
    assert data.report.disclaimer in out
    assert "Traceback" not in out
    assert "<object at 0x" not in out
    # status badge for an approved report
    assert "APPROVED" in out
    # a stat tile for a known metric key and its shortened source tag
    assert "pe_ratio".replace("_", " ").title() in out or "Pe Ratio" in out
    sid = data.report.metrics["pe_ratio"].source_id
    assert sid[:12] in out


def test_render_no_report_shows_explicit_empty_state_not_partial_content(conn):
    # No report generated at all: render must show an explicit "no approved
    # report yet" state and must never fabricate metrics/narrative/claims.
    data = build_dashboard_data(conn, "AAPL")
    assert data.report is None

    out = render_html.render(data)

    assert "AAPL" in out
    assert "NO REPORT" in out
    assert "no approved report yet" in out.lower()
    # disclaimer banner is still always present even with no report
    assert "not investment advice" in out.lower()
    assert "Traceback" not in out
    assert "<object at 0x" not in out


def test_render_shows_rejection_trail_when_present(conn):
    saved = _approve_report(conn)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO guardrail_rejections
             (subject_type, subject_id, stage, reason, offending_text, created_at)
           VALUES (?,?,?,?,?,?)""",
        ("analysis_report", saved.id, "provenance", "seeded render test rejection",
         "some offending text", now),
    )
    conn.commit()

    data = build_dashboard_data(conn, "AAPL")
    out = render_html.render(data)

    assert "seeded render test rejection" in out
    assert "some offending text" in out
    assert "provenance" in out


def test_render_escapes_untrusted_text(conn):
    saved = _approve_report(conn)
    data = build_dashboard_data(conn, "AAPL")
    # Mutate narrative/claim text in place to simulate untrusted LLM/fixture
    # output containing HTML — render() must escape it, never inject it raw.
    data.report.narrative = "<script>alert(1)</script> AAPL narrative"
    if data.report.claims:
        data.report.claims[0].text = "<img src=x onerror=alert(1)> claim text"

    out = render_html.render(data)

    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out
    assert "<img src=x onerror=alert(1)>" not in out
