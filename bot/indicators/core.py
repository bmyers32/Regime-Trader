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
