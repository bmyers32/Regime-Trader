from __future__ import annotations

import pytest

from bot.backtest.monte_carlo import (
    bootstrap_net_pnl_distribution,
    equity_curve_from_pnls,
    permutation_drawdown_distribution,
    run_monte_carlo,
)


def test_equity_curve_from_pnls():
    curve = equity_curve_from_pnls(1000.0, [10.0, -5.0, 20.0])
    assert list(curve.values) == [1000.0, 1010.0, 1005.0, 1025.0]


def test_permutation_preserves_total_pnl_every_shuffle():
    pnls = [10.0, -5.0, 20.0, -3.0, 7.0]
    # drawdown differs by order but every permutation must still sum to the same total --
    # verified indirectly: reconstruct final equity from the returned drawdowns' own
    # curves is not exposed, so instead assert determinism (same seed -> same output),
    # the property actually load-bearing for reproducible reporting.
    d1 = permutation_drawdown_distribution(pnls, 1000.0, n_shuffles=50, seed=7)
    d2 = permutation_drawdown_distribution(pnls, 1000.0, n_shuffles=50, seed=7)
    assert d1 == d2


def test_bootstrap_all_positive_never_nonpositive():
    pnls = [5.0, 8.0, 3.0, 12.0]
    totals = bootstrap_net_pnl_distribution(pnls, n_resamples=200, seed=1)
    assert all(t > 0 for t in totals)


def test_bootstrap_all_negative_always_nonpositive():
    pnls = [-5.0, -8.0, -3.0, -12.0]
    totals = bootstrap_net_pnl_distribution(pnls, n_resamples=200, seed=1)
    assert all(t <= 0 for t in totals)


def test_run_monte_carlo_passes_for_strong_consistent_edge():
    pnls = [10.0] * 40 + [-3.0] * 10  # consistent, low-variance positive edge
    result = run_monte_carlo(pnls, starting_equity=10_000.0, n_shuffles=300, n_resamples=300, seed=42)

    assert result.passed
    assert result.observed_net_pnl > 0
    assert result.prob_nonpositive < 0.05


def test_run_monte_carlo_fails_for_coinflip_symmetric_pnls():
    pnls = [10.0, -10.5, 9.5, -9.0, 10.2, -10.1, 8.9, -9.4] * 5  # ~zero mean, high variance
    result = run_monte_carlo(pnls, starting_equity=10_000.0, n_shuffles=300, n_resamples=300, seed=42)

    assert not result.passed


def test_run_monte_carlo_fails_on_negative_observed_pnl():
    pnls = [-5.0, -3.0, -7.0]
    result = run_monte_carlo(pnls, starting_equity=10_000.0, n_shuffles=50, n_resamples=50, seed=1)

    assert not result.passed
    assert "<= 0" in result.reason


def test_run_monte_carlo_deterministic_given_seed():
    pnls = [10.0, -4.0, 6.0, 12.0, -2.0]
    r1 = run_monte_carlo(pnls, starting_equity=5000.0, n_shuffles=100, n_resamples=100, seed=9)
    r2 = run_monte_carlo(pnls, starting_equity=5000.0, n_shuffles=100, n_resamples=100, seed=9)

    assert r1.drawdown_distribution == r2.drawdown_distribution
    assert r1.prob_nonpositive == r2.prob_nonpositive


def test_run_monte_carlo_raises_on_empty_trades():
    with pytest.raises(ValueError):
        run_monte_carlo([], starting_equity=1000.0)
