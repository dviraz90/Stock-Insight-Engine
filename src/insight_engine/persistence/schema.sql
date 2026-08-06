-- Verified Data Store — spec §6. SQLite for the prototype.
-- Every number is traceable to a row in `sources` (§2.5, §11.5).

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS instruments (
    ticker   TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    exchange TEXT NOT NULL,
    sector   TEXT NOT NULL,
    currency TEXT NOT NULL
);

-- source_id is the content hash of the raw payload (see RawRecord.hash_payload),
-- which makes provenance resolvable and redelivery idempotent.
CREATE TABLE IF NOT EXISTS sources (
    source_id    TEXT PRIMARY KEY,
    source_name  TEXT NOT NULL,
    source_url   TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    source_hash  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fundamentals (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker    TEXT NOT NULL REFERENCES instruments(ticker),
    period    TEXT NOT NULL,
    metric    TEXT NOT NULL,
    value     REAL NOT NULL,
    unit      TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    UNIQUE(ticker, period, metric, source_id)
);

CREATE TABLE IF NOT EXISTS prices (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker    TEXT NOT NULL REFERENCES instruments(ticker),
    ts        TEXT NOT NULL,
    open      REAL NOT NULL,
    high      REAL NOT NULL,
    low       REAL NOT NULL,
    close     REAL NOT NULL,
    volume    INTEGER NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    UNIQUE(ticker, ts, source_id)
);

CREATE TABLE IF NOT EXISTS filings (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker    TEXT NOT NULL REFERENCES instruments(ticker),
    type      TEXT NOT NULL,
    filed_at  TEXT NOT NULL,
    url       TEXT NOT NULL,
    raw_text  TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id)
);

CREATE TABLE IF NOT EXISTS analysis_reports (
    id           TEXT PRIMARY KEY,
    ticker       TEXT NOT NULL REFERENCES instruments(ticker),
    generated_at TEXT NOT NULL,
    data_as_of   TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    narrative    TEXT NOT NULL,
    status       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id TEXT NOT NULL REFERENCES analysis_reports(id),
    text      TEXT NOT NULL,
    source_id TEXT REFERENCES sources(source_id)
);

CREATE TABLE IF NOT EXISTS insights (
    id                 TEXT PRIMARY KEY,
    report_id          TEXT NOT NULL REFERENCES analysis_reports(id),
    user_id            TEXT NOT NULL,
    context            TEXT NOT NULL,
    considerations_json TEXT NOT NULL,
    status             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS guardrail_rejections (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type   TEXT NOT NULL,
    subject_id     TEXT NOT NULL,
    stage          TEXT NOT NULL,
    reason         TEXT NOT NULL,
    offending_text TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
