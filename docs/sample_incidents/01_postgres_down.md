# Sample incident — Postgres outage mid-run

## Reproduction

```bash
uv run python -m src.pipeline         # write a healthy baseline run first
python scripts/break_it.py --mode postgres    # docker compose stop postgres
uv run python -m src.pipeline          # fails at connect time (OperationalError)
# Because the DB is down, the pipeline can't write its own audit row.
# Start postgres again and insert a synthetic audit row reflecting the outage,
# then run `uv run python -m src.monitor` to fire the diagnosis.
```

> Note: this scenario reveals a real reliability gap — if Postgres is down at
> connect time, the pipeline cannot write its own `job_runs` audit row. The
> "v2" backlog item for a separate checkpoint store (not the DB under test)
> would close this gap.

## Raw `job_runs` row (before the LLM)

```
job_id=8 status=failed rows_written=0 duration_sec=15
error_type=OperationalError
error_message=connection failed: connection to server at "127.0.0.1", port 5434 failed: Connection refused
log_snippet: psycopg.OperationalError ... Connection refused ... Is the server running on that host ...
```

## LLM-generated incident (claude-haiku-4-5-20251001)

> **Root cause**
>
> Job_id=8 failed with an `OperationalError` during the database connection phase. The pipeline attempted to connect to PostgreSQL at `127.0.0.1:5434` and received "Connection refused." This indicates the Postgres server was either not running, not listening on that port, or not accepting TCP/IP connections at the time of job execution (2026-04-20T04:17:09Z). Zero rows were written because the pipeline exited before any data ingestion could occur.
>
> **Evidence**
>
> - **get_job_log**: Job_id=8 status is "failed" with error_type "OperationalError"; log shows `connection to server at "127.0.0.1", port 5434 failed: Connection refused` at 2026-04-19 21:16:51.
> - **get_last_job_metrics**: rows_written=0, duration_sec=15.0, confirming no data ingestion occurred and the job spent its runtime attempting the connection.
>
> **Recommended action**
>
> Verify that the Postgres server is running and listening on `127.0.0.1:5434`, then retry job_id=8.

## Cost

- 2 tool-use iterations (`get_job_log`, `get_last_job_metrics`)
- 2,395 input tokens / 357 output tokens
- ≈ $0.004 per incident at Haiku pricing
