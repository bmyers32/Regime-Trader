"""
Phase 5 exit-criteria tests — trend_pullback (PROMPTS.md §4 row 5, unit-test slice).

Covers: SL tested both directions (long below entry, short above — the exact failure
mode TRADING-RULES §1.3 exists to prevent), near-miss vetoes visible per veto reason
(outside_pullback_zone, no_reversal_trigger, rsi_wrong_side, beyond_ema200), and the
regime-routing hard gate (non-trending regimes / insufficient warmup -> None, i.e.
"not consulted", not a vetoed near-miss).

Full TRADING-RULES §5 gates (backtest-with-real-costs, walk-forward, parameter
stability, per-regime attribution, Monte Carlo) are Session B scope — see HANDOFF.md.
These are strategy-level unit tests only.

Synthetic fixtures: a long, mostly-noise-free warmup trend (for clean EMA20/50/200
alignment) followed by a short pullback, then one hand-tuned final bar engineered to
land at a specific point relative to the EMA20-EMA50 zone / body-pct / RSI. Indicator
values used to calibrate each fixture are computed via the SAME bot.indicators.core
functions this strategy calls — those functions have their own golden-value tests
(tests/test_indicators.py); this file tests the STRATEGY's gating/scoring/veto
assembly logic given known indicator inputs, not indicator correctness itself.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bot.regime.classifier import RegimeResult, RegimeState
from bot.strategies.trend_pullback import TrendPullback

_PARAMS = {
    "rsi_period": 14,
    "pullback_zone_atr_min": 0.25,
    "pullback_zone_atr_max": 0.5,
    "sl_atr_mult": 1.75,
    "swing_lookback_bars": 10,
    "entry_threshold": 0.6,
    "score_weights": {
        "pullback_zone": 0.3,
        "reversal_trigger": 0.25,
        "rsi_side": 0.25,
        "ema200_side": 0.2,
    },
}


def _bars(times, opens, highs, lows, closes) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": 100,
            "complete": True,
        }
    )


def _build_up(
    n_warmup: int = 210,
    warmup_drift: float = 0.0004,
    pullback_bars: int = 10,
    pullback_drift: float = -0.0006,
    final_ohlc: tuple[float, float, float, float] | None = None,
    start: float = 1.10000,
) -> pd.DataFrame:
    """Clean uptrend warmup (EMA20/50/200 aligned up) + short pullback + optional final bar."""
    closes = [start]
    for _ in range(n_warmup - 1):
        closes.append(closes[-1] + warmup_drift)
    for _ in range(pullback_bars):
        closes.append(closes[-1] + pullback_drift)
    closes = np.array(closes)
    opens = np.concatenate([[start], closes[:-1]])
    highs = np.maximum(opens, closes) + 0.0003
    lows = np.minimum(opens, closes) - 0.0003
    times = [pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(hours=i) for i in range(len(closes))]
    df = _bars(times, opens, highs, lows, closes)
    if final_ohlc is not None:
        o, h, l, c = final_ohlc
        extra_time = times[-1] + pd.Timedelta(hours=1)
        df = pd.concat([df, _bars([extra_time], [o], [h], [l], [c])], ignore_index=True)
    return df


def _build_down(
    n_warmup: int = 210,
    warmup_drift: float = -0.0004,
    bounce_bars: int = 10,
    bounce_drift: float = 0.0006,
    final_ohlc: tuple[float, float, float, float] | None = None,
    start: float = 1.20000,
) -> pd.DataFrame:
    """Mirror of _build_up: clean downtrend warmup + short bounce + optional final bar."""
    closes = [start]
    for _ in range(n_warmup - 1):
        closes.append(closes[-1] + warmup_drift)
    for _ in range(bounce_bars):
        closes.append(closes[-1] + bounce_drift)
    closes = np.array(closes)
    opens = np.concatenate([[start], closes[:-1]])
    highs = np.maximum(opens, closes) + 0.0003
    lows = np.minimum(opens, closes) - 0.0003
    times = [pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(hours=i) for i in range(len(closes))]
    df = _bars(times, opens, highs, lows, closes)
    if final_ohlc is not None:
        o, h, l, c = final_ohlc
        extra_time = times[-1] + pd.Timedelta(hours=1)
        df = pd.concat([df, _bars([extra_time], [o], [h], [l], [c])], ignore_index=True)
    return df


_UP = RegimeResult(RegimeState.TRENDING_UP, confidence=0.8, bars_in_regime=20)
_DOWN = RegimeResult(RegimeState.TRENDING_DOWN, confidence=0.8, bars_in_regime=20)
_STRATEGY = TrendPullback(_PARAMS, "EUR_USD")


# ---------------------------------------------------------------------------
# Regime routing hard gate — "not consulted" vs. "consulted and vetoed"
# ---------------------------------------------------------------------------

class TestRegimeRouting:
    @pytest.mark.parametrize(
        "regime",
        [
            RegimeResult(RegimeState.RANGING, confidence=0.5, bars_in_regime=5),
            RegimeResult(RegimeState.EXPANSION, confidence=0.5, bars_in_regime=5),
            RegimeResult(RegimeState.COMPRESSION, confidence=0.5, bars_in_regime=5),
        ],
    )
    def test_non_trending_regime_returns_none(self, regime) -> None:
        """Non-TRENDING regimes never route to this playbook — None, not a vetoed Signal."""
        window = _build_up()
        assert _STRATEGY.generate_signal(window, regime) is None

    def test_insufficient_warmup_returns_none(self) -> None:
        """TRENDING regime but window shorter than EMA200's warmup floor -> None."""
        window = _build_up(n_warmup=50, pullback_bars=0)
        assert _STRATEGY.generate_signal(window, _UP) is None


# ---------------------------------------------------------------------------
# SL tested both directions (TRADING-RULES §1.3 — the exact historical failure mode)
# ---------------------------------------------------------------------------

class TestStopLossBothDirections:
    def test_long_setup_fires_sl_below_entry_tp_none(self) -> None:
        window = _build_up(final_ohlc=(1.1776, 1.1798, 1.1774, 1.1795))
        signal = _STRATEGY.generate_signal(window, _UP)

        assert signal is not None
        assert signal.vetoes == []
        assert signal.direction == "long"
        assert signal.tp is None
        assert signal.sl < signal.entry_ref, "long SL must sit below entry"
        assert signal.confidence_score == pytest.approx(1.0, abs=1e-9)

    def test_short_setup_fires_sl_above_entry_tp_none(self) -> None:
        window = _build_down(final_ohlc=(1.1208, 1.1208, 1.1202, 1.1205))
        signal = _STRATEGY.generate_signal(window, _DOWN)

        assert signal is not None
        assert signal.vetoes == []
        assert signal.direction == "short"
        assert signal.tp is None
        assert signal.sl > signal.entry_ref, "short SL must sit above entry"
        assert signal.confidence_score == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Near-miss visibility — every veto reason surfaces distinctly
# ---------------------------------------------------------------------------

class TestNearMissVetoes:
    def test_rsi_wrong_side_veto(self) -> None:
        """Reversal candle triggers but is too weak to flip RSI back above 50 yet."""
        window = _build_up(final_ohlc=(1.1776, 1.1784, 1.1774, 1.1782))
        signal = _STRATEGY.generate_signal(window, _UP)

        assert signal is not None
        assert "rsi_wrong_side" in signal.vetoes
        assert signal.confidence_score < _PARAMS["entry_threshold"] + 0.2  # still a near-miss, not a strong fire

    def test_no_reversal_trigger_veto(self) -> None:
        """Small-bodied bar at the pullback zone: no engulfing, no >=60% body, no HA flip."""
        window = _build_up(final_ohlc=(1.1780, 1.1785, 1.1778, 1.1781))
        signal = _STRATEGY.generate_signal(window, _UP)

        assert signal is not None
        assert "no_reversal_trigger" in signal.vetoes

    def test_outside_pullback_zone_veto(self) -> None:
        """Reversal overshoots far past the EMA20-EMA50 zone (>0.5x ATR beyond it)."""
        window = _build_up(final_ohlc=(1.1776, 1.1902, 1.1774, 1.1900))
        signal = _STRATEGY.generate_signal(window, _UP)

        assert signal is not None
        assert "outside_pullback_zone" in signal.vetoes

    def test_beyond_ema200_is_scored_not_vetoed(self) -> None:
        """
        §3.1 lists EMA200 pullback depth under the SAME "Score:" bullet as the
        pullback-zone/reversal-trigger/RSI components — not under "Hard gates:"
        (regime/spread/blackout only). A pullback deep enough to close beyond EMA200
        must reduce confidence_score via score_weights['ema200_side'], never force an
        unconditional no-fire the way a veto does — that would recreate the exact
        AND-stack anti-pattern TRADING-RULES §1.1 exists to prevent.
        """
        window = _build_up(pullback_bars=140, pullback_drift=-0.0006)
        signal = _STRATEGY.generate_signal(window, _UP)

        assert signal is not None
        assert not any("ema200" in v for v in signal.vetoes)
        assert "beyond_ema200_zone" in signal.reasons

    def test_vetoed_signal_never_fires_even_if_score_clears_threshold(self) -> None:
        """
        A near-miss can still score >= entry_threshold on its passing components —
        vetoes must be checked independently by the caller (BacktestEngine), never
        inferred from score alone. This is the property the engine's fire condition
        (`not signal.vetoes and score >= threshold`) depends on.
        """
        window = _build_up(final_ohlc=(1.1776, 1.1902, 1.1774, 1.1900))
        signal = _STRATEGY.generate_signal(window, _UP)

        assert signal.vetoes  # non-empty
        assert signal.confidence_score >= _PARAMS["entry_threshold"]
