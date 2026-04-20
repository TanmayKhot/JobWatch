"""Monitor loop: polls job_runs and triggers the diagnosis flow on new failures."""

from __future__ import annotations

import argparse
import logging
import sys
import time

import psycopg

from src.alert_sinks import fan_out
from src.config import ROWS_WRITTEN_THRESHOLD
from src.db import get_conn
from src.diagnose import diagnose

log = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 5


def _initial_seen_id(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM job_runs")
        (max_id,) = cur.fetchone()
    return int(max_id)


def _fetch_new_failures(
    conn: psycopg.Connection, last_seen_id: int
) -> list[tuple[int, str, int, str | None]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status, rows_written, error_type
              FROM job_runs
             WHERE id > %s
               AND finished_at IS NOT NULL
               AND (status = 'failed' OR rows_written < %s)
          ORDER BY id ASC
            """,
            (last_seen_id, ROWS_WRITTEN_THRESHOLD),
        )
        return cur.fetchall()


def _handle_failure(
    job_id: int, status: str, rows_written: int, error_type: str | None
) -> None:
    log.info(
        "triggering diagnosis for job_id=%d status=%s rows=%d error=%s",
        job_id, status, rows_written, error_type,
    )
    try:
        result = diagnose(job_id=job_id)
        header = f"Incident (job_id={job_id}, status={status})"
        body = (
            f"{header}\n\n{result['text']}\n\n"
            f"(tokens: {result['input_tokens']} in / {result['output_tokens']} out; "
            f"iterations: {result['iterations']}; model: {result['model']})"
        )
        fan_out(body, job_id=job_id, status=status)
    except Exception:
        log.exception("failed to diagnose / fan out for job_id=%d", job_id)


def run(once: bool = False) -> int:
    conn = get_conn()
    last_seen_id = _initial_seen_id(conn)
    log.info(
        "monitor started; last_seen_id=%d, poll=%ds, rows_threshold=%d",
        last_seen_id, POLL_INTERVAL_SEC, ROWS_WRITTEN_THRESHOLD,
    )
    try:
        while True:
            try:
                failures = _fetch_new_failures(conn, last_seen_id)
            except psycopg.Error:
                log.exception("DB error while polling; reconnecting")
                try:
                    conn.close()
                except Exception:
                    pass
                time.sleep(POLL_INTERVAL_SEC)
                conn = get_conn()
                continue

            for (job_id, status, rows_written, error_type) in failures:
                _handle_failure(job_id, status, rows_written, error_type)
                last_seen_id = max(last_seen_id, job_id)
                if once:
                    return 0

            time.sleep(POLL_INTERVAL_SEC)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    p = argparse.ArgumentParser()
    p.add_argument(
        "--once",
        action="store_true",
        help="Process the first new failure then exit (used in tests).",
    )
    args = p.parse_args()
    sys.exit(run(once=args.once) or 0)


if __name__ == "__main__":
    main()
