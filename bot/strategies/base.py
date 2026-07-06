"""
Shared Strategy contract (CLAUDE.md Core Interfaces).

Defined here, ahead of any concrete playbook, so the Phase 4 backtester and the
Phase 5-7 playbooks (trend_pullback, range_reversion, squeeze_breakout) import
the SAME Signal/Strategy types. This module holds the contract only — no
playbook logic, no thresholds.

Backtest and live share this exact interface (Prime Directive 7): a Strategy
implementation must not know or care whether generate_signal() is being called
by bot.backtest.engine.BacktestEngine or the live run_bot.py loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd

from bot.regime.classifier import RegimeResult


@dataclass
class Signal:
    """
    One strategy evaluation's output. Emitted whether or not the signal fires —
    near-misses (fired=False equivalent) are represented by the caller choosing
    not to act on a low confidence_score, but the Signal itself always carries
    reasons/vetoes so SignalLog can journal the "why" either way.
    """

    strategy: str
    instrument: str
    direction: str  # "long" | "short"
    entry_ref: float  # reference price at signal time (mid, no cost applied)
    sl: float
    tp: float | None
    confidence_score: float
    reasons: list[str] = field(default_factory=list)
    vetoes: list[str] = field(default_factory=list)


class Strategy(Protocol):
    """
    window: the LTF (execution timeframe) OHLCV history up to and including the
    latest CLOSED candle — never a forming candle (Prime Directive 3).
    regime: the current confirmed RegimeResult from the anchor-TF classifier.

    Returns None when no signal fires. Returning a Signal does not imply it
    should be acted on — callers compare confidence_score against a threshold.
    """

    def generate_signal(self, window: pd.DataFrame, regime: RegimeResult) -> Signal | None: ...
