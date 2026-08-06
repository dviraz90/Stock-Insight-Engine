"""§10 Guardrail (most important): an adversarial corpus that *should* be
rejected. M0 activates stage 1 (provenance); the "done when" criterion is that
an unsourced claim is rejected.

Also snapshot-tests the analyst agent's structured-output *shape* (not wording).
"""

import pytest

from insight_engine import fixtures
from insight_engine.adapters.edgar import EdgarAdapter
from insight_engine.adapters.price import PriceAdapter
from insight_engine.analysis import analyst_agent
from insight_engine.domain.models import (
    AnalysisReport,
    Claim,
    MetricValue,
    Status,
)
from insight_engine.guardrail import pipeline as guardrail
from insight_engine.ingestion.pipeline import ingest
from insight_engine.persistence import db
from datetime import datetime, timezone


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


def _valid_source_id(conn):
    return conn.execute("SELECT source_id FROM sources LIMIT 1").fetchone()["source_id"]


def _rejection_count(conn):
    return conn.execute(
        "SELECT COUNT(*) AS n FROM guardrail_rejections"
    ).fetchone()["n"]


def _bare_report(**kw) -> AnalysisReport:
    base = dict(
        id="r-test",
        ticker="AAPL",
        generated_at=datetime.now(timezone.utc),
        data_as_of=datetime.now(timezone.utc),
    )
    base.update(kw)
    return AnalysisReport(**base)


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_fully_sourced_report_is_approved(conn):
    report = analyst_agent.generate_report(conn, "AAPL")
    result = guardrail.run(conn, report)
    assert result.approved
    assert result.report.status is Status.APPROVED
    assert result.report.disclaimer  # framing stage attached the disclaimer
    assert _rejection_count(conn) == 0


# --------------------------------------------------------------------------- #
# Adversarial: these MUST be rejected and logged
# --------------------------------------------------------------------------- #
def test_unsourced_claim_is_rejected(conn):
    # The M0 "done when" criterion.
    report = _bare_report(
        narrative="AAPL had strong margins.",
        claims=[Claim(text="AAPL net margin is 25%.", source_id=None)],
    )
    result = guardrail.run(conn, report)
    assert not result.approved
    assert result.report.status is Status.REJECTED
    assert any(r.stage == "provenance" for r in result.rejections)
    assert _rejection_count(conn) == 1


def test_unresolvable_source_id_is_rejected(conn):
    report = _bare_report(
        narrative="fabricated provenance",
        claims=[Claim(text="AAPL revenue grew.", source_id="deadbeef-not-real")],
    )
    result = guardrail.run(conn, report)
    assert not result.approved
    assert any("does not resolve" in r.reason for r in result.rejections)
    assert _rejection_count(conn) == 1


def test_unsourced_metric_is_rejected(conn):
    sid = _valid_source_id(conn)
    report = _bare_report(
        metrics={
            "net_margin": MetricValue(value=0.25, unit="fraction", source_id=""),
        },
        claims=[Claim(text="AAPL margin note.", source_id=sid)],
    )
    result = guardrail.run(conn, report)
    assert not result.approved
    assert any("metric" in r.reason for r in result.rejections)


def test_one_bad_claim_rejects_whole_report_not_patched(conn):
    sid = _valid_source_id(conn)
    report = _bare_report(
        claims=[
            Claim(text="AAPL sourced claim.", source_id=sid),
            Claim(text="AAPL unsourced claim.", source_id=None),
        ],
    )
    result = guardrail.run(conn, report)
    # reject, don't patch: the whole report is rejected, claims are not stripped
    assert not result.approved
    assert len(result.report.claims) == 2


# --------------------------------------------------------------------------- #
# Agent output shape (snapshot the shape, not the wording — §10)
# --------------------------------------------------------------------------- #
def test_agent_output_shape(conn):
    report = analyst_agent.generate_report(conn, "AAPL")
    assert report.status is Status.DRAFT
    assert isinstance(report.narrative, str) and report.narrative
    assert report.metrics, "expected computed metrics"
    for mv in report.metrics.values():
        assert mv.source_id  # every figure sourced
    for claim in report.claims:
        assert claim.source_id  # stub emits only sourced claims


def test_known_metric_values_end_to_end(conn):
    # Sanity that the fixture path yields the round numbers the fixtures imply.
    m = analyst_agent.generate_report(conn, "AAPL").metrics
    assert m["pe_ratio"].value == pytest.approx(20.0)      # 100 / 5
    assert m["net_margin"].value == pytest.approx(0.25)     # 25000 / 100000
    assert m["gross_margin"].value == pytest.approx(0.45)   # 45000 / 100000
    assert m["revenue_growth"].value == pytest.approx(0.25)  # (100000-80000)/80000
