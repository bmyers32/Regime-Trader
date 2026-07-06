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
  - Signal.tp == None means "no TP exit path" (position only closes via SL). ATR-based
    trailing (trend_pullback, Phase 5) is strategy-specific and out of this engine's
    scope; it will need its own exit-update mechanism when that playbook lands.
  - equity_curve tracks REALIZED equity only (mark-to-market unrealized PnL is an
    EquitySnapshot/dashboard concern, Phase 8+).
  - A SizingError (missing/unavailable currency conversion) propagates and aborts the
    run rather than silently skipping the trade — refuse loudly, per sizing.py's contract.
"""

from __future__ import annotations

import pandas as pd

from bot.backtest.costs import apply_entry_cost, apply_exit_cost, rollover_cost_pips, spread_gate_ok
from bot.backtest.results import BacktestResult, BacktestTrade, compute_metrics
from bot.backtest.sizing import pip_size, pip_value_per_unit, size_position
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
    ) -> None:
        self._strategy = strategy
        self._classifier = regime_classifier
        self._instrument = instrument
        self._account_currency = account_currency
        self._risk_pct = risk_pct
        self._starting_equity = starting_equity
        self._cost_cfg = cost_cfg
        self._conversion_series = conversion_series or {}

    def run(self, ltf_df: pd.DataFrame, htf_df: pd.DataFrame) -> BacktestResult:
        self._classifier.reset()

        htf_times = htf_df["time"].to_numpy()
        equity = self._starting_equity
        equity_points: list[tuple] = []
        trades: list[BacktestTrade] = []

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
                    next_bar = ltf_df.iloc[i + 1]
                    open_position = self._try_open_position(signal, next_bar, cached_regime, equity)

            equity_points.append((bar_time, equity))

        equity_curve = pd.Series(
            [e for _, e in equity_points],
            index=pd.Index([t for t, _ in equity_points], name="time"),
            dtype=float,
        )
        metrics = compute_metrics(trades, equity_curve)
        return BacktestResult(trades=trades, equity_curve=equity_curve, metrics=metrics)

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
            "units": units,
            "regime_at_entry": regime.regime.value,
            "risk_amount": equity * (self._risk_pct / 100.0),
        }

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

        price_diff = (
            filled_exit - position["entry_px"]
            if direction == "long"
            else position["entry_px"] - filled_exit
        )
        pips = price_diff / pip_size(instrument)
        pv = pip_value_per_unit(
            instrument, self._account_currency, filled_exit, bar_time, self._conversion_series
        )
        pnl = pips * pv * position["units"]

        rollover_pips = rollover_cost_pips(
            self._cost_cfg, direction, position["entry_ts"], bar_time
        )
        pnl += rollover_pips * pv * position["units"]

        pnl_r = pnl / position["risk_amount"] if position["risk_amount"] else 0.0
        equity += pnl

        trade = BacktestTrade(
            instrument=instrument,
            direction=direction,
            entry_ts=position["entry_ts"],
            exit_ts=bar_time,
            entry_px=position["entry_px"],
            exit_px=filled_exit,
            units=position["units"],
            pnl=pnl,
            pnl_r=pnl_r,
            exit_reason=exit_reason,
            regime_at_entry=position["regime_at_entry"],
        )
        return trade, equity
