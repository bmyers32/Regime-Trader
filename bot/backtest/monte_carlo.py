"""
TRADING-RULES §5.6: Monte Carlo trade-order shuffles -> drawdown confidence intervals.

Extended beyond literal order-permutation (HANDOFF.md Track 2 dispositions): pure
permutation of a FIXED set of trade PnLs leaves their sum unchanged, so it can never
flag a positive total that only happened because of which specific trades occurred --
it can only ever speak to drawdown PATH risk, not to whether the total itself is
distinguishable from luck. Bootstrap resampling WITH replacement (composition varies,
sum does not have to) is added to test that: if resampling from the SAME realized
trade PnLs frequently produces a non-positive total, the observed positive result is
statistically unremarkable, not evidence of edge.

Explicit pass rule (not "a CI was computed"):
    passed = observed_net_pnl > 0
             AND P(bootstrap resample net_pnl <= 0) <= max_prob_nonpositive
             AND permutation drawdown p95 <= max_acceptable_drawdown
All three thresholds are constructor args -- provisional defaults, not domain law.

Limitation (independence assumption): both methods resample/reorder trade PnLs as if
they were i.i.d. draws. Real trades are not independent when exits are serially
correlated -- e.g. trend_pullback's ATR/Chandelier trail during a persistent regime,
where consecutive trades' outcomes share the same regime run. That correlation means
real drawdown clustering is understated here, so this gate is slightly lenient on
trend-following strategies specifically. Block bootstrap (resampling contiguous
blocks of trades instead of single trades) is the known upgrade if/when correlation
is suspected to matter; not implemented this session (HANDOFF.md Track 2 disposition).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from bot.backtest.results import max_drawdown

_LIMITATIONS_NOTE = (
    "Both Monte Carlo methods (permutation drawdown-path CI and bootstrap "
    "P(net_pnl<=0)) assume trade PnLs are independent draws. Serially correlated "
    "trades (e.g. trailing exits during a persistent regime) mean real drawdown "
    "clustering is understated -- gate 6 is slightly lenient on trend-following "
    "strategies specifically. Block bootstrap (resampling contiguous blocks of "
    "trades rather than single trades) is the known upgrade if correlation is "
    "suspected to matter; not implemented this session."
)


def equity_curve_from_pnls(starting_equity: float, pnls) -> pd.Series:
    values = [starting_equity]
    running = starting_equity
    for p in pnls:
        running += float(p)
        values.append(running)
    return pd.Series(values)


def permutation_drawdown_distribution(
    trade_pnls: list[float], starting_equity: float, n_shuffles: int = 1000, seed: int = 42
) -> list[float]:
    rng = np.random.default_rng(seed)
    pnls_arr = np.array(trade_pnls, dtype=float)
    drawdowns = []
    for _ in range(n_shuffles):
        shuffled = rng.permutation(pnls_arr)
        curve = equity_curve_from_pnls(starting_equity, shuffled)
        drawdowns.append(max_drawdown(curve))
    return drawdowns


def bootstrap_net_pnl_distribution(trade_pnls: list[float], n_resamples: int = 1000, seed: int = 43) -> list[float]:
    rng = np.random.default_rng(seed)
    pnls_arr = np.array(trade_pnls, dtype=float)
    n = len(pnls_arr)
    return [float(rng.choice(pnls_arr, size=n, replace=True).sum()) for _ in range(n_resamples)]


def _percentile(values: list[float], q: float) -> float:
    return float(np.percentile(values, q * 100))


@dataclass
class MonteCarloResult:
    observed_net_pnl: float = 0.0
    observed_drawdown: float = 0.0
    n_shuffles: int = 0
    n_resamples: int = 0
    seed: int = 0
    drawdown_distribution: list[float] = field(default_factory=list)
    drawdown_p95: float = 0.0
    prob_nonpositive: float = 0.0
    passed: bool = False
    reason: str = ""
    limitations: str = _LIMITATIONS_NOTE


def _judge_monte_carlo(
    observed_net_pnl: float,
    prob_nonpositive: float,
    drawdown_p95: float,
    max_prob_nonpositive: float,
    max_acceptable_drawdown: float,
) -> tuple[bool, str]:
    if observed_net_pnl <= 0:
        return False, f"observed_net_pnl={observed_net_pnl:.2f} <= 0"
    if prob_nonpositive > max_prob_nonpositive:
        return False, (
            f"bootstrap P(net_pnl<=0)={prob_nonpositive:.1%} > max_prob_nonpositive="
            f"{max_prob_nonpositive:.1%} -- observed positive result is not "
            "distinguishable from noise"
        )
    if drawdown_p95 > max_acceptable_drawdown:
        return False, (
            f"permutation drawdown p95={drawdown_p95:.1%} > "
            f"max_acceptable_drawdown={max_acceptable_drawdown:.1%}"
        )
    return True, (
        f"observed_net_pnl={observed_net_pnl:.2f} > 0; bootstrap P(net_pnl<=0)="
        f"{prob_nonpositive:.1%} <= max_prob_nonpositive={max_prob_nonpositive:.1%}; "
        f"permutation drawdown p95={drawdown_p95:.1%} <= "
        f"max_acceptable_drawdown={max_acceptable_drawdown:.1%}"
    )


def run_monte_carlo(
    trade_pnls: list[float],
    starting_equity: float,
    n_shuffles: int = 1000,
    n_resamples: int = 1000,
    seed: int = 42,
    max_prob_nonpositive: float = 0.05,
    max_acceptable_drawdown: float = 0.30,
) -> MonteCarloResult:
    if not trade_pnls:
        raise ValueError("trade_pnls must not be empty")

    observed_net_pnl = float(sum(trade_pnls))
    observed_drawdown = max_drawdown(equity_curve_from_pnls(starting_equity, trade_pnls))

    drawdown_dist = permutation_drawdown_distribution(trade_pnls, starting_equity, n_shuffles, seed)
    bootstrap_totals = bootstrap_net_pnl_distribution(trade_pnls, n_resamples, seed + 1)

    drawdown_p95 = _percentile(drawdown_dist, 0.95)
    prob_nonpositive = sum(1 for t in bootstrap_totals if t <= 0) / len(bootstrap_totals)

    passed, reason = _judge_monte_carlo(
        observed_net_pnl, prob_nonpositive, drawdown_p95, max_prob_nonpositive, max_acceptable_drawdown
    )

    return MonteCarloResult(
        observed_net_pnl=observed_net_pnl,
        observed_drawdown=observed_drawdown,
        n_shuffles=n_shuffles,
        n_resamples=n_resamples,
        seed=seed,
        drawdown_distribution=drawdown_dist,
        drawdown_p95=drawdown_p95,
        prob_nonpositive=prob_nonpositive,
        passed=passed,
        reason=reason,
    )
