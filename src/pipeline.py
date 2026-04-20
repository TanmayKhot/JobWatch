"""Pipeline entrypoint: ingest all tickers and record a job_runs row."""

from __future__ import annotations

import io
import logging
import time
from datetime import datetime, timezone

import psycopg

from src import ingest
from src.config import TICKERS
from src.db import get_conn
from src.metrics import (
    pipeline_duration_seconds,
    pipeline_rows_written_total,
    pipeline_runs_total,
)

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def _start_job(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO job_runs (started_at, status) VALUES (%s, %s) RETURNING id",
            (datetime.now(timezone.utc), "running"),
        )
        (job_id,) = cur.fetchone()
    conn.commit()
    return job_id


def _finish_job(
    conn: psycopg.Connection,
    job_id: int,
    status: str,
    rows_written: int,
    error_type: str | None,
    error_message: str | None,
    log_snippet: str | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE job_runs
               SET finished_at = %s,
                   status = %s,
                   rows_written = %s,
                   error_type = %s,
                   error_message = %s,
                   log_snippet = %s
             WHERE id = %s
            """,
            (
                datetime.now(timezone.utc),
                status,
                rows_written,
                error_type,
                error_message,
                log_snippet,
                job_id,
            ),
        )
    conn.commit()


def _emit_metrics(status: str, rows: int, duration: float) -> None:
    pipeline_duration_seconds.observe(duration)
    pipeline_rows_written_total.inc(rows)
    pipeline_runs_total.labels(status=status).inc()


def run_once() -> dict:
    stderr_buf = io.StringIO()
    capture_handler = logging.StreamHandler(stderr_buf)
    capture_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logging.getLogger().addHandler(capture_handler)

    rows_written = 0
    per_ticker_failures: list[str] = []
    error_type: str | None = None
    error_message: str | None = None
    job_id: int | None = None
    conn: psycopg.Connection | None = None
    start = time.perf_counter()

    try:
        try:
            conn = get_conn()
            job_id = _start_job(conn)
            log.info("pipeline run %d started", job_id)
        except Exception as exc:
            error_type = type(exc).__name__
            error_message = str(exc)
            log.exception("cannot start pipeline (DB unreachable?)")
            raise

        for ticker in TICKERS:
            try:
                df = ingest.fetch(ticker)
                df = ingest.transform(df)
                n = ingest.write(conn, ticker, df)
                conn.commit()
                rows_written += n
                log.info("wrote %d rows for %s", n, ticker)
                if n == 0:
                    per_ticker_failures.append(f"{ticker}: no rows")
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                per_ticker_failures.append(
                    f"{ticker}: {type(exc).__name__}: {exc}"
                )
                log.exception("failed to ingest %s", ticker)
    except Exception as exc:
        if error_type is None:
            error_type = type(exc).__name__
            error_message = str(exc)
            log.exception("pipeline fatal error")
    finally:
        duration = time.perf_counter() - start

        if error_type is not None:
            status = "failed"
        elif rows_written == 0:
            status = "failed"
            error_type = "NoRowsWritten"
            error_message = "Pipeline wrote 0 rows across all tickers."
        else:
            status = "success"

        log_snippet = (stderr_buf.getvalue()[-2000:]) or None

        if job_id is not None and conn is not None:
            try:
                _finish_job(
                    conn, job_id, status, rows_written,
                    error_type, error_message, log_snippet,
                )
            except Exception:
                log.exception("failed to update job_runs row")
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

        _emit_metrics(status, rows_written, duration)
        logging.getLogger().removeHandler(capture_handler)

    log.info(
        "pipeline run %s | %s | rows_written=%d | duration=%.2fs",
        job_id, status, rows_written, duration,
    )
    if per_ticker_failures:
        log.info("per-ticker issues: %s", per_ticker_failures)

    return {
        "job_id": job_id,
        "status": status,
        "rows_written": rows_written,
        "duration_sec": round(duration, 2),
        "error_type": error_type,
        "error_message": error_message,
        "per_ticker_failures": per_ticker_failures,
    }


def main() -> None:
    summary = run_once()
    print(summary)


if __name__ == "__main__":
    main()
