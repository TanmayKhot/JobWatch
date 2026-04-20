"""Fault-injection: MCP tools must return a structured error, never raise.

The monitor calls these tools in-process from the diagnosis loop; a bare
exception would abort the run. The `_instrumented` decorator is the contract
we're validating.
"""

from __future__ import annotations

import psycopg
import pytest

from src.mcp_server import server as mcp_server


@pytest.fixture
def db_down(monkeypatch):
    """Force every pool checkout to raise OperationalError, as if Postgres died."""

    class _FakePool:
        def connection(self):
            raise psycopg.OperationalError("simulated: connection refused")

    monkeypatch.setattr(mcp_server, "get_pool", lambda *a, **kw: _FakePool())


def test_query_recent_rows_returns_error_dict_when_db_down(db_down):
    result = mcp_server.query_recent_rows("AAPL", limit=5)
    assert isinstance(result, dict)
    assert result["error_type"] == "OperationalError"
    assert "connection refused" in result["error"]


def test_get_job_log_returns_error_dict_when_db_down(db_down):
    result = mcp_server.get_job_log()
    assert isinstance(result, dict)
    assert result["error_type"] == "OperationalError"


def test_get_last_job_metrics_returns_error_dict_when_db_down(db_down):
    result = mcp_server.get_last_job_metrics()
    assert isinstance(result, dict)
    assert result["error_type"] == "OperationalError"


def test_metrics_counter_records_error_status(db_down):
    from src.metrics import mcp_tool_calls_total

    before = mcp_tool_calls_total.labels(tool="query_recent_rows", status="error")._value.get()
    mcp_server.query_recent_rows("AAPL")
    after = mcp_tool_calls_total.labels(tool="query_recent_rows", status="error")._value.get()
    assert after == before + 1
