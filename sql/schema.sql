CREATE TABLE IF NOT EXISTS ohlcv (
    ticker          TEXT        NOT NULL,
    ts              DATE        NOT NULL,
    open            NUMERIC,
    high            NUMERIC,
    low             NUMERIC,
    close           NUMERIC,
    volume          BIGINT,
    rolling_avg_20  NUMERIC,
    anomaly         BOOLEAN     NOT NULL DEFAULT FALSE,
    PRIMARY KEY (ticker, ts)
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_ts_desc
    ON ohlcv (ticker, ts DESC);

CREATE TABLE IF NOT EXISTS job_runs (
    id              SERIAL      PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    status          TEXT        NOT NULL CHECK (status IN ('running','success','failed')),
    rows_written    INTEGER     NOT NULL DEFAULT 0,
    error_type      TEXT,
    error_message   TEXT,
    log_snippet     TEXT
);

CREATE INDEX IF NOT EXISTS idx_job_runs_started_at_desc
    ON job_runs (started_at DESC);
