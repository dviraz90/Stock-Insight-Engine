"""LLM client port — spec §5.3, §8, §11.4.

The LLM's *only* job is composing an explanation over already-computed, sourced
tool results. It never states a figure from memory and never does arithmetic:
the composed claims must reference figures the tools produced, each with the
source_id the tool attached.

Two implementations behind one port:
  - `StubLLMClient`    — deterministic, offline, default. Lets the slice run and
                         be snapshot-tested (§10 "test shape, not wording").
  - `AnthropicLLMClient` — real SDK call with a structured-output contract.
"""

from __future__ import annotations

import json
from typing import Protocol

from ..domain.models import Claim, MetricValue

# Human-readable labels for the metric keys metrics.py emits.
_LABELS = {
    "pe_ratio": "price-to-earnings ratio",
    "net_margin": "net profit margin",
    "gross_margin": "gross margin",
    "revenue_growth": "revenue growth versus the prior period",
    "daily_volatility": "daily price volatility",
}


class Composition:
    """Structured LLM output: a narrative plus per-claim provenance."""

    def __init__(self, narrative: str, claims: list[Claim]) -> None:
        self.narrative = narrative
        self.claims = claims


class LLMClient(Protocol):
    def compose(
        self, ticker: str, metrics: dict[str, MetricValue]
    ) -> Composition: ...


def _fmt(key: str, mv: MetricValue) -> str:
    label = _LABELS.get(key, key.replace("_", " "))
    if mv.unit == "fraction":
        return f"{label} of {mv.value * 100:.1f}%"
    if mv.unit == "ratio":
        return f"{label} of {mv.value:.2f}"
    return f"{label} of {mv.value:g}"


class StubLLMClient:
    """Deterministic composer. Every claim it emits is sourced from a metric's
    own source_id — it structurally cannot introduce an unsourced figure. It also
    only *describes* what the numbers show; it emits no directives or forecasts.
    """

    def compose(self, ticker: str, metrics: dict[str, MetricValue]) -> Composition:
        claims: list[Claim] = []
        for key, mv in metrics.items():
            claims.append(
                Claim(
                    text=f"{ticker} shows a {_fmt(key, mv)}.",
                    source_id=mv.source_id,
                )
            )
        if claims:
            body = " ".join(c.text for c in claims)
            narrative = (
                f"The latest verified figures for {ticker} are summarized below. "
                f"{body} These figures describe what the reported data shows and "
                f"are provided for educational context only."
            )
        else:
            narrative = f"No verified figures are currently available for {ticker}."
        return Composition(narrative=narrative, claims=claims)


# Same instruction the real model receives; keeps the two paths honest.
_SYSTEM = (
    "You explain verified financial figures for educational context only. "
    "STRICT RULES: use only the figures provided in the tool results; never "
    "state a number from memory; never compute new numbers; never give "
    "directives (buy/sell/hold/recommend), predictions, price targets, or "
    "portfolio allocations. For every sentence that states a figure, emit a "
    "claim object citing the source_id of the figure you used. Respond with a "
    "single JSON object: {\"narrative\": str, \"claims\": "
    "[{\"text\": str, \"source_id\": str}]} and nothing else."
)


class AnthropicLLMClient:
    """Real composer via the Anthropic Messages API with a structured-output
    contract. Not exercised in the offline slice (no key / no egress in the
    prototype sandbox); wired so production just swaps this in. Model id is
    configurable rather than hard-coded so it survives model updates."""

    def __init__(self, *, model: str = "claude-sonnet-4-6", client=None) -> None:
        self._model = model
        self._client = client  # inject for testing; else lazy-construct

    def _ensure_client(self):
        if self._client is None:
            from anthropic import Anthropic  # imported lazily; optional dep

            self._client = Anthropic()
        return self._client

    def compose(self, ticker: str, metrics: dict[str, MetricValue]) -> Composition:
        client = self._ensure_client()
        tool_results = {
            key: {"value": mv.value, "unit": mv.unit, "source_id": mv.source_id}
            for key, mv in metrics.items()
        }
        user = (
            f"Ticker: {ticker}\nVerified metric tool results (the ONLY numbers you "
            f"may reference):\n{json.dumps(tool_results, indent=2)}"
        )
        resp = client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        ).strip()
        data = json.loads(_strip_fences(text))
        claims = [
            Claim(text=c["text"], source_id=c.get("source_id")) for c in data.get("claims", [])
        ]
        return Composition(narrative=data.get("narrative", ""), claims=claims)


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    return t.strip()
