# CLAUDE.md — Stock Market Insight Engine

Claude Code reads this file automatically each session. Keep it high-signal.

## What this is

An AI system that ingests **verified** market data, computes metrics, and
produces **educational, sourced** analysis of publicly traded instruments. It is
**informational / decision-support only — NOT investment advice.** The full
design lives in `ARCHITECTURE.md`; this file is the working contract.

Current state: **M0 (vertical slice) complete** — one hardcoded ticker (`AAPL`)
flows end to end, guardrail provenance gate active, 20 tests passing. Runs
offline (bundled fixtures + a stub LLM); no API key or network needed.

## Hard constraints — DO NOT VIOLATE (spec §2)

These are the reason the product is legal. Enforce them in code, never weaken
them to make a feature work:

1. **No directives** — never emit buy/sell/hold/"you should"/"we recommend".
2. **No predictions** — no price targets, no "will rise/fall", no forecasts.
3. **No portfolio construction** — no allocations, no position sizing.
4. **No money movement** — never custody funds or execute trades.
5. **Every factual claim is sourced** — a claim without a resolvable `source_id`
   is REJECTED by the guardrail.
6. **Every number is verified** — figures in generated text must match stored
   values. The LLM never states a figure from memory and never does arithmetic;
   `analysis/metrics.py` computes in pure Python.
7. **Disclaimer + `data_as_of`** attach to every user-facing output.

Guardrail rule: **reject, don't patch.** Never strip/rewrite bad output to make
it pass — reject the whole thing and log to `guardrail_rejections`. A guardrail
that edits output hides bugs.

If a change would require relaxing any of the above, stop and flag it instead.

## Run

```bash
pip install -r requirements.txt        # offline slice needs only pydantic
export PYTHONPATH=src
python -m insight_engine.cli ingest    # idempotent write side
python -m insight_engine.cli report    # prints an APPROVED, sourced, disclaimed report
```

`--live` swaps in the real EDGAR transport + Anthropic LLM; the price provider is
an open decision (spec §12) and is intentionally unwired.

## Test

```bash
PYTHONPATH=src pytest -q
```

Three suites (spec §10): pure metric math (no LLM), ingestion idempotency (same
payload twice → one row), adversarial guardrail corpus. When adding a guardrail
stage, add its adversarial cases in the same PR.

## Module map (src/insight_engine/)

- `domain/` — the four aggregates + events. Plain Pydantic. **No SQL, no HTTP, no
  LLM knowledge here** (ports/adapters at the edges only).
- `adapters/` — `DataAdapter` port + EDGAR/price adapters. Transport is injected
  (HTTP for live, fixture for offline). Adding a provider = new transport.
- `ingestion/` — idempotent write side; emits domain events.
- `persistence/` — SQLite: `schema.sql` + thin helpers. Idempotency via `UNIQUE`
  + `INSERT OR IGNORE`. `source_id` = content hash of the raw payload.
- `analysis/` — `metrics.py` (pure math, unit-tested), `tools.py` (typed, sourced
  tool contracts), `llm.py` (LLM port: `StubLLMClient` offline / `AnthropicLLMClient`
  live), `analyst_agent.py` (orchestrates tools, caps depth at 12, emits DRAFT).
- `guardrail/` — deterministic pipeline. Stage 1 (provenance) + stage 4 (framing)
  active; stages 2 (numeric) & 3 (directive) scaffolded for M1.
- `fixtures/` — offline AAPL data so the slice runs without network.

## Conventions

- Python 3.12, `from __future__ import annotations`, type hints everywhere.
- Pydantic models for every tool contract and agent output.
- Deterministic code over LLM calls wherever a deterministic answer exists.
- Don't over-engineer: add abstraction when a second implementation exists, not
  before. M0 is meant to be modest.
- The LLM only composes prose over already-computed, already-sourced results.

## Next milestones (spec §9)

- **M1** — activate guardrail stages 2 (numeric re-extraction vs stored values)
  and 3 (directive/prediction regex filter, blocklist in spec §5.5); full
  `guardrail_rejections` logging; extend the adversarial corpus (phrased-around
  directives like "investors may wish to acquire…").
- **M2** — `UserProfile` + watchlist; Insight agent, gated by the same guardrail.
- **M3** — multi-ticker, debounced event-driven regeneration, FastAPI read
  endpoints, previous-approved-version fallback.
