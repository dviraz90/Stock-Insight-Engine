# Stock Market Insight Engine — M0 (Spine)

Informational / decision-support only. **Not investment advice.** The system is
built so it *structurally cannot* emit advice (see the architecture spec §2).
These modules describe the engineering design, not legal compliance — a fintech
attorney must review before any public launch.

This repo implements **M0 — the vertical slice** from the spec's §9: one ticker
flowing end to end, with the guardrail's provenance gate active.

```
Data Adapters → Ingestion (idempotent) → Verified Store (SQLite)
    → compute_metrics (pure Python) → Analyst Agent (structured DRAFT)
    → Compliance Guardrail (stage 1) → APPROVED report → CLI
```

## Run it (offline, no API key, no network)

The slice runs against bundled fixtures for one hardcoded ticker (`AAPL`) and a
deterministic stub LLM, so it works with no egress and no key.

```bash
pip install -r requirements.txt        # pydantic is all the offline slice needs
export PYTHONPATH=src

python -m insight_engine.cli ingest    # idempotent write side
python -m insight_engine.cli report    # prints an APPROVED, sourced, disclaimed report
```

## Test

```bash
PYTHONPATH=src pytest -q
```

Covers the three suites the spec calls out (§10): pure metric math (no LLM),
ingestion idempotency (same payload twice → one row), and the adversarial
guardrail corpus (unsourced claim / unresolvable source / unsourced metric are
all rejected and logged). The M0 "done when" — *an unsourced claim is rejected* —
is `test_unsourced_claim_is_rejected`.

## What maps to what

| Spec | Module |
|---|---|
| §5.1 Data adapters (port + provenance) | `adapters/base.py`, `adapters/edgar.py`, `adapters/price.py` |
| §5.2 Ingestion (idempotent, emits events) | `ingestion/pipeline.py`, storage `UNIQUE` + `INSERT OR IGNORE` in `persistence/db.py` |
| §5.3 Analyst agent (LLM orchestrates, code computes, capped depth) | `analysis/analyst_agent.py`, `analysis/tools.py`, `analysis/metrics.py`, `analysis/llm.py` |
| §5.5 Guardrail (deterministic, reject-don't-patch, logged) | `guardrail/pipeline.py` |
| §5.6 Read model (serve only APPROVED, keep previous on failure) | `persistence/db.py` (`latest_approved_report`), `cli.py` |
| §4 Domain model (four boring aggregates) | `domain/models.py` |
| §6 Persistence schema | `persistence/schema.sql` |
| §10 Testing | `tests/` |

## Design choices honoring the spec's constraints

- **Every number is sourced.** `compute_metrics` runs in pure Python; the LLM
  never does arithmetic and never states a figure from memory. Each
  `MetricValue` and each `Claim` carries a `source_id` that must resolve to a
  row in `sources` (a content hash of the raw payload).
- **Reject, don't patch.** The guardrail rejects the whole output on any failed
  claim; it never strips or rewrites. Rejections are logged to
  `guardrail_rejections` — the compliance evidence and the debug signal.
- **Ports at the edges only.** `DataAdapter` and `LLMClient` are the only ports.
  Transports (HTTP vs fixture) and the LLM impl (Anthropic vs stub) are injected;
  the domain core is plain Python.
- **CQRS.** A user request never triggers a live LLM call — the read model serves
  pre-approved reports; regeneration happens on the write side.

## Going live

`--live` swaps in `EdgarAdapter(_http_transport(...))` and `AnthropicLLMClient`.
The price provider (spec §12 open decision) is intentionally not wired: pick one
with a permitted free tier, implement its transport, and pass it to
`PriceAdapter`. EDGAR requires a descriptive `User-Agent` (their ToS).

## What's deliberately *not* here (per §11: don't over-engineer)

Guardrail stages 2 (numeric re-extraction) and 3 (directive filter) are
scaffolded in `guardrail/pipeline.py` but activate at **M1**, alongside the
adversarial extensions in §10. The Insight agent (§5.4, M2), FastAPI endpoints,
debounced multi-ticker regeneration, and a real queue (§7, §8, M3) come later.
