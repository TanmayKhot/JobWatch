"""Prometheus metrics shared between the pipeline and the MCP server."""

from __future__ import annotations

from prometheus_client import Counter, Histogram, start_http_server

pipeline_runs_total = Counter(
    "pipeline_runs_total",
    "Total pipeline runs, labeled by status",
    ["status"],
)

pipeline_rows_written_total = Counter(
    "pipeline_rows_written_total",
    "Total OHLCV rows written by the pipeline",
)

pipeline_duration_seconds = Histogram(
    "pipeline_duration_seconds",
    "Pipeline run duration in seconds",
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)

mcp_tool_calls_total = Counter(
    "mcp_tool_calls_total",
    "MCP tool call count",
    ["tool", "status"],
)

mcp_tool_latency_seconds = Histogram(
    "mcp_tool_latency_seconds",
    "MCP tool call latency in seconds",
    ["tool"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)

_started = False


def start_metrics_server(port: int) -> None:
    global _started
    if _started:
        return
    try:
        start_http_server(port)
    except OSError as exc:
        if exc.errno == 98:
            _started = True
            return
        raise
    _started = True
