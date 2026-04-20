"""Transform correctness: rolling_avg_20 and 3-sigma anomaly flagging."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.ingest import transform


def _bars(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1_000] * len(closes),
        },
        index=idx,
    )


def test_transform_empty_df_returns_empty() -> None:
    assert transform(pd.DataFrame()).empty


def test_rolling_avg_matches_manual_mean() -> None:
    closes = list(np.linspace(100.0, 119.0, num=25))
    out = transform(_bars(closes))
    # Row 19 (20th bar) is the first one with enough history.
    expected = float(np.mean(closes[0:20]))
    assert abs(out["rolling_avg_20"].iloc[19] - expected) < 1e-9
    # Early rows should be NaN until the window fills.
    assert out["rolling_avg_20"].iloc[:19].isna().all()


def test_anomaly_flagged_on_large_spike() -> None:
    flat = [100.0] * 20
    spike = [100.0] * 4 + [1_000.0]  # huge jump at index 24
    out = transform(_bars(flat + spike))
    assert out["anomaly"].iloc[24]
    # The flat region should not be flagged.
    assert not out["anomaly"].iloc[19:24].any()


def test_anomaly_never_flagged_on_flat_series() -> None:
    out = transform(_bars([100.0] * 40))
    assert not out["anomaly"].any()
