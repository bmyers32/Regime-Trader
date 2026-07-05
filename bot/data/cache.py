"""
Parquet-backed candle cache. One file per instrument+granularity under cache_dir.

Files live in instance/candle_cache/ which is gitignored (instance/ rule in .gitignore).
On a fresh clone the directory is empty; bot startup fetches history on first warm_up.

Phase 8 construction order:
    cache = CandleCache(cache_dir)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


class CandleCache:
    """
    Stores and retrieves OHLCV DataFrames as parquet files.

    Thread-safety: not designed for concurrent writers — the bot is single-threaded.
    Reads from the dashboard are safe (parquet writes are atomic file-replace).
    """

    def __init__(self, cache_dir: Path) -> None:
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, instrument: str, granularity: str) -> Path:
        return self._dir / f"{instrument}_{granularity}.parquet"

    def load(self, instrument: str, granularity: str) -> pd.DataFrame | None:
        """Return cached DataFrame, or None if no cache file exists."""
        p = self._path(instrument, granularity)
        if not p.exists():
            return None
        df = pd.read_parquet(p)
        # Restore UTC timezone after parquet round-trip (parquet preserves tz but double-check)
        if not df.empty and df["time"].dt.tz is None:
            df["time"] = df["time"].dt.tz_localize("UTC")
        return df

    def save(self, instrument: str, granularity: str, df: pd.DataFrame) -> None:
        """
        Write DataFrame to parquet atomically (write to tmp, then rename).
        Atomic replace prevents a crash mid-write from corrupting the cache.
        """
        if df.empty:
            return
        p = self._path(instrument, granularity)
        tmp = p.with_suffix(".tmp.parquet")
        df.to_parquet(tmp, index=False)
        tmp.replace(p)

    def last_complete_ts(self, instrument: str, granularity: str) -> datetime | None:
        """
        Return the UTC timestamp of the most recent candle in cache, or None.
        Used by DataProvider to set from= on every incremental fetch.
        """
        df = self.load(instrument, granularity)
        if df is None or df.empty:
            return None
        ts = df["time"].max()
        # pd.Timestamp → python datetime, UTC-aware
        return ts.to_pydatetime().astimezone(timezone.utc)
