"""
Event-driven backtest engine (TRADING-RULES §1.13: PnL sim w/ costs, not a signal CSV).

Timing (AGENTS.md invariable — verified, not assumed):
  - No repainting (Prime Directive 3): Strategy.generate_signal() sees the LTF window
    up to and including the CURRENT closed bar only. A resulting Signal is filled at
    the NEXT bar's open — never the signal bar's own close.
  - Regime call cadence: RegimeClassifier.classify() is called exactly once per newly
    closed HTF candle, not once per LTF bar. The classifier's hysteresis counts "bars"
    per call (bars_in_regime += 1 each call); calling it once per LTF bar would inflate
    that count at the LTF rate instead of the HTF rate the thresholds were written in
    (anchor:execution ratio is 4-6:1, TRADING-RULES §2). Between HTF closes, the last
    RegimeResult is cached and reused.
  - classifier.reset() is called at the start of every run() so two sequential runs on
    the same RegimeClassifier instance produce identical results (its own contract).

Sizing and cost model are delegated to bot.backtest.sizing / bot.backtest.costs — the
SAME modules the live executor will call in Phase 8 (Prime Directive 7). This engine
does not reimplement either.

Simplifications explicit for this phase (documented, not hidden):
  - Exactly one open position at a time for the instrument being run.
  - If both SL and TP fall within one bar's high/low range, SL is assumed to trigger
    first (conservative — standard backtest convention to avoid overstating results).
  - Signal.tp == None means "no TP exit path" unless exit_cfg is supplied, in which
    case partial-at-1R + ATR/Chandelier trailing applies instead (TRADING-RULES §3.1;
    see _check_exit_with_trailing). exit_cfg=None reproduces this original Phase 4
    fixed-SL/TP-only behavior exactly.
  - equity_curve tracks REALIZED equity only (mark-to-market unrealized PnL is an
    EquitySnapshot/dashboard concern, Phase 8+).
  - A SizingError (missing/unavailable currency conversion) propagates and aborts the
    run rather than silently skipping the trade — refuse loudly, per sizing.py's contract.
"""

from __future__ import annotations

import pandas as pd

from bot.backtest.costs import (
    apply_entry_cost,
    apply_exit_cost,
    entry_blackout_ok,
    rollover_cost_pips,
    spread_gate_ok,
)
from bot.backtest.results import (
    BacktestResult,
    BacktestTrade,
    SignalEvaluation,
    compute_metrics,
    compute_signal_funnel,
)
from bot.backtest.sizing import pip_size, pip_value_per_unit, size_position
from bot.indicators.core import atr as _atr
from bot.regime.classifier import RegimeClassifier, RegimeResult
from bot.strategies.base import Strategy


class BacktestEngine:
    def __init__(
        self,
        strategy: Strategy,
        regime_classifier: RegimeClassifier,
        instrument: str,
        account_currency: str,
        risk_pct: float,
        starting_equity: float,
        cost_cfg: dict,
        conversion_series: dict[str, pd.DataFrame] | None = None,
        exit_cfg: dict | None = None,
        signal_threshold: float = 1.0,
        record_signals: bool = True,
    ) -> None:
        """
        exit_cfg: optional partial-at-1R + ATR/Chandelier-trail exit policy (TRADING-
          RULES §3.1, HANDOFF.md Session A Decision 1). None (default) reproduces exact
          Phase 4 fixed SL/TP behavior — zero regression for strategies that don't use
          it. Keys: partial_fraction, partial_at_r, breakeven_after_partial,
          trail_atr_period, trail_atr_mult.
        signal_threshold / record_signals: near-miss journaling (Decision 3). A Signal
          only fires when it carries no vetoes AND confidence_score >= signal_threshold;
          every consulted evaluation (generate_signal() returned non-None) is otherwise
          recorded to BacktestResult.signal_log regardless of fire/no-fire. Default
          threshold of 1.0 with record_signals=True reproduces every Phase 4 test's
          behavior unchanged (those test-double signals carry vetoes=[] and
          confidence_score=1.0, so they still always fire).
        """
        self._strategy = strategy
        self._classifier = regime_classifier
        self._instrument = instrument
        self._account_currency = account_currency
        self._risk_pct = risk_pct
        self._starting_equity = starting_equity
        self._cost_cfg = cost_cfg
        self._conversion_series = conversion_series or {}
        self._exit_cfg = exit_cfg
        self._signal_threshold = signal_threshold
        self._record_signals = record_signals

    def run(self, ltf_df: pd.DataFrame, htf_df: pd.DataFrame) -> BacktestResult:
        self._classifier.reset()

        htf_times = htf_df["time"].to_numpy()
        equity = self._starting_equity
        equity_points: list[tuple] = []
        trades: list[BacktestTrade] = []
        signal_log: list[SignalEvaluation] = []

        ltf_atr = (
            _atr(ltf_df["high"], ltf_df["low"], ltf_df["close"], self._exit_cfg["trail_atr_period"])
            if self._exit_cfg is not None
            else None
        )

        open_position: dict | None = None
        cached_regime: RegimeResult | None = None
        last_htf_ts = None

        n = len(ltf_df)
        for i in range(n):
            bar = ltf_df.iloc[i]
            bar_time = bar["time"]

            htf_pos = int(htf_times.searchsorted(bar_time, side="right")) - 1
            if htf_pos >= 0:
                latest_htf_ts = htf_times[htf_pos]
                if last_htf_ts is None or latest_htf_ts != last_htf_ts:
                    htf_window = htf_df.iloc[: htf_pos + 1]
                    cached_regime = self._classifier.classify(htf_window)
                    last_htf_ts = latest_htf_ts

            if cached_regime is None:
                # Not enough anchor-TF history yet to classify — no trading possible.
                equity_points.append((bar_time, equity))
                continue

            if open_position is not None:
                if self._exit_cfg is not None:
                    atr_now = ltf_atr.iloc[i]
                    exit_info = self._check_exit_with_trailing(open_position, bar, atr_now)
                else:
                    exit_info = self._check_exit(open_position, bar)
                if exit_info is not None:
                    exit_px, exit_reason = exit_info
                    trade, equity = self._close_position(
                        open_position, exit_px, exit_reason, bar_time, equity, cached_regime
                    )
                    trades.append(trade)
                    open_position = None

            if open_position is None and i + 1 < n:
                window = ltf_df.iloc[: i + 1]
                signal = self._strategy.generate_signal(window, cached_regime)
                if signal is not None:
                    fired = (not signal.vetoes) and (signal.confidence_score >= self._signal_threshold)
                    if self._record_signals:
                        signal_log.append(
                            SignalEvaluation(
                                ts=bar_time,
                                instrument=self._instrument,
                                strategy=signal.strategy,
                                direction=signal.direction,
                                score=signal.confidence_score,
                                threshold=self._signal_threshold,
                                fired=fired,
                                vetoes=list(signal.vetoes),
                                reasons=list(signal.reasons),
                            )
                        )
                    if fired:
                        next_bar = ltf_df.iloc[i + 1]
                        open_position = self._try_open_position(signal, next_bar, cached_regime, equity)

            equity_points.append((bar_time, equity))

        equity_curve = pd.Series(
            [e for _, e in equity_points],
            index=pd.Index([t for t, _ in equity_points], name="time"),
            dtype=float,
        )
        metrics = compute_metrics(trades, equity_curve)
        if self._record_signals:
            metrics["signal_funnel"] = compute_signal_funnel(signal_log, self._signal_threshold)
        return BacktestResult(trades=trades, equity_curve=equity_curve, metrics=metrics, signal_log=signal_log)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _check_exit(self, position: dict, bar: pd.Series) -> tuple[float, str] | None:
        direction = position["direction"]
        sl = position["sl"]
        tp = position["tp"]

        if direction == "long":
            sl_hit = bar["low"] <= sl
            tp_hit = tp is not None and bar["high"] >= tp
        else:
            sl_hit = bar["high"] >= sl
            tp_hit = tp is not None and bar["low"] <= tp

        if sl_hit:
            return sl, "sl"
        if tp_hit:
            return tp, "tp"
        return None

    def _try_open_position(
        self, signal, next_bar: pd.Series, regime: RegimeResult, equity: float
    ) -> dict | None:
        bar_time = next_bar["time"]
        if not spread_gate_ok(self._cost_cfg, bar_time):
            return None
        if not entry_blackout_ok(self._cost_cfg, bar_time):
            return None

        filled = apply_entry_cost(
            next_bar["open"], signal.direction, self._instrument, self._cost_cfg, bar_time
        )
        stop_distance = abs(filled - signal.sl)

        units = size_position(
            equity=equity,
            risk_pct=self._risk_pct,
            stop_distance=stop_distance,
            instrument=self._instrument,
            account_currency=self._account_currency,
            price=filled,
            bar_time=bar_time,
            conversion_series=self._conversion_series,
        )

        return {
            "direction": signal.direction,
            "entry_ts": bar_time,
            "entry_px": filled,
            "sl": signal.sl,
            "tp": signal.tp,
            "units": units,  # current tradable size; reduced in place by a partial close
            "initial_units": units,  # fixed at open — original full size for the trade record
            "regime_at_entry": regime.regime.value,
            "bars_in_regime_at_entry": regime.bars_in_regime,
            "risk_amount": equity * (self._risk_pct / 100.0),
            "partial_done": False,
            "trail_extreme": None,
            "partial_exit_ts": None,
            "partial_exit_px": None,
            "partial_exit_units": None,
            "partial_exit_pnl": None,
        }

    def _check_exit_with_trailing(
        self, position: dict, bar: pd.Series, atr_now: float
    ) -> tuple[float, str] | None:
        """
        TRADING-RULES §3.1 exit: partial close at partial_at_r (limit-style, no
        slippage), then an ATR/Chandelier trail on the remainder. SL keeps priority
        on any bar where both the original stop and the partial target are touched
        (same conservative same-bar tie-break convention as _check_exit).
        """
        direction = position["direction"]
        cfg = self._exit_cfg

        sl_hit = bar["low"] <= position["sl"] if direction == "long" else bar["high"] >= position["sl"]
        if sl_hit:
            return position["sl"], "trail" if position["partial_done"] else "sl"

        if not position["partial_done"]:
            stop_distance = abs(position["entry_px"] - position["sl"])
            target_r = cfg["partial_at_r"]
            if direction == "long":
                partial_price = position["entry_px"] + target_r * stop_distance
                partial_hit = bar["high"] >= partial_price
            else:
                partial_price = position["entry_px"] - target_r * stop_distance
                partial_hit = bar["low"] <= partial_price

            if partial_hit:
                # Documented simplification (same spirit as the SL/TP tie-break): if
                # this same bar's range would ALSO have breached the newly-set
                # breakeven/trail stop after the partial executes, that isn't checked
                # until the NEXT bar. One exit-decision per bar, same as _check_exit.
                self._execute_partial(position, partial_price, bar)
            return None

        # Documented simplification, same spirit as the SL/TP tie-break above:
        # ratcheting the trail and checking it against the same bar that produced
        # the new extreme (rather than deferring the check to the next bar).
        new_extreme = (
            max(position["trail_extreme"], bar["high"])
            if direction == "long"
            else min(position["trail_extreme"], bar["low"])
        )
        position["trail_extreme"] = new_extreme
        if not pd.isna(atr_now):
            trail_stop = (
                new_extreme - cfg["trail_atr_mult"] * atr_now
                if direction == "long"
                else new_extreme + cfg["trail_atr_mult"] * atr_now
            )
            position["sl"] = (
                max(position["sl"], trail_stop) if direction == "long" else min(position["sl"], trail_stop)
            )

        sl_hit_after_ratchet = (
            bar["low"] <= position["sl"] if direction == "long" else bar["high"] >= position["sl"]
        )
        if sl_hit_after_ratchet:
            return position["sl"], "trail"
        return None

    def _execute_partial(self, position: dict, partial_price: float, bar: pd.Series) -> None:
        """Mutates position in place: books the partial leg, reduces units, arms the trail."""
        cfg = self._exit_cfg
        direction = position["direction"]
        bar_time = bar["time"]

        # Limit-style fill: the partial target is a resting exit, not an urgent market
        # order — half-spread only, no slippage (same economics apply_exit_cost already
        # gives a "tp" exit_reason).
        filled_partial = apply_exit_cost(
            partial_price, direction, self._instrument, self._cost_cfg, bar_time,
            exit_reason="tp", exit_regime=None,
        )
        partial_units = position["initial_units"] * cfg["partial_fraction"]

        price_diff = (
            filled_partial - position["entry_px"] if direction == "long" else position["entry_px"] - filled_partial
        )
        pips = price_diff / pip_size(self._instrument)
        pv = pip_value_per_unit(
            self._instrument, self._account_currency, filled_partial, bar_time, self._conversion_series
        )
        partial_pnl = pips * pv * partial_units

        position["partial_exit_ts"] = bar_time
        position["partial_exit_px"] = filled_partial
        position["partial_exit_units"] = partial_units
        position["partial_exit_pnl"] = partial_pnl
        position["units"] = position["initial_units"] - partial_units
        position["partial_done"] = True
        position["trail_extreme"] = bar["high"] if direction == "long" else bar["low"]

        if cfg["breakeven_after_partial"]:
            position["sl"] = position["entry_px"]

    def _close_position(
        self,
        position: dict,
        raw_exit_px: float,
        exit_reason: str,
        bar_time,
        equity: float,
        regime_at_exit: RegimeResult,
    ) -> tuple[BacktestTrade, float]:
        direction = position["direction"]
        instrument = self._instrument

        filled_exit = apply_exit_cost(
            raw_exit_px,
            direction,
            instrument,
            self._cost_cfg,
            bar_time,
            exit_reason,
            exit_regime=regime_at_exit.regime.value,
        )

        remaining_units = position["units"]  # already reduced in place by any partial
        price_diff = (
            filled_exit - position["entry_px"]
            if direction == "long"
            else position["entry_px"] - filled_exit
        )
        pips = price_diff / pip_size(instrument)
        pv = pip_value_per_unit(
            instrument, self._account_currency, filled_exit, bar_time, self._conversion_series
        )
        remainder_pnl = pips * pv * remaining_units
        partial_pnl = position["partial_exit_pnl"] or 0.0

        # TRADING-RULES §5.2 / HANDOFF.md Session A Decision 1d: rollover on units
        # ACTUALLY held per calendar-day segment — full size before any partial,
        # reduced size after. The two half-open intervals rollover_crossings() counts
        # partition (entry_ts, exit_ts] exactly, so no boundary is double-counted
        # (barring the vanishing edge case of partial_exit_ts landing exactly on a
        # rollover boundary).
        if position["partial_exit_ts"] is not None:
            rollover_pips_leg1 = rollover_cost_pips(
                self._cost_cfg, direction, position["entry_ts"], position["partial_exit_ts"]
            )
            rollover_pips_leg2 = rollover_cost_pips(
                self._cost_cfg, direction, position["partial_exit_ts"], bar_time
            )
            rollover_pnl = (
                rollover_pips_leg1 * pv * position["initial_units"]
                + rollover_pips_leg2 * pv * remaining_units
            )
        else:
            rollover_pips_full = rollover_cost_pips(
                self._cost_cfg, direction, position["entry_ts"], bar_time
            )
            rollover_pnl = rollover_pips_full * pv * position["initial_units"]

        pnl = partial_pnl + remainder_pnl + rollover_pnl
        pnl_r = pnl / position["risk_amount"] if position["risk_amount"] else 0.0
        equity += pnl

        trade = BacktestTrade(
            instrument=instrument,
            direction=direction,
            entry_ts=position["entry_ts"],
            exit_ts=bar_time,
            entry_px=position["entry_px"],
            exit_px=filled_exit,
            units=position["initial_units"],
            pnl=pnl,
            pnl_r=pnl_r,
            exit_reason=exit_reason,
            regime_at_entry=position["regime_at_entry"],
            bars_in_regime_at_entry=position["bars_in_regime_at_entry"],
            partial_exit_ts=position["partial_exit_ts"],
            partial_exit_px=position["partial_exit_px"],
            partial_exit_units=position["partial_exit_units"],
            partial_exit_pnl=position["partial_exit_pnl"],
        )
        return trade, equity
