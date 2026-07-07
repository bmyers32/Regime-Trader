"""
Generic parameter-grid search over a single fixed data slice (TRADING-RULES §5.3/§5.4
building block). Shared by walk_forward.py's per-window IS optimization and by
tests/test_validation_defendants.py's overfit-by-construction scenario.

IS/OOS isolation is structural, not conventional: select_best_params()'s only inputs
are ltf_slice/htf_slice, already bounded by the caller before this function is ever
invoked. There is no wider dataset, index, or timestamp reference reachable from
inside this function — it cannot see a bar it was not handed.
"""

from __future__ import annotations

from typing import Callable, Protocol

import pandas as pd

from bot.backtest.results import BacktestResult


class RunFn(Protocol):
    def __call__(self, params: dict, ltf_slice: pd.DataFrame, htf_slice: pd.DataFrame) -> BacktestResult: ...


def _default_metric(result: BacktestResult) -> float:
    return result.metrics["net_pnl"]


def select_best_params(
    run_fn: RunFn,
    ltf_slice: pd.DataFrame,
    htf_slice: pd.DataFrame,
    param_grid: list[dict],
    metric_fn: Callable[[BacktestResult], float] = _default_metric,
) -> tuple[dict, list[dict]]:
    """
    Returns (best_params, scoreboard). scoreboard has one entry per candidate:
    {"params", "score", "metrics"} — kept for diagnostics/reporting even though only
    best_params crosses the IS/OOS boundary.
    """
    if not param_grid:
        raise ValueError("param_grid must not be empty")

    scoreboard: list[dict] = []
    best_params: dict | None = None
    best_score: float | None = None

    for params in param_grid:
        result = run_fn(params, ltf_slice, htf_slice)
        score = metric_fn(result)
        scoreboard.append({"params": params, "score": score, "metrics": result.metrics})
        if best_score is None or score > best_score:
            best_score = score
            best_params = params

    return best_params, scoreboard
