from __future__ import annotations

import pandas as pd
import pytest

from bot.backtest.param_sweep import select_best_params
from bot.backtest.results import BacktestResult


def _make_run_fn(seen_slices: list):
    def run_fn(params: dict, ltf_slice: pd.DataFrame, htf_slice: pd.DataFrame) -> BacktestResult:
        seen_slices.append((ltf_slice, htf_slice))
        return BacktestResult(metrics={"net_pnl": params["x"]})

    return run_fn


def test_selects_max_metric_candidate():
    ltf = pd.DataFrame({"time": [1, 2, 3]})
    htf = pd.DataFrame({"time": [1]})
    grid = [{"x": -5.0}, {"x": 12.0}, {"x": 3.0}]

    best_params, scoreboard = select_best_params(_make_run_fn([]), ltf, htf, grid)

    assert best_params == {"x": 12.0}
    assert len(scoreboard) == 3
    assert {row["params"]["x"] for row in scoreboard} == {-5.0, 12.0, 3.0}


def test_only_receives_the_slices_it_was_given():
    ltf = pd.DataFrame({"time": [1, 2, 3]})
    htf = pd.DataFrame({"time": [1]})
    seen: list = []

    select_best_params(_make_run_fn(seen), ltf, htf, [{"x": 1.0}])

    assert len(seen) == 1
    seen_ltf, seen_htf = seen[0]
    assert seen_ltf is ltf
    assert seen_htf is htf


def test_custom_metric_fn():
    ltf = pd.DataFrame({"time": [1]})
    htf = pd.DataFrame({"time": [1]})
    grid = [{"x": 1.0}, {"x": 2.0}]

    def run_fn(params, ltf_slice, htf_slice):
        return BacktestResult(metrics={"net_pnl": params["x"], "max_drawdown": 1.0 / params["x"]})

    best_params, _ = select_best_params(run_fn, ltf, htf, grid, metric_fn=lambda r: -r.metrics["max_drawdown"])

    assert best_params == {"x": 2.0}


def test_empty_grid_raises():
    with pytest.raises(ValueError):
        select_best_params(lambda *a: None, pd.DataFrame(), pd.DataFrame(), [])
