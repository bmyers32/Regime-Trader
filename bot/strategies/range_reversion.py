"""
range_reversion: RANGING-only playbook (TRADING-RULES §3.2).

Spec-mapping decision (approved 2026-07-09, recorded in HANDOFF.md before this file
was written): §3.2's letter gives exactly TWO independent entry conditions joined by
"+" ("close back INSIDE lower BB (re-entry close, not pierce)" + "RSI<30 turning up"),
one separately-labeled "Hard veto:" bullet, and a session note this strategy does not
encode (per-session attribution answers that empirically instead — see
bot/backtest/results.py). Unlike trend_pullback's 4 scored components, this playbook
has only 2 — that is a deliberate match to the letter, not an underbuild.

Full TRADING-RULES §1.1 gate accounting for this playbook (2-3 hard gates + weighted
confluence):
  - Hard gate A: regime routing (RANGING only) — generate_signal() returns None
    outright when not routed, same "not consulted" semantics as trend_pullback.
  - Hard gate B: LTF-level instant expansion/ATR-spike veto (_expansion_veto below) —
    computed directly on THIS strategy's execution-TF window, not inherited from the
    HTF regime classifier's confirmed state. The classifier's own hysteresis
    (regime_confirm_bars=2, even with the "entering EXPANSION bypasses min-hold"
    exception) means a genuine ATR spike can exist for 1-2 bars before the confirmed
    regime flips off RANGING — §3.2 says "instantly disables new entries", which only
    makes sense as a faster, independent check. Unlike trend_pullback's near-miss
    components (all four lived under one "Score:" bullet with no veto language
    anywhere near them), §3.2's expansion condition has its OWN bullet, explicitly
    labeled "Hard veto", with disable-not-degrade language — keeping it a real veto
    here is following the letter, not reintroducing the §1.1 AND-stack anti-pattern
    Phase 5's law-drift fix corrected. When tripped, this bar IS consulted (a Signal
    is still returned, vetoes non-empty, journaled) — different from gate A's "not
    consulted".
  - Hard gates C/D: spread gate + entry blackout — ENGINE level
    (bot.backtest.costs.spread_gate_ok / entry_blackout_ok, wired into
    BacktestEngine._try_open_position), same shared infrastructure trend_pullback
    relies on. Not reimplemented here.
  - Weighted confluence (2 components): band_reentry, rsi_recovery — see below.

AND/OR pre-registration (disposition 1, before any real-data run): both scored
components are binary (0/1) and their weights sum to 1.0, so confidence_score can
only take values {0, w_a, w_b, 1.0}. The (entry_threshold, score_weights) search
therefore does not tune a continuous dial — it selects among discrete effective
regimes: threshold <= min(weight) -> OR (either component alone fires); min(weight)
< threshold <= max(weight) -> asymmetric (only the heavier-weighted component can
fire alone); threshold > max(weight) -> AND (both required, matching §3.2's literal
"+"). If a walk-forward window's IS selection lands in OR or asymmetric, that
OVERRULES §3.2's conjunctive letter for that window and MUST be stated explicitly in
the eventual §1.7 calibration note — not silently accepted as "the search found a
good threshold". scripts/run_validation_gates.py classifies and logs this per window.

Direction: RANGING carries no direction (unlike TRENDING_UP/DOWN), so this strategy
assigns its own candidate direction each consulted bar from price's side of the
middle band — close on the lower side (<= middle) candidates "long" (mean-reversion
buy-low setup), the upper side candidates "short" (sell-high setup). This is a cheap,
always-available direction signal (mirrors trend_pullback's regime-derived direction
being always available), NOT a hard gate: band_reentry/rsi_recovery still score 0
(never None, never a veto) when the candidate setup hasn't actually formed yet — this
is what keeps band_reentry a genuine near-miss-scoring component instead of a de-facto
gate (the exact failure mode Phase 5's law-drift audit found and fixed: a condition
that must be true for a Signal to exist at all is a hard gate wearing a score's
clothing).

Exit: SL = rejection-candle extreme (lookback low/high) +/- sl_atr_mult * ATR — a
tighter local structure than trend_pullback's swing extreme, matching §3.2's "beyond
rejection-candle extreme, ~1-1.5x ATR". TP = middle band (20 SMA) value AT SIGNAL
TIME, using BacktestEngine's existing plain SL/TP path (exit_cfg=None).
LIMITATION (approved 2026-07-09, disposition 3): this is a documented approximation —
Signal.tp is a fixed price level, it does not dynamically track the middle band's
movement between signal and fill/exit. The "optional runner toward opposite band" §3.2
describes is explicitly NOT implemented this phase (deferred to ROADMAP.md) — it would
need new price-level-based exit_cfg machinery beyond the existing R-multiple-based
partial/trail structure trend_pullback uses. "Never hold for full traversal" is
satisfied structurally by targeting the middle band only, never the opposite band.
"""

from __future__ import annotations

import pandas as pd

from bot.indicators.core import atr as _atr
from bot.indicators.core import bb_reentry_long as _bb_reentry_long
from bot.indicators.core import bb_reentry_short as _bb_reentry_short
from bot.indicators.core import bollinger_bands as _bollinger_bands
from bot.indicators.core import rsi as _rsi
from bot.regime.classifier import RegimeResult, RegimeState
from bot.strategies.base import Signal

# ATR14's 60-bar rolling mean (used by the expansion veto) needs several multiples of
# 60 bars to stabilise — same "accuracy improves after ~3x period" warmup convention
# ATR/ADX/EMA200 already use elsewhere in this codebase.
_EXPANSION_MEAN_WARMUP_BARS = 3 * 60


class RangeReversion:
    """
    params: instruments.yaml's range_reversion_params (defaults merged with any
    per-instrument range_reversion_calibration override).
    One instance per instrument (stateless otherwise — all indicators recomputed from
    the window each call, matching the Strategy Protocol's pure-function contract).
    """

    def __init__(self, params: dict, instrument: str) -> None:
        self._params = params
        self._instrument = instrument

    def generate_signal(self, window: pd.DataFrame, regime: RegimeResult) -> Signal | None:
        if regime.regime != RegimeState.RANGING:
            return None  # not routed to this playbook this bar -> nothing to journal

        p = self._params
        min_bars = max(
            p["bb_period"], p["rsi_period"] + 1, p["rejection_lookback_bars"], _EXPANSION_MEAN_WARMUP_BARS
        )
        if len(window) < min_bars:
            return None  # insufficient warmup -> not a real evaluation yet

        high = window["high"]
        low = window["low"]
        close = window["close"]
        last_close = close.iloc[-1]

        upper, middle, lower = _bollinger_bands(close, p["bb_period"], p["bb_std"])
        middle_now = middle.iloc[-1]
        rsi_series = _rsi(close, p["rsi_period"])
        atr14 = _atr(high, low, close, 14)
        atr_now = atr14.iloc[-1]

        direction = "long" if last_close <= middle_now else "short"

        reasons: list[str] = []
        vetoes: list[str] = []

        veto = self._expansion_veto(high, low, close, p)
        if veto is not None:
            vetoes.append(veto)

        reentry_score, reentry_reason = self._band_reentry_score(close, upper, lower, direction)
        reasons.append(reentry_reason)

        rsi_score, rsi_reason = self._rsi_recovery_score(rsi_series, direction, p)
        reasons.append(rsi_reason)

        weights = p["score_weights"]
        confidence_score = weights["band_reentry"] * reentry_score + weights["rsi_recovery"] * rsi_score

        sl = self._stop_loss(window, last_close, atr_now, direction, p)

        return Signal(
            strategy="range_reversion",
            instrument=self._instrument,
            direction=direction,
            entry_ref=last_close,
            sl=sl,
            tp=middle_now,  # static approximation — see module docstring, disposition 3
            confidence_score=confidence_score,
            reasons=reasons,
            vetoes=vetoes,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _band_reentry_score(
        close: pd.Series, upper: pd.Series, lower: pd.Series, direction: str
    ) -> tuple[float, str]:
        """
        §3.2 scored component: close-based re-entry (bot.indicators.core.bb_reentry_
        long/short). Binary (score, reason) 2-tuple — same style as trend_pullback's
        binary reversal_trigger_score. Absence of a re-entry event scores 0 via
        `reason`; it is NEVER required for the Signal to exist (that would make this
        a hard gate wearing a score's clothing — see module docstring).
        """
        if direction == "long":
            fired = bool(_bb_reentry_long(close, lower).iloc[-1])
        else:
            fired = bool(_bb_reentry_short(close, upper).iloc[-1])
        return (1.0, "band_reentry") if fired else (0.0, "no_band_reentry")

    @staticmethod
    def _rsi_recovery_score(rsi_series: pd.Series, direction: str, p: dict) -> tuple[float, str]:
        """
        §3.2 scored component: "RSI<30 turning up" (long), mirrored at the upper
        threshold for short ("RSI>70 turning down" — the letter's own "mirrored"
        instruction, not an invented threshold: overbought = 100 - oversold_threshold).
        Binary (score, reason) 2-tuple, same style as trend_pullback's rsi_side_score.
        """
        rsi_now = rsi_series.iloc[-1]
        rsi_prev = rsi_series.iloc[-2] if len(rsi_series) > 1 else float("nan")
        if pd.isna(rsi_now) or pd.isna(rsi_prev):
            return 0.0, "rsi_unavailable"

        oversold_thresh = p["rsi_oversold_threshold"]
        overbought_thresh = 100.0 - oversold_thresh

        if direction == "long":
            oversold = rsi_now < oversold_thresh
            turning_up = rsi_now > rsi_prev
            if not oversold:
                return 0.0, "rsi_not_oversold"
            if not turning_up:
                return 0.0, "rsi_oversold_not_turning"
            return 1.0, f"rsi_recovering={rsi_now:.1f}"

        overbought = rsi_now > overbought_thresh
        turning_down = rsi_now < rsi_prev
        if not overbought:
            return 0.0, "rsi_not_overbought"
        if not turning_down:
            return 0.0, "rsi_overbought_not_turning"
        return 1.0, f"rsi_recovering={rsi_now:.1f}"

    @staticmethod
    def _expansion_veto(high: pd.Series, low: pd.Series, close: pd.Series, p: dict) -> str | None:
        """
        Hard gate B (module docstring): LTF-level instant expansion/ATR-spike check,
        independent of the HTF regime classifier's hysteresis-lagged confirmed state.
        Reuses the SAME dimensionless ratio/mean-mult thresholds as
        bot.regime.classifier's EXPANSION detection (regime_params.atr_expansion_
        ratio / atr_expansion_mean_mult) — those are scale-invariant multipliers, not
        timeframe-bound periods, so applying them to this strategy's execution-TF ATR
        is a reuse of a validated dimensionless constant, not an untested new number.
        APPROVED CONTINGENT (disposition 4): this reuse holds only if a §1.7 pass-rate
        check on each pair's real H1 history shows this veto firing at neither <1% nor
        >95% of RANGING-consulted bars — see the pass-rate note this playbook's
        calibration_note carries once real data confirms it.
        """
        atr10 = _atr(high, low, close, 10)
        atr50 = _atr(high, low, close, 50)
        atr14 = _atr(high, low, close, 14)

        atr10_last = atr10.iloc[-1]
        atr50_last = atr50.iloc[-1]
        atr14_last = atr14.iloc[-1]

        ratio_expansion = (
            not pd.isna(atr50_last)
            and atr50_last > 0
            and (atr10_last / atr50_last) > p["expansion_veto_atr_ratio"]
        )
        atr_mean_60 = atr14.rolling(60).mean().iloc[-1]
        mean_expansion = (
            not pd.isna(atr_mean_60)
            and atr_mean_60 > 0
            and atr14_last > p["expansion_veto_atr_mean_mult"] * atr_mean_60
        )

        if ratio_expansion or mean_expansion:
            return "expansion_atr_spike"
        return None

    @staticmethod
    def _stop_loss(
        window: pd.DataFrame, last_close: float, atr_now: float, direction: str, p: dict
    ) -> float:
        """§3.2: SL beyond the rejection-candle extreme, ~1-1.5x ATR (sl_atr_mult default
        1.25, midpoint of that range — same convention trend_pullback used)."""
        recent = window.iloc[-p["rejection_lookback_bars"] :]
        if direction == "long":
            return recent["low"].min() - p["sl_atr_mult"] * atr_now
        return recent["high"].max() + p["sl_atr_mult"] * atr_now
