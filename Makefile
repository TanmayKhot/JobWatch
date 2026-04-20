.PHONY: help up down logs psql sync run-pipeline monitor mcp-metrics test break-postgres break-ticker restore-ticker load-test clean

help:
	@echo "JobWatch — common targets"
	@echo "  make up               Start Postgres (docker compose)"
	@echo "  make down             Stop Postgres"
	@echo "  make logs             Tail Postgres logs"
	@echo "  make psql             Open a psql shell against the local DB"
	@echo "  make sync             uv sync (install deps incl. dev extras)"
	@echo "  make run-pipeline     Run the ingest pipeline once"
	@echo "  make monitor          Run the failure monitor loop"
	@echo "  make mcp-metrics      Curl the MCP server /metrics endpoint"
	@echo "  make test             Run pytest"
	@echo "  make break-postgres   Stop Postgres to simulate a DB outage"
	@echo "  make break-ticker     Inject a bad ticker into .env"
	@echo "  make restore-ticker   Restore the default ticker list"
	@echo "  make load-test        Run the concurrency test (writes docs/concurrency_findings.md)"
	@echo "  make clean            Remove caches and logs"

up:
	docker compose up -d postgres

down:
	docker compose down

logs:
	docker compose logs -f postgres

psql:
	docker exec -it jobwatch-postgres psql -U jobwatch -d jobwatch

sync:
	uv sync --extra dev

run-pipeline:
	uv run python -m src.pipeline

monitor:
	uv run python -m src.monitor

mcp-metrics:
	curl -s http://localhost:9100/metrics | grep -E '^mcp_tool|^# HELP mcp'

test:
	uv run pytest -v

break-postgres:
	docker compose stop postgres

break-ticker:
	uv run python scripts/break_it.py --mode ticker

restore-ticker:
	uv run python scripts/break_it.py --mode restore

load-test:
	uv run python scripts/concurrency_test.py --n 1,2,3,5,10

clean:
	rm -rf .pytest_cache __pycache__ src/__pycache__ tests/__pycache__ incidents.log
	find . -name "*.pyc" -delete
