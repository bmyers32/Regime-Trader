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
    units: float  # ORIGINAL full entry size, even after a partial close (see partial_exit_units)
    pnl: float  # account currency, TOTAL across partial + remainder legs
    pnl_r: float  # R-multiple: pnl / initial risk amount
    exit_reason: str  # "sl" | "tp" | "trail" (remainder's terminal exit, after any partial)
    regime_at_entry: str
    # Partial-exit leg (TRADING-RULES §3.1 "partial at 1R; trail remainder"), all None
    # when no partial fired — e.g. no exit_cfg passed to BacktestEngine, or the
    # position never reached partial_at_r before its final exit. One BacktestTrade row
    # per entry either way (trade_count/win_rate semantics unchanged) — see HANDOFF.md
    # Session A Decision 1.
    partial_exit_ts: datetime | None = None
    partial_exit_px: float | None = None
    partial_exit_units: float | None = None
    partial_exit_pnl: float | None = None


@dataclass
class SignalEvaluation:
    """
    One generate_signal() consultation (bot.strategies.base.Signal was not None) —
    mirrors the real SignalLog journal's columns (bot/journal/models.py) so a Phase
    8/9 journal writer can persist the same shape. Near-misses (fired=False) are
    exactly as visible here as fired=True evaluations — that is the point.
    """

    ts: datetime
    instrument: str
    strategy: str
    direction: str
    score: float
    threshold: float
    fired: bool
    vetoes: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def compute_signal_funnel(signal_log: list[SignalEvaluation], threshold: float) -> dict:
    """
    Evaluation funnel: consulted -> gates_passed (no vetoes) -> threshold_cleared
    (score >= threshold) -> fired (both). Plus basic score distribution. This IS the
    TRADING-RULES §1.7 empirical pass-rate note for the confluence score/threshold —
    only a real run over historical data can produce it, a unit test cannot.
    """
    consulted = len(signal_log)
    gates_passed = sum(1 for s in signal_log if not s.vetoes)
    threshold_cleared = sum(1 for s in signal_log if s.score >= threshold)
    fired = sum(1 for s in signal_log if s.fired)
    scores = sorted(s.score for s in signal_log)

    def _median(values: list[float]) -> float | None:
        if not values:
            return None
        mid = len(values) // 2
        if len(values) % 2:
            return values[mid]
        return (values[mid - 1] + values[mid]) / 2.0

    return {
        "consulted": consulted,
        "gates_passed": gates_passed,
        "threshold_cleared": threshold_cleared,
        "fired": fired,
        "score_distribution": {
            "min": scores[0] if scores else None,
            "max": scores[-1] if scores else None,
            "mean": (sum(scores) / len(scores)) if scores else None,
            "median": _median(scores),
        },
    }


@dataclass
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    metrics: dict = field(default_factory=dict)
    signal_log: list[SignalEvaluation] = field(default_factory=list)


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
