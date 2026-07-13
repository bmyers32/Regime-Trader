"""
carry: D1/H4 carry-with-regime-conditioning playbook (TRADING-RULES §6, 2026-07-12
hearing, slot 2 of the pivot-cycle budget -- external-evidence thesis, forward-premium-
puzzle lineage: high-yield currencies tend not to depreciate enough to offset their
interest-rate differential -- hold the positive-carry direction, conditioned to stand
aside when volatility regimes make carry crash-prone). Full spec-mapping (signal
source, sign-stability exhibit, all six spec items, four amendments) resolved and
recorded in HANDOFF.md before this file was written, per PROMPTS.md §5.7.

Signal (spec C.1): direction = sign of the policy-rate differential (rate[base] -
rate[quote]) as of the current D-bar, looked up against real historical central-bank
policy rates (or best-available proxy) fetched from FRED and pinned to
calibration/rates/ (bot.data.rates.PolicyRateCache) -- NOT OANDA's own constant
financing-rate snapshot (that remains the engine's cost model, see the rollover note
below). ONE component, no minimum-differential threshold in the IS-search grid: both
this hearing's target pairs' real differentials sit at 2.6-5.3 percentage points across
the whole window (HANDOFF.md's sign-stability exhibit), so a small pre-declared floor
would be structurally inert -- fixed at 0.0 (pure sign), not searched. Signal-only per
the §1.1 exemption (2026-07-12): confidence_score is fixed at 1.0 whenever a signal
fires, same shape as momentum.

Regime-conditioning (spec C.2, THIS HEARING'S OWN CENTERPIECE -- intrinsic, not
decorative, unlike momentum's deliberate non-gating): EXPANSION on the D-anchor blocks
NEW entries only, journaled as a veto (reusing range_reversion's exact convention --
Signal still returned, vetoes non-empty, near-miss visible), NOT a force-flatten of an
open position. Rejected force-flatten: the classifier needs regime_confirm_bars=2
confirmed D-closes to enter EXPANSION (even though EXPANSION bypasses
regime_min_hold_bars on entry), so any mid-hold flatten would land ~2 days into a real
volatility event -- after the ATR trail/SL have already reacted to the same price
action that caused EXPANSION to confirm. That would buy new engine surface (none exists
today for a mid-hold consult-and-flatten) for an exit that structurally fires LATER
than exits already in place. Crash protection here is sizing + trail; this gate's job
is refusing to INITIATE into elevated volatility, which suspend-only does with zero new
engine surface -- momentum's own A3 exit-mechanics decision leaned on the same
minimal-surface bias. Unlike momentum (which never reads regime.regime at all -- its
own module docstring says so explicitly), this IS the first strategy to gate directly
on the D-anchor classifier's confirmed regime.regime, because regime-conditioning is
this hearing's whole point, not an afterthought.

Gate/score structure (spec C.3): (1) regime.htf_window is None -> not consulted
(engine bootstrap, momentum's own precedent); (2) insufficient rate-history warmup for
either currency -> not consulted; (3) exact-tie differential -> not consulted
(momentum's own tie-case precedent for its own signal_value==0.0); (4) EXPANSION veto
-> consulted, journaled, vetoes non-empty (computed only once a direction actually
exists, same order range_reversion's own veto-then-score flow uses). Spread/blackout
gates are engine-level (bot.backtest.costs), not reimplemented here, same as every
other playbook.

Exit (spec C.4): SAME ATR/Chandelier trail (partial-at-1R + trail remainder) every
playbook uses, reused as-is -- no new engine surface, directly inheriting slot 1's
A3/A7 null result on signal-flip exit as a revival mechanism (a directional-
continuation thesis, same shape momentum's exit-mechanics reasoning already covers).

Rollover interaction (spec C.6): this strategy's SIGNAL uses time-varying HISTORICAL
FRED differentials (bot.data.rates); the BACKTEST ENGINE's rollover COST uses a
constant PRESENT-DAY OANDA snapshot (instruments.yaml cost_model.rollover_pips_per_day,
scripts/fetch_financing_rates.py) -- these are explicitly NOT the same convention,
stated here rather than silently reconciled. See HANDOFF.md's C.6 section for the full
reconciliation check (both target pairs' OANDA rollover sign matches this signal's
predicted long direction) and the divergence's DIRECTION (both differentials narrowed
over the window, so the constant present-day snapshot under-credits early-window
trades relative to true history -- conservative for this thesis, not generous).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from bot.data.rates import PolicyRateCache, rate_asof
from bot.indicators.core import atr as _atr
from bot.regime.classifier import RegimeResult, RegimeState
from bot.strategies.base import Signal

# calibration/rates/ is TRACKED in git (amendment 3, HANDOFF.md) -- not injected via
# the strategy registry's shared (params, instrument) constructor signature. Same
# convention config.py/scripts/fetch_history.py already use for instruments.yaml/
# candle_cache: a hardcoded, repo-relative path for a calibration-type resource, not
# full dependency injection.
_RATES_DIR = Path(__file__).resolve().parent.parent.parent / "calibration" / "rates"

# ATR(14)'s Wilder smoothing needs several multiples of its period to converge -- same
# warmup convention momentum/range_reversion already use for their own ATR-based SLs.
_ATR_WARMUP_BARS = 3 * 14


class Carry:
    """
    params: instruments.yaml's carry_params (defaults merged with any per-instrument
    carry_calibration override). One instance per instrument; loads its two relevant
    currencies' rate history ONCE at construction (small files -- cheap to re-read even
    across many walk-forward candidates, see module docstring on the path convention).
    """

    def __init__(self, params: dict, instrument: str) -> None:
        self._params = params
        self._instrument = instrument
        self._base, self._quote = _split_instrument(instrument)

        cache = PolicyRateCache(_RATES_DIR)
        base_rates = cache.load(self._base)
        quote_rates = cache.load(self._quote)
        if base_rates is None or quote_rates is None:
            raise RuntimeError(
                f"No cached policy-rate history for {self._base}/{self._quote} -- "
                "run scripts/fetch_policy_rates.py first (see HANDOFF.md)."
            )
        self._base_rates = base_rates
        self._quote_rates = quote_rates

    def generate_signal(self, window: pd.DataFrame, regime: RegimeResult) -> Signal | None:
        if regime.htf_window is None:
            return None  # engine bootstrap: no anchor-TF history classified yet -> not consulted

        p = self._params
        if len(window) < _ATR_WARMUP_BARS:
            return None  # insufficient H4 warmup for the SL's own ATR -> not a real evaluation yet

        as_of = regime.htf_window["time"].iloc[[-1]]
        base_rate = rate_asof(self._base_rates, as_of).iloc[0]
        quote_rate = rate_asof(self._quote_rates, as_of).iloc[0]
        if pd.isna(base_rate) or pd.isna(quote_rate):
            return None  # rate history doesn't reach back this far yet -> not a real evaluation

        differential = base_rate - quote_rate
        if differential == 0.0:
            return None  # exact tie -> no signal, nothing to score (momentum's own tie precedent)

        direction = "long" if differential > 0 else "short"

        high, low, close = window["high"], window["low"], window["close"]
        atr_now = _atr(high, low, close, 14).iloc[-1]
        if pd.isna(atr_now) or atr_now <= 0.0:
            return None  # insufficient H4 ATR warmup -> not a real evaluation yet

        vetoes: list[str] = []
        if regime.regime == RegimeState.EXPANSION:
            vetoes.append("expansion_regime")  # spec C.2: suspend new entries only, journaled

        last_close = close.iloc[-1]
        sl = (
            last_close - p["sl_atr_mult"] * atr_now
            if direction == "long"
            else last_close + p["sl_atr_mult"] * atr_now
        )

        return Signal(
            strategy="carry",
            instrument=self._instrument,
            direction=direction,
            entry_ref=last_close,
            sl=sl,
            tp=None,  # exit_cfg drives the ATR/Chandelier trail -- see module docstring
            confidence_score=1.0,  # signal-only, TRADING-RULES §1.1 exemption
            reasons=[f"rate_differential_{self._base}_minus_{self._quote}={differential:.4f}"],
            vetoes=vetoes,
        )


def _split_instrument(instrument: str) -> tuple[str, str]:
    base, _, quote = instrument.partition("_")
    if not base or not quote:
        raise ValueError(f"Instrument name not in BASE_QUOTE form: {instrument!r}")
    return base, quote
