Here is a high-level walkthrough of what **JobWatch** is and what it does.

---

## What is JobWatch?

JobWatch is an **AI-powered on-call assistant for a financial data pipeline**. Its core idea is simple: instead of just recording that a pipeline failed, it automatically investigates the failure using an AI (Claude/Anthropic) and produces a plain-English incident report — almost like having a junior SRE who wakes up when something breaks, looks at the evidence, and writes up what happened.

---

## What does the pipeline do?

There is a scheduled data pipeline that:
- **Fetches stock market data** (OHLCV — Open, High, Low, Close, Volume) for a configured list of tickers from Yahoo Finance.
- **Transforms it** — calculating rolling averages and flagging statistical anomalies.
- **Stores it** in a PostgreSQL database.
- Every time it runs, it **records metadata about that run** — how many rows were written, whether it succeeded or failed, and a snippet of any error logs.

---

## What does the monitor do?

A separate **monitor** process keeps an eye on those run records. Every few seconds it checks:
- Did any run **fail**?
- Did any run write **fewer rows than expected** (a silent failure)?

When either of those happens, it triggers the diagnosis process.

---

## What does the AI diagnosis do?

This is the interesting part. When a bad run is detected, JobWatch:
1. **Calls Claude (Anthropic's AI)** with a set of tools that can query the database — looking at recent data rows, the job's error log, and pipeline metrics.
2. Claude **iteratively uses those tools** (up to 5 rounds) to gather evidence, like a detective piecing together what went wrong.
3. Claude then produces a **structured incident report** covering: root cause, evidence found, where to look in the code, and recommended action.

---

## How do alerts get delivered?

Once the diagnosis is complete, the incident report is:
- **Posted to Slack** (if a webhook is configured) as a nicely formatted message.
- **Appended to an `incidents.log` file** on disk.
- **Printed to the terminal** where the monitor is running.

---

## What else is included?

- An **MCP (Model Context Protocol) server** is also exposed, which allows external AI tools (like the MCP Inspector) to connect and use the same database-querying tools interactively.
- **Prometheus metrics** are emitted so you could hook up a Grafana dashboard in the future.
- **Fault injection scripts and tests** are included to deliberately break the pipeline and verify that the monitoring and diagnosis system catches it correctly.

---

## The big picture

In one sentence: **JobWatch automates the "what just broke and why?" investigation** that a human on-call engineer would normally do at 2am — by having an AI look at the same logs and database records a human would, and writing up a clear incident report automatically.
