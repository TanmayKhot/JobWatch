"""Central configuration. Loads .env at import time; validation is lazy."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=False)


DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://jobwatch:jobwatch@localhost:5434/jobwatch",
)
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "")
DIAGNOSIS_MODEL: str = os.getenv("DIAGNOSIS_MODEL", "claude-haiku-4-5-20251001")
METRICS_PORT: int = int(os.getenv("METRICS_PORT", "9100"))
ROWS_WRITTEN_THRESHOLD: int = int(os.getenv("ROWS_WRITTEN_THRESHOLD", "3"))

_RAW_TICKERS = os.getenv("TICKERS", "GOOGL,AMZN,AAPL,NFLX,NVDA,ORCL")
TICKERS: list[str] = [t.strip().upper() for t in _RAW_TICKERS.split(",") if t.strip()]


def require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Required environment variable {name!r} is not set. "
            f"Add it to .env (see .env.example) or export it."
        )
    return value
