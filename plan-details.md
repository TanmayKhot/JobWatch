# JobWatch — Phased Implementation & Test Plan

This file breaks the approved plan (`../plan.md`) into discrete, self-contained phases.
**Each phase must be fully tested and accepted before moving to the next.**
Every phase ends with a verification checklist; do not proceed on a red box.

Conventions used in every phase:
- **Deliverables** — exact files/functions to create.
- **Implementation notes** — non-obvious decisions the agent should honor.
- **How to test** — copy-pasteable commands plus expected output.
- **Acceptance** — the bar that must be green before moving on.

---

## Phase 0 — Scaffold (status: ✅ complete)

**Deliverables (already in place)**
- `.gitignore`, `.env.example`, `pyproject.toml`, `Makefile`
- `docker-compose.yml` (Postgres on host port **5434**, not 5432 — the host already runs a Postgres)
- `sql/schema.sql` with `ohlcv` and `job_runs` tables
- Empty `src/__init__.py`, `src/mcp_server/__init__.py`, `tests/__init__.py`

**How to test**
```bash
docker compose up -d postgres
docker exec jobwatch-postgres psql -U jobwatch -d jobwatch -c "\dt"
# Expect: job_runs and ohlcv tables
```

**Acceptance**
- [x] `docker compose ps postgres` shows `Up (healthy)` on port 5434
- [x] Both tables + indexes exist
- [x] `.env.example` has correct `DATABASE_URL` pointing at `localhost:5434`

---

## Phase 1 — Configuration + DB helpers

Establish the shared building blocks every other module will import.

**Deliverables**
- `src/config.py`
  - Loads `.env` via `python-dotenv`.
  - Exports typed constants: `DATABASE_URL`, `ANTHROPIC_API_KEY`, `SLACK_WEBHOOK_URL`, `TICKERS: list[str]`, `DIAGNOSIS_MODEL`, `METRICS_PORT: int`, `ROWS_WRITTEN_THRESHOLD: int`.
  - Raises a clear `RuntimeError` if a required key is missing when it's actually needed (lazy validation — don't crash import just because Slack URL is empty).
- `src/db.py`
  - `get_conn()` returns a psycopg3 connection with `autocommit=False`.
  - `get_pool(size: int)` returns a `psycopg_pool.ConnectionPool`.
  - `@contextmanager cursor()` helper that handles commit/rollback.

**Implementation notes**
- Use `psycopg` v3 (already in `pyproject.toml`). Do NOT mix psycopg2 style.
- Connection strings: pass `DATABASE_URL` directly; psycopg3 parses it.
- Keep `config.py` import-safe — reading env must never throw at import time.

**How to test**
```bash
uv sync --extra dev    # install deps into .venv
cp .env.example .env   # user should have filled in keys by now; leave SLACK blank is OK
uv run python -c "from src.config import DATABASE_URL, TICKERS; print(DATABASE_URL, TICKERS)"
# Expect tickers: ['GOOGL','AMZN','AAPL','NFLX','NVDA','ORCL']
uv run python -c "from src.db import get_conn; \
  c = get_conn(); cur = c.cursor(); cur.execute('SELECT 1'); print(cur.fetchone()); c.close()"
```
Expected output:
```
postgresql://jobwatch:jobwatch@localhost:5434/jobwatch ['GOOGL','AMZN','AAPL','NFLX','NVDA','ORCL']
(1,)
```

**Acceptance**
- [ ] `uv sync --extra dev` succeeds, `.venv/` is populated
- [ ] `from src.config import *` works with an empty `.env` (no required-var exceptions)
- [ ] `get_conn()` returns a live connection that can `SELECT 1`

---

## Phase 2 — Prometheus metrics module

Metrics must exist before any other module that wants to increment them.

**Deliverables**
- `src/metrics.py`
  - Counters: `pipeline_runs_total{status}`, `pipeline_rows_written_total`, `mcp_tool_calls_total{tool,status}`.
  - Histograms: `pipeline_duration_seconds`, `mcp_tool_latency_seconds{tool}`.
  - `start_metrics_server(port: int)` wraps `prometheus_client.start_http_server` with idempotency (don't crash if already bound).

**How to test**
```bash
uv run python -c "\
from src.metrics import start_metrics_server, mcp_tool_calls_total; \
start_metrics_server(9100); \
mcp_tool_calls_total.labels(tool='probe', status='ok').inc(); \
import time; time.sleep(1)" &
sleep 2
curl -s http://localhost:9100/metrics | grep mcp_tool_calls_total
kill %1 2>/dev/null
```
Expected: a line like `mcp_tool_calls_total{tool="probe",status="ok"} 1.0`.

**Acceptance**
- [ ] `/metrics` endpoint serves on 9100
- [ ] Counters and histograms show up after being touched once

---

## Phase 3 — Ingest pipeline (Block 1–3)

The core data flow: yfinance → transform → Postgres, with a `job_runs` audit row.

**Deliverables**
- `src/ingest.py`
  - `fetch(ticker: str, period: str = "60d") -> pandas.DataFrame` — calls `yfinance.Ticker(ticker).history(period=period)`. Must return an empty DataFrame for unknown tickers rather than raising.
  - `transform(df: pd.DataFrame) -> pd.DataFrame` — adds `rolling_avg_20` (simple 20-day moving average on close) and `anomaly` (True where `|close - rolling_avg_20| > 3 * rolling_std_20`).
  - `write(conn, ticker: str, df: pd.DataFrame) -> int` — upserts rows (`ON CONFLICT (ticker, ts) DO UPDATE SET ...`). Returns row count.
- `src/pipeline.py`
  - `run_once() -> dict` — iterates `TICKERS`, calls fetch/transform/write, captures exceptions per-ticker (one bad ticker must not kill the whole run), writes one `job_runs` row (status `running` at start, `success` or `failed` at end).
  - `main()` entrypoint. Captures stderr into `log_snippet` (last 2 KB) using `io.StringIO` redirect.

**Implementation notes**
- Use a single DB transaction per pipeline run — but per-ticker errors are caught and logged, not raised.
- `rows_written` counts total rows upserted across all tickers.
- `error_type` on failure is the exception class name (`'OperationalError'`, `'KeyError'`, etc).
- The `log_snippet` captures the tail of stderr for the MCP `get_job_log` tool to return later.

**How to test**
```bash
uv run python -m src.pipeline
# Should print summary like: "Pipeline run 1 | success | rows_written=300 | duration=4.2s"

# Verify DB
docker exec jobwatch-postgres psql -U jobwatch -d jobwatch -c \
  "SELECT ticker, COUNT(*) FROM ohlcv GROUP BY ticker ORDER BY ticker;"
# Expect ~40-60 rows per ticker for a 60d period

docker exec jobwatch-postgres psql -U jobwatch -d jobwatch -c \
  "SELECT id, status, rows_written, error_type FROM job_runs ORDER BY id DESC LIMIT 1;"
# Expect status='success', rows_written>0, error_type NULL
```

Also run with an intentionally bad ticker:
```bash
TICKERS=AAPL,ZZZZZ uv run python -m src.pipeline
# Expect: AAPL writes rows, ZZZZZ skipped with a warning, status='success' (no exception escaped)
# OR status='failed' with rows_written < threshold if that's the agreed policy.
```

**Acceptance**
- [ ] A clean run with the default 6 tickers (GOOGL, AMZN, AAPL, NFLX, NVDA, ORCL) inserts rows and logs `status='success'`
- [ ] A run with one invalid ticker does not crash; rows from valid tickers persist
- [ ] Re-running is idempotent (no duplicate-key errors)

---

## Phase 4 — MCP server with 3 tools (Block 3–5)

The server exposes three tools over the MCP stdio transport; each call records metrics.

**Deliverables**
- `src/mcp_server/server.py`
  - Uses `mcp.server.Server` with the low-level async API. stdio transport via `mcp.server.stdio.stdio_server()`.
  - Tools:
    - `query_recent_rows(ticker: str, limit: int = 10)` — returns list of OHLCV dicts.
    - `get_job_log(job_id: int | None = None)` — returns latest (or specific) `job_runs` row including `log_snippet`.
    - `get_last_job_metrics()` — returns `{rows_written, duration_sec, status, error_type, started_at, finished_at}`.
  - Each tool: increments `mcp_tool_calls_total{tool,status}`, observes `mcp_tool_latency_seconds{tool}`.
  - On startup, calls `start_metrics_server(METRICS_PORT)` so the server exposes `/metrics` concurrently with stdio MCP.
  - Every tool wraps DB calls in try/except and returns `{"error": "...", "error_type": "..."}` instead of raising. This is essential for the fault-injection test.
  - `main()` entrypoint runs `asyncio.run(async_main())`.

**Implementation notes**
- Declare tool schemas precisely — the LLM uses them to pick which tool to call.
- Do NOT reuse a single connection across async tasks; use the pool from `src/db.py`.
- Prometheus counters on a subprocess stdio server are visible via the metrics endpoint running in the same process.

**How to test manually (without an LLM)**

Write a tiny stdio probe in `scripts/mcp_probe.py` (temporary, can be committed):
```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(command="uv", args=["run", "python", "-m", "src.mcp_server.server"])
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        tools = await s.list_tools()
        print("TOOLS:", [t.name for t in tools.tools])
        result = await s.call_tool("query_recent_rows", {"ticker": "AAPL", "limit": 3})
        print("RESULT:", result.content)
asyncio.run(main())
```
```bash
uv run python scripts/mcp_probe.py
# Expect: TOOLS lists all 3 names; RESULT shows 3 rows for AAPL.
curl -s http://localhost:9100/metrics | grep mcp_tool
```

**Acceptance**
- [ ] `list_tools` returns exactly the 3 declared tools
- [ ] Each tool returns correctly shaped data against a live DB
- [ ] After a few calls, `mcp_tool_calls_total` and `mcp_tool_latency_seconds` appear on `/metrics`
- [ ] Calling a tool against a stopped DB returns `{"error": ...}` rather than raising

---

## Phase 5 — Alert sinks + diagnosis (Block 5–7)

Connect a failed `job_runs` row to an LLM-authored incident summary posted to Slack + stdout + file.

**Deliverables**
- `src/alert_sinks.py`
  - `post_to_slack(summary: str, blocks: list | None = None) -> bool` — POST to `SLACK_WEBHOOK_URL`. If unset, return False silently. Timeout 5s.
  - `append_to_log(summary: str, path: str = "incidents.log") -> None`
  - `print_to_stdout(summary: str) -> None`
  - `fan_out(summary, blocks=None)` — calls all three; any one failing doesn't stop the others.
- `src/diagnose.py`
  - `diagnose(job_id: int) -> str` — runs the Claude tool-use loop.
  - Uses the `anthropic` SDK; attaches the three MCP tools (declared statically in the code — you can either proxy via a real MCP client session or just call the tool handlers directly; for 1-day speed, call the handlers directly and let Claude think in terms of those tool names).
  - System prompt (checked into code, also mirrored in `docs/sample_incidents/PROMPT.md`):
    > You are an on-call reliability engineer for a daily financial data pipeline. A job has just failed. Use the tools to inspect the latest job log, recent DB rows, and job metrics. Produce a short incident report with exactly these sections: **Root cause** (one paragraph, quote evidence from tool calls), **Evidence** (bullet list, each item names the tool used), **Recommended action** (one line). Do not speculate beyond the evidence. If evidence is insufficient, say so plainly.
  - Model: `claude-haiku-4-5-20251001` (from `DIAGNOSIS_MODEL`).
  - Returns the final text; the caller fans it out to sinks.

**Implementation notes**
- Claude's tool-use loop: send initial message with tools; if response contains `tool_use` blocks, run the tools, append `tool_result` content, re-send. Cap at 5 loop iterations to prevent runaway.
- Slack blocks: wrap the diagnosis in a single `section` block with `mrkdwn` text. Include a header block with the incident ID and status.

**How to test**
1. Make sure a failed `job_runs` row exists:
```bash
# Cause a synthetic failure by running with an invalid DB URL
DATABASE_URL=postgresql://bad:bad@localhost:5434/nope uv run python -m src.pipeline || true

# Or insert a fake failure row manually:
docker exec jobwatch-postgres psql -U jobwatch -d jobwatch -c \
  "INSERT INTO job_runs (started_at, finished_at, status, rows_written, error_type, error_message, log_snippet) \
   VALUES (now()-interval '1 minute', now(), 'failed', 0, 'OperationalError', 'could not connect to server', 'connection refused on port 5434');"
```

2. Run the diagnose on that row:
```bash
uv run python -c "\
from src.diagnose import diagnose; \
from src.alert_sinks import fan_out; \
summary = diagnose(job_id=None); print(summary); fan_out(summary)"
```
Expected output: a 3-paragraph incident report in stdout; a line appended to `incidents.log`; if `SLACK_WEBHOOK_URL` is set, a message in your Slack channel.

**Acceptance**
- [ ] Diagnosis output has all three sections (Root cause / Evidence / Recommended action)
- [ ] The Evidence section references at least one tool by name (proving tool use actually ran)
- [ ] `incidents.log` has a new entry
- [ ] If Slack URL is set, message appears in-channel within 5s
- [ ] Total API cost printed at end of run (optional but nice — log token usage)

---

## Phase 6 — Monitor loop (finishes Block 5–7)

A lightweight loop that detects fresh failures and triggers the diagnose flow.

**Deliverables**
- `src/monitor.py`
  - Polls `job_runs` every 5 seconds for new rows (`id > last_seen_id`) with `status='failed'` OR `rows_written < ROWS_WRITTEN_THRESHOLD`.
  - On a hit, calls `diagnose(job_id)` and then `fan_out(summary)`.
  - Persists `last_seen_id` in-memory (fine for a demo; note this in README as a limitation).
  - `main()` entrypoint with a `--once` flag that processes at most one failure and exits (used in tests).

**How to test**
```bash
# Start the monitor in one terminal
uv run python -m src.monitor &
MON_PID=$!

# Insert a synthetic failure
docker exec jobwatch-postgres psql -U jobwatch -d jobwatch -c \
  "INSERT INTO job_runs (started_at, finished_at, status, rows_written, error_type, error_message, log_snippet) \
   VALUES (now(), now(), 'failed', 0, 'SyntheticError', 'injected for monitor test', 'test log tail');"

# Within ~10s you should see a diagnosis printed + Slack message + incidents.log entry.
kill $MON_PID
```

**Acceptance**
- [ ] Monitor detects the new failure within one polling interval
- [ ] Only fires once per new failure (no duplicate Slack messages for the same `job_runs.id`)

---

## Phase 7 — Failure injection + sample capture (Block 7–8)

Produce the two reproducible demo scenarios and capture their real LLM outputs.

**Deliverables**
- `scripts/break_it.py`
  - `--mode postgres` → `docker compose stop postgres` (wraps `subprocess.run`).
  - `--mode ticker` → rewrites `.env` to set `TICKERS=GOOGL,AMZN,ZZZZZ,NFLX,DELIST1`.
  - `--mode restore` → restores `TICKERS` to the default 6 (GOOGL, AMZN, AAPL, NFLX, NVDA, ORCL).
- `docs/sample_incidents/01_postgres_down.md` — captured diagnosis from scenario 1.
- `docs/sample_incidents/02_delisted_ticker.md` — captured diagnosis from scenario 2.
- `docs/sample_incidents/PROMPT.md` — the system prompt used (for reader transparency).

**Test / capture procedure**

Scenario 1 — Postgres outage:
```bash
uv run python -m src.monitor &
MON_PID=$!
uv run python -m src.pipeline &        # running pipeline
sleep 2
python scripts/break_it.py --mode postgres
# Pipeline will error; monitor picks up the failed job_runs row (if any got written before the stop)
# OR you insert a synthetic 'failed' row as in Phase 5.
# Save the printed diagnosis into docs/sample_incidents/01_postgres_down.md
docker compose start postgres
kill $MON_PID
```

Scenario 2 — Delisted ticker:
```bash
python scripts/break_it.py --mode ticker
uv run python -m src.pipeline        # writes job_runs with rows_written < threshold
uv run python -m src.monitor --once  # triggers diagnose once and exits
# Save output into docs/sample_incidents/02_delisted_ticker.md
python scripts/break_it.py --mode restore
```

**Acceptance**
- [ ] Two markdown files in `docs/sample_incidents/`, each with a full, believable LLM diagnosis
- [ ] `break_it.py --mode restore` cleanly reverts `.env`
- [ ] Running scenario 1 twice produces two distinct `incidents.log` entries

---

## Phase 8 — Concurrency test + semaphore finding (Block 8–9)

The interview-credible performance finding.

**Deliverables**
- `scripts/concurrency_test.py`
  - Arg `--n 1,2,3,5,10` (comma-separated concurrency levels).
  - For each N: spawn N asyncio tasks calling `query_recent_rows` (or the DB-backed handler directly — faster to set up than N stdio subprocesses, and it still surfaces the contention).
  - Records per-request latencies, computes p50/p95/p99.
  - Writes `docs/concurrency_findings.md` (markdown table) and `docs/concurrency_latency.png` (matplotlib, latency vs concurrency).
- Apply the fix: inside `src/mcp_server/server.py`, add `asyncio.Semaphore(3)` around the DB call. Re-run the test. Capture before/after numbers in the same markdown file.

**How to test**
```bash
# Baseline (no semaphore)
uv run python scripts/concurrency_test.py --n 1,2,3,5,10 --label baseline

# (edit server.py to add the semaphore)

# After fix
uv run python scripts/concurrency_test.py --n 1,2,3,5,10 --label fixed

cat docs/concurrency_findings.md
```
Expected: the markdown shows two tables (baseline and fixed) with p50/p95/p99. At some N, baseline p99 should spike meaningfully; fixed version should be flatter.

**Acceptance**
- [ ] Numbers are real (not hand-edited) — the script writes them
- [ ] There's a visible difference before/after the semaphore (even 2x on p99 is enough)
- [ ] Chart PNG renders and shows the shape clearly

---

## Phase 9 — Tests (minimal, high-signal)

**Deliverables**
- `tests/test_ingest.py`
  - Feed a hand-crafted DataFrame into `transform()`; assert `rolling_avg_20` is `NaN` for first 19 rows, correct on row 20+; assert `anomaly` flags the seeded outlier.
- `tests/test_fault_injection.py`
  - Use `testcontainers` to spin up a throwaway Postgres.
  - Start the MCP server subprocess pointed at that container.
  - Call `query_recent_rows`; assert a sensible result shape (may be empty).
  - Stop the container mid-test.
  - Call `query_recent_rows` again; assert the response is `{"error": ..., "error_type": ...}` and the server process is still alive.

**How to test**
```bash
uv run pytest -v
```

**Acceptance**
- [ ] Both tests pass green
- [ ] Fault-injection test actually kills the container (not a mock) — grep the test for `container.stop()` or equivalent

---

## Phase 10 — README, diagram, video (Block 9–10)

**Deliverables**
- `README.md` structured per `plan.md` (hook, architecture, before/after, quickstart, prompt, concurrency finding, limitations, cost note).
- `docs/architecture.md` with a Mermaid diagram (GitHub renders these natively).
- A 2-minute walkthrough recorded with Loom (or any screen recorder): boot the stack, show a live break, show the Slack message, show the concurrency chart. Paste the link in the README.

**Acceptance**
- [ ] README renders cleanly on GitHub (architecture diagram visible, before/after block visible above the fold)
- [ ] Video link works and stays under 3 minutes
- [ ] A fresh clone + `cp .env.example .env` + `docker compose up -d postgres` + `uv sync --extra dev` + `make run-pipeline` runs successfully on another machine

---

## Global rules of the road

1. **Commit after every phase** with a message like `phase N: <deliverable>`. The git log is part of the deliverable.
2. If a phase's tests don't pass, stop — do not accumulate partial work across phases.
3. Token cost monitor: print the Anthropic usage (input/output tokens) every diagnosis call. Budget ~$0.50 total for the whole 1-day build; halt and investigate if you burn past that.
4. If blocked for >20 min on any phase, cut scope (e.g., drop testcontainers in Phase 9 and replace with a plain integration test against the running compose DB).
