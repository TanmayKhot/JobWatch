"""LLM-backed incident diagnosis via the Anthropic tool-use loop."""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from src.config import DIAGNOSIS_MODEL, require
from src.mcp_server.server import (
    get_job_log,
    get_last_job_metrics,
    query_recent_rows,
)

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an on-call reliability engineer for a daily financial data pipeline that ingests OHLCV bars from yfinance into Postgres.

A job just failed or produced suspiciously few rows. Use the tools to investigate: the latest job_runs row (including its captured log_snippet), compact job metrics, and recent OHLCV rows per ticker when relevant.

The on-call engineer receiving this report is scanning many alerts at once. Give them precise pointers so they can jump straight to the failing record without re-deriving anything.

Produce a short incident report with exactly these four sections, in this order:

**Root cause** — bullet list of 3–5 short bullets. Each bullet states one concrete fact drawn from a tool call. Lead with the what, not prose. No paragraph.

**Evidence** — bullet list. Each bullet must have this shape:
  - `<tool_name>` — <the exact value or quoted log line that supports Root cause>

**Where to look** — bullet list of pointers for a human reviewer. Include every item that applies:
  - job_id=<N>
  - Time window: <started_at> → <finished_at> (UTC)
  - First failing log line, quoted verbatim from log_snippet (keep the timestamp prefix)
  - psql handle, e.g. `SELECT * FROM job_runs WHERE id = <N>;`
  - Affected tickers, if any

**Recommended action** — one line, imperative.

Rules:
- Do not speculate beyond what the tools returned. If evidence is insufficient, say so plainly in the Root cause bullets.
- Always cite the specific job_id and the started_at/finished_at timestamps so the reviewer can filter logs without rereading this report."""


TOOLS: list[dict[str, Any]] = [
    {
        "name": "query_recent_rows",
        "description": "Return the most recent OHLCV rows for a ticker, newest first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Ticker symbol, e.g. AAPL"},
                "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_job_log",
        "description": "Return the most recent job_runs row (or a specific job_id), including its captured log_snippet.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "integer", "description": "Optional specific job id."},
            },
        },
    },
    {
        "name": "get_last_job_metrics",
        "description": "Compact metrics for the most recent job_runs row: rows_written, status, error_type, duration_sec.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

_HANDLERS = {
    "query_recent_rows": query_recent_rows,
    "get_job_log": get_job_log,
    "get_last_job_metrics": get_last_job_metrics,
}


def _run_tool(name: str, args: dict) -> Any:
    fn = _HANDLERS[name]
    return fn(**args)


def diagnose(job_id: int | None = None, max_iterations: int = 5) -> dict[str, Any]:
    client = anthropic.Anthropic(api_key=require("ANTHROPIC_API_KEY"))

    user_msg = (
        "Diagnose the latest pipeline failure."
        if job_id is None
        else f"Diagnose pipeline failure for job_id={job_id}."
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_msg}]

    total_input_tokens = 0
    total_output_tokens = 0
    tool_calls_made: list[dict] = []

    for iteration in range(max_iterations):
        response = client.messages.create(
            model=DIAGNOSIS_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )
        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    args = block.input or {}
                    result = _run_tool(block.name, args)
                    tool_calls_made.append(
                        {"name": block.name, "args": args}
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, default=str),
                        }
                    )
            messages.append({"role": "user", "content": tool_results})
            continue

        text_parts = [b.text for b in response.content if b.type == "text"]
        text = "\n\n".join(text_parts).strip()
        return {
            "text": text,
            "iterations": iteration + 1,
            "tool_calls": tool_calls_made,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "model": DIAGNOSIS_MODEL,
        }

    return {
        "text": f"Diagnosis loop hit max_iterations={max_iterations} without a final answer.",
        "iterations": max_iterations,
        "tool_calls": tool_calls_made,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "model": DIAGNOSIS_MODEL,
    }
