# Stock Insight Engine — Delivery Plan

Status snapshot as of 2026-08-06. Full design lives in `ARCHITECTURE.md`;
this file tracks *what's next* and in what order.

## Current state — M0 (done)

The vertical slice ingests one hardcoded ticker (`AAPL`) from bundled
fixtures, computes metrics in pure Python, drafts a report via a stub LLM,
passes it through guardrail stage 1 (provenance), and serves it over the
CLI. 20 tests pass; the slice runs fully offline (no API key, no network).

```
Data Adapters → Ingestion (idempotent) → Verified Store (SQLite)
    → compute_metrics (pure Python) → Analyst Agent (structured DRAFT)
    → Compliance Guardrail (stage 1) → APPROVED report → CLI
```

## M1 — Guardrail complete (next up)

The guardrail is the product's legal foundation, so this is the priority
before any breadth work.

- [ ] Stage 2 — numeric re-extraction: pull every figure back out of the
      generated narrative and diff it against the stored `MetricValue`;
      reject on mismatch.
- [ ] Stage 3 — directive/prediction filter: regex + rule pass over the
      blocklist in spec §5.5 (`buy`, `sell`, `you should`, `we recommend`,
      `will rise`, `will fall`, `guaranteed`, `price target`, `strong buy`,
      `underweight`, `overweight`), including phrased-around forms like
      "investors may wish to acquire...".
- [ ] `guardrail_rejections` logging wired end-to-end (stage, reason,
      offending text) — this doubles as compliance evidence and the primary
      debugging signal.
- [ ] Extend the adversarial test corpus with cases for stages 2 and 3,
      added in the same PR as each stage per `CLAUDE.md`'s convention.

**Done when:** the adversarial corpus (hallucinated figure, unsourced
claim, phrased-around directive) is caught by the appropriate stage, and
every rejection is logged.

## M2 — Insight layer

- [ ] `UserProfile` aggregate — `user_id`, `watchlist`, `interests`; used
      only to filter/prioritize, never to instruct the LLM.
- [ ] Insight Agent — takes an `AnalysisReport` + `UserProfile`, produces
      educational context and `considerations` (never directives), gated by
      the same guardrail pipeline as the Analyst Agent.
- [ ] Snapshot tests on structured output shape, not narrative wording.

## M3 — Scale out

- [ ] Multi-ticker support, debounced event-driven regeneration (batch
      triggers per ticker on a ~15 min window per spec §7).
- [ ] FastAPI read endpoints serving only `APPROVED` reports/insights.
- [ ] Previous-approved-version fallback: if a regenerated report fails the
      guardrail, the read model keeps serving the last approved one —
      never nothing, never unapproved content.
- [ ] Real price/fundamentals provider wired into `PriceAdapter` (open
      decision, spec §12 — pick one with a permitted free tier).
- [ ] `--live` path exercised end-to-end: real `EdgarAdapter` transport +
      `AnthropicLLMClient`.

## Open decisions carried from the spec (§12)

- Price/fundamentals provider — check current free-tier ToS before
  committing.
- Target jurisdiction for first release — shapes disclaimer wording.
- `search_context` RAG: keyword search vs. embeddings at M2 (keyword is
  likely sufficient at prototype scale).

## Engineering principles to keep enforcing

Carried from `ARCHITECTURE.md` §11 and `CLAUDE.md` — restated here because
they're easy to erode as scope grows:

1. Don't over-engineer — add abstraction when a second implementation
   actually exists, not before.
2. Deterministic code over LLM calls wherever a deterministic answer
   exists; the LLM never does arithmetic or states a figure from memory.
3. Reject, don't patch — the guardrail rejects bad output outright, never
   rewrites it.
4. Ports/adapters at the edges only (`DataAdapter`, `LLMClient`); the
   domain core stays plain Python.
5. Every number traceable to a source, no exceptions.

If a future change would require relaxing any hard constraint in spec §2,
stop and flag it instead of working around it.
