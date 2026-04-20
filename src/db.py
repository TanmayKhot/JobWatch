"""Postgres connection helpers built on psycopg3."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg_pool import ConnectionPool

from src.config import DATABASE_URL


def get_conn() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL)


_POOL: ConnectionPool | None = None


def get_pool(size: int = 5) -> ConnectionPool:
    global _POOL
    if _POOL is None:
        _POOL = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=1,
            max_size=size,
            open=True,
        )
    return _POOL


@contextmanager
def cursor() -> Iterator[psycopg.Cursor]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
