"""
Phase 4 — position sizing tests (bot/backtest/sizing.py).

Exit criteria verified here:
  EC-1  direct case (quote == account_currency): hand-computed units
  EC-2  self-conversion case (base == account_currency): hand-computed units
  EC-3  cross case, 'divide' orientation (ACCT_QUOTE conversion pair): hand-computed units
  EC-4  cross case, 'multiply' orientation (QUOTE_ACCT conversion pair): hand-computed units
  EC-5  refusal: missing conversion series raises SizingError, never a fallback guess
  EC-6  refusal: non-positive equity/risk_pct/stop_distance raise SizingError
  EC-7  no-lookahead: rate used at bar t never postdates t (searchsorted alignment)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from bot.backtest.sizing import SizingError, pip_size, pip_value_per_unit, size_position


def _ts(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _series(times: list[datetime], closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"time": pd.to_datetime(times, utc=True), "close": closes})


# ---------------------------------------------------------------------------
# EC-1 direct: quote == account_currency
# ---------------------------------------------------------------------------

def test_direct_case_eur_usd():
    # EUR_USD, account=USD, quote=USD -> pip_value_per_unit == pip_size == 0.0001
    pv = pip_value_per_unit("EUR_USD", "USD", price=1.10, bar_time=_ts(2024, 1, 1))
    assert pv == pytest.approx(0.0001)

    # equity=10000, risk_pct=1% -> risk_amount=100. stop_distance=0.0020 (20 pips).
    # units = 100 / (20 * 0.0001) = 100 / 0.002 = 50000
    units = size_position(
        equity=10000, risk_pct=1.0, stop_distance=0.0020,
        instrument="EUR_USD", account_currency="USD", price=1.10, bar_time=_ts(2024, 1, 1),
    )
    assert units == pytest.approx(50000.0)


# ---------------------------------------------------------------------------
# EC-2 self-conversion: base == account_currency
# ---------------------------------------------------------------------------

def test_self_conversion_case_usd_jpy():
    # USD_JPY, account=USD, base=USD, quote=JPY, price=150.0
    # pip_size(USD_JPY) = 0.01 (JPY-quoted). pip_value_per_unit = 0.01 / 150.0
    pv = pip_value_per_unit("USD_JPY", "USD", price=150.0, bar_time=_ts(2024, 1, 1))
    assert pv == pytest.approx(0.01 / 150.0)

    # equity=10000, risk_pct=1% -> risk_amount=100. stop_distance=0.50 (50 pips at 0.01/pip).
    # stop_distance_pips = 0.50 / 0.01 = 50. units = 100 / (50 * (0.01/150)) = 100 / (0.5/150)
    # = 100 * 150 / 0.5 = 30000
    units = size_position(
        equity=10000, risk_pct=1.0, stop_distance=0.50,
        instrument="USD_JPY", account_currency="USD", price=150.0, bar_time=_ts(2024, 1, 1),
    )
    assert units == pytest.approx(30000.0)


# ---------------------------------------------------------------------------
# EC-3 cross, divide orientation: GBP_JPY needs USD_JPY (ACCT_QUOTE form)
# ---------------------------------------------------------------------------

def test_cross_case_divide_gbp_jpy_via_usd_jpy():
    usd_jpy = _series([_ts(2024, 1, 1, 0), _ts(2024, 1, 1, 6)], [150.0, 150.0])
    conversion_series = {"USD_JPY": usd_jpy}

    # GBP_JPY: base=GBP, quote=JPY, neither == USD -> cross via USD_JPY, orientation 'divide'.
    # pip_size(GBP_JPY) = 0.01. pip_value_per_unit = 0.01 / 150.0 (same math as self-conversion,
    # since USD_JPY IS the ACCT_QUOTE pair here).
    pv = pip_value_per_unit(
        "GBP_JPY", "USD", price=190.0, bar_time=_ts(2024, 1, 1, 3),
        conversion_series=conversion_series,
    )
    assert pv == pytest.approx(0.01 / 150.0)

    # equity=10000, risk_pct=0.5% -> risk_amount=50. stop_distance=1.00 (100 pips).
    # stop_distance_pips = 100. units = 50 / (100 * (0.01/150)) = 50 * 150 / 1.0 = 7500
    units = size_position(
        equity=10000, risk_pct=0.5, stop_distance=1.00,
        instrument="GBP_JPY", account_currency="USD", price=190.0, bar_time=_ts(2024, 1, 1, 3),
        conversion_series=conversion_series,
    )
    assert units == pytest.approx(7500.0)


# ---------------------------------------------------------------------------
# EC-4 cross, multiply orientation: EUR_GBP needs GBP_USD (QUOTE_ACCT form)
# ---------------------------------------------------------------------------

def test_cross_case_multiply_eur_gbp_via_gbp_usd():
    gbp_usd = _series([_ts(2024, 1, 1, 0), _ts(2024, 1, 1, 6)], [1.25, 1.25])
    conversion_series = {"GBP_USD": gbp_usd}

    # EUR_GBP: base=EUR, quote=GBP, neither == USD -> cross via GBP_USD, orientation 'multiply'.
    # pip_size(EUR_GBP) = 0.0001. pip_value_per_unit = 0.0001 * 1.25
    pv = pip_value_per_unit(
        "EUR_GBP", "USD", price=0.85, bar_time=_ts(2024, 1, 1, 3),
        conversion_series=conversion_series,
    )
    assert pv == pytest.approx(0.0001 * 1.25)

    # equity=10000, risk_pct=1% -> risk_amount=100. stop_distance=0.0030 (30 pips).
    # stop_distance_pips = 30. units = 100 / (30 * 0.000125) = 100 / 0.00375 = 26666.67
    units = size_position(
        equity=10000, risk_pct=1.0, stop_distance=0.0030,
        instrument="EUR_GBP", account_currency="USD", price=0.85, bar_time=_ts(2024, 1, 1, 3),
        conversion_series=conversion_series,
    )
    assert units == pytest.approx(100 / (30 * 0.0001 * 1.25))


# ---------------------------------------------------------------------------
# EC-5 refusal: no conversion series available
# ---------------------------------------------------------------------------

def test_refuses_when_conversion_series_missing():
    with pytest.raises(SizingError):
        pip_value_per_unit("GBP_JPY", "USD", price=190.0, bar_time=_ts(2024, 1, 1))


def test_refuses_when_conversion_series_has_no_prior_observation():
    # Series exists but every observation is AFTER bar_time — no lookahead permitted.
    usd_jpy = _series([_ts(2024, 6, 1), _ts(2024, 6, 2)], [150.0, 151.0])
    with pytest.raises(SizingError):
        pip_value_per_unit(
            "GBP_JPY", "USD", price=190.0, bar_time=_ts(2024, 1, 1),
            conversion_series={"USD_JPY": usd_jpy},
        )


# ---------------------------------------------------------------------------
# EC-6 refusal: invalid inputs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "kwargs",
    [
        dict(equity=0, risk_pct=1.0, stop_distance=0.001),
        dict(equity=-100, risk_pct=1.0, stop_distance=0.001),
        dict(equity=10000, risk_pct=0, stop_distance=0.001),
        dict(equity=10000, risk_pct=1.0, stop_distance=0),
        dict(equity=10000, risk_pct=1.0, stop_distance=-0.001),
    ],
)
def test_refuses_invalid_inputs(kwargs):
    with pytest.raises(SizingError):
        size_position(
            instrument="EUR_USD", account_currency="USD", price=1.10,
            bar_time=_ts(2024, 1, 1), **kwargs,
        )


# ---------------------------------------------------------------------------
# EC-7 no-lookahead alignment
# ---------------------------------------------------------------------------

def test_conversion_rate_never_postdates_bar():
    usd_jpy = _series(
        [_ts(2024, 1, 1, 0), _ts(2024, 1, 1, 6), _ts(2024, 1, 1, 12)],
        [149.0, 150.0, 151.0],
    )
    conversion_series = {"USD_JPY": usd_jpy}

    # Querying exactly at the middle timestamp must use that bar's own rate (150.0),
    # never the next one (151.0) — inclusive backward lookup.
    pv = pip_value_per_unit(
        "GBP_JPY", "USD", price=190.0, bar_time=_ts(2024, 1, 1, 6),
        conversion_series=conversion_series,
    )
    assert pv == pytest.approx(0.01 / 150.0)

    # Querying just before the second observation must still resolve to the first (149.0).
    pv_before = pip_value_per_unit(
        "GBP_JPY", "USD", price=190.0, bar_time=_ts(2024, 1, 1, 5),
        conversion_series=conversion_series,
    )
    assert pv_before == pytest.approx(0.01 / 149.0)


def test_pip_size_jpy_vs_non_jpy():
    assert pip_size("USD_JPY") == pytest.approx(0.01)
    assert pip_size("GBP_JPY") == pytest.approx(0.01)
    assert pip_size("EUR_USD") == pytest.approx(0.0001)
    assert pip_size("EUR_GBP") == pytest.approx(0.0001)
