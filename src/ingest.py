"""Fetch, transform, and persist OHLCV data."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import psycopg
import yfinance as yf

log = logging.getLogger(__name__)


def fetch(ticker: str, period: str = "60d") -> pd.DataFrame:
    try:
        df = yf.Ticker(ticker).history(period=period, auto_adjust=False, actions=False)
    except Exception as exc:
        log.warning("fetch failed for %s: %s", ticker, exc)
        return pd.DataFrame()
    if df is None or df.empty:
        log.warning("fetch returned no rows for %s", ticker)
        return pd.DataFrame()
    df = df.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    return df[["open", "high", "low", "close", "volume"]]


def transform(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["rolling_avg_20"] = out["close"].rolling(window=20).mean()
    rolling_std = out["close"].rolling(window=20).std()
    deviation = (out["close"] - out["rolling_avg_20"]).abs()
    out["anomaly"] = (deviation > 3 * rolling_std).fillna(False).astype(bool)
    return out


_UPSERT_SQL = """
INSERT INTO ohlcv (ticker, ts, open, high, low, close, volume, rolling_avg_20, anomaly)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (ticker, ts) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    rolling_avg_20 = EXCLUDED.rolling_avg_20,
    anomaly = EXCLUDED.anomaly
"""


def write(conn: psycopg.Connection, ticker: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    rows = []
    for ts, row in df.iterrows():
        rows.append(
            (
                ticker,
                ts.date(),
                _f(row["open"]),
                _f(row["high"]),
                _f(row["low"]),
                _f(row["close"]),
                _i(row["volume"]),
                _f(row.get("rolling_avg_20")),
                bool(row.get("anomaly", False)),
            )
        )
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_SQL, rows)
    return len(rows)


def _f(v: Any) -> float | None:
    if v is None or pd.isna(v):
        return None
    return float(v)


def _i(v: Any) -> int | None:
    if v is None or pd.isna(v):
        return None
    return int(v)
