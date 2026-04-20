# Backlog

Items deferred during the 1-day build. Track here so nothing gets lost.

## v2 / post-demo

- [ ] Grafana dashboard panel (pipeline health: job runtime, row counts, error rate; MCP: tool latency + error rate).
- [ ] PagerDuty sink (parallel to Slack) — reuse incident-body formatting, add PD routing key.
- [ ] Retry with exponential backoff on yfinance fetch (currently logs and skips).
- [ ] Auth on the MCP server (token header) — currently open.
- [ ] Replace in-memory `last_seen_id` in the monitor with a checkpoint table so restarts don't miss failures.
- [ ] Locust-based load test (current `concurrency_test.py` covers p50/p95/p99 adequately for the interview story).
- [ ] Full pytest matrix across correctness / fault-injection / recovery / schema-drift (minimal coverage ships in Phase 9).
- [ ] Cron/systemd timer for daily ingest after market close.
