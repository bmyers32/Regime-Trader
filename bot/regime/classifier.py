"""
RegimeClassifier: classifies the current market regime from a HTF OHLCV window.

Regime priority (highest to lowest):
  1. EXPANSION  — elevated ATR signals stand-aside / reduce-size
  2. TRENDING_UP / TRENDING_DOWN — ADX + EMA alignment + slope persistence
  3. COMPRESSION — narrow BB arms the squeeze_breakout playbook
  4. RANGING — default when nothing else fires

TRENDING precedes COMPRESSION because a strongly-trending market (ADX>25, fully aligned
EMAs, consistent slope) is not a squeeze setup. COMPRESSION is reserved for range-bound or
weakly-directional markets where a breakout from the squeeze is likely. If TRENDING conditions
are met, COMPRESSION is irrelevant regardless of BB width.

Hysteresis:
  - confirm_bars consecutive candles required to switch (§2 law: 2 candles)
  - min_hold_bars must elapse in current regime before a switch is allowed
  - EXCEPTION: entering EXPANSION bypasses min_hold_bars (only confirm_bars required);
    exiting EXPANSION respects full hysteresis. Rationale: min-hold must never keep
    range_reversion eligible during a live breakout (TRADING-RULES §3.2 hard veto).

Gray zone (adx_range_max ≤ ADX < adx_trend_min): _raw_regime returns _INDETERMINATE.
  classify() treats this as "hold current regime" — increments bars_in_regime but does
  not advance the switch candidate.

All parameters come from instruments.yaml via the params dict (no hardcoded thresholds).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from bot.indicators.core import adx as _adx
from bot.indicators.core import atr as _atr
from bot.indicators.core import bb_width as _bb_width
from bot.indicators.core import bollinger_bands as _bollinger_bands
from bot.indicators.core import ema as _ema

# Private sentinel returned by _raw_regime when ADX is in the gray zone (no clean signal)
_INDETERMINATE = object()


class RegimeState(str, Enum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    EXPANSION = "EXPANSION"
    COMPRESSION = "COMPRESSION"


@dataclass
class RegimeResult:
    regime: RegimeState
    confidence: float
    """
    Observability only. No strategy or risk logic may gate on this value
    without §5 validation.
    """
    bars_in_regime: int
    htf_window: pd.DataFrame | None = None
    """
    TRADING-RULES §6 (2026-07-12, D1/H4 momentum hearing): the anchor-TF window
    AS OF this classify() call, i.e. htf_window.iloc[:htf_pos+1] from the engine's
    own caller — ending at the last CLOSED anchor candle, never a forming one
    (Prime Directive 3), unchanged for every LTF bar until the next anchor close.
    Lets a strategy compute its own signal directly from raw anchor-TF price
    history (not just the classified RegimeState enum) without changing
    generate_signal()'s contracted (window, regime) signature — the Strategy
    Protocol is a CLAUDE.md Core Interface, "do not drift".
    READ-ONLY: this is a reference into engine/classifier state, not a copy.
    Strategy code must never mutate it in place. Defaulted to None so every
    existing positional 3-arg RegimeResult(...) construction (trend_pullback/
    range_reversion/squeeze_breakout tests, test_validation_defendants.py) keeps
    working unchanged.
    """


class RegimeClassifier:
    """
    Stateful regime classifier for one instrument.

    One instance per instrument per run. Call reset() between backtest runs to
    ensure two sequential runs on the same instance produce identical results.

    params keys (all come from instruments.yaml merged with defaults):
      adx_period, adx_trend_min, adx_range_max, adx_exhaustion,
      slope_persist_bars, atr_expansion_ratio, atr_expansion_mean_mult,
      bb_period, bb_std, bb_compression_pct, bb_compression_window,
      regime_confirm_bars, regime_min_hold_bars
    """

    def __init__(self, params: dict) -> None:
        self._params = params
        self._current_regime: RegimeState | None = None
        self._bars_in_regime: int = 0
        self._last_confidence: float = 0.0
        self._candidate_regime: RegimeState | None = None
        self._candidate_bars: int = 0

    def reset(self) -> None:
        """Reset all state. Required before each backtest run."""
        self._current_regime = None
        self._bars_in_regime = 0
        self._last_confidence = 0.0
        self._candidate_regime = None
        self._candidate_bars = 0

    def classify(self, htf_window: pd.DataFrame) -> RegimeResult:
        """
        Classify the current regime from the supplied HTF window.

        htf_window: DataFrame with columns {open, high, low, close, volume, complete}.
        All rows must have complete==True (DataProvider guarantees this).
        Returns a RegimeResult describing the current confirmed regime.
        """
        raw_regime, raw_confidence = self._raw_regime(htf_window)

        # Bootstrap: first call sets current regime without hysteresis
        if self._current_regime is None:
            boot = (
                RegimeState.RANGING
                if raw_regime is _INDETERMINATE
                else raw_regime
            )
            self._current_regime = boot
            self._bars_in_regime = 1
            self._last_confidence = 0.0 if raw_regime is _INDETERMINATE else raw_confidence
            return RegimeResult(self._current_regime, self._last_confidence, self._bars_in_regime, htf_window)

        # Gray zone: hold regime, still count the bar
        if raw_regime is _INDETERMINATE:
            self._bars_in_regime += 1
            return RegimeResult(self._current_regime, self._last_confidence, self._bars_in_regime, htf_window)

        # Same regime: reinforce, clear any pending candidate
        if raw_regime == self._current_regime:
            self._bars_in_regime += 1
            self._last_confidence = raw_confidence
            self._candidate_regime = None
            self._candidate_bars = 0
            return RegimeResult(self._current_regime, self._last_confidence, self._bars_in_regime, htf_window)

        # Different regime: advance switch candidate
        if raw_regime == self._candidate_regime:
            self._candidate_bars += 1
        else:
            self._candidate_regime = raw_regime
            self._candidate_bars = 1

        confirmed = self._candidate_bars >= self._params["regime_confirm_bars"]

        # Asymmetric: entering EXPANSION bypasses min_hold_bars
        entering_expansion = self._candidate_regime == RegimeState.EXPANSION
        hold_ok = entering_expansion or (
            self._bars_in_regime >= self._params["regime_min_hold_bars"]
        )

        if confirmed and hold_ok:
            self._current_regime = self._candidate_regime
            self._bars_in_regime = 1
            self._last_confidence = raw_confidence
            self._candidate_regime = None
            self._candidate_bars = 0
        else:
            self._bars_in_regime += 1

        return RegimeResult(self._current_regime, self._last_confidence, self._bars_in_regime, htf_window)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _raw_regime(
        self, htf_window: pd.DataFrame
    ) -> tuple[object, float]:
        """
        Compute the raw (unfiltered) regime from the last bar of htf_window.
        Returns (_INDETERMINATE, 0.0) for the ADX gray zone or insufficient data.
        """
        p = self._params
        high = htf_window["high"]
        low = htf_window["low"]
        close = htf_window["close"]

        adx_s = _adx(high, low, close, p["adx_period"])
        current_adx = adx_s.iloc[-1]

        # --- EXPANSION (highest priority) ---
        atr10 = _atr(high, low, close, 10)
        atr50 = _atr(high, low, close, 50)
        atr14 = _atr(high, low, close, 14)

        atr10_last = atr10.iloc[-1]
        atr50_last = atr50.iloc[-1]
        atr14_last = atr14.iloc[-1]

        # Only valid when ATR(50) has converged (need 50+ bars)
        expansion_by_ratio = (
            not pd.isna(atr50_last)
            and atr50_last > 0
            and (atr10_last / atr50_last) > p["atr_expansion_ratio"]
        )
        atr_mean_60 = atr14.rolling(60).mean().iloc[-1]
        expansion_by_mean = (
            not pd.isna(atr_mean_60)
            and atr_mean_60 > 0
            and atr14_last > p["atr_expansion_mean_mult"] * atr_mean_60
        )

        if expansion_by_ratio or expansion_by_mean:
            if expansion_by_ratio:
                ratio = atr10_last / atr50_last
                conf = min(1.0, max(0.01, (ratio - p["atr_expansion_ratio"]) / p["atr_expansion_ratio"]))
            else:
                ratio = atr14_last / atr_mean_60
                conf = min(1.0, max(0.01, (ratio - p["atr_expansion_mean_mult"]) / p["atr_expansion_mean_mult"]))
            return RegimeState.EXPANSION, conf

        # --- TRENDING (all three gates: ADX, alignment, slope) ---
        # Checked before COMPRESSION: a strongly-trending market is not a squeeze setup.
        ema20 = _ema(close, 20)
        ema50 = _ema(close, 50)
        ema200 = _ema(close, 200)

        e20 = ema20.iloc[-1]
        e50 = ema50.iloc[-1]
        e200 = ema200.iloc[-1]

        aligned_up = e20 > e50 > e200
        aligned_down = e20 < e50 < e200

        adx_strong = current_adx > p["adx_trend_min"]

        if adx_strong and (aligned_up or aligned_down):
            n = p["slope_persist_bars"]
            diffs = ema20.diff().iloc[-n:]
            slope_up = not diffs.isna().any() and bool((diffs > 0).all())
            slope_down = not diffs.isna().any() and bool((diffs < 0).all())

            if aligned_up and slope_up:
                conf = min(1.0, current_adx / p["adx_trend_min"])
                return RegimeState.TRENDING_UP, conf
            if aligned_down and slope_down:
                conf = min(1.0, current_adx / p["adx_trend_min"])
                return RegimeState.TRENDING_DOWN, conf
            # Alignment + ADX met but slope failed → fall through to compression / ranging

        # --- COMPRESSION ---
        upper, middle, lower = _bollinger_bands(close, p["bb_period"], p["bb_std"])
        width = _bb_width(upper, middle, lower)
        width_pct = width.rolling(p["bb_compression_window"]).quantile(
            p["bb_compression_pct"] / 100.0
        )
        width_last = width.iloc[-1]
        pct_thresh = width_pct.iloc[-1]

        if not pd.isna(pct_thresh) and not pd.isna(width_last) and width_last < pct_thresh:
            # Confidence: how far below the threshold (lower width = higher confidence)
            conf = min(1.0, max(0.01, 1.0 - (width_last / pct_thresh)))
            return RegimeState.COMPRESSION, conf

        # --- RANGING ---
        if current_adx < p["adx_range_max"]:
            conf = max(0.01, 1.0 - (current_adx / p["adx_range_max"]))
            return RegimeState.RANGING, conf

        # --- Gray zone: adx_range_max ≤ ADX < adx_trend_min (or slope failed above adx_trend_min) ---
        return _INDETERMINATE, 0.0
