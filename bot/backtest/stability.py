"""
TRADING-RULES §5.4: +-10% neighbors perform similarly; a sharp peak = overfit = reject.

Scoping (HANDOFF.md Track 2 dispositions): one-parameter-at-a-time +-10% is the
default for independent numeric params. It cannot detect a compensating-pair ridge
(param A up + param B down landing back on a good score) among independent params --
that is recorded in StabilityResult.limitations, not silently glossed over.
score_weights is a special case: TRADING-RULES §3.1 requires those weights to sum to
1.0, so a compensating pair isn't merely "worth checking" -- the sum constraint
guarantees one exists. simplex_groups therefore gets a dedicated pairwise sweep (raise
one weight, lower another by the same absolute amount, both directions, all pairs).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from bot.backtest.param_sweep import RunFn, _default_metric
from bot.backtest.results import BacktestResult

_LIMITATIONS_NOTE = (
    "One-at-a-time +/-10% sweep does not test compensating ridges among independent "
    "(non-simplex) params; only simplex_groups (params constrained to sum to a fixed "
    "total, e.g. score_weights) get pairwise compensating perturbation. Full "
    "pairwise/combinatorial sweep across all independent params is out of scope "
    "(TRADING-RULES §5.4 scoping, HANDOFF.md Track 2 dispositions)."
)


def get_by_path(d: dict, path: str):
    obj = d
    for part in path.split("."):
        obj = obj[part]
    return obj


def set_by_path(d: dict, path: str, value) -> dict:
    """Returns a deep-copied dict with `path` set to `value`; never mutates the input."""
    new_d = copy.deepcopy(d)
    parts = path.split(".")
    obj = new_d
    for part in parts[:-1]:
        obj = obj[part]
    obj[parts[-1]] = value
    return new_d


@dataclass
class NeighborEval:
    key: str
    direction: str
    params: dict
    metric: float


@dataclass
class StabilityResult:
    base_params: dict = field(default_factory=dict)
    base_metric: float = 0.0
    neighbors: list[NeighborEval] = field(default_factory=list)
    passed: bool = False
    reason: str = ""
    limitations: str = _LIMITATIONS_NOTE


def perturb_one_at_a_time(base_params: dict, keys: list[str], pct: float = 0.10) -> list[dict]:
    neighbors = []
    for key in keys:
        base_value = get_by_path(base_params, key)
        for direction, factor in (("-10%", 1 - pct), ("+10%", 1 + pct)):
            neighbors.append(
                {"key": key, "direction": direction, "params": set_by_path(base_params, key, base_value * factor)}
            )
    return neighbors


def perturb_simplex_pairs(base_params: dict, keys: list[str], pct: float = 0.10) -> list[dict]:
    """
    All ordered pairs (donor, recipient) among `keys`: donor increases by pct*its own
    value, recipient decreases by that same absolute amount -- the group's sum is
    invariant, which is exactly the ridge a simplex-constrained param set can hide.
    """
    neighbors = []
    for donor in keys:
        for recipient in keys:
            if donor == recipient:
                continue
            donor_value = get_by_path(base_params, donor)
            recipient_value = get_by_path(base_params, recipient)
            delta = donor_value * pct
            params = set_by_path(base_params, donor, donor_value + delta)
            params = set_by_path(params, recipient, recipient_value - delta)
            neighbors.append(
                {"key": f"{donor}(+)/{recipient}(-)", "direction": "compensating_pair", "params": params}
            )
    return neighbors


def _judge_stability(
    base_metric: float, neighbors: list[NeighborEval], max_relative_deviation: float
) -> tuple[bool, str]:
    if base_metric <= 0:
        return False, f"base_metric={base_metric:.2f} <= 0 -- no profitable peak to test stability of"
    worst_rel_dev = 0.0
    for n in neighbors:
        if n.metric <= 0:
            return False, (
                f"neighbor {n.key} ({n.direction}) metric={n.metric:.2f} flips sign vs "
                f"base_metric={base_metric:.2f} -- sharp peak / overfit"
            )
        rel_dev = abs(n.metric - base_metric) / abs(base_metric)
        worst_rel_dev = max(worst_rel_dev, rel_dev)
        if rel_dev > max_relative_deviation:
            return False, (
                f"neighbor {n.key} ({n.direction}) metric={n.metric:.2f} deviates {rel_dev:.1%} "
                f"from base_metric={base_metric:.2f} (> max_relative_deviation="
                f"{max_relative_deviation:.0%}) -- sharp peak / overfit"
            )
    return True, (
        f"base_metric={base_metric:.2f}; worst neighbor deviation={worst_rel_dev:.1%} "
        f"<= max_relative_deviation={max_relative_deviation:.0%} across {len(neighbors)} neighbors"
    )


def run_stability_sweep(
    run_fn: RunFn,
    ltf_slice: pd.DataFrame,
    htf_slice: pd.DataFrame,
    base_params: dict,
    keys: list[str],
    pct: float = 0.10,
    simplex_groups: list[list[str]] | None = None,
    metric_fn: Callable[[BacktestResult], float] = _default_metric,
    max_relative_deviation: float = 0.5,
) -> StabilityResult:
    base_result = run_fn(base_params, ltf_slice, htf_slice)
    base_metric = metric_fn(base_result)

    raw_neighbors = perturb_one_at_a_time(base_params, keys, pct)
    for group in simplex_groups or []:
        raw_neighbors.extend(perturb_simplex_pairs(base_params, group, pct))

    evals = []
    for candidate in raw_neighbors:
        result = run_fn(candidate["params"], ltf_slice, htf_slice)
        metric = metric_fn(result)
        evals.append(NeighborEval(key=candidate["key"], direction=candidate["direction"], params=candidate["params"], metric=metric))

    passed, reason = _judge_stability(base_metric, evals, max_relative_deviation)

    return StabilityResult(
        base_params=base_params,
        base_metric=base_metric,
        neighbors=evals,
        passed=passed,
        reason=reason,
    )
