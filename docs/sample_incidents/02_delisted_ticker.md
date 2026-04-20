# Sample incident — delisted / invalid tickers

## Reproduction

```bash
python scripts/break_it.py --mode ticker      # TICKERS=ZZZZZ,DELIST1,NOTREAL
uv run python -m src.pipeline                 # writes job_runs (status=failed, rows=0)
uv run python -m src.monitor                  # polls, fires diagnosis on the failed row
python scripts/break_it.py --mode restore     # reset .env + restart postgres
```

## Raw `job_runs` row (before the LLM)

```
job_id=7 status=failed rows_written=0 error_type=NoRowsWritten
duration_sec=1.78
log_snippet: yfinance HTTP 404 for ZZZZZ, DELIST1, NOTREAL; each "possibly delisted"
```

## LLM-generated incident (claude-haiku-4-5-20251001)

> **Root cause**
>
> Job 7 failed with error type `NoRowsWritten` because the pipeline attempted to fetch OHLCV data for three ticker symbols—ZZZZZ, DELIST1, and NOTREAL—all of which returned HTTP 404 errors and "possibly delisted" warnings from yfinance. The log shows each ticker returned zero rows, resulting in 0 rows written across all tickers. The job ran for 1.78 seconds and completed with status "failed" at 2026-04-20T04:11:21.
>
> **Evidence**
>
> - **get_job_log**: Job 7 contains log_snippet showing three consecutive yfinance HTTP 404 errors with "Quote not found" messages for ZZZZZ, DELIST1, and NOTREAL; each ticker logged "possibly delisted; no price data found."
> - **get_last_job_metrics**: Job 7 has `rows_written: 0`, `error_type: "NoRowsWritten"`, and `status: "failed"` with `duration_sec: 1.781652`.
>
> **Recommended action**
>
> Remove ZZZZZ, DELIST1, and NOTREAL from the ticker ingestion list, as they are invalid or delisted symbols that yfinance cannot resolve.

## Cost

- 2 tool-use iterations (`get_last_job_metrics`, `get_job_log`)
- 2,807 input tokens / 408 output tokens
- ≈ $0.005 per incident at Haiku pricing
