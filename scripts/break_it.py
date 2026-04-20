"""Chaos helpers for reproducible demo failures.

Modes:
  postgres  -> docker compose stop postgres (pipeline will hit OperationalError)
  ticker    -> rewrite .env TICKERS= to include bogus symbols
  restore   -> reset TICKERS to the default six + restart postgres if needed
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

DEFAULT_TICKERS = "GOOGL,AMZN,AAPL,NFLX,NVDA,ORCL"
BROKEN_TICKERS = "ZZZZZ,DELIST1,NOTREAL"

TICKER_RE = re.compile(r"^TICKERS=.*$", re.MULTILINE)


def _rewrite_tickers(value: str) -> None:
    if not ENV_PATH.exists():
        sys.exit(f"no .env at {ENV_PATH}")
    text = ENV_PATH.read_text()
    new_line = f"TICKERS={value}"
    if TICKER_RE.search(text):
        text = TICKER_RE.sub(new_line, text, count=1)
    else:
        text = text.rstrip() + f"\n{new_line}\n"
    ENV_PATH.write_text(text)
    print(f"[break_it] .env TICKERS -> {value}")


def _compose(*args: str) -> int:
    cmd = ["docker", "compose", *args]
    print(f"[break_it] {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=ENV_PATH.parent).returncode


def mode_postgres() -> int:
    return _compose("stop", "postgres")


def mode_ticker() -> int:
    _rewrite_tickers(BROKEN_TICKERS)
    return 0


def mode_restore() -> int:
    _rewrite_tickers(DEFAULT_TICKERS)
    _compose("start", "postgres")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", required=True, choices=["postgres", "ticker", "restore"])
    args = p.parse_args()
    return {
        "postgres": mode_postgres,
        "ticker": mode_ticker,
        "restore": mode_restore,
    }[args.mode]()


if __name__ == "__main__":
    sys.exit(main())
