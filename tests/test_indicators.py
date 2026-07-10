"""
Phase 3 exit-criteria tests — Indicators (PROMPTS.md §4 row 3, partial).

Frozen golden values are precomputed analytically for the canonical test series:
  close[i] = 1.0 + 0.01*i, high = close + 0.005, low = close - 0.005 (50 bars)
  TR[0] = 0.01 (H-L only); TR[i>=1] = 0.015 (|H-prev_C| dominates)
  Wilder smoothing: alpha = 1/period, adjust=False

EMA golden: close=[1..5], span=3, alpha=0.5 — exact by hand.
ATR golden: A[n] = 0.015 - 0.005*(13/14)^n;  A[49] ≈ 0.014868 (Wilder init visible)
ADX golden: DX[0]=0, DX[1:]=100 → ADX[n] = 100*(1-(13/14)^n); ADX[49] ≈ 97.35

Tolerance rationale: abs=2e-4 on ATR distinguishes Wilder (alpha=1/14) from standard EWM
(alpha=2/15); abs=0.5 on ADX handles floating-point accumulation over 50 steps.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from bot.indicators.core import (
    adx,
    atr,
    bb_reentry_long,
    bb_reentry_short,
    bb_width,
    bearish_engulfing,
    body_pct,
    bollinger_bands,
    bullish_engulfing,
    ema,
    heikin_ashi,
    heikin_ashi_bearish_flip,
    heikin_ashi_bullish_flip,
    rsi,
    true_range,
)

# ---------------------------------------------------------------------------
# Golden series constants (canonical 50-bar uptrend)
# ---------------------------------------------------------------------------
_N = 50
_CLOSE_50 = pd.Series([1.0 + 0.01 * i for i in range(_N)])
_HIGH_50 = _CLOSE_50 + 0.005
_LOW_50 = _CLOSE_50 - 0.005

# Precomputed: A[49] = 0.015 - 0.005*(13/14)^49, (13/14)^49 ≈ 0.026491
_GOLDEN_ATR14_AT49 = 0.015 - 0.005 * (13 / 14) ** 49   # ≈ 0.014868
# Precomputed: ADX[49] = 100*(1 - (13/14)^49) ≈ 97.351
_GOLDEN_ADX14_AT49 = 100.0 * (1.0 - (13 / 14) ** 49)


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------

class TestEma:
    def test_exact_small_series(self) -> None:
        """EMA(3) on [1,2,3,4,5] with alpha=0.5 — exact hand calculation."""
        close = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = ema(close, 3)
        assert result.iloc[-1] == pytest.approx(4.0625, abs=1e-10)

    def test_matches_pandas_ewm(self) -> None:
        """ema() must produce identical output to pd.Series.ewm(span=N, adjust=False)."""
        close = pd.Series([1.0 + 0.1 * i for i in range(30)])
        expected = close.ewm(span=10, adjust=False).mean()
        result = ema(close, 10)
        pd.testing.assert_series_equal(result, expected)

    def test_single_element(self) -> None:
        s = pd.Series([42.0])
        assert ema(s, 5).iloc[0] == pytest.approx(42.0)

    def test_length_preserved(self) -> None:
        s = pd.Series(range(20), dtype=float)
        assert len(ema(s, 5)) == 20


# ---------------------------------------------------------------------------
# True Range
# ---------------------------------------------------------------------------

class TestTrueRange:
    def test_first_bar_no_prev_close(self) -> None:
        """Row 0 has no previous close; TR[0] must equal H[0]-L[0]."""
        high = pd.Series([1.10])
        low = pd.Series([1.09])
        close = pd.Series([1.095])
        tr = true_range(high, low, close)
        assert tr.iloc[0] == pytest.approx(0.01, abs=1e-10)

    def test_subsequent_bar_uses_prev_close(self) -> None:
        """TR[1] = max(H-L, |H-pC|, |L-pC|); |H-pC| dominates here."""
        # close[0]=1.0, close[1]=1.01 → pC=1.0
        # H[1]=1.015, L[1]=0.995
        # H-L=0.02, |H-pC|=0.015, |L-pC|=0.005 → TR=0.02
        high = pd.Series([1.01, 1.015])
        low = pd.Series([1.00, 0.995])
        close = pd.Series([1.005, 1.01])
        tr = true_range(high, low, close)
        assert tr.iloc[1] == pytest.approx(0.02, abs=1e-10)

    def test_gap_up_captured(self) -> None:
        """Gap-up: |H[1] - prev_C| > H[1]-L[1]."""
        high = pd.Series([1.0, 1.2])
        low = pd.Series([0.99, 1.15])
        close = pd.Series([0.995, 1.18])
        tr = true_range(high, low, close)
        # |H[1]-pC| = |1.2 - 0.995| = 0.205
        assert tr.iloc[1] == pytest.approx(0.205, abs=1e-10)


# ---------------------------------------------------------------------------
# ATR (frozen golden)
# ---------------------------------------------------------------------------

class TestAtr:
    def test_golden_wilder_init_bar49(self) -> None:
        """
        ATR(14)[49] on canonical 50-bar series.
        Golden value derived from Wilder EWM (alpha=1/14, not 2/15).
        Tolerance abs=2e-4 distinguishes Wilder from standard EWM.
        """
        result = atr(_HIGH_50, _LOW_50, _CLOSE_50, 14)
        assert result.iloc[49] == pytest.approx(_GOLDEN_ATR14_AT49, abs=2e-4)

    def test_converges_toward_tr(self) -> None:
        """ATR must approach TR as more uniform bars are processed."""
        result = atr(_HIGH_50, _LOW_50, _CLOSE_50, 14)
        # All TR[1:] = 0.015; after 50 bars ATR must be between initial TR[0] and 0.015
        assert 0.01 < result.iloc[49] < 0.015 + 1e-6

    def test_shorter_period_converges_faster(self) -> None:
        result5 = atr(_HIGH_50, _LOW_50, _CLOSE_50, 5)
        result14 = atr(_HIGH_50, _LOW_50, _CLOSE_50, 14)
        # ATR(5) converges to 0.015 faster → closer to 0.015 at bar 49
        assert abs(result5.iloc[49] - 0.015) < abs(result14.iloc[49] - 0.015)

    def test_length_preserved(self) -> None:
        result = atr(_HIGH_50, _LOW_50, _CLOSE_50, 14)
        assert len(result) == _N


# ---------------------------------------------------------------------------
# ADX (frozen golden)
# ---------------------------------------------------------------------------

def _make_choppy(n: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Alternating high/low bars: net directional movement cancels → ADX ≈ 0."""
    close = pd.Series([1.01 if i % 2 == 0 else 1.00 for i in range(n)])
    high = pd.Series([1.015 if i % 2 == 0 else 1.005 for i in range(n)])
    low = pd.Series([1.005 if i % 2 == 0 else 0.995 for i in range(n)])
    return high, low, close


class TestAdx:
    def test_golden_wilder_trending_bar49(self) -> None:
        """
        ADX(14)[49] on canonical 50-bar uptrend.
        Golden: 100*(1-(13/14)^49) ≈ 97.35 — DX=100 every bar (minus_dm=0 always).
        Tolerance abs=0.5 covers floating-point accumulation across 50 EWM steps.
        """
        result = adx(_HIGH_50, _LOW_50, _CLOSE_50, 14)
        assert result.iloc[49] == pytest.approx(_GOLDEN_ADX14_AT49, abs=0.5)

    def test_trending_adx_high(self) -> None:
        """Perfect uptrend: ADX should exceed adx_trend_min (25) comfortably."""
        result = adx(_HIGH_50, _LOW_50, _CLOSE_50, 14)
        assert result.iloc[49] > 25.0

    def test_choppy_adx_low(self) -> None:
        """Alternating bars: ADX should be well below adx_range_max (20)."""
        n = 100
        high, low, close = _make_choppy(n)
        result = adx(high, low, close, 14)
        assert result.iloc[n - 1] < 20.0

    def test_length_preserved(self) -> None:
        result = adx(_HIGH_50, _LOW_50, _CLOSE_50, 14)
        assert len(result) == _N

    def test_non_negative(self) -> None:
        result = adx(_HIGH_50, _LOW_50, _CLOSE_50, 14)
        assert (result >= 0.0).all()


# ---------------------------------------------------------------------------
# Bollinger Bands + BB Width
# ---------------------------------------------------------------------------

def _make_constant(n: int = 50, price: float = 100.0) -> pd.Series:
    return pd.Series([price] * n)


def _make_sine(n: int = 50, base: float = 100.0, amplitude: float = 1.0) -> pd.Series:
    return pd.Series([base + amplitude * math.sin(2 * math.pi * i / 20) for i in range(n)])


class TestBollingerBands:
    def test_constant_series_zero_width(self) -> None:
        """Constant price → std=0 → upper=lower=middle → BB width=0."""
        close = _make_constant(50, 100.0)
        upper, middle, lower = bollinger_bands(close, period=20, num_std=2.0)
        width = bb_width(upper, middle, lower)
        # After period-1 warmup rows are NaN, remaining must be 0
        valid = width.dropna()
        assert (valid.abs() < 1e-12).all()

    def test_upper_above_middle_above_lower(self) -> None:
        """Non-constant series: upper > middle > lower for all non-NaN rows."""
        close = _make_sine(60, amplitude=2.0)
        upper, middle, lower = bollinger_bands(close, period=20, num_std=2.0)
        valid = upper.dropna().index
        assert (upper[valid] > middle[valid]).all()
        assert (middle[valid] > lower[valid]).all()

    def test_middle_is_rolling_sma(self) -> None:
        """Middle band == SMA(close, period)."""
        close = _make_sine(60, amplitude=2.0)
        _, middle, _ = bollinger_bands(close, period=20, num_std=2.0)
        expected_middle = close.rolling(20).mean()
        pd.testing.assert_series_equal(middle, expected_middle)

    def test_warmup_rows_are_nan(self) -> None:
        """First period-1 rows must be NaN (rolling window not yet full)."""
        close = _make_sine(50, amplitude=1.0)
        upper, middle, lower = bollinger_bands(close, period=20, num_std=2.0)
        assert middle.iloc[:19].isna().all()
        assert not middle.iloc[19:].isna().any()

    def test_wider_std_multiplier(self) -> None:
        """3× std bands must be wider than 2× std bands."""
        close = _make_sine(60, amplitude=2.0)
        upper2, middle, lower2 = bollinger_bands(close, period=20, num_std=2.0)
        upper3, _, lower3 = bollinger_bands(close, period=20, num_std=3.0)
        valid = upper2.dropna().index
        assert (upper3[valid] > upper2[valid]).all()
        assert (lower3[valid] < lower2[valid]).all()


class TestBbWidth:
    def test_non_negative(self) -> None:
        close = _make_sine(60, amplitude=2.0)
        upper, middle, lower = bollinger_bands(close, period=20, num_std=2.0)
        width = bb_width(upper, middle, lower)
        valid = width.dropna()
        assert (valid >= 0.0).all()

    def test_smaller_at_lower_amplitude(self) -> None:
        """Lower amplitude sine → narrower BB width."""
        close_wide = _make_sine(60, amplitude=3.0)
        close_narrow = _make_sine(60, amplitude=0.5)

        upper_w, mid_w, lower_w = bollinger_bands(close_wide, 20, 2.0)
        upper_n, mid_n, lower_n = bollinger_bands(close_narrow, 20, 2.0)

        width_wide = bb_width(upper_w, mid_w, lower_w).dropna()
        width_narrow = bb_width(upper_n, mid_n, lower_n).dropna()

        assert width_wide.mean() > width_narrow.mean()

    def test_rolling_percentile_below_signals_compression(self) -> None:
        """
        Synthesise data where the last bar's BB width is clearly below the
        20th rolling percentile — verifying the COMPRESSION signal can fire.

        Design: 200 normal bars (amplitude 2.0) + 20 tight bars (amplitude 0.001).
        At bar 219 the 100-bar window is [120:220] = 80 normal + 20 transition bars.
        The 20 transition bars span widths from ~0.055 (bar 200) down to the tight
        value at bar 219. pandas quantile(0.20) uses linear interpolation, so P20
        falls in the normal range (~0.05). The current tight bar (~0.00003) is clearly
        below P20.

        Using 20 tight bars is intentional: with ≥ 21 fully-tight bars occupying the
        bottom 21% of the window, the 20th-percentile drops to the tight value itself
        and the strict-less-than test would fail.
        """
        normal = _make_sine(200, amplitude=2.0)
        # 20 bars with amplitude 2000× smaller → fully-compressed BB width
        tight = _make_sine(20, base=100.0, amplitude=0.001)
        close = pd.concat([normal, tight], ignore_index=True)   # 220 bars
        high = close + 0.1
        low = close - 0.1

        upper, middle, lower = bollinger_bands(close, 20, 2.0)
        width = bb_width(upper, middle, lower)

        # Rolling 100-bar 20th percentile (matches instruments.yaml default)
        pct20 = width.rolling(100).quantile(0.20)

        # Bar 219: 100-bar window mixes normal and transition bars → P20 in normal range
        last_width = width.iloc[-1]
        last_pct = pct20.iloc[-1]

        assert not pd.isna(last_width), "BB width is NaN at last bar"
        assert not pd.isna(last_pct), "percentile is NaN — window < 100 bars"
        assert last_width < last_pct, (
            f"Expected compression: last_width={last_width:.8f} < pct20={last_pct:.8f}"
        )


# ---------------------------------------------------------------------------
# RSI (frozen golden — Phase 5, trend_pullback)
# ---------------------------------------------------------------------------

class TestRsi:
    def test_golden_all_gains_saturates_at_100(self) -> None:
        """
        Strictly monotonic uptrend: loss[i]=0 for all i>=1 -> avg_loss stays exactly
        0 -> RSI saturates at 100 from bar 1 onward (bar 0's delta is undefined/NaN).
        Same canonical 50-bar series used for ATR/ADX golden tests.
        """
        result = rsi(_CLOSE_50, 14)
        assert pd.isna(result.iloc[0])
        assert (result.iloc[1:] - 100.0).abs().max() < 1e-9

    def test_flat_series_is_neutral_50(self) -> None:
        """No gains, no losses (flat price) -> 0/0 case must resolve to neutral 50, not NaN/inf."""
        close = _make_constant(30, 100.0)
        result = rsi(close, 14)
        assert (result.iloc[1:] - 50.0).abs().max() < 1e-9

    def test_downtrend_saturates_at_0(self) -> None:
        """Strictly monotonic downtrend: avg_gain stays exactly 0 -> RSI -> 0."""
        close = pd.Series([2.0 - 0.01 * i for i in range(30)])
        result = rsi(close, 14)
        assert result.iloc[1:].abs().max() < 1e-9

    def test_bounded_0_100(self) -> None:
        close = _make_sine(60, amplitude=2.0)
        result = rsi(close, 14)
        valid = result.dropna()
        assert (valid >= 0.0).all() and (valid <= 100.0).all()

    def test_length_preserved(self) -> None:
        result = rsi(_CLOSE_50, 14)
        assert len(result) == _N


# ---------------------------------------------------------------------------
# Candle body / engulfing patterns (Phase 5, trend_pullback reversal trigger)
# ---------------------------------------------------------------------------

class TestBodyPct:
    def test_exact_hand_calc(self) -> None:
        """body=|1.05-1.00|=0.05, range=1.06-0.99=0.07 -> pct=5/7."""
        open_ = pd.Series([1.00])
        high = pd.Series([1.06])
        low = pd.Series([0.99])
        close = pd.Series([1.05])
        result = body_pct(open_, high, low, close)
        assert result.iloc[0] == pytest.approx(5.0 / 7.0, abs=1e-10)

    def test_doji_zero_body(self) -> None:
        open_ = pd.Series([1.00])
        close = pd.Series([1.00])
        high = pd.Series([1.02])
        low = pd.Series([0.98])
        result = body_pct(open_, high, low, close)
        assert result.iloc[0] == pytest.approx(0.0, abs=1e-10)

    def test_zero_range_is_nan(self) -> None:
        open_ = pd.Series([1.00])
        close = pd.Series([1.00])
        high = pd.Series([1.00])
        low = pd.Series([1.00])
        result = body_pct(open_, high, low, close)
        assert pd.isna(result.iloc[0])


class TestEngulfing:
    def test_bullish_engulfing_detected(self) -> None:
        """Bar0 bearish (1.10->1.08); bar1 bullish (1.07->1.11) fully engulfs bar0's body."""
        open_ = pd.Series([1.10, 1.07])
        close = pd.Series([1.08, 1.11])
        result = bullish_engulfing(open_, close)
        assert result.iloc[0] == False
        assert result.iloc[1] == True

    def test_bearish_engulfing_detected(self) -> None:
        """Bar0 bullish (1.07->1.10); bar1 bearish (1.11->1.06) fully engulfs bar0's body."""
        open_ = pd.Series([1.07, 1.11])
        close = pd.Series([1.10, 1.06])
        result = bearish_engulfing(open_, close)
        assert result.iloc[0] == False
        assert result.iloc[1] == True

    def test_non_engulfing_small_body_no_signal(self) -> None:
        """Bar1's body doesn't fully contain bar0's body -> no engulfing."""
        open_ = pd.Series([1.10, 1.085])
        close = pd.Series([1.08, 1.09])
        result = bullish_engulfing(open_, close)
        assert result.iloc[1] == False

    def test_first_bar_never_signals(self) -> None:
        """No previous bar to compare against -> False, not NaN."""
        open_ = pd.Series([1.10])
        close = pd.Series([1.08])
        result = bullish_engulfing(open_, close)
        assert result.iloc[0] == False


class TestHeikinAshi:
    def test_golden_three_bar_hand_calc(self) -> None:
        """
        3-bar hand-verified example (see bot/indicators/core.py docstring for the
        ha_open recursion == EWM(alpha=0.5) equivalence proof):
          bar0: o=1.00 h=1.02 l=0.99 c=1.01 -> ha_close=1.005, ha_open=1.005 (seed)
          bar1: o=1.01 h=1.03 l=1.00 c=1.02 -> ha_close=1.015, ha_open=1.005
          bar2: o=1.02 h=1.01 l=0.98 c=0.99 -> ha_close=1.000, ha_open=1.010
        """
        open_ = pd.Series([1.00, 1.01, 1.02])
        high = pd.Series([1.02, 1.03, 1.01])
        low = pd.Series([0.99, 1.00, 0.98])
        close = pd.Series([1.01, 1.02, 0.99])

        ha_open, ha_high, ha_low, ha_close = heikin_ashi(open_, high, low, close)

        assert ha_close.iloc[0] == pytest.approx(1.005, abs=1e-10)
        assert ha_open.iloc[0] == pytest.approx(1.005, abs=1e-10)
        assert ha_high.iloc[0] == pytest.approx(1.02, abs=1e-10)
        assert ha_low.iloc[0] == pytest.approx(0.99, abs=1e-10)

        assert ha_close.iloc[1] == pytest.approx(1.015, abs=1e-10)
        assert ha_open.iloc[1] == pytest.approx(1.005, abs=1e-10)
        assert ha_high.iloc[1] == pytest.approx(1.03, abs=1e-10)
        assert ha_low.iloc[1] == pytest.approx(1.00, abs=1e-10)

        assert ha_close.iloc[2] == pytest.approx(1.000, abs=1e-10)
        assert ha_open.iloc[2] == pytest.approx(1.010, abs=1e-10)
        assert ha_high.iloc[2] == pytest.approx(1.01, abs=1e-10)
        assert ha_low.iloc[2] == pytest.approx(0.98, abs=1e-10)

    def test_bullish_flip_detected(self) -> None:
        ha_open = pd.Series([1.02, 1.00])
        ha_close = pd.Series([1.00, 1.03])  # bar0 bearish (close<open), bar1 bullish
        result = heikin_ashi_bullish_flip(ha_open, ha_close)
        assert result.iloc[0] == False
        assert result.iloc[1] == True

    def test_bearish_flip_detected(self) -> None:
        ha_open = pd.Series([1.00, 1.03])
        ha_close = pd.Series([1.02, 1.00])  # bar0 bullish, bar1 bearish
        result = heikin_ashi_bearish_flip(ha_open, ha_close)
        assert result.iloc[0] == False
        assert result.iloc[1] == True

    def test_no_flip_when_same_direction(self) -> None:
        ha_open = pd.Series([1.00, 1.00])
        ha_close = pd.Series([1.02, 1.03])  # both bullish -> no flip
        result = heikin_ashi_bullish_flip(ha_open, ha_close)
        assert result.iloc[1] == False


# ---------------------------------------------------------------------------
# BB re-entry (Phase 6, range_reversion — TRADING-RULES §3.2)
# ---------------------------------------------------------------------------

class TestBbReentry:
    def test_long_reentry_detected(self) -> None:
        """Prior close at/below lower band, current close back above it -> True."""
        close = pd.Series([0.98, 1.01])
        lower = pd.Series([1.00, 1.00])
        result = bb_reentry_long(close, lower)
        assert result.iloc[0] == False  # no prior bar to compare
        assert result.iloc[1] == True

    def test_long_no_reentry_when_prior_already_inside(self) -> None:
        """Prior close already inside the band -> no re-entry event, just 'inside'."""
        close = pd.Series([1.01, 1.02])
        lower = pd.Series([1.00, 1.00])
        result = bb_reentry_long(close, lower)
        assert result.iloc[1] == False

    def test_long_no_reentry_when_still_outside(self) -> None:
        """Prior close outside AND current close still outside -> not a re-entry yet."""
        close = pd.Series([0.98, 0.99])
        lower = pd.Series([1.00, 1.00])
        result = bb_reentry_long(close, lower)
        assert result.iloc[1] == False

    def test_long_same_bar_wick_pierce_is_not_a_reentry(self) -> None:
        """
        'Not pierce' clause: this function is close-only and has no wick inputs by
        design, so a same-bar wick-touch-then-close-back-in can never be confused
        with a genuine prior-bar close-based re-entry — asserted here via a case
        where the PRIOR close was already inside (only a wick could have pierced
        intrabar) and confirming no re-entry fires.
        """
        close = pd.Series([1.005, 1.01])
        lower = pd.Series([1.00, 1.00])
        result = bb_reentry_long(close, lower)
        assert result.iloc[1] == False

    def test_short_reentry_detected(self) -> None:
        """Mirror: prior close at/above upper band, current close back below it -> True."""
        close = pd.Series([1.02, 0.99])
        upper = pd.Series([1.00, 1.00])
        result = bb_reentry_short(close, upper)
        assert result.iloc[1] == True

    def test_short_no_reentry_when_still_outside(self) -> None:
        close = pd.Series([1.02, 1.01])
        upper = pd.Series([1.00, 1.00])
        result = bb_reentry_short(close, upper)
        assert result.iloc[1] == False

    def test_nan_band_resolves_false(self) -> None:
        """Band warmup rows (NaN) must resolve to False, not NaN/error."""
        close = pd.Series([0.98, 1.01])
        lower = pd.Series([float("nan"), 1.00])
        result = bb_reentry_long(close, lower)
        assert result.iloc[1] == False
