"""MCP stdio server exposing three tools backed by the pipeline's Postgres state."""

from __future__ import annotations

import functools
import logging
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from src.config import METRICS_PORT
from src.db import get_pool
from src.metrics import (
    mcp_tool_calls_total,
    mcp_tool_latency_seconds,
    start_metrics_server,
)

log = logging.getLogger(__name__)

mcp = FastMCP("jobwatch")


def _instrumented(tool_name: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            status = "ok"
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                status = "error"
                log.exception("tool %s failed", tool_name)
                return {"error": str(exc), "error_type": type(exc).__name__}
            finally:
                mcp_tool_calls_total.labels(tool=tool_name, status=status).inc()
                mcp_tool_latency_seconds.labels(tool=tool_name).observe(
                    time.perf_counter() - start
                )

        return wrapper

    return deco


def _serialize(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def _rows(cur) -> list[dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [{c: _serialize(v) for c, v in zip(cols, row)} for row in cur.fetchall()]


@mcp.tool()
@_instrumented("query_recent_rows")
def query_recent_rows(ticker: str, limit: int = 10) -> dict[str, Any]:
    """Return the most recent OHLCV rows for a ticker, newest first."""
    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT ticker, ts, open, high, low, close, volume,
                   rolling_avg_20, anomaly
              FROM ohlcv
             WHERE ticker = %s
          ORDER BY ts DESC
             LIMIT %s
            """,
            (ticker.upper(), int(limit)),
        )
        rows = _rows(cur)
    return {"ticker": ticker.upper(), "count": len(rows), "rows": rows}


@mcp.tool()
@_instrumented("get_job_log")
def get_job_log(job_id: int | None = None) -> dict[str, Any]:
    """Return the most recent job_runs row (or a specific job_id), including log_snippet."""
    with get_pool().connection() as conn, conn.cursor() as cur:
        if job_id is None:
            cur.execute(
                """
                SELECT id, started_at, finished_at, status, rows_written,
                       error_type, error_message, log_snippet
                  FROM job_runs
              ORDER BY id DESC
                 LIMIT 1
                """
            )
        else:
            cur.execute(
                """
                SELECT id, started_at, finished_at, status, rows_written,
                       error_type, error_message, log_snippet
                  FROM job_runs
                 WHERE id = %s
                """,
                (int(job_id),),
            )
        rows = _rows(cur)
    if not rows:
        return {"error": "no job_runs row found", "error_type": "NotFound"}
    return rows[0]


@mcp.tool()
@_instrumented("get_last_job_metrics")
def get_last_job_metrics() -> dict[str, Any]:
    """Return compact metrics for the most recent job_runs row."""
    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status, rows_written, error_type,
                   started_at, finished_at,
                   EXTRACT(EPOCH FROM (finished_at - started_at)) AS duration_sec
              FROM job_runs
          ORDER BY id DESC
             LIMIT 1
            """
        )
        rows = _rows(cur)
    if not rows:
        return {"error": "no job_runs row yet", "error_type": "NotFound"}
    return rows[0]


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=None)
    start_metrics_server(METRICS_PORT)
    mcp.run()


if __name__ == "__main__":
    main()
