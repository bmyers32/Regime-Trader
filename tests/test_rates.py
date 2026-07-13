"""
bot.data.rates tests (TRADING-RULES §6, 2026-07-12 carry-with-regime-conditioning
hearing, slot 2, amendment 1). Covers: the as-of/no-lookahead effective-date shift
(daily currencies unchanged, monthly-proxy currencies pushed to the first of the
FOLLOWING month), rate_asof's no-lookahead property (never returns a value whose
effective date is after the query date -- same discipline test_backtest.py's
RegimeResult.htf_window no-lookahead test uses), and PolicyRateCache's save/load
round-trip.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from bot.data.rates import PolicyRateCache, apply_effective_date_shift, rate_asof


def _raw(dates: list[str], rates: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"date": pd.to_datetime(dates, utc=True), "rate": rates})


class TestEffectiveDateShift:
    def test_daily_currency_unchanged(self) -> None:
        raw = _raw(["2024-03-15", "2024-03-16"], [5.25, 5.25])
        shifted = apply_effective_date_shift(raw, "USD")
        assert list(shifted["date"]) == list(raw["date"])

    def test_monthly_proxy_currency_shifts_to_first_of_next_month(self) -> None:
        raw = _raw(["2024-03-01", "2024-04-01"], [0.1, 0.25])
        shifted = apply_effective_date_shift(raw, "JPY")
        assert list(shifted["date"]) == list(pd.to_datetime(["2024-04-01", "2024-05-01"], utc=True))

    def test_monthly_proxy_mid_month_observation_still_shifts_to_next_month_start(self) -> None:
        """OECD MEI dates observations to the 1st regardless -- but the shift logic
        itself must not depend on the observation already being month-aligned."""
        raw = _raw(["2024-03-17"], [0.1])
        shifted = apply_effective_date_shift(raw, "AUD")
        assert shifted["date"].iloc[0] == pd.Timestamp("2024-04-01", tz="UTC")

    def test_only_jpy_and_aud_get_shifted(self) -> None:
        raw = _raw(["2024-03-15"], [1.0])
        for ccy in ("USD", "EUR", "GBP"):
            assert apply_effective_date_shift(raw, ccy)["date"].iloc[0] == raw["date"].iloc[0]
        for ccy in ("JPY", "AUD"):
            assert apply_effective_date_shift(raw, ccy)["date"].iloc[0] == pd.Timestamp(
                "2024-04-01", tz="UTC"
            )


class TestRateAsofNoLookahead:
    def test_returns_latest_effective_value_on_or_before_query_date(self) -> None:
        rates = _raw(["2024-01-01", "2024-06-01", "2024-12-01"], [1.0, 2.0, 3.0])
        queries = pd.Series(pd.to_datetime(["2024-03-01", "2024-06-01", "2024-11-30"], utc=True))
        result = rate_asof(rates, queries)
        assert list(result) == [1.0, 2.0, 2.0]

    def test_never_returns_a_value_whose_effective_date_is_after_the_query(self) -> None:
        """The no-lookahead property, directly: for every query date, the returned
        rate's effective date must be <= the query date -- swept across a dense grid
        straddling every real observation so no off-by-one slips through."""
        rates = _raw(["2024-02-01", "2024-05-01", "2024-08-01"], [0.5, 0.75, 1.0])
        grid = pd.Series(pd.date_range("2024-01-15", "2024-09-15", freq="D", tz="UTC"))
        result = rate_asof(rates, grid)

        for query_date, returned_rate in zip(grid, result):
            if pd.isna(returned_rate):
                assert query_date < rates["date"].iloc[0]
                continue
            effective_date = rates.loc[rates["rate"] == returned_rate, "date"].iloc[0]
            assert effective_date <= query_date

    def test_nan_before_first_effective_date(self) -> None:
        rates = _raw(["2024-06-01"], [1.0])
        queries = pd.Series(pd.to_datetime(["2024-01-01", "2024-06-01"], utc=True))
        result = rate_asof(rates, queries)
        assert pd.isna(result.iloc[0])
        assert result.iloc[1] == 1.0

    def test_result_aligned_to_original_index_including_gaps(self) -> None:
        """rate_asof internally sorts by date for the merge -- the returned Series
        must still line up with as_of_dates' own (possibly non-contiguous) index."""
        rates = _raw(["2024-01-01", "2024-06-01"], [1.0, 2.0])
        queries = pd.Series(
            pd.to_datetime(["2024-07-01", "2024-02-01", "2024-08-01"], utc=True),
            index=[10, 20, 30],
        )
        result = rate_asof(rates, queries)
        assert list(result.index) == [10, 20, 30]
        assert result.loc[10] == 2.0  # July -> June observation
        assert result.loc[20] == 1.0  # Feb -> Jan observation
        assert result.loc[30] == 2.0  # Aug -> June observation


class TestPolicyRateCache:
    def test_save_then_load_round_trips(self, tmp_path: Path) -> None:
        cache = PolicyRateCache(tmp_path)
        df = _raw(["2024-01-01", "2024-02-01"], [1.0, 1.5])
        cache.save("USD", df)

        loaded = cache.load("USD")
        assert loaded is not None
        assert list(loaded["date"]) == list(df["date"])
        assert list(loaded["rate"]) == list(df["rate"])

    def test_load_missing_currency_returns_none(self, tmp_path: Path) -> None:
        cache = PolicyRateCache(tmp_path)
        assert cache.load("XYZ") is None

    def test_save_empty_dataframe_is_a_noop(self, tmp_path: Path) -> None:
        cache = PolicyRateCache(tmp_path)
        cache.save("USD", pd.DataFrame(columns=["date", "rate"]))
        assert cache.load("USD") is None
