"""Dashboard presentation layer — plan.md §2.

`render(data: DashboardData) -> str` is a pure function: no I/O, no DB access,
no network. It returns one self-contained HTML string (inline <style>, a
sliver of vanilla JS only for the internals collapse toggle — no external
assets or CDN links) so the file works fully offline when opened directly in
a browser.

Deliberately duck-types `data` instead of importing
`insight_engine.dashboard.read_model` at module scope, so this module can be
built and tested independently of that module landing (see plan.md
"Execution" — parallel build against the shared `DashboardData` contract).
The expected shape (mirrors read_model.py's Pydantic view models):

    DashboardData
        generated_at: datetime
        instrument: Instrument            # .ticker .name .exchange .sector
        report: ReportView | None         # None only if never approved
            id, status, generated_at, data_as_of
            metrics: dict[str, MetricValue]   # .value .unit .source_id
            narrative: str
            claims: list[Claim]               # .text .source_id
            disclaimer: str | None
        rejections: list[RejectionView]   # .stage .reason .offending_text .created_at
        fundamentals: list[FundamentalRow]  # .period .metric .value .unit .source_id
        prices: list[PriceRow]              # .ts .open .high .low .close .volume .source_id
        sources: dict[str, SourceView]      # .source_id .source_name .source_url .retrieved_at

Every text field pulled from `data` is untrusted-ish (LLM/fixture output) and
is passed through `html.escape` before interpolation — see CLAUDE.md hard
constraints and spec §5.6 ("never show partial/unapproved content").
"""

from __future__ import annotations

import html as _html
from typing import Any

# Kept in sync with guardrail.pipeline.DISCLAIMER (spec §2.7 / CLAUDE.md hard
# constraint #7: disclaimer + data_as_of attach to every user-facing output —
# including the "no approved report yet" state, which has no report-generated
# disclaimer to show).
_FALLBACK_DISCLAIMER = (
    "This is educational, informational content only and is not investment "
    "advice, an offer, or a solicitation. Figures are as of the data-as-of "
    "timestamp and may be delayed or revised. Consult a licensed professional "
    "before making any financial decision."
)

_GUARDRAIL_STAGES_NOTE = (
    "Guardrail stages active today: 1 (provenance) and 4 (framing). "
    "Scaffolded for M1: 2 (numeric re-extraction vs. stored values) and "
    "3 (directive/prediction filter)."
)


def esc(value: Any) -> str:
    """html.escape every text field before interpolation, tolerating None."""
    if value is None:
        return ""
    return _html.escape(str(value))


def _short_id(source_id: str | None, n: int = 12) -> str:
    if not source_id:
        return "NONE"
    return source_id[:n]


def _iso(value: Any) -> str:
    """Best-effort ISO-8601 string for a datetime-or-str field."""
    if value is None:
        return ""
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(value)


def _enum_str(value: Any) -> str:
    """Unwrap a Status-like enum (`.value`) or pass a plain str through."""
    if value is None:
        return ""
    return str(getattr(value, "value", value))


def _status_of(report: Any) -> str:
    if report is None:
        return "NO REPORT"
    return _enum_str(report.status).upper() or "NO REPORT"


def _status_badge(status: str) -> str:
    css_class = {
        "APPROVED": "badge-approved",
        "REJECTED": "badge-rejected",
    }.get(status, "badge-none")
    icon = {"APPROVED": "✓", "REJECTED": "✕"}.get(status, "–")
    return (
        f'<span class="badge {css_class}">'
        f'<span aria-hidden="true">{icon}</span> {esc(status)}</span>'
    )


def _source_tag(source_id: str | None, sources: dict) -> str:
    short = esc(_short_id(source_id))
    if not source_id:
        return f'<span class="src-tag src-tag-missing" title="no source_id">[{short}]</span>'
    src = sources.get(source_id) if sources else None
    if src is not None:
        title = (
            f"{esc(getattr(src, 'source_name', ''))} — "
            f"{esc(getattr(src, 'source_url', ''))} — "
            f"retrieved {esc(_iso(getattr(src, 'retrieved_at', '')))} — "
            f"{esc(source_id)}"
        )
    else:
        title = esc(source_id)
    return f'<span class="src-tag" title="{title}">[{short}…]</span>'


def _metric_label(key: str) -> str:
    return esc(key.replace("_", " ").title())


# --------------------------------------------------------------------------- #
# Section builders
# --------------------------------------------------------------------------- #
def _header_section(instrument: Any, status: str, generated_at: Any) -> str:
    return f"""
<header class="page-header">
  <div class="header-top">
    <div class="ticker-block">
      <span class="ticker">{esc(instrument.ticker)}</span>
      <span class="inst-name">{esc(instrument.name)}</span>
    </div>
    {_status_badge(status)}
  </div>
  <div class="inst-meta">
    <span>{esc(instrument.exchange)}</span>
    <span class="dot">&middot;</span>
    <span>{esc(instrument.sector)}</span>
    <span class="dot">&middot;</span>
    <span class="muted">dashboard generated {esc(_iso(generated_at))}</span>
  </div>
</header>
"""


def _disclaimer_banner(disclaimer: str | None, data_as_of: Any) -> str:
    text = disclaimer or _FALLBACK_DISCLAIMER
    as_of = (
        f'<div class="data-as-of">data_as_of: <span class="mono">{esc(_iso(data_as_of))}</span></div>'
        if data_as_of is not None
        else '<div class="data-as-of">data_as_of: <span class="mono">n/a &mdash; no approved report yet</span></div>'
    )
    return f"""
<div class="disclaimer-banner">
  <div class="disclaimer-text"><strong>Not investment advice.</strong> {esc(text)}</div>
  {as_of}
</div>
"""


def _no_report_section(ticker: str) -> str:
    return f"""
<section class="card report-section empty-state">
  <h2>Report</h2>
  <p class="empty-state-text">
    No approved report yet for <strong>{esc(ticker)}</strong>. This view never
    shows partial or unapproved content &mdash; run
    <code>python -m insight_engine.cli report</code> (or <code>dashboard</code>
    again) to generate one.
  </p>
</section>
"""


def _stat_tiles(metrics: dict, sources: dict) -> str:
    if not metrics:
        return '<p class="muted">No metrics computed.</p>'
    tiles = []
    for key in sorted(metrics.keys()):
        mv = metrics[key]
        value = getattr(mv, "value", None)
        unit = getattr(mv, "unit", "")
        source_id = getattr(mv, "source_id", None)
        value_str = f"{value:g}" if isinstance(value, (int, float)) else esc(value)
        tiles.append(f"""
    <div class="stat-tile">
      <div class="stat-label">{_metric_label(key)}</div>
      <div class="stat-value-row">
        <span class="stat-value">{esc(value_str)}</span>
        <span class="stat-unit">{esc(unit)}</span>
      </div>
      {_source_tag(source_id, sources)}
    </div>""")
    return f'<div class="stat-grid">{"".join(tiles)}</div>'


def _claims_list(claims: list, sources: dict) -> str:
    if not claims:
        return '<p class="muted">No claims in this report.</p>'
    items = []
    for c in claims:
        text = esc(getattr(c, "text", ""))
        source_id = getattr(c, "source_id", None)
        items.append(
            f'<li class="claim-item">{text} {_source_tag(source_id, sources)}</li>'
        )
    return f'<ul class="claims-list">{"".join(items)}</ul>'


def _report_section(report: Any, sources: dict) -> str:
    return f"""
<section class="card report-section">
  <h2>Report</h2>
  <div class="report-meta muted">
    id: <span class="mono">{esc(getattr(report, 'id', ''))}</span>
    &middot; generated_at: <span class="mono">{esc(_iso(getattr(report, 'generated_at', None)))}</span>
  </div>

  <h3>Metrics</h3>
  {_stat_tiles(getattr(report, "metrics", {}) or {}, sources)}

  <h3>Narrative</h3>
  <p class="narrative">{esc(getattr(report, "narrative", ""))}</p>

  <h3>Claims</h3>
  {_claims_list(getattr(report, "claims", []) or [], sources)}
</section>
"""


def _sources_table(sources: dict) -> str:
    if not sources:
        return '<p class="muted">No sources recorded.</p>'
    rows = []
    for sid in sorted(sources.keys()):
        s = sources[sid]
        rows.append(f"""
    <tr>
      <td class="mono">{esc(sid)}</td>
      <td>{esc(getattr(s, 'source_name', ''))}</td>
      <td><span class="mono url-cell">{esc(getattr(s, 'source_url', ''))}</span></td>
      <td class="mono">{esc(_iso(getattr(s, 'retrieved_at', '')))}</td>
    </tr>""")
    return f"""
<div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>source_id</th><th>source_name</th><th>source_url</th><th>retrieved_at</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</div>"""


def _fundamentals_table(fundamentals: list, sources: dict) -> str:
    if not fundamentals:
        return '<p class="muted">No fundamentals recorded.</p>'
    rows = []
    for f in fundamentals:
        rows.append(f"""
    <tr>
      <td class="mono">{esc(getattr(f, 'period', ''))}</td>
      <td>{esc(getattr(f, 'metric', ''))}</td>
      <td class="num">{esc(getattr(f, 'value', ''))}</td>
      <td>{esc(getattr(f, 'unit', ''))}</td>
      <td>{_source_tag(getattr(f, 'source_id', None), sources)}</td>
    </tr>""")
    return f"""
<div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>period</th><th>metric</th><th>value</th><th>unit</th><th>source</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</div>"""


def _prices_table(prices: list, sources: dict) -> str:
    if not prices:
        return '<p class="muted">No price rows recorded.</p>'
    rows = []
    for p in prices:
        rows.append(f"""
    <tr>
      <td class="mono">{esc(getattr(p, 'ts', ''))}</td>
      <td class="num">{esc(getattr(p, 'open', ''))}</td>
      <td class="num">{esc(getattr(p, 'high', ''))}</td>
      <td class="num">{esc(getattr(p, 'low', ''))}</td>
      <td class="num">{esc(getattr(p, 'close', ''))}</td>
      <td class="num">{esc(getattr(p, 'volume', ''))}</td>
      <td>{_source_tag(getattr(p, 'source_id', None), sources)}</td>
    </tr>""")
    return f"""
<div class="table-wrap">
  <table class="data-table">
    <thead><tr><th>ts</th><th>open</th><th>high</th><th>low</th><th>close</th><th>volume</th><th>source</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</div>"""


def _rejections_panel(rejections: list) -> str:
    if not rejections:
        return ""
    rows = []
    for r in rejections:
        rows.append(f"""
    <tr>
      <td>{esc(getattr(r, 'stage', ''))}</td>
      <td>{esc(getattr(r, 'reason', ''))}</td>
      <td>{esc(getattr(r, 'offending_text', ''))}</td>
      <td class="mono">{esc(_iso(getattr(r, 'created_at', '')))}</td>
    </tr>""")
    return f"""
<div class="rejections-panel">
  <h3><span aria-hidden="true">&#9888;</span> Guardrail rejection trail ({len(rejections)})</h3>
  <div class="table-wrap">
    <table class="data-table">
      <thead><tr><th>stage</th><th>reason</th><th>offending_text</th><th>created_at</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
  </div>
</div>"""


def _internals_section(
    sources: dict, fundamentals: list, prices: list, rejections: list
) -> str:
    return f"""
<details class="card internals">
  <summary><span class="chevron" aria-hidden="true">&#9656;</span> Internals / audit</summary>
  <div class="internals-body">
    <p class="stage-note muted">{esc(_GUARDRAIL_STAGES_NOTE)}</p>
    {_rejections_panel(rejections)}
    <h3>Sources (provenance ledger)</h3>
    {_sources_table(sources)}
    <h3>Raw fundamentals</h3>
    {_fundamentals_table(fundamentals, sources)}
    <h3>Raw price series</h3>
    {_prices_table(prices, sources)}
  </div>
</details>
"""


_STYLE = """
:root {
  color-scheme: light;
  --page-plane:     #f9f9f7;
  --surface-1:      #fcfcfb;
  --text-primary:   #0b0b0b;
  --text-secondary: #52514e;
  --text-muted:     #898781;
  --gridline:       #e1e0d9;
  --border:         rgba(11,11,11,0.10);
  --status-good:      #0ca30c;
  --status-warning:   #fab219;
  --status-serious:   #ec835a;
  --status-critical:  #d03b3b;
  --accent:         #2a78d6;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --page-plane:     #0d0d0d;
    --surface-1:      #1a1a19;
    --text-primary:   #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted:     #898781;
    --gridline:       #2c2c2a;
    --border:         rgba(255,255,255,0.10);
    --status-good:      #0ca30c;
    --status-warning:   #fab219;
    --status-serious:   #ec835a;
    --status-critical:  #d03b3b;
    --accent:         #3987e5;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 24px;
  background: var(--page-plane);
  color: var(--text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  line-height: 1.5;
}
.dashboard { max-width: 960px; margin: 0 auto; }
.muted { color: var(--text-muted); }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.85em; }
h1, h2, h3 { color: var(--text-primary); }
h2 { font-size: 1.15rem; margin: 0 0 12px; }
h3 { font-size: 0.95rem; margin: 20px 0 8px; color: var(--text-secondary); }
.card {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 18px 20px;
  margin-bottom: 16px;
}
.page-header { margin-bottom: 16px; }
.header-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.ticker-block { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.ticker { font-size: 1.7rem; font-weight: 700; letter-spacing: 0.01em; }
.inst-name { font-size: 1rem; color: var(--text-secondary); }
.inst-meta { margin-top: 6px; font-size: 0.85rem; color: var(--text-secondary); }
.inst-meta .dot { margin: 0 6px; color: var(--text-muted); }

.badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 12px; border-radius: 999px;
  font-size: 0.75rem; font-weight: 700; letter-spacing: 0.02em;
  border: 1px solid transparent; white-space: nowrap;
}
.badge-approved { color: var(--status-good); border-color: var(--status-good); background: color-mix(in srgb, var(--status-good) 12%, transparent); }
.badge-rejected { color: var(--status-critical); border-color: var(--status-critical); background: color-mix(in srgb, var(--status-critical) 12%, transparent); }
.badge-none { color: var(--text-muted); border-color: var(--border); background: var(--page-plane); }

.disclaimer-banner {
  background: var(--page-plane);
  border: 1px solid var(--border);
  border-left: 4px solid var(--status-warning);
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 16px;
  font-size: 0.82rem;
  color: var(--text-secondary);
}
.disclaimer-text strong { color: var(--text-primary); }
.data-as-of { margin-top: 4px; font-size: 0.78rem; }

.empty-state-text { color: var(--text-secondary); }
.empty-state-text code {
  background: var(--page-plane); border: 1px solid var(--border);
  border-radius: 4px; padding: 1px 5px; font-size: 0.85em;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 12px;
}
.stat-tile {
  background: var(--page-plane);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
}
.stat-label { font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px; }
.stat-value-row { display: flex; align-items: baseline; gap: 5px; }
.stat-value { font-size: 1.5rem; font-weight: 600; color: var(--text-primary); }
.stat-unit { font-size: 0.78rem; color: var(--text-secondary); }

.src-tag {
  display: inline-block;
  margin-top: 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.68rem;
  color: var(--text-secondary);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1px 6px;
  cursor: help;
}
.src-tag-missing { color: var(--status-critical); border-color: var(--status-critical); }

.narrative { color: var(--text-primary); white-space: pre-wrap; }

.claims-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.claim-item {
  background: var(--page-plane);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 0.9rem;
}

.internals summary {
  cursor: pointer;
  font-size: 1.05rem;
  font-weight: 600;
  list-style: none;
  display: flex;
  align-items: center;
  gap: 6px;
}
.internals summary::-webkit-details-marker { display: none; }
.internals[open] summary { margin-bottom: 8px; }
.chevron { transition: transform 0.15s ease; display: inline-block; }
.internals[open] .chevron { transform: rotate(90deg); }
.stage-note { font-size: 0.82rem; margin-top: 0; }

.table-wrap { overflow-x: auto; max-width: 100%; }
.data-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
.data-table th {
  text-align: left; font-weight: 600; color: var(--text-muted);
  border-bottom: 1px solid var(--gridline); padding: 6px 8px; white-space: nowrap;
}
.data-table td {
  padding: 6px 8px; border-bottom: 1px solid var(--gridline);
  font-variant-numeric: tabular-nums;
}
.data-table td.num { text-align: right; }
.url-cell { word-break: break-all; }

.rejections-panel {
  border: 1px solid var(--status-critical);
  border-radius: 8px;
  padding: 10px 14px;
  margin-top: 8px;
  background: color-mix(in srgb, var(--status-critical) 6%, transparent);
}
.rejections-panel h3 { margin-top: 0; color: var(--status-critical); }

footer.page-footer { margin-top: 24px; font-size: 0.75rem; color: var(--text-muted); text-align: center; }
"""

_SCRIPT = """
document.querySelectorAll('details.internals').forEach(function (d) {
  d.addEventListener('toggle', function () {
    var chevron = d.querySelector('.chevron');
    if (chevron) { chevron.textContent = ''; }
  });
});
"""


def render(data: Any) -> str:
    """Render a self-contained HTML dashboard page for `data` (a DashboardData).

    Pure function: no I/O. Every text field pulled from `data` is escaped via
    `html.escape` before interpolation. Never renders partial/unapproved
    content — if `data.report` is None, the report section shows an explicit
    "no approved report yet" state instead.
    """
    instrument = data.instrument
    report = data.report
    sources = dict(getattr(data, "sources", None) or {})
    rejections = list(getattr(data, "rejections", None) or [])
    fundamentals = list(getattr(data, "fundamentals", None) or [])
    prices = list(getattr(data, "prices", None) or [])

    status = _status_of(report)
    disclaimer = getattr(report, "disclaimer", None) if report is not None else None
    data_as_of = getattr(report, "data_as_of", None) if report is not None else None

    header_html = _header_section(instrument, status, data.generated_at)
    banner_html = _disclaimer_banner(disclaimer, data_as_of)
    report_html = (
        _report_section(report, sources)
        if report is not None
        else _no_report_section(instrument.ticker)
    )
    internals_html = _internals_section(sources, fundamentals, prices, rejections)

    title = esc(f"{instrument.ticker} — Stock Insight Dashboard")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{_STYLE}</style>
</head>
<body>
<div class="dashboard">
  {header_html}
  {banner_html}
  {report_html}
  {internals_html}
  <footer class="page-footer">Stock Insight Engine &mdash; informational / decision-support only, not investment advice.</footer>
</div>
<script>{_SCRIPT}</script>
</body>
</html>
"""
