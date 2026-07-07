"""
TRADING-RULES §5.3: IS/OOS split (~70/30) then rolling walk-forward (optimize rolling
window -> test next unseen segment -> roll); judge the stitched OOS equity curve only.

IS/OOS isolation is structural (HANDOFF.md Track 2 dispositions), not conventional:
  - select_best_params() (bot.backtest.param_sweep) is only ever handed an IS-bounded
    slice built by run_walk_forward() BEFORE the call -- it has no path to any bar at
    or after the OOS boundary.
  - An explicit assert at the boundary (`is_slice["time"].max() < oos_start_ts`) is a
    runtime tripwire against a future off-by-one refactor, not just documentation.
  - OOS evaluation runs the chosen (frozen) params over an EXTENDED slice that
    prepends real IS history purely so indicators (e.g. EMA200) are warmed up
    correctly at the OOS boundary -- this is genuinely-past information relative to
    OOS, never a peek forward. Trades/equity from that prepended IS portion are
    trimmed by entry_ts/index before anything is scored (same entry-time attribution
    convention BacktestTrade.regime_at_entry already uses elsewhere in this codebase).

Default step_bars=oos_bars produces the standard rolling-WFO shape: IS windows OVERLAP
from roll to roll (each new IS window slides forward by one OOS-length), but the OOS
windows themselves are contiguous and non-overlapping -- oos_start(k+1) == oos_end(k)
exactly -- so stitching the OOS segments end-to-end partitions the full OOS timeline
with no gap and no double-counted bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from bot.backtest.param_sweep import RunFn, _default_metric, select_best_params
from bot.backtest.results import BacktestResult, BacktestTrade, compute_metrics


@dataclass
class WindowOOSResult:
    """Already-trimmed OOS trades/equity for one rolled window (entry_ts/index >= this window's oos_start_ts only)."""

    trades: list[BacktestTrade]
    equity_curve: pd.Series


@dataclass
class WalkForwardWindow:
    window_index: int
    is_start_ts: pd.Timestamp
    oos_start_ts: pd.Timestamp  # == is_end_ts; IS is [is_start_ts, oos_start_ts)
    oos_end_ts: pd.Timestamp  # inclusive: timestamp of this window's last OOS bar
    chosen_params: dict
    is_scoreboard: list[dict]
    oos: WindowOOSResult


@dataclass
class WalkForwardReport:
    windows: list[WalkForwardWindow] = field(default_factory=list)
    stitched_trades: list[BacktestTrade] = field(default_factory=list)
    stitched_equity: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    stitched_metrics: dict = field(default_factory=dict)
    passed: bool = False
    reason: str = ""


def generate_window_bounds(
    n_bars: int, is_bars: int, oos_bars: int, step_bars: int | None = None
) -> list[tuple[int, int, int]]:
    """Returns (is_start_idx, oos_start_idx, oos_end_idx) bar-index bounds, oos_end_idx exclusive."""
    if step_bars is None:
        step_bars = oos_bars
    if is_bars <= 0 or oos_bars <= 0 or step_bars <= 0:
        raise ValueError("is_bars, oos_bars, step_bars must all be positive")

    bounds: list[tuple[int, int, int]] = []
    is_start_idx = 0
    while is_start_idx + is_bars + oos_bars <= n_bars:
        oos_start_idx = is_start_idx + is_bars
        oos_end_idx = oos_start_idx + oos_bars
        bounds.append((is_start_idx, oos_start_idx, oos_end_idx))
        is_start_idx += step_bars
    return bounds


def _bound_htf(htf_df: pd.DataFrame, max_ltf_ts) -> pd.DataFrame:
    return htf_df[htf_df["time"] <= max_ltf_ts]


def stitch_oos_results(window_results: list[WindowOOSResult]) -> tuple[list[BacktestTrade], pd.Series]:
    """
    Pure concatenation across already-trimmed, chronologically-ordered, non-overlapping
    OOS windows (TRADING-RULES §5.3's "stitched OOS equity curve"). Raises loudly on a
    duplicate or out-of-order timestamp -- that would mean the caller's window bounds
    overlapped or were mis-ordered, not something to silently paper over.
    """
    all_trades: list[BacktestTrade] = []
    equity_parts: list[pd.Series] = []
    for wr in window_results:
        all_trades.extend(wr.trades)
        equity_parts.append(wr.equity_curve)

    stitched_equity = pd.concat(equity_parts) if equity_parts else pd.Series(dtype=float)
    if not stitched_equity.index.is_unique:
        raise ValueError("stitched OOS equity curve has duplicate timestamps -- overlapping windows")
    if not stitched_equity.index.is_monotonic_increasing:
        raise ValueError("stitched OOS equity curve is out of chronological order")

    all_trades.sort(key=lambda t: t.entry_ts)
    return all_trades, stitched_equity


def default_gate3_pass_fn(metrics: dict, min_trade_count: int = 20) -> tuple[bool, str]:
    """
    Provisional default, not domain law -- override via pass_fn for a real per-pair
    verdict. min_trade_count guards against a thin sample winning by luck (TRADING-
    RULES §2's same concern, generalized here).
    """
    if metrics["trade_count"] < min_trade_count:
        return False, f"stitched OOS trade_count={metrics['trade_count']} < min_trade_count={min_trade_count} (thin sample)"
    if metrics["net_pnl"] <= 0:
        return False, f"stitched OOS net_pnl={metrics['net_pnl']:.2f} <= 0"
    return True, (
        f"stitched OOS net_pnl={metrics['net_pnl']:.2f} > 0 with "
        f"trade_count={metrics['trade_count']} >= min_trade_count={min_trade_count}"
    )


def run_walk_forward(
    ltf_df: pd.DataFrame,
    htf_df: pd.DataFrame,
    run_fn: RunFn,
    param_grid: list[dict],
    is_bars: int,
    oos_bars: int,
    step_bars: int | None = None,
    metric_fn: Callable[[BacktestResult], float] = _default_metric,
    pass_fn: Callable[[dict], tuple[bool, str]] | None = None,
) -> WalkForwardReport:
    if pass_fn is None:
        pass_fn = default_gate3_pass_fn

    n_bars = len(ltf_df)
    bounds = generate_window_bounds(n_bars, is_bars, oos_bars, step_bars)
    if not bounds:
        raise ValueError("not enough bars for even one IS/OOS window")

    windows: list[WalkForwardWindow] = []
    oos_results: list[WindowOOSResult] = []

    for idx, (is_start_idx, oos_start_idx, oos_end_idx) in enumerate(bounds):
        is_slice = ltf_df.iloc[is_start_idx:oos_start_idx]
        oos_start_ts = ltf_df["time"].iloc[oos_start_idx]
        oos_end_ts = ltf_df["time"].iloc[oos_end_idx - 1]

        assert is_slice["time"].max() < oos_start_ts, (
            "IS/OOS isolation violated: IS slice reaches into the OOS boundary"
        )
        htf_is_slice = _bound_htf(htf_df, is_slice["time"].iloc[-1])
        chosen_params, scoreboard = select_best_params(run_fn, is_slice, htf_is_slice, param_grid, metric_fn)

        eval_slice = ltf_df.iloc[is_start_idx:oos_end_idx]  # IS+OOS: real warmup history, never a future peek
        htf_eval_slice = _bound_htf(htf_df, eval_slice["time"].iloc[-1])
        full_result = run_fn(chosen_params, eval_slice, htf_eval_slice)

        trimmed_trades = [t for t in full_result.trades if t.entry_ts >= oos_start_ts]
        trimmed_equity = full_result.equity_curve[full_result.equity_curve.index >= oos_start_ts]

        window_oos = WindowOOSResult(trades=trimmed_trades, equity_curve=trimmed_equity)
        oos_results.append(window_oos)
        windows.append(
            WalkForwardWindow(
                window_index=idx,
                is_start_ts=ltf_df["time"].iloc[is_start_idx],
                oos_start_ts=oos_start_ts,
                oos_end_ts=oos_end_ts,
                chosen_params=chosen_params,
                is_scoreboard=scoreboard,
                oos=window_oos,
            )
        )

    stitched_trades, stitched_equity = stitch_oos_results(oos_results)
    stitched_metrics = compute_metrics(stitched_trades, stitched_equity)
    passed, reason = pass_fn(stitched_metrics)

    return WalkForwardReport(
        windows=windows,
        stitched_trades=stitched_trades,
        stitched_equity=stitched_equity,
        stitched_metrics=stitched_metrics,
        passed=passed,
        reason=reason,
    )
