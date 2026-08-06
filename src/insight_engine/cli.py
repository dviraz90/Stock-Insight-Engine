"""CLI — spec §9 M0 "CLI command that prints an approved report".

Wires the whole vertical slice for one hardcoded ticker:

    ingest  ->  compute_metrics  ->  analyst agent (DRAFT)
            ->  guardrail (stage 1)  ->  print APPROVED report

Offline by default (uses the bundled fixtures + StubLLMClient) so it runs with no
network egress and no API key. `--live` switches the adapters/LLM to real
implementations once providers and a key are configured.

Usage:
    python -m insight_engine.cli ingest [--db PATH] [--ticker AAPL]
    python -m insight_engine.cli report [--db PATH] [--ticker AAPL]
"""

from __future__ import annotations

import argparse
import sys

from . import fixtures
from .adapters.edgar import EdgarAdapter
from .adapters.price import PriceAdapter
from .analysis import analyst_agent
from .analysis.llm import AnthropicLLMClient, StubLLMClient
from .guardrail import pipeline as guardrail
from .ingestion.pipeline import ingest as ingest_pipeline
from .persistence import db


def _build_adapters(live: bool, user_agent: str):
    if live:
        from .adapters.edgar import _http_transport  # real transport

        # NOTE: a live PriceAdapter transport depends on the provider chosen in
        # spec §12; not shipped in M0. EDGAR live transport is available.
        edgar = EdgarAdapter(_http_transport(user_agent))
        raise SystemExit(
            "live mode needs a configured price provider (spec §12 open decision). "
            "Run without --live to use bundled fixtures."
        )
    edgar = EdgarAdapter(fixtures.edgar_transport)
    price = PriceAdapter(fixtures.price_transport)
    return [edgar, price]


def _prepare(conn, ticker: str, live: bool, user_agent: str) -> int:
    db.init_db(conn)
    inst = fixtures.INSTRUMENT
    db.upsert_instrument(
        conn,
        ticker=inst["ticker"], name=inst["name"], exchange=inst["exchange"],
        sector=inst["sector"], currency=inst["currency"],
    )
    adapters = _build_adapters(live, user_agent)
    new_rows, _events = ingest_pipeline(conn, ticker, adapters)
    return new_rows


def cmd_ingest(args) -> int:
    conn = db.connect(args.db)
    new_rows = _prepare(conn, args.ticker, args.live, args.user_agent)
    print(f"Ingested {new_rows} new row(s) for {args.ticker}.")
    return 0


def cmd_report(args) -> int:
    conn = db.connect(args.db)
    _prepare(conn, args.ticker, args.live, args.user_agent)

    llm = AnthropicLLMClient() if args.live else StubLLMClient()
    report = analyst_agent.generate_report(conn, args.ticker, llm=llm)
    result = guardrail.run(conn, report)
    db.save_report(conn, result.report)

    if not result.approved:
        # §5.6: never show unapproved content; fall back to previous approved.
        print(f"[REJECTED] new report for {args.ticker} failed the guardrail:")
        for r in result.rejections:
            print(f"  - stage={r.stage} reason={r.reason} text={r.offending_text!r}")
        prev = db.latest_approved_report(conn, args.ticker)
        if prev is None:
            print("No previously approved report to serve.")
            return 1
        print("\nServing last approved report instead:\n")
        _print_row(prev)
        return 0

    _print_report(result.report)
    return 0


def _print_report(report) -> None:
    print("=" * 68)
    print(f"ANALYSIS REPORT — {report.ticker}   [{report.status.value}]")
    print(f"generated_at: {report.generated_at.isoformat()}")
    print(f"data_as_of:   {report.data_as_of.isoformat()}")
    print("-" * 68)
    print("Metrics (every figure sourced):")
    for key, mv in report.metrics.items():
        print(f"  {key:>16}: {mv.value:<12g} {mv.unit:<24} [src {mv.source_id[:12]}…]")
    print("-" * 68)
    print("Narrative:")
    print(f"  {report.narrative}")
    print("-" * 68)
    print("Claims (each traceable to a source):")
    for c in report.claims:
        src = (c.source_id or "NONE")[:12]
        print(f"  • {c.text}  [src {src}…]")
    print("-" * 68)
    print("Disclaimer:")
    print(f"  {report.disclaimer}")
    print("=" * 68)


def _print_row(row) -> None:
    print(f"ANALYSIS REPORT — {row['ticker']}   [{row['status']}]")
    print(f"generated_at: {row['generated_at']}")
    print(f"data_as_of:   {row['data_as_of']}")
    print(f"narrative: {row['narrative']}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="insight-engine")
    p.add_argument("--db", default="insight.db", help="SQLite path")
    p.add_argument("--ticker", default=fixtures.HARDCODED_TICKER)
    p.add_argument("--live", action="store_true", help="use real providers/LLM")
    p.add_argument(
        "--user-agent",
        default="insight-engine-prototype contact@example.com",
        help="User-Agent for SEC EDGAR (required by their ToS)",
    )
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("ingest").set_defaults(func=cmd_ingest)
    sub.add_parser("report").set_defaults(func=cmd_report)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
