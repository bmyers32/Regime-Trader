from __future__ import annotations

import pandas as pd
import pytest

from bot.backtest.results import BacktestResult
from bot.backtest.stability import (
    get_by_path,
    perturb_one_at_a_time,
    perturb_simplex_pairs,
    run_stability_sweep,
    set_by_path,
)

_EMPTY = pd.DataFrame()


def test_get_set_by_path_nested():
    d = {"score_weights": {"a": 0.3, "b": 0.25}}
    assert get_by_path(d, "score_weights.a") == 0.3

    updated = set_by_path(d, "score_weights.a", 0.5)
    assert updated["score_weights"]["a"] == 0.5
    assert d["score_weights"]["a"] == 0.3  # original untouched


def test_perturb_one_at_a_time_values_and_no_mutation():
    base = {"sl_atr_mult": 2.0, "entry_threshold": 0.6}
    neighbors = perturb_one_at_a_time(base, ["sl_atr_mult", "entry_threshold"], pct=0.10)

    assert len(neighbors) == 4
    values = {(n["key"], n["direction"]): get_by_path(n["params"], n["key"]) for n in neighbors}
    assert values[("sl_atr_mult", "-10%")] == pytest.approx(1.8)
    assert values[("sl_atr_mult", "+10%")] == pytest.approx(2.2)
    assert values[("entry_threshold", "-10%")] == pytest.approx(0.54)
    assert values[("entry_threshold", "+10%")] == pytest.approx(0.66)
    assert base == {"sl_atr_mult": 2.0, "entry_threshold": 0.6}


def test_perturb_one_at_a_time_int_param_rounds_and_produces_valid_runs():
    """TRADING-RULES §6 (2026-07-12, A8): an int-typed base value must round the
    perturbed +/-10% float back to an int, not leave a float that a bar-slicing/
    lookback operation (e.g. window.iloc[-n:]) would reject with a TypeError. Uses
    momentum's own N grid values (20/60/120) as the representative int key."""
    base = {"n": 20, "sl_atr_mult": 1.5}
    neighbors = perturb_one_at_a_time(base, ["n", "sl_atr_mult"], pct=0.10)

    values = {(n["key"], n["direction"]): get_by_path(n["params"], n["key"]) for n in neighbors}
    assert values[("n", "-10%")] == 18
    assert values[("n", "+10%")] == 22
    assert isinstance(values[("n", "-10%")], int)
    assert isinstance(values[("n", "+10%")], int)
    # float-typed key unaffected -- strictly additive fix
    assert values[("sl_atr_mult", "-10%")] == pytest.approx(1.35)
    assert base == {"n": 20, "sl_atr_mult": 1.5}  # original untouched

    # No float-index TypeError: the rounded int is actually usable for slicing.
    dummy_series = list(range(30))
    for n in ["n"]:
        for direction in ("-10%", "+10%"):
            k = values[(n, direction)]
            dummy_series[-k:]  # would raise TypeError if k were a float


def test_perturb_one_at_a_time_int_param_rounds_larger_n_values():
    base = {"n": 60}
    neighbors = perturb_one_at_a_time(base, ["n"], pct=0.10)
    values = {n["direction"]: get_by_path(n["params"], "n") for n in neighbors}
    assert values["-10%"] == 54
    assert values["+10%"] == 66

    base_120 = {"n": 120}
    neighbors_120 = perturb_one_at_a_time(base_120, ["n"], pct=0.10)
    values_120 = {n["direction"]: get_by_path(n["params"], "n") for n in neighbors_120}
    assert values_120["-10%"] == 108
    assert values_120["+10%"] == 132


def test_perturb_simplex_pairs_preserves_sum():
    base = {"score_weights": {"a": 0.3, "b": 0.25, "c": 0.25, "d": 0.2}}
    keys = ["score_weights.a", "score_weights.b", "score_weights.c", "score_weights.d"]

    neighbors = perturb_simplex_pairs(base, keys, pct=0.10)

    assert len(neighbors) == 4 * 3  # all ordered donor/recipient pairs
    for n in neighbors:
        total = sum(n["params"]["score_weights"].values())
        assert total == pytest.approx(1.0)


def _run_fn_factory(metric_fn):
    def run_fn(params, ltf_slice, htf_slice):
        return BacktestResult(metrics={"net_pnl": metric_fn(params)})

    return run_fn


def test_stability_sweep_passes_for_smooth_stable_metric():
    run_fn = _run_fn_factory(lambda p: 100.0 + p["a"] + p["b"])
    base_params = {"a": 10.0, "b": 20.0}

    result = run_stability_sweep(run_fn, _EMPTY, _EMPTY, base_params, ["a", "b"])

    assert result.passed
    assert result.base_metric == pytest.approx(130.0)
    assert len(result.neighbors) == 4


def test_stability_sweep_fails_on_sharp_peak():
    def metric_fn(p):
        return 100.0 if abs(p["a"] - 10.0) < 1e-9 else -5.0

    run_fn = _run_fn_factory(metric_fn)
    base_params = {"a": 10.0}

    result = run_stability_sweep(run_fn, _EMPTY, _EMPTY, base_params, ["a"])

    assert not result.passed
    assert "sharp peak" in result.reason


def test_stability_sweep_fails_when_base_metric_nonpositive():
    run_fn = _run_fn_factory(lambda p: -10.0)
    result = run_stability_sweep(run_fn, _EMPTY, _EMPTY, {"a": 1.0}, ["a"])

    assert not result.passed
    assert "no profitable peak" in result.reason


def test_stability_sweep_includes_simplex_pairs_and_limitations_note():
    run_fn = _run_fn_factory(lambda p: 100.0 + sum(p["score_weights"].values()))
    base_params = {"score_weights": {"a": 0.3, "b": 0.25, "c": 0.25, "d": 0.2}}
    keys = ["score_weights.a"]
    groups = [["score_weights.a", "score_weights.b", "score_weights.c", "score_weights.d"]]

    result = run_stability_sweep(run_fn, _EMPTY, _EMPTY, base_params, keys, simplex_groups=groups)

    # 2 one-at-a-time neighbors + 12 compensating-pair neighbors
    assert len(result.neighbors) == 2 + 12
    assert "one-at-a-time" in result.limitations.lower()
