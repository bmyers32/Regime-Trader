"""
PolicyRateCache: parquet-per-currency cache for historical central-bank policy-rate
(or best-available proxy) series, TRADING-RULES §6 carry-with-regime-conditioning
hearing (slot 2). See HANDOFF.md for the full signal-source resolution and the four
amendments this module implements.

Unlike bot/data/cache.py's CandleCache (instance/candle_cache/, gitignored, per-machine,
re-fetched every warm_up), this cache is TRACKED in git under calibration/rates/ --
small, holds no secrets, and a hearing's evidence must survive a fresh clone without
re-hitting FRED or trusting whichever machine happened to fetch it (amendment 3,
HANDOFF.md).

As-of / no-lookahead convention (amendment 1, HANDOFF.md):
  - Daily-source currencies (USD, EUR, GBP): the observation date IS the effective
    date -- no extra lag.
  - Monthly OECD-proxy currencies (JPY, AUD): effective from the FIRST DAY OF THE
    FOLLOWING MONTH, modeling OECD MEI's real publication lag -- never the nominal
    observation-month date.
No backfill, no interpolation either case -- rate_asof() only ever returns a value
whose effective date is <= the requested date (no-lookahead property tested in
tests/test_rates.py).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# Currencies whose FRED source is a monthly OECD proxy -- these get the "shift to
# first of next month" no-lookahead treatment. Daily-source currencies (USD, EUR, GBP)
# use their observation date as-is.
_MONTHLY_FREQUENCY_CURRENCIES = frozenset({"JPY", "AUD"})


class PolicyRateCache:
    """
    Stores/retrieves per-currency policy-rate history as parquet under a TRACKED
    (not gitignored) directory. One file per currency: {CCY}_policy_rate.parquet,
    columns {date, rate}. Mirrors bot.data.cache.CandleCache's per-instrument
    convention, adapted for currency-keyed (not instrument+granularity-keyed) data.
    """

    def __init__(self, cache_dir: Path) -> None:
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, currency: str) -> Path:
        return self._dir / f"{currency}_policy_rate.parquet"

    def load(self, currency: str) -> pd.DataFrame | None:
        """Return cached {date, rate} DataFrame (effective-date-adjusted), or None."""
        p = self._path(currency)
        if not p.exists():
            return None
        df = pd.read_parquet(p)
        if not df.empty and df["date"].dt.tz is None:
            df["date"] = df["date"].dt.tz_localize("UTC")
        return df

    def save(self, currency: str, df: pd.DataFrame) -> None:
        """
        Write {date, rate} DataFrame to parquet atomically (write to tmp, then rename).
        `date` must already be the EFFECTIVE date (post no-lookahead shift) -- this
        cache does not apply the monthly-proxy shift itself; the fetcher does, once, at
        fetch time (scripts/fetch_policy_rates.py, via apply_effective_date_shift), so
        every downstream reader (including rate_asof()) works off already-lawful dates.
        """
        if df.empty:
            return
        p = self._path(currency)
        tmp = p.with_suffix(".tmp.parquet")
        df.sort_values("date").reset_index(drop=True).to_parquet(tmp, index=False)
        tmp.replace(p)


def apply_effective_date_shift(raw_df: pd.DataFrame, currency: str) -> pd.DataFrame:
    """
    Convert a raw fetched {date, rate} series (date = FRED's own observation date) into
    the effective-date convention rate_asof() assumes (amendment 1, HANDOFF.md):
      - Daily-source currencies (USD, EUR, GBP): unchanged -- observation date IS the
        effective date.
      - Monthly-proxy currencies (JPY, AUD): shifted to the first day of the FOLLOWING
        month -- models the real OECD MEI publication lag. A March observation becomes
        effective 1 April, never retroactively 1 March.
    """
    df = raw_df.copy()
    if currency in _MONTHLY_FREQUENCY_CURRENCIES:
        shifted = df["date"].dt.tz_localize(None).dt.to_period("M").dt.to_timestamp() + pd.DateOffset(
            months=1
        )
        df["date"] = shifted.dt.tz_localize("UTC")
    return df


def rate_asof(rate_df: pd.DataFrame, as_of_dates: pd.Series) -> pd.Series:
    """
    Look up each date in `as_of_dates` against `rate_df` (columns {date, rate}, already
    effective-date-shifted) via merge_asof(direction='backward') -- the same
    no-lookahead-safe idiom scripts/run_validation_gates.py already uses to broadcast
    the HTF regime timeline onto LTF bars. Returns a Series aligned to as_of_dates'
    original index; NaN for any date earlier than the rate series' first effective date.
    """
    lookup = pd.DataFrame({"date": as_of_dates.reset_index(drop=True), "_orig_pos": range(len(as_of_dates))})
    merged = pd.merge_asof(
        lookup.sort_values("date"),
        rate_df[["date", "rate"]].sort_values("date"),
        on="date",
        direction="backward",
    ).sort_values("_orig_pos")
    return pd.Series(merged["rate"].to_numpy(), index=as_of_dates.index)
