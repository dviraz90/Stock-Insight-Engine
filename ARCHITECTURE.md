# Stock Market Insight Engine — Architecture Spec

> **Read this file fully before writing code.** It defines both *what* to build and
> the hard constraints that must not be violated. Section 2 is non-negotiable:
> the product's legal position depends on it.

---

## 1. Purpose

An AI-powered system that ingests verified market data, produces **structured
analysis** of publicly traded instruments, and presents **educational context**
to users.

Two agents:

| Agent | Responsibility |
|---|---|
| **Analyst Agent** | Retrieves verified data, computes metrics, explains what the numbers show |
| **Insight Agent** | Contextualizes analysis against a user's watchlist and stated interests |

Both are gated by a deterministic **Compliance Guardrail** before any output
reaches a user.

---

## 2. Hard Constraints (do not violate)

This product is positioned as **informational / decision-support**, NOT as
investment advice. Automated buy/sell recommendations are a regulated activity
in most jurisdictions (SEC/state RIA in the US, MiFID II in the EU, ISA licensing
in Israel). The system is designed so that it *structurally cannot* emit advice.

**Rules enforced in code:**

1. **No directives.** Never output "buy", "sell", "you should", "we recommend".
2. **No predictions.** No price targets, no "will rise/fall", no forecasts.
3. **No portfolio construction.** No allocation percentages, no position sizing.
4. **No money movement.** The system never custodies funds or executes trades.
5. **Every factual claim is sourced.** A claim without a `source_id` is rejected.
6. **Every number is verified.** Figures in generated text must match stored values.
7. **Disclaimer + data-as-of timestamp** attached to every user-facing output.

> These rules describe the engineering design, not legal compliance. A
> fintech attorney must review before any public launch.

**Also constrained:**

- Market data must come from **licensed/permitted sources only**. No scraping
  exchange feeds. Respect every provider's ToS and rate limits.
- The LLM never states a figure from memory. Numbers come from tools only.

---

## 3. High-Level Architecture

```
  Data Adapters (EDGAR, price feed)
            │
            ▼
   Ingestion Pipeline  ──emits──►  Domain Events
   (write side, async)                   │
            │                            ▼
            ▼                    Analysis Workers
   Verified Data Store  ◄──reads──  Analyst Agent
   (SQLite)                              │
                                         ▼
                                 Structured AnalysisReport
                                         │
                                         ▼
                                   Insight Agent
                                         │
                                         ▼
                            ┌────────────────────────┐
                            │  COMPLIANCE GUARDRAIL  │  ← reject, don't patch
                            └────────────────────────┘
                                         │
                                    (approved only)
                                         ▼
                                  Read Model / API ──► User
```

**CQRS split.** The write side (ingestion + analysis) is async and expensive.
The read side serves pre-computed, already-approved reports. A user request
NEVER triggers a live LLM call against raw feeds.

---

## 4. Domain Model

Four aggregates. Keep them boring.

### `Instrument`
- `ticker` (PK), `name`, `exchange`, `sector`, `currency`
- Owns fundamentals snapshots and price history references.

### `AnalysisReport`
- `id`, `ticker`, `generated_at`, `data_as_of`
- `metrics: dict[str, MetricValue]` — each with `value`, `unit`, `source_id`
- `narrative: str` — LLM-generated explanation
- `claims: list[Claim]` — each with `text`, `source_id`
- `status: DRAFT | APPROVED | REJECTED`

### `Insight`
- `id`, `report_id`, `user_id`, `generated_at`
- `context: str` — educational framing
- `considerations: list[str]` — factors to be aware of, never directives
- `status: DRAFT | APPROVED | REJECTED`

### `UserProfile`
- `user_id`, `watchlist: list[ticker]`, `interests: list[str]`
- Used ONLY to filter and prioritize what is shown. Never to instruct.

---

## 5. Components

### 5.1 Data Adapters

One module per source, behind a common `DataAdapter` port (hexagonal — the
domain must not know which provider is in use).

```python
class DataAdapter(Protocol):
    def fetch(self, ticker: str, since: datetime) -> list[RawRecord]: ...
```

Every `RawRecord` carries: `payload`, `source_name`, `retrieved_at`,
`source_url`, `source_hash`.

**Start with:**
- `EdgarAdapter` — SEC EDGAR filings (free, stable, well documented)
- `PriceAdapter` — one price/fundamentals provider (free tier for prototype)

> Provider free-tier limits change frequently. Verify current terms before
> committing to one. Keep the adapter interface narrow so swapping is cheap.

### 5.2 Ingestion Pipeline (write side)

Async workers. Each consumer **must be idempotent** — feeds redeliver constantly.

- Dedupe key: `(ticker, period, source_hash)`
- Backfills are **cursor-based** — a crash resumes, never restarts
- Persist raw payload alongside normalized data (audit trail + reprocessing)

Emits: `PriceUpdated`, `FilingPublished`, `FundamentalsRevised`

### 5.3 Analyst Agent

The LLM orchestrates; **code computes**. The LLM's only job is composing an
explanation over tool results.

**Tool contracts** (typed in, typed out, every result carries `source_id`):

```python
get_fundamentals(ticker: str, period: str) -> Fundamentals
get_price_series(ticker: str, range: str) -> PriceSeries   # OHLCV
compute_metrics(ticker: str)              -> Metrics       # computed in CODE
get_filings(ticker: str, type: str, since: date) -> list[Filing]
search_context(ticker: str, query: str)   -> list[Passage] # RAG over filings/news
```

**Rules:**
- `compute_metrics` calculates P/E, margins, growth rates, volatility **in Python**.
  The LLM never does arithmetic.
- No tool returns free text the model can silently reinterpret as fact.
  Everything typed, everything sourced.
- **Cap tool-call depth** (suggest: 12 calls / report) so one report cannot spiral.
- Output must be structured (JSON schema), not prose. Narrative is one field.

### 5.4 Insight Agent

Input: `AnalysisReport` + `UserProfile`.
Output: educational context — what these fundamentals typically indicate, how a
value-vs-growth lens reads them, what risk factors are disclosed in the filings.

Surfaces **considerations**, never **directives**. Same structured-output rule.

### 5.5 Compliance Guardrail

**A deterministic pipeline. Not an LLM asking an LLM to behave.**
Four stages, in order. Any failure → reject the whole output, do not patch it.

| Stage | Check | Failure action |
|---|---|---|
| 1. Provenance | Every claim has a resolvable `source_id` | REJECT |
| 2. Numeric | Re-extract every figure from text, diff vs stored value | REJECT |
| 3. Directive filter | Regex/rules block imperatives, predictions, price targets | REJECT |
| 4. Framing | Attach disclaimer, `data_as_of`, generation timestamp | — |

**Stage 3 blocklist (starting set — extend):**
`buy`, `sell`, `you should`, `we recommend`, `will rise`, `will fall`,
`guaranteed`, `price target`, `strong buy`, `underweight`, `overweight`

An LLM classifier may run as a **second** pass. Never as the only pass.

**Log every rejection** with stage, reason, and the offending text. This log is
both the compliance evidence and the primary debugging signal.

### 5.6 Read Model / API

Serves only `APPROVED` reports and insights.

**Critical:** if a newly generated report fails the guardrail, the previously
approved report stays live. Never show nothing, never show unapproved content.

---

## 6. Persistence

SQLite for the prototype (matches existing tooling; migrate later if needed).

```sql
instruments(ticker PK, name, exchange, sector, currency)

sources(source_id PK, source_name, source_url, retrieved_at, source_hash)

fundamentals(id PK, ticker FK, period, metric, value, unit, source_id FK,
             UNIQUE(ticker, period, metric, source_id))

prices(id PK, ticker FK, ts, open, high, low, close, volume, source_id FK,
       UNIQUE(ticker, ts, source_id))

filings(id PK, ticker FK, type, filed_at, url, raw_text, source_id FK)

analysis_reports(id PK, ticker FK, generated_at, data_as_of, metrics_json,
                 narrative, status)

claims(id PK, report_id FK, text, source_id FK)

insights(id PK, report_id FK, user_id, context, considerations_json, status)

guardrail_rejections(id PK, subject_type, subject_id, stage, reason,
                     offending_text, created_at)
```

---

## 7. Event Flow

```
FilingPublished / PriceUpdated / FundamentalsRevised
        │
        ▼  (debounced per ticker — see below)
   Analysis Worker
        │
        ▼
 AnalysisReportGenerated (status=DRAFT)
        │
        ▼
   Guardrail  ──► APPROVED ──► materialize into read model
        └──────► REJECTED ──► log, keep previous approved version
```

**Debounce.** Batch triggers per ticker on a short window (suggest 15 min).
Without this, a busy trading day regenerates the same report dozens of times
and burns the entire LLM budget.

---

## 8. Tech Stack

- **Python 3.12+**
- **FastAPI** — read API
- **SQLite** — verified data store (prototype)
- **Anthropic SDK** — agent calls, structured outputs
- **Pydantic** — every tool contract and agent output is a validated model
- **pytest** — tests
- Queue: start with an in-process async queue. Only add Redis/RabbitMQ when
  there is an actual reason to.

---

## 9. Implementation Plan

Build a **vertical slice first**. Breadth comes later.

### M0 — Spine (start here)
- [x] `EdgarAdapter` + one `PriceAdapter`, one hardcoded ticker
- [x] SQLite schema + idempotent ingestion for that ticker
- [x] `compute_metrics` in pure Python, fully unit tested
- [x] Analyst agent producing a structured `AnalysisReport`
- [x] Guardrail **stage 1 only** (provenance)
- [x] CLI command that prints an approved report

**Done when:** one ticker flows end to end and an unsourced claim is rejected.

### M1 — Guardrail complete
- [ ] Stages 2, 3, 4
- [ ] `guardrail_rejections` logging
- [ ] Adversarial test suite (see §10)

### M2 — Insight layer
- [ ] `UserProfile` + watchlist
- [ ] Insight agent, gated by the same guardrail

### M3 — Scale out
- [ ] Multi-ticker, debounced event-driven regeneration
- [ ] FastAPI read endpoints
- [ ] Previous-approved-version fallback

---

## 10. Testing

- **Metrics:** pure unit tests with known inputs. No LLM in the loop.
- **Ingestion:** feed the same payload twice, assert exactly one row.
- **Guardrail (most important):** an adversarial corpus of outputs that *should*
  be rejected — hallucinated figures, unsourced claims, phrased-around
  directives ("investors may wish to acquire..."). Assert every one is caught.
- **Agents:** snapshot-test structured output shape, not narrative wording.

---

## 11. Engineering Principles

1. **Do not over-engineer.** This spec describes the target shape. For M0,
   modest structure is correct — a few clean modules, not a framework. Add
   abstraction when a second implementation actually exists, not before.
2. **Deterministic code over LLM calls** wherever a deterministic answer exists.
3. **Reject, don't patch.** A guardrail that rewrites bad output hides bugs.
4. **Ports and adapters at the edges only** — data providers and the LLM client.
   The domain core stays plain Python.
5. **Every number traceable to a source. No exceptions.**

---

## 12. Open Decisions

- [ ] Which price/fundamentals provider (check current free-tier terms)
- [ ] Target jurisdiction for the first release — shapes disclaimer wording
- [ ] Whether `search_context` RAG uses embeddings or plain keyword search at M2
      (keyword is likely sufficient at prototype scale)
