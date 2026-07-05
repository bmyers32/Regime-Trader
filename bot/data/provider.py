"""
DataProvider: the single entry point that strategy code and the backtester use
to obtain OHLCV DataFrames.

Design invariants:
- Every get_candles() call makes exactly ONE OANDA request using from=last_cached_ts
  (DECISION 1). There is no "skip if fresh" guard — callers always get up-to-date data.
- complete==True is enforced by CandleFetcher; DataProvider never touches incomplete candles.
- Boundary-candle deduplication: the candle at last_cached_ts may be returned again by
  OANDA; merge + drop_duplicates(keep='last') on 'time' is idempotent.
- warm_up() is the live-loop entry point: reads parquet + gap-fetches live_warmup_candles.
- fetch_history() is the one-time historical store builder (not called in live loop).

Phase 8 construction order:
    provider = DataProvider(fetcher, cache, precision, instruments_config)
    provider.warm_up(instrument_names, granularities)
    # then main loop calls provider.get_candles(...)
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pandas as pd

from .cache import CandleCache
from .fetcher import CandleFetcher, _granularity_to_minutes
from .precision import PrecisionRegistry


class DataProvider:
    """
    Orchestrates CandleFetcher and CandleCache.

    instruments_config: the INSTRUMENTS dict from config.py (includes defaults).
    The 'defaults' sub-dict is accessed via instruments_config.get('defaults', {}).
    Pass the merged config so per-instrument overrides are respected.
    """

    def __init__(
        self,
        fetcher: CandleFetcher,
        cache: CandleCache,
        precision: PrecisionRegistry,
        instruments_config: dict,
    ) -> None:
        self._fetcher = fetcher
        self._cache = cache
        self._precision = precision
        self._cfg = instruments_config

    def get_candles(
        self, instrument: str, granularity: str, n_bars: int = 500
    ) -> pd.DataFrame:
        """
        Return the most recent `n_bars` complete candles for instrument/granularity.

        Always makes exactly ONE incremental OANDA request (from=last_cached_ts).
        Result is merged with existing cache, deduplicated, re-sorted, saved, then
        the tail n_bars rows are returned.
        """
        existing = self._cache.load(instrument, granularity)
        last_ts = self._cache.last_complete_ts(instrument, granularity)

        if last_ts is None:
            # No cache — full count-based fetch so the cycle can proceed
            new = self._fetcher.fetch(instrument, granularity, count=n_bars)
        else:
            # Incremental: one request from last cached timestamp (inclusive)
            new = self._fetcher.fetch(instrument, granularity, from_dt=last_ts)

        merged = _merge(existing, new)
        self._cache.save(instrument, granularity, merged)
        return merged.tail(n_bars).reset_index(drop=True)

    def warm_up(self, instrument_names: list[str], granularities: list[str]) -> None:
        """
        Live-loop startup: read existing parquet + fetch one gap per pair/TF.

        Gap-fetch is bounded by live_warmup_candles from instruments defaults
        (default 750). This ensures recent context is ready before the first cycle
        without pulling unlimited history on every restart.

        Instruments with no cache fall back to live_warmup_candles count fetch.
        """
        defaults = self._cfg.get("defaults", {})
        warmup_count = int(defaults.get("live_warmup_candles", 750))

        for instrument in instrument_names:
            for gran in granularities:
                last_ts = self._cache.last_complete_ts(instrument, gran)
                if last_ts is None:
                    new = self._fetcher.fetch(instrument, gran, count=warmup_count)
                else:
                    # Exactly one incremental request — bounded implicitly by OANDA response
                    new = self._fetcher.fetch(instrument, gran, from_dt=last_ts)

                existing = self._cache.load(instrument, gran)
                merged = _merge(existing, new)
                self._cache.save(instrument, gran, merged)

    def fetch_history(self, instrument: str, granularity: str) -> None:
        """
        One-time historical store builder. Fetches history_years of candles and
        saves to cache. Call from a setup script or CLI — NOT from the live loop.

        Subsequent calls are cheap: get_candles() incrementally maintains the cache.
        """
        defaults = self._cfg.get("defaults", {})
        history_years = float(defaults.get("history_years", 2))
        minutes_per_bar = _granularity_to_minutes(granularity)
        # Approximate candle count, with 40% buffer for weekends/gaps
        candle_estimate = math.ceil(
            history_years * 365 * 24 * 60 / minutes_per_bar * 0.72
        )
        start_dt = datetime.now(timezone.utc) - timedelta(
            days=math.ceil(history_years * 365 * 1.05)
        )
        new = self._fetcher.fetch(instrument, granularity, from_dt=start_dt)
        existing = self._cache.load(instrument, granularity)
        merged = _merge(existing, new)
        self._cache.save(instrument, granularity, merged)


def _merge(
    existing: pd.DataFrame | None,
    new: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge existing cache with newly fetched candles.
    Deduplicates on 'time', keeping the latest value (idempotent boundary-candle handling).
    Returns sorted ascending by time.
    """
    if existing is None or existing.empty:
        return new.sort_values("time").reset_index(drop=True)
    if new.empty:
        return existing.sort_values("time").reset_index(drop=True)

    combined = pd.concat([existing, new], ignore_index=True)
    combined = (
        combined.drop_duplicates(subset="time", keep="last")
        .sort_values("time")
        .reset_index(drop=True)
    )
    return combined
