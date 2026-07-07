"""
trend_pullback: TRENDING-only playbook (TRADING-RULES §3.1).

Direction comes from the anchor-TF regime classifier (RegimeState.TRENDING_UP/DOWN)
— that IS the "HTF EMA alignment via merge_asof(direction='backward')" §3.1 describes;
the classifier already performs that backward-asof join at the HTF level (bot/regime/
classifier.py). This strategy only computes LTF-side (execution TF) indicators off the
window it's given.

Hard gate: regime must be TRENDING_UP/DOWN, else generate_signal() returns None
outright — the bar was never routed to this playbook, so there is nothing to journal
(CLAUDE.md's "near-misses journaled too" applies to evaluations this playbook was
actually consulted for). Once routed, this strategy ALWAYS returns a Signal (never
None) so every consulted bar is visible to the caller for near-miss journaling
(HANDOFF.md Session A Decision 3) — vetoes/reasons/confidence_score carry the "why".

Spread-gate and blackout-window hard gates from §3.1's prose are NOT implemented here:
spread is already enforced at the engine level (bot/backtest/costs.spread_gate_ok,
independent of any Strategy) and blackout is a TRADING-RULES §4 Risk Invariant ("risk
layer enforces; strategies cannot override") — Phase 8 scope. The Strategy Protocol
signature (window, regime) has no calendar hook by design; do not add one here.

Exit: SL only (tp=None) — ATR-multiple vs. the recent swing extreme, whichever is
farther (more protective). No fixed TP: the partial-at-1R + ATR/Chandelier trail
described in §3.1 is a generic BacktestEngine capability (exit_cfg), not something
this Signal encodes, so the same trend_pullback code path works unchanged once Phase 8
wires the live executor's equivalent exit-cfg-aware trailing logic.
"""

from __future__ import annotations

import pandas as pd

from bot.indicators.core import atr as _atr
from bot.indicators.core import bearish_engulfing as _bearish_engulfing
from bot.indicators.core import body_pct as _body_pct
from bot.indicators.core import bullish_engulfing as _bullish_engulfing
from bot.indicators.core import ema as _ema
from bot.indicators.core import heikin_ashi as _heikin_ashi
from bot.indicators.core import heikin_ashi_bearish_flip as _ha_bearish_flip
from bot.indicators.core import heikin_ashi_bullish_flip as _ha_bullish_flip
from bot.indicators.core import rsi as _rsi
from bot.regime.classifier import RegimeResult, RegimeState
from bot.strategies.base import Signal

# EMA200 needs several multiples of its period to be a meaningful anchor (same
# "accuracy improves after ~3x period" caveat as ATR/ADX's Wilder warm-up).
_EMA200_WARMUP_BARS = 201


class TrendPullback:
    """
    params: instruments.yaml's trend_pullback_params (defaults merged with any
    per-instrument trend_pullback_calibration override — see instruments.yaml).
    One instance per instrument (stateless otherwise; all indicators are recomputed
    from the window each call, matching the Strategy Protocol's pure-function contract).
    """

    def __init__(self, params: dict, instrument: str) -> None:
        self._params = params
        self._instrument = instrument

    def generate_signal(self, window: pd.DataFrame, regime: RegimeResult) -> Signal | None:
        if regime.regime not in (RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN):
            return None  # not routed to this playbook this bar -> nothing to journal

        p = self._params
        min_bars = max(_EMA200_WARMUP_BARS, p["swing_lookback_bars"], p["rsi_period"] + 1)
        if len(window) < min_bars:
            return None  # insufficient warmup -> not a real evaluation yet

        direction = "long" if regime.regime == RegimeState.TRENDING_UP else "short"

        open_ = window["open"]
        high = window["high"]
        low = window["low"]
        close = window["close"]

        ema20 = _ema(close, 20).iloc[-1]
        ema50 = _ema(close, 50).iloc[-1]
        ema200 = _ema(close, 200).iloc[-1]
        atr_now = _atr(high, low, close, 14).iloc[-1]
        rsi_now = _rsi(close, p["rsi_period"]).iloc[-1]
        last_close = close.iloc[-1]

        reasons: list[str] = []
        vetoes: list[str] = []

        pullback_score, zone_veto, zone_reason = self._pullback_zone_score(
            last_close, ema20, ema50, atr_now, p
        )
        if zone_veto:
            vetoes.append(zone_veto)
        if zone_reason:
            reasons.append(zone_reason)

        trigger_score, trigger_veto, trigger_reason = self._reversal_trigger_score(
            open_, high, low, close, direction
        )
        if trigger_veto:
            vetoes.append(trigger_veto)
        if trigger_reason:
            reasons.append(trigger_reason)

        rsi_score, rsi_veto, rsi_reason = self._rsi_side_score(rsi_now, direction)
        if rsi_veto:
            vetoes.append(rsi_veto)
        if rsi_reason:
            reasons.append(rsi_reason)

        ema200_score, ema200_reason = self._ema200_side_score(last_close, ema200, direction)
        reasons.append(ema200_reason)

        weights = p["score_weights"]
        confidence_score = (
            weights["pullback_zone"] * pullback_score
            + weights["reversal_trigger"] * trigger_score
            + weights["rsi_side"] * rsi_score
            + weights["ema200_side"] * ema200_score
        )

        sl = self._stop_loss(window, last_close, atr_now, direction, p)

        return Signal(
            strategy="trend_pullback",
            instrument=self._instrument,
            direction=direction,
            entry_ref=last_close,
            sl=sl,
            tp=None,
            confidence_score=confidence_score,
            reasons=reasons,
            vetoes=vetoes,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _pullback_zone_score(
        last_close: float, ema20: float, ema50: float, atr_now: float, p: dict
    ) -> tuple[float, str | None, str | None]:
        """§3.1 score component: proximity to the EMA20-EMA50 pullback zone."""
        zone_lo, zone_hi = min(ema20, ema50), max(ema20, ema50)
        if zone_lo <= last_close <= zone_hi:
            dist_atr = 0.0
        elif pd.isna(atr_now) or atr_now <= 0.0:
            return 0.0, "outside_pullback_zone", None
        elif last_close < zone_lo:
            dist_atr = (zone_lo - last_close) / atr_now
        else:
            dist_atr = (last_close - zone_hi) / atr_now

        zone_min, zone_max = p["pullback_zone_atr_min"], p["pullback_zone_atr_max"]
        if dist_atr > zone_max:
            return 0.0, "outside_pullback_zone", None
        if dist_atr <= zone_min:
            return 1.0, None, f"pullback_zone_dist_atr={dist_atr:.3f}"
        score = 1.0 - (dist_atr - zone_min) / (zone_max - zone_min)
        return max(0.0, score), None, f"pullback_zone_dist_atr={dist_atr:.3f}"

    @staticmethod
    def _reversal_trigger_score(
        open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, direction: str
    ) -> tuple[float, str | None, str | None]:
        """§3.1 score component: ONE reversal trigger required (engulfing OR body>=60% OR HA flip)."""
        if direction == "long":
            engulf = bool(_bullish_engulfing(open_, close).iloc[-1])
        else:
            engulf = bool(_bearish_engulfing(open_, close).iloc[-1])

        body = _body_pct(open_, high, low, close).iloc[-1]
        candle_direction_ok = (
            close.iloc[-1] > open_.iloc[-1] if direction == "long" else close.iloc[-1] < open_.iloc[-1]
        )
        body_trigger = bool(not pd.isna(body) and body >= 0.60 and candle_direction_ok)

        ha_open, _, _, ha_close = _heikin_ashi(open_, high, low, close)
        if direction == "long":
            ha_flip = bool(_ha_bullish_flip(ha_open, ha_close).iloc[-1])
        else:
            ha_flip = bool(_ha_bearish_flip(ha_open, ha_close).iloc[-1])

        fired = [name for name, hit in (("engulfing", engulf), ("body>=60%", body_trigger), ("ha_flip", ha_flip)) if hit]
        if not fired:
            return 0.0, "no_reversal_trigger", None
        return 1.0, None, "reversal_trigger:" + "+".join(fired)

    @staticmethod
    def _ema200_side_score(last_close: float, ema200: float, direction: str) -> tuple[float, str]:
        """
        §3.1 score component: pullback depth vs. EMA200 — listed under the same
        "Score:" bullet as the other three components, not "Hard gates:" (regime/
        spread/blackout only), so it is scored here rather than vetoed. Vetoing it
        would recreate the AND-stack anti-pattern TRADING-RULES §1.1 exists to
        prevent: this playbook's only hard gate is regime-routing (generate_signal's
        early `return None`); every other component must be outweighable, never a
        unilateral no-fire.
        """
        on_side = last_close >= ema200 if direction == "long" else last_close <= ema200
        return (1.0, "on_side_of_ema200") if on_side else (0.0, "beyond_ema200_zone")

    @staticmethod
    def _rsi_side_score(rsi_now: float, direction: str) -> tuple[float, str | None, str | None]:
        """§3.1 score component: RSI>50 for long, RSI<50 for short."""
        if pd.isna(rsi_now):
            return 0.0, "rsi_unavailable", None
        on_side = rsi_now > 50.0 if direction == "long" else rsi_now < 50.0
        if not on_side:
            return 0.0, "rsi_wrong_side", None
        return 1.0, None, f"rsi={rsi_now:.1f}"

    @staticmethod
    def _stop_loss(
        window: pd.DataFrame, last_close: float, atr_now: float, direction: str, p: dict
    ) -> float:
        """§3.1: SL = ATR-multiple vs. recent swing extreme, whichever is farther (more protective)."""
        recent = window.iloc[-p["swing_lookback_bars"] :]
        if direction == "long":
            sl_by_atr = last_close - p["sl_atr_mult"] * atr_now
            sl_by_swing = recent["low"].min()
            return min(sl_by_atr, sl_by_swing)
        sl_by_atr = last_close + p["sl_atr_mult"] * atr_now
        sl_by_swing = recent["high"].max()
        return max(sl_by_atr, sl_by_swing)
