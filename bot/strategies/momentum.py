"""
momentum: D1/H4 time-series momentum playbook (TRADING-RULES §6, 2026-07-12 hearing,
slot 1 of the pivot-cycle budget — external-evidence thesis, Moskowitz/Ooi/Pedersen
lineage: an instrument's own trailing return predicts its continuation at multi-week
horizons).

Signal (spec-mapping (1)): direction = sign of trailing_return(D-close, n) — ONE
component, N searched per-window IS-only from the pre-declared set {20, 60, 120}
(bot/config/instruments.yaml's momentum_params — the grid itself lives in
scripts/run_validation_gates.py, same convention as trend_pullback's entry_threshold/
score_weights grid). No volatility-adjusted variant, no indicator zoo.

Gate/score split (spec-mapping (2), TRADING-RULES §1.1 EXEMPTION, §6 2026-07-12): a
single-scoreable-component strategy may be signal-only — confidence_score is fixed at
1.0 whenever a signal fires; there is no weighted confluence to arbitrate, and adding
one would be decorative (the padded-AND-stack failure mode §1.1 exists to prevent, just
inverted). vetoes is structurally always empty: warmup/data-availability gates return
None outright (not consulted, nothing to journal), same "not routed" semantics
trend_pullback/range_reversion use for their own hard gates. Spread/blackout gates are
engine-level (bot.backtest.costs), not reimplemented here.

NO regime gate: regime.regime is never read for entry decisions — RegimeResult's own
docstring licenses this ("no strategy logic may gate on this value without §5
validation"), and this hearing's thesis is unconditional continuation, not
regime-conditional (that's slot 2's carry-with-regime-conditioning territory).

Timeframe roles (spec-mapping (3)): D1 = anchor, H4 = execution. The signal itself is
computed on regime.htf_window (the D-close series) — NOT on `window` (the H4 execution
series `generate_signal` also receives) — because the Strategy Protocol's (window,
regime) signature only ever carried the LTF window before this hearing; RegimeResult
gained an optional htf_window field (bot/regime/classifier.py, defaulted, backward
compatible) specifically so a strategy can consult raw anchor-TF price history without
changing that contracted signature (CLAUDE.md Core Interfaces, "do not drift").
regime.htf_window is READ-ONLY — a reference into engine/classifier state, never
mutated here.

Exit: SL = sl_atr_mult * ATR(14) computed on the H4 `window` (same convention every
other playbook uses for its own SL), no swing-extreme combination — §3.x's other
playbooks each cite a specific "beyond swing/rejection extreme" structure from their
own TRADING-RULES prose; no equivalent structure is prescribed for momentum, so a pure
ATR-multiple SL is the undecorated default, not an omission. No fixed TP (tp=None) —
partial-at-1R + ATR/Chandelier trail applies via BacktestEngine's exit_cfg, reused
as-is (spec-mapping (3) exit-mechanics decision: the engine only calls generate_signal
when flat, so neither a time-based nor signal-flip exit exists without new engine
surface; the trail needs none and already forces the protective stop TRADING-RULES §4
requires regardless of exit style).
"""

from __future__ import annotations

import pandas as pd

from bot.indicators.core import atr as _atr
from bot.indicators.core import trailing_return as _trailing_return
from bot.regime.classifier import RegimeResult
from bot.strategies.base import Signal

# ATR(14)'s Wilder smoothing needs several multiples of its period to converge --
# same "accuracy improves after ~3x period" warmup convention ATR/ADX/EMA200 already
# use elsewhere in this codebase (see range_reversion.py's _EXPANSION_MEAN_WARMUP_BARS).
_ATR_WARMUP_BARS = 3 * 14


class Momentum:
    """
    params: instruments.yaml's momentum_params (defaults merged with any per-instrument
    momentum_calibration override), PLUS the per-run "n" key the walk-forward's own
    param grid sets (scripts/run_validation_gates.py's build_param_grid_momentum) --
    n is the signal itself, not a fixed instruments.yaml constant.
    One instance per instrument (stateless otherwise -- all indicators recomputed from
    the window/htf_window each call, matching the Strategy Protocol's pure-function
    contract).
    """

    def __init__(self, params: dict, instrument: str) -> None:
        self._params = params
        self._instrument = instrument

    def generate_signal(self, window: pd.DataFrame, regime: RegimeResult) -> Signal | None:
        if regime.htf_window is None:
            return None  # engine bootstrap: no anchor-TF history classified yet -> not consulted

        p = self._params
        n = p["n"]

        d_close = regime.htf_window["close"]
        if len(d_close) < n + 1:
            return None  # insufficient D-bar warmup for this N -> not a real evaluation yet
        if len(window) < _ATR_WARMUP_BARS:
            return None  # insufficient H4 warmup for the SL's own ATR -> not a real evaluation yet

        signal_value = _trailing_return(d_close, n).iloc[-1]
        if pd.isna(signal_value) or signal_value == 0.0:
            return None  # no clear sign (or exact flat tie) -> no signal, nothing to score

        direction = "long" if signal_value > 0 else "short"

        high, low, close = window["high"], window["low"], window["close"]
        atr_now = _atr(high, low, close, 14).iloc[-1]
        if pd.isna(atr_now) or atr_now <= 0.0:
            return None  # insufficient H4 ATR warmup -> not a real evaluation yet

        last_close = close.iloc[-1]
        sl = (
            last_close - p["sl_atr_mult"] * atr_now
            if direction == "long"
            else last_close + p["sl_atr_mult"] * atr_now
        )

        return Signal(
            strategy="momentum",
            instrument=self._instrument,
            direction=direction,
            entry_ref=last_close,
            sl=sl,
            tp=None,  # exit_cfg drives the ATR/Chandelier trail — see module docstring
            confidence_score=1.0,  # signal-only, TRADING-RULES §1.1 exemption (§6, 2026-07-12)
            reasons=[f"trailing_return_n{n}={signal_value:.4f}"],
            vetoes=[],  # structurally always empty — see module docstring
        )
