# JobWatch — an AI-Ops on-caller for a daily data pipeline

A small financial-data pipeline (yfinance → Postgres) paired with an LLM
diagnosis loop that turns a raw `job_runs` row into a plain-English incident
report delivered to Slack + stdout + a local log.

The interesting part isn't the pipeline. It's what happens **after** a failure:
the monitor notices, Claude reads the audit row and queries an MCP server for
supporting evidence, and writes a three-section incident summary citing the
actual rows and error messages.

---

## Before / after

**Raw `job_runs` row that a human would get paged on:**

```
job_id=7 status=failed rows_written=0 error_type=NoRowsWritten
duration_sec=1.78
log_snippet: yfinance HTTP 404 for ZZZZZ, DELIST1, NOTREAL; each "possibly delisted"
```

**What Slack / `incidents.log` actually receives:**

> **Root cause**
>
> Job 7 failed with error type `NoRowsWritten` because the pipeline attempted to fetch OHLCV data for three ticker symbols—ZZZZZ, DELIST1, and NOTREAL—all of which returned HTTP 404 errors and "possibly delisted" warnings from yfinance. The log shows each ticker returned zero rows, resulting in 0 rows written across all tickers.
>
> **Evidence**
>
> - **get_job_log**: Job 7 log_snippet shows three consecutive yfinance HTTP 404s for ZZZZZ, DELIST1, NOTREAL.
> - **get_last_job_metrics**: `rows_written: 0`, `error_type: "NoRowsWritten"`, `duration_sec: 1.78`.
>
> **Recommended action**
>
> Remove ZZZZZ, DELIST1, and NOTREAL from the ticker ingestion list, as they are invalid or delisted symbols that yfinance cannot resolve.

Two more captured incidents live in [`docs/sample_incidents/`](docs/sample_incidents).

---

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the Mermaid diagram.

Four moving parts:

- **pipeline** — one-shot ingest; writes `ohlcv` rows and a `job_runs` audit row.
- **monitor** — long-running poll over `job_runs`; triggers diagnosis on failures or `rows_written < threshold`.
- **mcp_server** — stdio MCP server exposing three tools (`query_recent_rows`, `get_job_log`, `get_last_job_metrics`) + Prometheus on `:9100`.
- **postgres** — one container, host port `5434`, schema in `sql/schema.sql`.

---

## The prompt

The prompt IS the product. Verbatim, kept in sync at [`docs/sample_incidents/PROMPT.md`](docs/sample_incidents/PROMPT.md):

```
You are an on-call reliability engineer for a daily financial data pipeline that ingests
OHLCV bars from yfinance into Postgres.

A job just failed or produced suspiciously few rows. Use the tools to investigate: the
latest job_runs row (including its captured log_snippet), compact job metrics, and recent
OHLCV rows per ticker when relevant.

Produce a short incident report with exactly these three sections, in this order:

**Root cause** — one paragraph. Quote concrete evidence from tool calls.
**Evidence** — bullet list. Each bullet names the tool used and the key fact it surfaced.
**Recommended action** — one line, imperative.

Do not speculate beyond what the tools returned. If the evidence is insufficient to
determine a cause, say so plainly in the Root cause section.
```

---

## Quickstart

```bash
cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY (required) and optionally SLACK_WEBHOOK_URL

make up                    # start postgres on :5434, schema auto-loaded
make sync                  # uv sync the Python env
make run-pipeline          # one ingest run for the configured tickers
make monitor               # start the monitor (long-running)

# In another terminal, trigger a failure:
make break-ticker          # .env TICKERS=ZZZZZ,DELIST1,NOTREAL
make run-pipeline          # produces a failed job_runs row
# -> monitor picks it up within 5s, diagnose fires, Slack + incidents.log updated

make restore-ticker        # revert .env
make down
```

Run the tests:

```bash
make test                  # pytest — transform correctness + MCP fault injection
```

Run the concurrency benchmark:

```bash
make load-test             # writes docs/concurrency_findings.md + PNG
```

---

## Concurrency finding — connection reuse eliminates the p95 tail

`query_recent_rows` is the hot path under fan-out. The first draft used
`psycopg.connect()` per call. At N=10 concurrent callers the p95 climbed past
50ms even though the query itself is a single-row `ORDER BY ts DESC LIMIT 10`.

Routing the same query through a warm `psycopg_pool.ConnectionPool` collapsed
the tail by roughly an order of magnitude:

| N  | conn p95 (ms) | pool p95 (ms) |
|----|---------------|---------------|
| 1  | 14.9          | 1.1           |
| 3  | 71.1          | 2.0           |
| 5  | 96.3          | 2.7           |
| 10 | 56.1          | 5.7           |

Full numbers, chart, and reproduction script: [`docs/concurrency_findings.md`](docs/concurrency_findings.md).

The fix is one line in `src/mcp_server/server.py` (`get_conn()` → `get_pool().connection()`); it's already applied.

---

## Cost

~$0.005 per incident at Haiku pricing, based on the two captured scenarios (2–3 tool-use iterations, ~2.5K input + ~400 output tokens). Switching to Sonnet for polish would roughly 10× it and is worth it only for demos.

---

## Known limitations (a.k.a. v2)

See [`BACKLOG.md`](BACKLOG.md) for the full list. The load-bearing ones:

- **No checkpoint for the monitor** — restart loses `last_seen_id` and will miss failures written while down. A dedicated checkpoint table (or separate durable store) closes this.
- **No auth on the MCP server** — stdio only for now; any network exposure would need a token header.
- **Pipeline can't write its own audit row if Postgres is down at connect time.** This is exactly the `docs/sample_incidents/01_postgres_down.md` scenario; the synthetic row in that capture stands in for the real one.
- **No retry with backoff** on yfinance fetches — delisted tickers are logged and skipped.

---

## Files worth reading first

- [`src/diagnose.py`](src/diagnose.py) — the tool-use loop.
- [`src/mcp_server/server.py`](src/mcp_server/server.py) — three tools, one decorator that guarantees structured errors.
- [`src/monitor.py`](src/monitor.py) — the poll + fan-out.
- [`docs/sample_incidents/`](docs/sample_incidents) — captured LLM outputs.
