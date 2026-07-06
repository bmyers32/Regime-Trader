"""
Backtest output types. Trades carry regime_at_entry (matching the Trade journal
model's column of the same name) so per-regime attribution (TRADING-RULES §5.5) is
structurally available as soon as real strategies exist (Phase 5+) — this phase only
proves the plumbing with a test-double Strategy, real per-regime expectancy analysis
lands with trend_pullback.

BacktestEngine.run() returns a BacktestResult in-memory. It does not write the
journal — BacktestRun/Trade rows are written by the Phase 9 dashboard-queue/worker
that wraps this engine, not by the engine itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd


@dataclass
class BacktestTrade:
    instrument: str
    direction: str  # "long" | "short"
    entry_ts: datetime
    exit_ts: datetime
    entry_px: float
    exit_px: float
    units: float
    pnl: float  # account currency
    pnl_r: float  # R-multiple: pnl / initial risk amount
    exit_reason: str  # "sl" | "tp" | "trail"
    regime_at_entry: str


@dataclass
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    metrics: dict = field(default_factory=dict)


def max_drawdown(equity_curve: pd.Series) -> float:
    """Largest peak-to-trough drop as a positive fraction of the peak. 0.0 for <2 points."""
    if len(equity_curve) < 2:
        return 0.0
    running_max = equity_curve.cummax()
    drawdown = (running_max - equity_curve) / running_max
    return float(drawdown.max())


def compute_metrics(trades: list[BacktestTrade], equity_curve: pd.Series) -> dict:
    """
    Net PnL, trade count, win rate, max drawdown, and per-regime attribution
    (count/net_pnl/win_rate keyed by regime_at_entry) — the shape §5.5 needs once
    real strategies populate regime_at_entry with more than one regime value.
    """
    trade_count = len(trades)
    net_pnl = sum(t.pnl for t in trades)
    win_rate = (sum(1 for t in trades if t.pnl > 0) / trade_count) if trade_count else 0.0

    per_regime: dict[str, dict] = {}
    for t in trades:
        bucket = per_regime.setdefault(t.regime_at_entry, {"count": 0, "net_pnl": 0.0, "wins": 0})
        bucket["count"] += 1
        bucket["net_pnl"] += t.pnl
        if t.pnl > 0:
            bucket["wins"] += 1
    for bucket in per_regime.values():
        bucket["win_rate"] = bucket["wins"] / bucket["count"] if bucket["count"] else 0.0
        del bucket["wins"]

    return {
        "trade_count": trade_count,
        "net_pnl": net_pnl,
        "win_rate": win_rate,
        "max_drawdown": max_drawdown(equity_curve),
        "per_regime": per_regime,
    }
