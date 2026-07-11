"""
Pure vectorized indicator functions.

No state; no side effects. All inputs are pd.Series aligned by integer index.
Callers must pass only complete==True candles (enforced by DataProvider upstream).

Wilder smoothing: alpha = 1/period, adjust=False — standard for ATR and ADX.
EMA uses standard exponential (alpha = 2/(period+1)) via span= parameter.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average — alpha = 2/(period+1)."""
    return series.ewm(span=period, adjust=False).mean()


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """
    True Range = max(H-L, |H-prev_C|, |L-prev_C|).
    Row 0 has no previous close; pandas max(axis=1, skipna=True) returns H[0]-L[0].
    """
    prev_close = close.shift(1)
    return pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    """
    Average True Range via Wilder smoothing (alpha = 1/period, adjust=False).
    Initialises at TR[0] (H-L only, no previous close).
    """
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """
    ADX (Average Directional Index) via Wilder smoothing.
    Returns the ADX line only; +DI and -DI are intermediate values discarded here.

    When both +DI and -DI are zero (no directional movement), DX is set to 0
    rather than NaN so the ADX EWM initialises cleanly.

    Accuracy improves after ~3× period bars due to Wilder EWM warm-up.
    """
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=high.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=high.index,
    )

    atr_s = atr(high, low, close, period)

    smoothed_plus = plus_dm.ewm(alpha=1.0 / period, adjust=False).mean()
    smoothed_minus = minus_dm.ewm(alpha=1.0 / period, adjust=False).mean()

    # Guard: replace zero ATR with NaN so division yields NaN (not inf)
    atr_safe = atr_s.where(atr_s != 0.0, np.nan)
    plus_di = 100.0 * smoothed_plus / atr_safe
    minus_di = 100.0 * smoothed_minus / atr_safe

    denom = plus_di + minus_di
    dx = (100.0 * (plus_di - minus_di).abs() / denom).where(denom != 0.0, 0.0)

    return dx.ewm(alpha=1.0 / period, adjust=False).mean()


def bollinger_bands(
    close: pd.Series, period: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Bollinger Bands: (upper, middle, lower).
    Uses population std (ddof=0) to match most charting platform implementations.
    Returns NaN for the first period-1 rows.
    """
    middle = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def bb_width(
    upper: pd.Series, middle: pd.Series, lower: pd.Series
) -> pd.Series:
    """
    Normalised Bollinger Band width: (upper - lower) / middle.
    Comparable across price levels. Returns NaN where middle == 0.
    """
    return (upper - lower) / middle.where(middle != 0.0, np.nan)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index via Wilder smoothing (alpha = 1/period, adjust=False) —
    same convention as atr()/adx() for consistency (TRADING-RULES: visually-similar
    formulas diverge at the decimal where thresholds live; one smoothing convention
    throughout avoids that trap).

    avg_loss == 0 saturates RSI at 100 (all gains, no losses in the smoothing window)
    unless avg_gain is also 0 (a flat series), which is neutral at 50 rather than
    an undefined 0/0.
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()

    avg_loss_safe = avg_loss.where(avg_loss != 0.0, np.nan)
    rs = avg_gain / avg_loss_safe
    result = 100.0 - 100.0 / (1.0 + rs)
    return result.where(avg_loss != 0.0, np.where(avg_gain == 0.0, 50.0, 100.0))


def body_pct(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series
) -> pd.Series:
    """Candle body as a fraction of its full range: |close-open| / (high-low). NaN where high==low."""
    candle_range = high - low
    return (close - open_).abs() / candle_range.where(candle_range != 0.0, np.nan)


def bullish_engulfing(open_: pd.Series, close: pd.Series) -> pd.Series:
    """Prior candle bearish, current candle bullish, current body fully contains prior body."""
    prev_open = open_.shift(1)
    prev_close = close.shift(1)
    prev_bearish = prev_close < prev_open
    current_bullish = close > open_
    engulfs = (open_ <= prev_close) & (close >= prev_open)
    return (prev_bearish & current_bullish & engulfs).fillna(False)


def bearish_engulfing(open_: pd.Series, close: pd.Series) -> pd.Series:
    """Prior candle bullish, current candle bearish, current body fully contains prior body."""
    prev_open = open_.shift(1)
    prev_close = close.shift(1)
    prev_bullish = prev_close > prev_open
    current_bearish = close < open_
    engulfs = (open_ >= prev_close) & (close <= prev_open)
    return (prev_bullish & current_bearish & engulfs).fillna(False)


def heikin_ashi(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Heikin-Ashi OHLC. ha_close is a plain vectorized average; ha_open is a recursive
    running average (ha_open[i] = (ha_open[i-1] + ha_close[i-1]) / 2) with no closed
    vectorized form — EXCEPT it is exactly an EWM(alpha=0.5, adjust=False) driven by
    ha_close shifted by one bar, seeded at index 0 with (open[0]+close[0])/2. Using
    ewm() (pandas' C-level recursion) keeps this vectorized without a per-row loop.
    """
    ha_close = (open_ + high + low + close) / 4.0

    driver = ha_close.shift(1)
    driver.iloc[0] = (open_.iloc[0] + close.iloc[0]) / 2.0
    ha_open = driver.ewm(alpha=0.5, adjust=False).mean()

    ha_high = pd.concat([high, ha_open, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([low, ha_open, ha_close], axis=1).min(axis=1)
    return ha_open, ha_high, ha_low, ha_close


def heikin_ashi_bullish_flip(ha_open: pd.Series, ha_close: pd.Series) -> pd.Series:
    """Current HA candle bullish, prior HA candle was bearish-or-flat."""
    current_bullish = ha_close > ha_open
    prev_not_bullish = ha_close.shift(1) <= ha_open.shift(1)
    return (current_bullish & prev_not_bullish).fillna(False)


def heikin_ashi_bearish_flip(ha_open: pd.Series, ha_close: pd.Series) -> pd.Series:
    """Current HA candle bearish, prior HA candle was bullish-or-flat."""
    current_bearish = ha_close < ha_open
    prev_not_bearish = ha_close.shift(1) >= ha_open.shift(1)
    return (current_bearish & prev_not_bearish).fillna(False)


def bb_reentry_long(close: pd.Series, lower_band: pd.Series) -> pd.Series:
    """
    TRADING-RULES §3.2: "close back INSIDE lower BB (re-entry close, not pierce)".
    Close-based, not wick-based: prior bar's CLOSE was at/below the lower band
    (outside), current bar's CLOSE is back above it (inside) — deliberately NOT a
    same-bar wick-touches-then-closes-back-in pattern, which is what "not pierce"
    rules out. NaN (band warmup) on either side resolves to False via fillna.
    """
    prev_outside = close.shift(1) <= lower_band.shift(1)
    current_inside = close > lower_band
    return (prev_outside & current_inside).fillna(False)


def bb_reentry_short(close: pd.Series, upper_band: pd.Series) -> pd.Series:
    """Mirror of bb_reentry_long at the upper band (TRADING-RULES §3.2 short side)."""
    prev_outside = close.shift(1) >= upper_band.shift(1)
    current_inside = close < upper_band
    return (prev_outside & current_inside).fillna(False)


def bb_breakout_long(close: pd.Series, upper_band: pd.Series) -> pd.Series:
    """
    TRADING-RULES §3.3: "close beyond band" (upside). Close-based, not wick-based --
    same convention as bb_reentry_long/short, opposite direction: a close OUTSIDE the
    band, not a re-entry back inside. NaN (band warmup) resolves to False via fillna.
    """
    return (close > upper_band).fillna(False)


def bb_breakout_short(close: pd.Series, lower_band: pd.Series) -> pd.Series:
    """Mirror of bb_breakout_long at the lower band (TRADING-RULES §3.3 short side)."""
    return (close < lower_band).fillna(False)
